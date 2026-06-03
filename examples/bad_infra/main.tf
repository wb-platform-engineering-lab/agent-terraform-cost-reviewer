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
  name                      = "job-queue"
  receive_wait_time_seconds = 0  # C-018: short polling — every poll billed even when queue empty
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

# C-016: Step Functions STANDARD type — expensive for high-volume workflows
resource "aws_sfn_state_machine" "order_flow" {
  name     = "order-processing"
  role_arn = aws_iam_role.lambda_role.arn
  type     = "STANDARD"
  # At 1M executions/day: ~$750/mo vs ~$1/mo with EXPRESS
  definition = jsonencode({
    Comment = "Order processing workflow"
    StartAt = "ProcessOrder"
    States = {
      ProcessOrder = { Type = "Task", Resource = aws_lambda_function.processor.arn, End = true }
    }
  })
}

# C-017: API Gateway stage with caching disabled
resource "aws_api_gateway_rest_api" "api" {
  name = "my-api"
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id          = aws_api_gateway_rest_api.api.id
  stage_name           = "prod"
  deployment_id        = "placeholder"
  cache_cluster_enabled = false  # every request hits Lambda — no caching benefit
  # cache_cluster_size not set — missing 50–90% Lambda invocation savings
}

# C-019: ECR repository with no lifecycle policy — images accumulate forever
resource "aws_ecr_repository" "app" {
  name                 = "my-app"
  image_tag_mutability = "MUTABLE"
  # No aws_ecr_lifecycle_policy — CI/CD pushes accumulate GB of old images
}

# C-020: Kinesis stream with fixed shards — should use ON_DEMAND for variable traffic
resource "aws_kinesis_stream" "events" {
  name        = "event-stream"
  shard_count = 10
  # Fixed provisioned shards: 10 × $0.015/hr = $108/mo regardless of actual throughput
  # Should use stream_mode_details block with on-demand mode instead
}

# C-021: ECS service with no Spot capacity — 100% on-demand pricing
resource "aws_ecs_service" "api" {
  name            = "api-service"
  cluster         = "my-cluster"
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 3
  launch_type     = "FARGATE"
  # All tasks run on on-demand capacity — no mixed Spot strategy configured
  # Missing 60-70% compute savings from using a Spot capacity provider
}

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
