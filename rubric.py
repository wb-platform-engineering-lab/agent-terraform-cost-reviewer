"""
Cost review rubric for the Terraform Cost Reviewer.

Each check defines:
  - id:           unique identifier
  - name:         short name
  - description:  what the reviewer looks for
  - severity:     FAIL | WARN | INFO
  - patterns:     regex patterns that indicate the check PASSES
  - anti_patterns: regex patterns that indicate a problem
  - cross_resource: True if this check requires graph reasoning across resources
  - est_saving:   rough monthly saving estimate
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
        "patterns": [],
        "anti_patterns": [r'resource\s+"aws_nat_gateway"'],
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
        "patterns": [r'resource\s+"aws_vpc_endpoint"'],
        "anti_patterns": [],
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
        "patterns": [r'resource\s+"aws_lambda_event_source_mapping"'],
        "anti_patterns": [r'resource\s+"aws_cloudwatch_event_rule"'],
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
        "patterns": [r"retention_in_days\s*=\s*[1-9]"],
        "anti_patterns": [],
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
        "patterns": [r'resource\s+"aws_s3_bucket_lifecycle_configuration"'],
        "anti_patterns": [],
        "cross_resource": True,
        "est_saving": "20–80% S3 storage cost",
    },

    # ── C6 — EBS gp2 Volumes ──────────────────────────────────────────
    {
        "id": "C-006",
        "name": "EBS / RDS volumes using gp2 instead of gp3",
        "description": (
            "aws_ebs_volume or aws_db_instance resources using type = \"gp2\". "
            "gp3 provides the same baseline performance (3,000 IOPS, 125 MB/s throughput) "
            "at 20% lower cost with no architecture change required."
        ),
        "severity": "WARN",
        "patterns": [r'type\s*=\s*"gp3"'],
        "anti_patterns": [r'type\s*=\s*"gp2"'],
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
        "patterns": [r"compress\s*=\s*true"],
        "anti_patterns": [r"compress\s*=\s*false"],
        "cross_resource": False,
        "est_saving": "20–80% CloudFront bandwidth cost",
    },

    # ── C8 — Fargate Over-provisioned ─────────────────────────────────
    {
        "id": "C-008",
        "name": "Fargate tasks hardcoded at maximum CPU/memory",
        "description": (
            "aws_ecs_task_definition with cpu = \"4096\" or memory = \"8192\" as defaults. "
            "Fargate billing is per vCPU-hour and GB-hour. Over-provisioned tasks "
            "for workloads that don't need this capacity waste 30–70% of compute cost. "
            "Profile actual usage and right-size."
        ),
        "severity": "WARN",
        "patterns": [],
        "anti_patterns": [r'cpu\s*=\s*"?4096"?'],
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
        "patterns": [],
        "anti_patterns": [r"memory_size\s*=\s*3008"],
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
        "patterns": [
            r'billing_mode\s*=\s*"PAY_PER_REQUEST"',
            r'resource\s+"aws_appautoscaling_target"',
        ],
        "anti_patterns": [r'billing_mode\s*=\s*"PROVISIONED"'],
        "cross_resource": True,
        "est_saving": "40–80% DynamoDB cost at variable traffic",
    },

    # ── C11 — Elastic IP Orphans ───────────────────────────────────────
    {
        "id": "C-011",
        "name": "Elastic IPs allocated without guaranteed association",
        "description": (
            "aws_eip resources defined without a clear association to a running resource "
            "(NAT Gateway or EC2 instance). AWS charges $0.005/hr (~$3.65/mo) for every "
            "allocated EIP not attached to a running instance."
        ),
        "severity": "WARN",
        "patterns": [r'resource\s+"aws_eip_association"', r'instance\s*=\s*aws_instance'],
        "anti_patterns": [r'resource\s+"aws_eip"'],
        "cross_resource": True,
        "est_saving": "$3.65/mo per idle EIP",
    },

    # ── C12 — Lambda to RDS Without RDS Proxy ─────────────────────────
    {
        "id": "C-012",
        "name": "Lambda connecting to RDS without RDS Proxy",
        "description": (
            "aws_lambda_function references an RDS endpoint (via environment variables or SSM) "
            "but no aws_db_proxy is defined. Lambda opens a new DB connection per invocation. "
            "At scale this exhausts RDS connection limits, requiring a larger (more expensive) "
            "RDS instance class. RDS Proxy pools connections and allows using a smaller instance."
        ),
        "severity": "FAIL",
        "patterns": [r'resource\s+"aws_db_proxy"'],
        "anti_patterns": [],
        "cross_resource": True,
        "est_saving": "1–2 RDS instance size reduction ($50–500/mo)",
    },

    # ── C13 — Reserved Capacity Missing ───────────────────────────────
    {
        "id": "C-013",
        "name": "No reserved capacity for stable long-running resources",
        "description": (
            "RDS, ElastiCache, or Redshift instances are defined without corresponding "
            "reserved instance purchase comments or aws_rds_reserved_instance resources. "
            "On-demand pricing for stable workloads costs 40–60% more than 1-year reserved pricing. "
            "Flag for FinOps review if these resources run 24/7."
        ),
        "severity": "INFO",
        "patterns": [r"reserved", r"aws_rds_reserved_instance", r"aws_elasticache_reserved_cache_node"],
        "anti_patterns": [],
        "cross_resource": False,
        "est_saving": "40–60% on RDS/ElastiCache/Redshift",
    },

    # ── C14 — Multi-AZ on Non-Production ──────────────────────────────
    {
        "id": "C-014",
        "name": "Multi-AZ RDS enabled on what appears to be non-production",
        "description": (
            "aws_db_instance with multi_az = true in a module or workspace that appears "
            "to be non-production (name/path contains 'dev', 'staging', 'test', 'sandbox'). "
            "Multi-AZ doubles RDS cost. Non-prod environments rarely require it."
        ),
        "severity": "WARN",
        "patterns": [],
        "anti_patterns": [r"multi_az\s*=\s*true"],
        "cross_resource": False,
        "est_saving": "50% RDS cost in non-prod environments",
    },

    # ── C15 — Missing S3 Intelligent Tiering ──────────────────────────
    {
        "id": "C-015",
        "name": "Large S3 buckets without Intelligent-Tiering",
        "description": (
            "S3 buckets used for data lake, archives, or ML datasets have no lifecycle rule "
            "transitioning objects to S3 Intelligent-Tiering. For buckets with unpredictable "
            "access patterns, Intelligent-Tiering automatically moves objects between tiers "
            "and can save 40–68% on storage costs."
        ),
        "severity": "INFO",
        "patterns": [r"INTELLIGENT_TIERING", r"intelligent.tiering"],
        "anti_patterns": [],
        "cross_resource": False,
        "est_saving": "40–68% on infrequently accessed S3 objects",
    },
]

PILLAR_NAME = "Cost Optimization"
