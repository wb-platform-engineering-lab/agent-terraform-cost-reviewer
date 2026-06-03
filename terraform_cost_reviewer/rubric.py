"""
Cost review rubric for the Terraform Cost Reviewer.

Each check defines:
  id            — unique identifier
  name          — short display name
  description   — what is being checked and why it matters
  severity      — FAIL | WARN | INFO (used when check is not passing)
  cross_resource — True if this check requires reasoning across multiple resources
  est_saving    — rough monthly saving estimate (for report display)

Check logic lives in tools.run_cost_checks, using the hcl2-parsed resource graph
rather than regex on raw text. This gives accurate attribute values (bool, int, str)
and eliminates false positives from comments or variable names.
"""

CHECKS = [

    # ── C1 — NAT Gateway Sprawl ────────────────────────────────────────
    {
        "id": "C-001",
        "name": "NAT Gateway count vs AZ count",
        "description": (
            "Multiple aws_nat_gateway resources defined without a centralized egress module. "
            "One NAT Gateway per AZ costs ~$130/mo each. Centralizing to a shared services VPC "
            "or using a single NAT for non-prod reduces this significantly."
        ),
        "severity": "FAIL",
        "cross_resource": True,
        "est_saving": "$100–500/mo per redundant gateway",
    },

    # ── C2 — VPC Endpoints Missing ─────────────────────────────────────
    {
        "id": "C-002",
        "name": "Missing VPC endpoints for S3 / DynamoDB",
        "description": (
            "Lambda or ECS resources are inside a VPC but no aws_vpc_endpoint is defined "
            "for S3 or DynamoDB. Traffic to these services routes through NAT Gateway, "
            "incurring data transfer charges (~$0.045/GB). VPC endpoints are free for S3/DynamoDB."
        ),
        "severity": "FAIL",
        "cross_resource": True,
        "est_saving": "$20–300/mo depending on data volume",
    },

    # ── C3 — SQS Polling Anti-Pattern ─────────────────────────────────
    {
        "id": "C-003",
        "name": "Lambda polling SQS via schedule (not event-driven)",
        "description": (
            "An aws_cloudwatch_event_rule (schedule) triggers a Lambda that manually polls SQS. "
            "AWS charges for every Lambda invocation and every SQS API call. "
            "Replace with aws_lambda_event_source_mapping — AWS polls for free and invokes Lambda only when messages exist."
        ),
        "severity": "FAIL",
        "cross_resource": True,
        "est_saving": "$10–200/mo depending on message volume",
    },

    # ── C4 — CloudWatch Log Retention ─────────────────────────────────
    {
        "id": "C-004",
        "name": "Log groups with no retention policy",
        "description": (
            "aws_cloudwatch_log_group resources defined without retention_in_days. "
            "Logs accumulate indefinitely at $0.03/GB/month storage + $0.50/GB ingestion. "
            "Set retention_in_days to 7, 14, 30, or 90 depending on compliance requirements."
        ),
        "severity": "FAIL",
        "cross_resource": False,
        "est_saving": "$5–100/mo per log group",
    },

    # ── C5 — S3 Lifecycle Policy ───────────────────────────────────────
    {
        "id": "C-005",
        "name": "S3 buckets missing lifecycle configuration",
        "description": (
            "aws_s3_bucket resources have no aws_s3_bucket_lifecycle_configuration attached. "
            "Without lifecycle rules, objects (especially logs, artifacts, backups) accumulate in S3 Standard "
            "at $0.023/GB/month indefinitely. Transition to S3-IA after 30 days, Glacier after 90."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "20–80% S3 storage cost",
    },

    # ── C6 — EBS gp2 Volumes ──────────────────────────────────────────
    {
        "id": "C-006",
        "name": "EBS / RDS volumes using gp2 instead of gp3",
        "description": (
            "aws_ebs_volume or aws_db_instance resources using type/storage_type = \"gp2\". "
            "gp3 provides the same baseline performance (3,000 IOPS, 125 MB/s throughput) "
            "at 20% lower cost with no architecture change required."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "20% on EBS/RDS storage",
    },

    # ── C7 — CloudFront Compression ───────────────────────────────────
    {
        "id": "C-007",
        "name": "CloudFront distribution compression disabled",
        "description": (
            "aws_cloudfront_distribution with compress = false or compress not set. "
            "Enabling compression reduces data transfer by 20–80% for text-based content "
            "(HTML, CSS, JS, JSON) at no additional cost."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "20–80% CloudFront bandwidth cost",
    },

    # ── C8 — Fargate Over-provisioned ─────────────────────────────────
    {
        "id": "C-008",
        "name": "Fargate tasks hardcoded at maximum CPU/memory",
        "description": (
            "aws_ecs_task_definition with cpu = 4096 (maximum). "
            "Fargate billing is per vCPU-hour and GB-hour. Over-provisioned tasks "
            "for workloads that don't need this capacity waste 30–70% of compute cost. "
            "Profile actual usage and right-size."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "30–70% Fargate cost",
    },

    # ── C9 — Lambda Memory Over-provisioned ───────────────────────────
    {
        "id": "C-009",
        "name": "Lambda functions at maximum memory (3008 MB)",
        "description": (
            "aws_lambda_function with memory_size = 3008 (the maximum). "
            "Lambda billing is duration × memory. Max memory is 6x more expensive than 512 MB "
            "for the same duration. Use Lambda Power Tuning to find the optimal memory setting."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "Up to 6x Lambda cost reduction",
    },

    # ── C10 — DynamoDB Provisioned Without Auto-Scaling ───────────────
    {
        "id": "C-010",
        "name": "DynamoDB PROVISIONED mode without auto-scaling",
        "description": (
            "aws_dynamodb_table with billing_mode = \"PROVISIONED\" but no aws_appautoscaling_target "
            "linked to it. Provisioned capacity without auto-scaling means you pay for peak capacity "
            "24/7 regardless of actual usage. Either switch to PAY_PER_REQUEST or add auto-scaling."
        ),
        "severity": "FAIL",
        "cross_resource": True,
        "est_saving": "40–80% DynamoDB cost at variable traffic",
    },

    # ── C11 — Elastic IP Orphans ───────────────────────────────────────
    {
        "id": "C-011",
        "name": "Elastic IPs allocated without guaranteed association",
        "description": (
            "More aws_eip resources are defined than can be accounted for by NAT Gateways, "
            "EC2 instances, and explicit aws_eip_association resources. "
            "AWS charges $0.005/hr (~$3.65/mo) for every allocated EIP not attached to a running instance."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "$3.65/mo per idle EIP",
    },

    # ── C12 — Lambda to RDS Without RDS Proxy ─────────────────────────
    {
        "id": "C-012",
        "name": "Lambda connecting to RDS without RDS Proxy",
        "description": (
            "aws_lambda_function and aws_db_instance/aws_rds_cluster coexist "
            "but no aws_db_proxy is defined. Lambda opens a new DB connection per invocation. "
            "At scale this exhausts RDS connection limits, requiring a larger (more expensive) "
            "RDS instance class. RDS Proxy pools connections and allows using a smaller instance."
        ),
        "severity": "FAIL",
        "cross_resource": True,
        "est_saving": "1–2 RDS instance size reduction ($50–500/mo)",
    },

    # ── C13 — Reserved Capacity Missing ───────────────────────────────
    {
        "id": "C-013",
        "name": "No reserved capacity for stable long-running resources",
        "description": (
            "RDS or ElastiCache instances are defined without corresponding reserved instance "
            "resources. On-demand pricing for stable workloads costs 40–60% more than 1-year "
            "reserved pricing. Flag for FinOps review if these resources run 24/7."
        ),
        "severity": "INFO",
        "cross_resource": False,
        "est_saving": "40–60% on RDS/ElastiCache/Redshift",
    },

    # ── C14 — Multi-AZ on Non-Production ──────────────────────────────
    {
        "id": "C-014",
        "name": "Multi-AZ RDS enabled on what appears to be non-production",
        "description": (
            "aws_db_instance with multi_az = true. Multi-AZ doubles RDS cost. "
            "Verify this is intentional for production — non-prod environments rarely require it."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "50% RDS cost in non-prod environments",
    },

    # ── C15 — Missing S3 Intelligent Tiering ──────────────────────────
    {
        "id": "C-015",
        "name": "Large S3 buckets without Intelligent-Tiering",
        "description": (
            "S3 buckets exist but no lifecycle rule transitions objects to S3 Intelligent-Tiering. "
            "For buckets with unpredictable access patterns, Intelligent-Tiering automatically moves "
            "objects between tiers and can save 40–68% on storage costs."
        ),
        "severity": "INFO",
        "cross_resource": False,
        "est_saving": "40–68% on infrequently accessed S3 objects",
    },

    # ── C16 — Step Functions STANDARD vs EXPRESS ───────────────────────
    {
        "id": "C-016",
        "name": "Step Functions using STANDARD type for high-volume workflows",
        "description": (
            "aws_sfn_state_machine with type = \"STANDARD\" (or default) for workflows that run "
            "at high frequency. STANDARD costs $0.025 per 1,000 state transitions. EXPRESS costs "
            "$0.00001 per invocation + $0.00001667 per GB-second. At 1M executions/day, "
            "STANDARD costs ~$750/mo vs EXPRESS ~$1/mo."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "10–1000x cost reduction for high-volume workflows",
    },

    # ── C17 — API Gateway Caching Disabled ────────────────────────────
    {
        "id": "C-017",
        "name": "API Gateway stage with caching disabled",
        "description": (
            "aws_api_gateway_stage defined without cache_cluster_enabled = true. "
            "Every API request invokes the backend Lambda or integration. For read-heavy APIs "
            "with cacheable responses, enabling API Gateway caching ($0.02/hr for 0.5 GB cache) "
            "can eliminate 50–90% of Lambda invocations."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "50–90% Lambda invocation cost for read-heavy APIs",
    },

    # ── C18 — SQS Short Polling ────────────────────────────────────────
    {
        "id": "C-018",
        "name": "SQS queue using short polling (receive_wait_time_seconds = 0)",
        "description": (
            "aws_sqs_queue with receive_wait_time_seconds = 0 (default) uses short polling. "
            "Short polling returns immediately even when the queue is empty, generating "
            "empty API calls billed at $0.40/million requests. "
            "Set receive_wait_time_seconds = 20 (long polling) to eliminate empty calls."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "$5–50/mo per high-traffic queue",
    },

    # ── C19 — ECR Without Lifecycle Policy ────────────────────────────
    {
        "id": "C-019",
        "name": "ECR repository without lifecycle policy",
        "description": (
            "aws_ecr_repository defined without a corresponding aws_ecr_lifecycle_policy. "
            "Container images accumulate silently — each tag pushed retains all layers. "
            "A busy CI/CD pipeline pushing daily can accumulate hundreds of GB at $0.10/GB/month. "
            "Add a lifecycle policy to expire untagged images after 1 day and keep only the last N tagged images."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "$10–200/mo depending on image churn rate",
    },

    # ── C20 — Kinesis Fixed Shards vs On-Demand ───────────────────────
    {
        "id": "C-020",
        "name": "Kinesis Data Stream with fixed shard count (not On-Demand)",
        "description": (
            "aws_kinesis_stream with a fixed shard_count and no stream_mode_details block "
            "setting stream_mode = \"ON_DEMAND\". Fixed shards are billed at $0.015/shard-hr "
            "regardless of utilization. On-Demand mode scales automatically and charges only "
            "for actual throughput used. For variable traffic, On-Demand saves 40–80% over fixed shards."
        ),
        "severity": "WARN",
        "cross_resource": False,
        "est_saving": "40–80% Kinesis cost for variable workloads",
    },

    # ── C21 — ECS/EKS No Spot Instances ───────────────────────────────
    {
        "id": "C-021",
        "name": "ECS/EKS workloads using on-demand only (no Spot capacity)",
        "description": (
            "aws_ecs_service defined without a FARGATE_SPOT capacity_provider_strategy, "
            "or aws_eks_node_group without capacity_type = \"SPOT\". "
            "Fargate Spot is 60–70% cheaper than on-demand for stateless, interruption-tolerant workloads. "
            "A mixed strategy (70% Spot, 30% on-demand) saves 40–50% overall with minimal availability risk."
        ),
        "severity": "WARN",
        "cross_resource": True,
        "est_saving": "40–70% on Fargate/EC2 compute cost",
    },
]

PILLAR_NAME = "Cost Optimization"
