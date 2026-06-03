# ─────────────────────────────────────────────────────────────────────────────
# BAD INFRA — violates all 15 cost checks
# This is intentionally poorly architected for testing the reviewer.
# DO NOT use in production.
# ─────────────────────────────────────────────────────────────────────────────

# C-001: NAT Gateway sprawl — 3 NAT Gateways, one per AZ, no centralized egress
resource "aws_nat_gateway" "az_a" {
  allocation_id = aws_eip.nat_a.id
  subnet_id     = aws_subnet.public_a.id
}

resource "aws_nat_gateway" "az_b" {
  allocation_id = aws_eip.nat_b.id
  subnet_id     = aws_subnet.public_b.id
}

resource "aws_nat_gateway" "az_c" {
  allocation_id = aws_eip.nat_c.id
  subnet_id     = aws_subnet.public_c.id
}

# C-002: No VPC endpoints — Lambda inside VPC but S3/DynamoDB traffic goes through NAT
resource "aws_lambda_function" "processor" {
  function_name = "order-processor"
  runtime       = "python3.12"
  handler       = "main.handler"
  filename      = "lambda.zip"
  role          = aws_iam_role.lambda_role.arn
  # C-009: Memory at maximum — 3008 MB default for all functions
  memory_size   = 3008
  timeout       = 900

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      DB_HOST    = aws_db_instance.primary.address
      QUEUE_URL  = aws_sqs_queue.jobs.url
      BUCKET     = aws_s3_bucket.artifacts.bucket
    }
  }
}

# C-003: Lambda polling SQS via schedule instead of event-driven trigger
resource "aws_cloudwatch_event_rule" "poll_schedule" {
  name                = "sqs-poller"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "invoke_lambda" {
  rule      = aws_cloudwatch_event_rule.poll_schedule.name
  target_id = "lambda"
  arn       = aws_lambda_function.processor.arn
}

resource "aws_sqs_queue" "jobs" {
  name = "job-queue"
  # No DLQ
}

# C-004: Log groups with no retention — logs accumulate forever
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name = "/aws/lambda/order-processor"
  # retention_in_days not set
}

resource "aws_cloudwatch_log_group" "ecs_logs" {
  name = "/ecs/api-service"
  # retention_in_days not set
}

# C-005: S3 bucket with no lifecycle configuration
resource "aws_s3_bucket" "artifacts" {
  bucket = "my-app-artifacts-prod"
}

resource "aws_s3_bucket" "logs" {
  bucket = "my-app-access-logs-prod"
}

# C-006: EBS volume using gp2 — should be gp3
resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 500
  type              = "gp2"
}

# C-006: RDS also on gp2
resource "aws_db_instance" "primary" {
  identifier        = "prod-db"
  engine            = "postgres"
  engine_version    = "15.4"
  instance_class    = "db.r5.2xlarge"
  allocated_storage = 200
  storage_type      = "gp2"
  # C-014: Multi-AZ enabled — but this module is used for dev too
  multi_az          = true
  username          = "admin"
  password          = "hardcoded-secret-123"
  skip_final_snapshot = true
  # C-012: No RDS Proxy — Lambda connects directly
}

# C-007: CloudFront with compression disabled
resource "aws_cloudfront_distribution" "cdn" {
  enabled = true

  default_cache_behavior {
    target_origin_id       = "S3Origin"
    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    allowed_methods = ["GET", "HEAD"]
    cached_methods  = ["GET", "HEAD"]
  }

  origin {
    domain_name = aws_s3_bucket.artifacts.bucket_regional_domain_name
    origin_id   = "S3Origin"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# C-008: Fargate task at maximum CPU and memory
resource "aws_ecs_task_definition" "api" {
  family                   = "api-service"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "8192"

  container_definitions = jsonencode([{
    name  = "api"
    image = "my-api:latest"
    portMappings = [{ containerPort = 8080 }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"  = "/ecs/api-service"
        "awslogs-region" = "us-east-1"
      }
    }
  }])
}

# C-010: DynamoDB in PROVISIONED mode with no auto-scaling
resource "aws_dynamodb_table" "sessions" {
  name           = "user-sessions"
  billing_mode   = "PROVISIONED"
  read_capacity  = 100
  write_capacity = 100
  hash_key       = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }
  # No aws_appautoscaling_target — paying for 100 RCU/WCU 24/7
}

# C-011: Elastic IPs with no association (will be idle when instance is stopped)
resource "aws_eip" "nat_a" { vpc = true }
resource "aws_eip" "nat_b" { vpc = true }
resource "aws_eip" "nat_c" { vpc = true }
resource "aws_eip" "spare" { vpc = true }  # idle — never associated

# Minimal networking boilerplate
resource "aws_subnet" "public_a"  { vpc_id = "vpc-xxx" cidr_block = "10.0.1.0/24" availability_zone = "us-east-1a" }
resource "aws_subnet" "public_b"  { vpc_id = "vpc-xxx" cidr_block = "10.0.2.0/24" availability_zone = "us-east-1b" }
resource "aws_subnet" "public_c"  { vpc_id = "vpc-xxx" cidr_block = "10.0.3.0/24" availability_zone = "us-east-1c" }
resource "aws_subnet" "private_a" { vpc_id = "vpc-xxx" cidr_block = "10.0.4.0/24" availability_zone = "us-east-1a" }
resource "aws_security_group" "lambda_sg" { vpc_id = "vpc-xxx" name = "lambda-sg" }
resource "aws_iam_role" "lambda_role" {
  name               = "lambda-role"
  assume_role_policy = "{}"
}
