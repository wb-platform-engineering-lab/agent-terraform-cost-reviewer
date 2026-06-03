# ─────────────────────────────────────────────────────────────────────────────
# GOOD INFRA — passes all 15 cost checks
# Well-architected for cost efficiency.
# ─────────────────────────────────────────────────────────────────────────────

# C-001: Single NAT Gateway — centralized egress via shared services VPC
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
  tags          = { Name = "centralized-nat" }
}

# C-002: VPC endpoints for S3 and DynamoDB — traffic stays within AWS backbone
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.us-east-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id       = aws_vpc.main.id
  service_name = "com.amazonaws.us-east-1.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

# C-003: Event-driven Lambda — SQS triggers Lambda directly, no polling
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10
  enabled          = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "job-queue"
  visibility_timeout_seconds = 300
  receive_wait_time_seconds  = 20  # C-018: long polling — eliminates empty ReceiveMessage API calls
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "jobs_dlq" {
  name = "job-queue-dlq"
}

# C-009: Lambda memory right-sized — not at maximum
resource "aws_lambda_function" "processor" {
  function_name = "order-processor"
  runtime       = "python3.12"
  handler       = "main.handler"
  filename      = "lambda.zip"
  role          = aws_iam_role.lambda_role.arn
  memory_size   = 512
  timeout       = 300

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda_sg.id]
  }

  environment {
    variables = {
      DB_PROXY_HOST = aws_db_proxy.main.endpoint
      QUEUE_URL     = aws_sqs_queue.jobs.url
      BUCKET        = aws_s3_bucket.artifacts.bucket
    }
  }
}

# C-004: Log groups with explicit retention policies
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/order-processor"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "ecs_logs" {
  name              = "/ecs/api-service"
  retention_in_days = 14
}

# C-005: S3 buckets with lifecycle configurations
resource "aws_s3_bucket" "artifacts" {
  bucket = "my-app-artifacts-prod"
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts_lifecycle" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

resource "aws_s3_bucket" "logs" {
  bucket = "my-app-access-logs-prod"
}

resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"
    expiration {
      days = 90
    }
  }
}

# C-006: EBS and RDS using gp3
resource "aws_ebs_volume" "data" {
  availability_zone = "us-east-1a"
  size              = 500
  type              = "gp3"
  iops              = 3000
  throughput        = 125
}

resource "aws_db_instance" "primary" {
  identifier        = "prod-db"
  engine            = "postgres"
  engine_version    = "15.4"
  instance_class    = "db.t4g.medium"
  allocated_storage = 200
  storage_type      = "gp3"
  multi_az          = false  # C-014: non-prod — single AZ
  username          = "admin"
  password          = data.aws_secretsmanager_secret_version.db_password.secret_string
  skip_final_snapshot = false
  backup_retention_period = 7
}

# C-012: RDS Proxy for Lambda connection pooling
resource "aws_db_proxy" "main" {
  name                   = "prod-db-proxy"
  debug_logging          = false
  engine_family          = "POSTGRESQL"
  idle_client_timeout    = 1800
  require_tls            = true
  role_arn               = aws_iam_role.rds_proxy_role.arn

  auth {
    auth_scheme = "SECRETS"
    secret_arn  = aws_secretsmanager_secret.db_creds.arn
    iam_auth    = "DISABLED"
  }

  vpc_subnet_ids         = [aws_subnet.private.id]
  vpc_security_group_ids = [aws_security_group.rds_proxy_sg.id]
}

resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name
  connection_pool_config {
    max_connections_percent = 100
  }
}

resource "aws_db_proxy_target" "main" {
  db_instance_identifier = aws_db_instance.primary.id
  db_proxy_name          = aws_db_proxy.main.name
  target_group_name      = aws_db_proxy_default_target_group.main.name
}

# C-007: CloudFront with compression enabled
resource "aws_cloudfront_distribution" "cdn" {
  enabled = true

  default_cache_behavior {
    target_origin_id       = "S3Origin"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

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

# C-008: Fargate task right-sized
resource "aws_ecs_task_definition" "api" {
  family                   = "api-service"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"

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

# C-010: DynamoDB on-demand (or provisioned with auto-scaling)
resource "aws_dynamodb_table" "sessions" {
  name         = "user-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# C-011: Single EIP, properly associated
resource "aws_eip" "nat" {
  vpc = true
}

# C-013: Reserved instance tag for FinOps tracking
# (Reserved instance purchase tracked in FinOps system — see reserved_instances.md)

# C-015: S3 Intelligent-Tiering for unpredictable access pattern bucket
resource "aws_s3_bucket_lifecycle_configuration" "artifacts_intelligent_tiering" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "intelligent-tiering"
    status = "Enabled"
    transition {
      days          = 0
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}

# C-016: Step Functions EXPRESS type — ~750x cheaper than STANDARD for high-volume
resource "aws_sfn_state_machine" "order_flow" {
  name     = "order-processing"
  role_arn = aws_iam_role.lambda_role.arn
  type     = "EXPRESS"
  definition = jsonencode({
    Comment = "Order processing workflow"
    StartAt = "ProcessOrder"
    States = {
      ProcessOrder = { Type = "Task", Resource = aws_lambda_function.processor.arn, End = true }
    }
  })
}

# C-017: API Gateway with caching enabled — reduces Lambda invocations 50–90%
resource "aws_api_gateway_rest_api" "api" {
  name = "my-api"
}

resource "aws_api_gateway_stage" "prod" {
  rest_api_id           = aws_api_gateway_rest_api.api.id
  stage_name            = "prod"
  deployment_id         = "placeholder"
  cache_cluster_enabled = true
  cache_cluster_size    = "0.5"
}

# C-019: ECR with lifecycle policy — keeps only last 10 tagged images, expires untagged after 1 day
resource "aws_ecr_repository" "app" {
  name                 = "my-app"
  image_tag_mutability = "IMMUTABLE"
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only last 10 tagged images"
        selection = {
          tagStatus   = "tagged"
          tagPrefixList = ["v"]
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = { type = "expire" }
      }
    ]
  })
}

# C-020: Kinesis On-Demand — scales automatically, no over-provisioned shards
resource "aws_kinesis_stream" "events" {
  name = "event-stream"

  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }
}

# C-021: ECS service with mixed Spot/on-demand strategy — 60-70% compute savings
resource "aws_ecs_service" "api" {
  name            = "api-service"
  cluster         = "my-cluster"
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 3

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 70
    base              = 0
  }

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 30
    base              = 1  # keep at least 1 on-demand task for stability
  }
}

# Networking
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1a"
}

resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.4.0/24"
  availability_zone = "us-east-1a"
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
}

resource "aws_security_group" "lambda_sg" {
  vpc_id = aws_vpc.main.id
  name   = "lambda-sg"
}

resource "aws_security_group" "rds_proxy_sg" {
  vpc_id = aws_vpc.main.id
  name   = "rds-proxy-sg"
}

resource "aws_iam_role" "lambda_role" {
  name               = "lambda-role"
  assume_role_policy = "{}"
}

resource "aws_iam_role" "rds_proxy_role" {
  name               = "rds-proxy-role"
  assume_role_policy = "{}"
}

resource "aws_secretsmanager_secret" "db_creds" {
  name = "prod/db/credentials"
}
