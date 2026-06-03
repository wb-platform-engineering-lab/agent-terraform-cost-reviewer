"""
Tool definitions and implementations for agent-terraform-cost-reviewer.

Tools give the agent the ability to read, search, and graph-analyse
a Terraform codebase for cost anti-patterns.

All structural analysis (build_resource_graph, run_cost_checks) uses the
hcl_parser module which parses HCL with python-hcl2 rather than regex on raw
text. This means attribute values are real Python types (bool, int, str) and
resource counts are exact, eliminating false positives from comments and
variable names.
"""

import os
import re

from .hcl_parser import (
    parse_terraform_dir,
    by_type_index,
    get_attr,
    get_list_attr,
)


# ─────────────────────────────────────────────
# TOOL DEFINITIONS (for the Claude agent loop)
# ─────────────────────────────────────────────

DEFINITIONS = [
    {
        "name": "list_files",
        "description": (
            "List all Terraform (.tf, .tfvars) files in a directory recursively. "
            "Use this first to discover the module structure of the Terraform codebase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to scan for Terraform files.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a Terraform file. "
            "Use this to examine specific .tf files flagged by build_resource_graph or run_cost_checks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search for a pattern across all Terraform files in a directory. "
            "Use this to check whether a specific resource type or attribute exists anywhere."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory to search in.",
                },
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for.",
                },
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "build_resource_graph",
        "description": (
            "Parse all Terraform files in the target directory and extract a resource relationship graph. "
            "Returns a structured map of all AWS resources, their key cost-relevant attributes, "
            "and cross-resource references. Use this BEFORE run_cost_checks to understand "
            "resource relationships (e.g. Lambda→SQS, Lambda→RDS, NAT Gateway count, VPC endpoints). "
            "Parsing uses python-hcl2, so attribute values are exact (not regex estimates)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The root directory of the Terraform codebase.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_cost_checks",
        "description": (
            "Run all 21 automated cost checks against the Terraform codebase at the given path. "
            "Returns structured findings per check with pass/fail status. "
            "Call this after build_resource_graph to get the automated baseline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The root directory of the Terraform codebase to review.",
                }
            },
            "required": ["path"],
        },
    },
]


# ─────────────────────────────────────────────
# IMPLEMENTATIONS
# ─────────────────────────────────────────────

def list_files(path: str) -> str:
    """List all Terraform files in a directory recursively."""
    if ".." in path:
        return "Error: invalid path"

    extensions = (".tf", ".tfvars", ".tfvars.json")
    found = []
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in (".terraform", "__pycache__", "node_modules", ".git")
            ]
            for f in files:
                if f.endswith(extensions):
                    rel = os.path.relpath(os.path.join(root, f), path)
                    found.append(rel)
    except Exception as e:
        return f"Error: {e}"

    if not found:
        return f"No Terraform files found in {path}"
    return f"Found {len(found)} Terraform files:\n" + "\n".join(sorted(found))


def read_file(path: str, max_chars: int = 6000) -> str:
    """Read a file, truncating if it exceeds max_chars."""
    if ".." in path:
        return "Error: invalid path"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n... [truncated — {len(content)} total chars]"
        return content
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def search_code(path: str, pattern: str) -> str:
    """Search for a regex pattern across all Terraform files in a directory."""
    if ".." in path:
        return "Error: invalid path"

    matches = []
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".terraform"]
            for f in files:
                if f.endswith((".tf", ".tfvars")):
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                            for lineno, line in enumerate(fh, 1):
                                if re.search(pattern, line, re.IGNORECASE):
                                    rel = os.path.relpath(fpath, path)
                                    matches.append(f"{rel}:{lineno}: {line.rstrip()}")
                    except Exception:
                        pass
    except Exception as e:
        return f"Error: {e}"

    if not matches:
        return f"Pattern '{pattern}' not found in {path}"
    if len(matches) > 40:
        matches = matches[:40] + [f"... [{len(matches) - 40} more matches]"]
    return "\n".join(matches)


def build_resource_graph(path: str) -> str:
    """
    Parse all .tf files with hcl2 and emit a cost-focused resource graph.
    Attribute values are exact Python types, not regex estimates.
    """
    if ".." in path:
        return "Error: invalid path"

    parsed = parse_terraform_dir(path)
    resources = parsed["resources"]

    if not resources and not parsed["parse_errors"]:
        return "No Terraform resource blocks found."

    byt = by_type_index(parsed)
    type_counts = {t: len(v) for t, v in byt.items()}
    total = len(resources)

    lines = [
        f"Resource Graph — {total} resources across {len(type_counts)} types "
        f"({parsed['file_count']} .tf files parsed)"
    ]

    if parsed["parse_errors"]:
        lines.append(f"\n⚠️  Parse warnings ({len(parsed['parse_errors'])} file(s)):")
        for err in parsed["parse_errors"][:5]:
            lines.append(f"  {err}")

    # ── Cost-relevant resource summary ────────────────────────────────
    COST_TYPES = [
        "aws_nat_gateway", "aws_vpc_endpoint",
        "aws_lambda_function", "aws_lambda_event_source_mapping",
        "aws_cloudwatch_event_rule",
        "aws_db_instance", "aws_rds_cluster", "aws_db_proxy",
        "aws_dynamodb_table", "aws_appautoscaling_target",
        "aws_ecs_task_definition", "aws_ecs_service", "aws_ecs_capacity_provider",
        "aws_eks_node_group",
        "aws_cloudwatch_log_group",
        "aws_s3_bucket", "aws_s3_bucket_lifecycle_configuration",
        "aws_cloudfront_distribution",
        "aws_eip", "aws_eip_association",
        "aws_elasticache_cluster", "aws_elasticache_replication_group",
        "aws_sfn_state_machine", "aws_api_gateway_stage",
        "aws_ecr_repository", "aws_ecr_lifecycle_policy",
        "aws_kinesis_stream",
    ]

    lines.append("\n=== Cost-Relevant Resources ===")
    for rtype in COST_TYPES:
        if rtype not in type_counts:
            continue
        instances = byt[rtype]
        lines.append(f"  {rtype}: {len(instances)}")
        for res in instances[:4]:
            # Show key attribute values where available
            attrs = res["attrs"]
            detail_parts = []
            for attr in ("memory_size", "billing_mode", "retention_in_days",
                         "multi_az", "type", "storage_type", "cpu", "memory",
                         "stream_mode", "cache_cluster_enabled",
                         "receive_wait_time_seconds"):
                val = get_attr(attrs, attr)
                if val is not None:
                    detail_parts.append(f"{attr}={val!r}")
            detail = f"  ({', '.join(detail_parts)})" if detail_parts else ""
            lines.append(f"    - {res['type']}.{res['name']}  [{res['file']}]{detail}")

    lines.append("\n=== All Resource Type Counts ===")
    for rtype, count in sorted(type_counts.items()):
        lines.append(f"  {rtype}: {count}")

    # ── Key attribute values ──────────────────────────────────────────
    lines.append("\n=== Key Cost Attributes ===")

    for res in byt.get("aws_lambda_function", [])[:3]:
        mem = get_attr(res["attrs"], "memory_size")
        if mem is not None:
            lines.append(f"  Lambda {res['name']}: memory_size={mem}")

    for res in byt.get("aws_ecs_task_definition", [])[:3]:
        cpu = get_attr(res["attrs"], "cpu")
        mem = get_attr(res["attrs"], "memory")
        if cpu or mem:
            lines.append(f"  ECS task {res['name']}: cpu={cpu}, memory={mem}")

    for res in byt.get("aws_dynamodb_table", [])[:3]:
        mode = get_attr(res["attrs"], "billing_mode")
        if mode:
            lines.append(f"  DynamoDB {res['name']}: billing_mode={mode!r}")

    for res in byt.get("aws_cloudwatch_log_group", [])[:5]:
        ret = get_attr(res["attrs"], "retention_in_days")
        lines.append(f"  LogGroup {res['name']}: retention_in_days={ret!r}")

    for res in byt.get("aws_sqs_queue", [])[:3]:
        wait = get_attr(res["attrs"], "receive_wait_time_seconds")
        lines.append(f"  SQS {res['name']}: receive_wait_time_seconds={wait!r}")

    for res in byt.get("aws_sfn_state_machine", [])[:3]:
        sm_type = get_attr(res["attrs"], "type")
        lines.append(f"  StepFunctions {res['name']}: type={sm_type!r}")

    for res in byt.get("aws_kinesis_stream", [])[:3]:
        smd = get_attr(res["attrs"], "stream_mode_details", "stream_mode")
        shards = get_attr(res["attrs"], "shard_count")
        lines.append(f"  Kinesis {res['name']}: stream_mode={smd!r}, shard_count={shards!r}")

    # ── Cross-resource relationship flags ─────────────────────────────
    lines.append("\n=== Cross-Resource Flags ===")

    has_lambda      = "aws_lambda_function" in type_counts
    has_esm         = "aws_lambda_event_source_mapping" in type_counts
    has_schedule    = "aws_cloudwatch_event_rule" in type_counts
    has_sqs         = "aws_sqs_queue" in type_counts
    has_rds         = "aws_db_instance" in type_counts or "aws_rds_cluster" in type_counts
    has_rds_proxy   = "aws_db_proxy" in type_counts
    nat_count       = type_counts.get("aws_nat_gateway", 0)
    has_vpc_ep      = "aws_vpc_endpoint" in type_counts
    has_dynamo      = "aws_dynamodb_table" in type_counts
    has_autoscaling = "aws_appautoscaling_target" in type_counts
    has_s3          = "aws_s3_bucket" in type_counts
    has_s3_lc       = "aws_s3_bucket_lifecycle_configuration" in type_counts
    has_log_groups  = "aws_cloudwatch_log_group" in type_counts
    has_sfn         = "aws_sfn_state_machine" in type_counts
    has_api_stage   = "aws_api_gateway_stage" in type_counts
    has_ecr         = "aws_ecr_repository" in type_counts
    has_ecr_lc      = "aws_ecr_lifecycle_policy" in type_counts
    has_kinesis     = "aws_kinesis_stream" in type_counts
    has_ecs         = "aws_ecs_service" in type_counts
    has_eks         = "aws_eks_node_group" in type_counts

    # NAT sprawl
    if nat_count > 1:
        lines.append(
            f"  ⚠️  RISK: {nat_count} NAT Gateways — consider centralized egress (C-001)"
        )
    elif nat_count == 1:
        lines.append("  ✅  Single NAT Gateway (centralized egress) (C-001)")

    # VPC endpoints
    if has_lambda and not has_vpc_ep:
        lines.append(
            "  ⚠️  RISK: Lambda present but NO VPC endpoints — S3/DynamoDB via NAT (C-002)"
        )

    # SQS polling
    if has_lambda and has_sqs and has_schedule and not has_esm:
        lines.append(
            "  ⚠️  RISK: Lambda + SQS + CloudWatch schedule, NO event_source_mapping — polling anti-pattern (C-003)"
        )
    elif has_esm:
        lines.append("  ✅  aws_lambda_event_source_mapping present (event-driven) (C-003)")

    # Log retention
    if has_log_groups:
        missing_ret = [
            res for res in byt["aws_cloudwatch_log_group"]
            if get_attr(res["attrs"], "retention_in_days") is None
        ]
        if missing_ret:
            lines.append(
                f"  ⚠️  RISK: {len(missing_ret)} log group(s) without retention_in_days (C-004)"
            )

    # S3 lifecycle
    if has_s3 and not has_s3_lc:
        lines.append(
            f"  ⚠️  RISK: {type_counts['aws_s3_bucket']} S3 bucket(s), NO lifecycle configuration (C-005)"
        )

    # DynamoDB autoscaling
    if has_dynamo and not has_autoscaling:
        provisioned = [
            res for res in byt["aws_dynamodb_table"]
            if get_attr(res["attrs"], "billing_mode") == "PROVISIONED"
        ]
        if provisioned:
            lines.append(
                f"  ⚠️  RISK: {len(provisioned)} DynamoDB table(s) PROVISIONED, NO autoscaling (C-010)"
            )

    # Lambda → RDS without proxy
    if has_lambda and has_rds and not has_rds_proxy:
        lines.append(
            "  ⚠️  RISK: Lambda + RDS but NO aws_db_proxy — connection pool risk (C-012)"
        )

    # ECR lifecycle
    if has_ecr and not has_ecr_lc:
        lines.append(
            f"  ⚠️  RISK: {type_counts['aws_ecr_repository']} ECR repo(s), NO lifecycle policy (C-019)"
        )

    # Kinesis on-demand
    if has_kinesis:
        fixed = [
            res for res in byt["aws_kinesis_stream"]
            if get_attr(res["attrs"], "stream_mode_details", "stream_mode") != "ON_DEMAND"
        ]
        if fixed:
            lines.append(
                f"  ⚠️  RISK: {len(fixed)} Kinesis stream(s) with fixed shards — consider ON_DEMAND (C-020)"
            )

    # ECS without Spot
    if has_ecs:
        no_spot = []
        for svc in byt["aws_ecs_service"]:
            strategies = get_list_attr(svc["attrs"], "capacity_provider_strategy")
            has_spot = any(
                s.get("capacity_provider") == "FARGATE_SPOT"
                for s in strategies if isinstance(s, dict)
            )
            if not has_spot:
                no_spot.append(svc["name"])
        if no_spot:
            lines.append(
                f"  ⚠️  RISK: {len(no_spot)} ECS service(s) without Spot capacity — missing 60-70% savings (C-021)"
            )

    # Step Functions type
    if has_sfn:
        standard = [
            res for res in byt["aws_sfn_state_machine"]
            if get_attr(res["attrs"], "type") != "EXPRESS"
        ]
        if standard:
            lines.append(
                f"  ⚠️  RISK: {len(standard)} Step Functions state machine(s) using STANDARD type (C-016)"
            )

    # API Gateway caching
    if has_api_stage:
        no_cache = [
            res for res in byt["aws_api_gateway_stage"]
            if get_attr(res["attrs"], "cache_cluster_enabled") is not True
        ]
        if no_cache:
            lines.append(
                f"  ⚠️  RISK: {len(no_cache)} API Gateway stage(s) without caching (C-017)"
            )

    if not parsed["hcl2_available"]:
        lines.append("\n⚠️  python-hcl2 not installed — attribute values not available (run: pip install python-hcl2)")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# CHECK EVALUATORS
# ─────────────────────────────────────────────

def _evaluate_check(check_id: str, byt: dict) -> tuple[str, str]:
    """
    Evaluate one cost check against the parsed resource graph.

    Returns (status, detail) where status is one of:
      "pass"  — check satisfied
      "fail"  — definite anti-pattern detected
      "warn"  — concern detected (non-fatal)
      "info"  — advisory only
    """

    def exists(*rtypes):
        return any(t in byt for t in rtypes)

    def resources(*rtypes):
        out = []
        for t in rtypes:
            out.extend(byt.get(t, []))
        return out

    def count(rtype):
        return len(byt.get(rtype, []))

    # ── C-001: NAT Gateway sprawl ──────────────────────────────────────
    if check_id == "C-001":
        n = count("aws_nat_gateway")
        if n > 1:
            return "fail", f"{n} NAT Gateways defined — centralize to reduce cost"
        return "pass", f"{n} NAT Gateway(s) — centralized egress OK" if n == 1 else "No NAT Gateways defined"

    # ── C-002: Missing VPC endpoints ──────────────────────────────────
    if check_id == "C-002":
        if exists("aws_vpc_endpoint"):
            return "pass", f"{count('aws_vpc_endpoint')} VPC endpoint(s) defined"
        if exists("aws_lambda_function", "aws_ecs_service"):
            return "fail", "Lambda/ECS present without VPC endpoints — S3/DynamoDB traffic via NAT"
        return "pass", "No Lambda/ECS requiring VPC endpoints"

    # ── C-003: SQS polling anti-pattern ───────────────────────────────
    if check_id == "C-003":
        if exists("aws_lambda_event_source_mapping"):
            return "pass", "Event source mapping present (event-driven SQS trigger)"
        if (exists("aws_cloudwatch_event_rule")
                and exists("aws_lambda_function")
                and exists("aws_sqs_queue")):
            return "fail", "CloudWatch schedule + Lambda + SQS without event source mapping"
        return "pass", "No SQS polling anti-pattern detected"

    # ── C-004: Log group retention ────────────────────────────────────
    if check_id == "C-004":
        log_groups = byt.get("aws_cloudwatch_log_group", [])
        if not log_groups:
            return "info", "No CloudWatch log groups defined"
        missing = [
            f"{r['type']}.{r['name']}"
            for r in log_groups
            if get_attr(r["attrs"], "retention_in_days") is None
        ]
        if missing:
            sample = ", ".join(missing[:3])
            suffix = f" (and {len(missing)-3} more)" if len(missing) > 3 else ""
            return "fail", f"{len(missing)} log group(s) without retention_in_days: {sample}{suffix}"
        return "pass", f"All {len(log_groups)} log group(s) have retention_in_days set"

    # ── C-005: S3 lifecycle ───────────────────────────────────────────
    if check_id == "C-005":
        s3 = count("aws_s3_bucket")
        if not s3:
            return "pass", "No S3 buckets defined"
        if exists("aws_s3_bucket_lifecycle_configuration"):
            return "pass", f"Lifecycle configuration present for S3 buckets"
        return "warn", f"{s3} S3 bucket(s) without lifecycle configuration"

    # ── C-006: gp2 volumes ────────────────────────────────────────────
    if check_id == "C-006":
        gp2, gp3 = [], []
        for res in resources("aws_ebs_volume", "aws_db_instance",
                              "aws_rds_cluster", "aws_rds_cluster_instance"):
            # EBS uses 'type'; RDS uses 'storage_type'
            vol_type = (get_attr(res["attrs"], "storage_type")
                        or get_attr(res["attrs"], "type"))
            if vol_type == "gp2":
                gp2.append(f"{res['name']} ({res['file']})")
            elif vol_type == "gp3":
                gp3.append(res["name"])
        if gp2:
            return "fail", f"gp2 volume(s) found: {', '.join(gp2[:3])}"
        if gp3:
            return "pass", f"gp3 volume(s) in use: {', '.join(gp3[:3])}"
        return "info", "No EBS/RDS resources with explicit volume type"

    # ── C-007: CloudFront compression ────────────────────────────────
    if check_id == "C-007":
        cfds = byt.get("aws_cloudfront_distribution", [])
        if not cfds:
            return "pass", "No CloudFront distributions defined"
        for cfd in cfds:
            dcb_raw = cfd["attrs"].get("default_cache_behavior", [])
            dcb = dcb_raw[0] if isinstance(dcb_raw, list) and dcb_raw else (
                dcb_raw if isinstance(dcb_raw, dict) else {}
            )
            compress = dcb.get("compress")
            if compress is False:
                return "fail", f"CloudFront '{cfd['name']}' has compress = false"
            if compress is True:
                return "pass", f"CloudFront '{cfd['name']}' has compress = true"
        return "warn", "CloudFront distribution(s) found but compress not explicitly set"

    # ── C-008: Fargate max CPU ────────────────────────────────────────
    if check_id == "C-008":
        task_defs = byt.get("aws_ecs_task_definition", [])
        if not task_defs:
            return "pass", "No ECS task definitions defined"
        max_cpu = [
            f"{t['name']} ({t['file']})"
            for t in task_defs
            if str(get_attr(t["attrs"], "cpu") or "") == "4096"
        ]
        if max_cpu:
            return "fail", f"Max CPU (4096) on task definition(s): {', '.join(max_cpu[:3])}"
        return "pass", "No task definitions at maximum CPU"

    # ── C-009: Lambda max memory ──────────────────────────────────────
    if check_id == "C-009":
        lambdas = byt.get("aws_lambda_function", [])
        if not lambdas:
            return "pass", "No Lambda functions defined"
        max_mem = [
            fn["name"] for fn in lambdas
            if get_attr(fn["attrs"], "memory_size") == 3008
        ]
        if max_mem:
            return "fail", f"Lambda at max memory (3008 MB): {', '.join(max_mem[:3])}"
        return "pass", "No Lambda functions at maximum memory"

    # ── C-010: DynamoDB provisioned without autoscaling ───────────────
    if check_id == "C-010":
        tables = byt.get("aws_dynamodb_table", [])
        if not tables:
            return "pass", "No DynamoDB tables defined"
        has_autoscaling = exists("aws_appautoscaling_target")
        pay_per_req = [
            t for t in tables
            if get_attr(t["attrs"], "billing_mode") == "PAY_PER_REQUEST"
        ]
        provisioned = [
            t for t in tables
            if get_attr(t["attrs"], "billing_mode") == "PROVISIONED"
        ]
        if pay_per_req or has_autoscaling:
            return "pass", "DynamoDB uses PAY_PER_REQUEST or has auto-scaling"
        if provisioned:
            names = ", ".join(t["name"] for t in provisioned[:3])
            return "fail", f"PROVISIONED DynamoDB without auto-scaling: {names}"
        return "info", "DynamoDB billing mode not set (defaults to PROVISIONED — check manually)"

    # ── C-011: Elastic IP orphans ─────────────────────────────────────
    if check_id == "C-011":
        eip_count = count("aws_eip")
        if not eip_count:
            return "pass", "No Elastic IPs defined"
        # Count resources that legitimately consume an EIP
        accounted = (count("aws_nat_gateway")
                     + count("aws_instance")
                     + count("aws_eip_association"))
        if accounted >= eip_count:
            return "pass", f"{eip_count} EIP(s) appear fully utilized"
        orphans = eip_count - accounted
        return "warn", f"{eip_count} EIP(s) defined, ~{orphans} potentially unassociated"

    # ── C-012: Lambda → RDS without proxy ────────────────────────────
    if check_id == "C-012":
        if exists("aws_db_proxy"):
            return "pass", "RDS Proxy defined"
        if exists("aws_lambda_function") and exists("aws_db_instance", "aws_rds_cluster"):
            return "fail", "Lambda + RDS without RDS Proxy — connection pool exhaustion risk"
        return "pass", "No Lambda-to-RDS pattern requiring proxy"

    # ── C-013: Reserved capacity ──────────────────────────────────────
    if check_id == "C-013":
        if exists("aws_rds_reserved_instance", "aws_elasticache_reserved_cache_node"):
            return "pass", "Reserved capacity resources defined"
        if exists("aws_db_instance", "aws_rds_cluster",
                  "aws_elasticache_cluster", "aws_elasticache_replication_group"):
            return "info", "Stable RDS/ElastiCache resources without reserved capacity — consider Reserved Instances"
        return "pass", "No stable long-running resources requiring reserved capacity"

    # ── C-014: Multi-AZ on non-prod ──────────────────────────────────
    if check_id == "C-014":
        multi_az = [
            f"{r['type']}.{r['name']} ({r['file']})"
            for r in resources("aws_db_instance", "aws_rds_cluster")
            if get_attr(r["attrs"], "multi_az") is True
        ]
        if multi_az:
            return "warn", f"multi_az = true on: {', '.join(multi_az[:3])} — verify this is production"
        return "pass", "No Multi-AZ RDS resources found (or multi_az = false)"

    # ── C-015: S3 Intelligent-Tiering ────────────────────────────────
    if check_id == "C-015":
        s3 = count("aws_s3_bucket")
        if not s3:
            return "pass", "No S3 buckets defined"
        # Check lifecycle rules for INTELLIGENT_TIERING storage class
        has_it = exists("aws_s3_bucket_intelligent_tiering_configuration")
        if not has_it:
            for res in byt.get("aws_s3_bucket_lifecycle_configuration", []):
                for rule in get_list_attr(res["attrs"], "rule"):
                    if not isinstance(rule, dict):
                        continue
                    for transition in get_list_attr(rule, "transition"):
                        if (isinstance(transition, dict)
                                and transition.get("storage_class") == "INTELLIGENT_TIERING"):
                            has_it = True
        if has_it:
            return "pass", "S3 Intelligent-Tiering lifecycle rule present"
        return "info", f"{s3} S3 bucket(s) without Intelligent-Tiering — consider for data lake/archive buckets"

    # ── C-016: Step Functions STANDARD vs EXPRESS ─────────────────────
    if check_id == "C-016":
        sfn = byt.get("aws_sfn_state_machine", [])
        if not sfn:
            return "pass", "No Step Functions state machines defined"
        express = [s for s in sfn if get_attr(s["attrs"], "type") == "EXPRESS"]
        standard = [s for s in sfn if get_attr(s["attrs"], "type") != "EXPRESS"]
        if express and not standard:
            return "pass", f"Step Functions using EXPRESS type: {', '.join(s['name'] for s in express[:3])}"
        if standard:
            names = ", ".join(s["name"] for s in standard[:3])
            return "warn", f"Step Functions using STANDARD type (expensive at scale): {names}"
        return "info", "Step Functions present but type not determinable"

    # ── C-017: API Gateway caching ────────────────────────────────────
    if check_id == "C-017":
        stages = byt.get("aws_api_gateway_stage", [])
        if not stages:
            return "pass", "No API Gateway stages defined"
        disabled = [s for s in stages if get_attr(s["attrs"], "cache_cluster_enabled") is False]
        enabled  = [s for s in stages if get_attr(s["attrs"], "cache_cluster_enabled") is True]
        if disabled:
            return "warn", f"API Gateway caching disabled on: {', '.join(s['name'] for s in disabled[:3])}"
        if enabled:
            return "pass", f"API Gateway caching enabled on: {', '.join(s['name'] for s in enabled[:3])}"
        return "warn", f"{len(stages)} API Gateway stage(s) without explicit caching configuration"

    # ── C-018: SQS short polling ──────────────────────────────────────
    if check_id == "C-018":
        queues = byt.get("aws_sqs_queue", [])
        if not queues:
            return "pass", "No SQS queues defined"
        short, long_ = [], []
        for q in queues:
            wait = get_attr(q["attrs"], "receive_wait_time_seconds")
            if isinstance(wait, int) and wait == 0:
                short.append(q["name"])
            elif isinstance(wait, int) and wait > 0:
                long_.append(q["name"])
        if short:
            return "warn", f"Short polling (receive_wait_time_seconds=0) on: {', '.join(short[:3])}"
        if long_:
            return "pass", f"Long polling configured on: {', '.join(long_[:3])}"
        return "warn", f"{len(queues)} SQS queue(s) with no receive_wait_time_seconds set (defaults to short polling)"

    # ── C-019: ECR lifecycle policy ───────────────────────────────────
    if check_id == "C-019":
        ecr = count("aws_ecr_repository")
        if not ecr:
            return "pass", "No ECR repositories defined"
        if exists("aws_ecr_lifecycle_policy"):
            return "pass", f"ECR lifecycle policy defined for {ecr} repository(ies)"
        return "warn", f"{ecr} ECR repository(ies) without lifecycle policy"

    # ── C-020: Kinesis On-Demand ──────────────────────────────────────
    if check_id == "C-020":
        streams = byt.get("aws_kinesis_stream", [])
        if not streams:
            return "pass", "No Kinesis Data Streams defined"
        on_demand, fixed = [], []
        for s in streams:
            mode = get_attr(s["attrs"], "stream_mode_details", "stream_mode")
            if mode == "ON_DEMAND":
                on_demand.append(s["name"])
            else:
                shards = get_attr(s["attrs"], "shard_count")
                label = f"{s['name']} ({shards} shards)" if shards else s["name"]
                fixed.append(label)
        if on_demand and not fixed:
            return "pass", f"Kinesis ON_DEMAND mode: {', '.join(on_demand[:3])}"
        if fixed:
            return "warn", f"Kinesis fixed shards: {', '.join(fixed[:3])}"
        return "info", "Kinesis streams present but mode not determinable"

    # ── C-021: ECS/EKS without Spot ──────────────────────────────────
    if check_id == "C-021":
        ecs_svcs  = byt.get("aws_ecs_service", [])
        eks_nodes = byt.get("aws_eks_node_group", [])
        all_compute = ecs_svcs + eks_nodes
        if not all_compute:
            return "pass", "No ECS/EKS compute resources defined"

        # Check ECS for FARGATE_SPOT
        ecs_with_spot = []
        ecs_no_spot   = []
        for svc in ecs_svcs:
            strategies = get_list_attr(svc["attrs"], "capacity_provider_strategy")
            has_spot = any(
                isinstance(s, dict) and s.get("capacity_provider") == "FARGATE_SPOT"
                for s in strategies
            )
            (ecs_with_spot if has_spot else ecs_no_spot).append(svc["name"])

        # Check EKS for SPOT capacity type
        eks_with_spot = [
            n["name"] for n in eks_nodes
            if get_attr(n["attrs"], "capacity_type") == "SPOT"
        ]
        eks_no_spot = [
            n["name"] for n in eks_nodes
            if get_attr(n["attrs"], "capacity_type") != "SPOT"
        ]

        if ecs_with_spot and not ecs_no_spot and not eks_no_spot:
            return "pass", f"Spot capacity configured on: {', '.join((ecs_with_spot + eks_with_spot)[:3])}"
        no_spot_all = ecs_no_spot + eks_no_spot
        if no_spot_all:
            return "warn", f"{len(no_spot_all)} compute resource(s) without Spot capacity: {', '.join(no_spot_all[:3])}"
        return "pass", "Spot capacity configured"

    return "info", f"Unknown check id: {check_id}"


# ─────────────────────────────────────────────
# run_cost_checks
# ─────────────────────────────────────────────

def run_cost_checks(path: str) -> str:
    """Run all rubric checks against the Terraform codebase using hcl2-parsed data."""
    from .rubric import CHECKS

    parsed = parse_terraform_dir(path)
    byt = by_type_index(parsed)

    if not parsed["resources"] and not parsed["parse_errors"]:
        return "No Terraform resources found."

    lines = [f"Cost checks ({parsed['file_count']} .tf files parsed)\n"]

    if parsed["parse_errors"]:
        lines.append(f"⚠️  Parse warnings ({len(parsed['parse_errors'])} file(s) had issues):")
        for err in parsed["parse_errors"][:5]:
            lines.append(f"  {err}")
        lines.append("")

    findings = []
    total_pass = 0

    for check in CHECKS:
        status_key, detail = _evaluate_check(check["id"], byt)

        if status_key == "pass":
            total_pass += 1
            status_label = "✅ PASS"
        elif status_key == "fail":
            status_label = "❌ FAIL"
        elif status_key == "warn":
            status_label = "⚠️  WARN"
        else:
            status_label = "ℹ️  INFO"

        findings.append((status_label, check, detail))

    fail_count = sum(1 for s, _, _ in findings if "FAIL" in s)
    warn_count = sum(1 for s, _, _ in findings if "WARN" in s)
    info_count = sum(1 for s, _, _ in findings if "INFO" in s)

    lines.append(
        f"Results: {total_pass}/{len(CHECKS)} passing  |  "
        f"{fail_count} FAIL  |  {warn_count} WARN  |  {info_count} INFO\n"
    )

    for status_label, check, detail in findings:
        cross = " [cross-resource]" if check["cross_resource"] else ""
        lines.append(f"{status_label} [{check['id']}] {check['name']}{cross}")
        if "PASS" not in status_label:
            desc = check["description"][:140] + ("…" if len(check["description"]) > 140 else "")
            lines.append(f"    → {detail}")
            lines.append(f"    ℹ  {desc}")
            lines.append(f"    💰 Est. saving: {check['est_saving']}")

    lines.append(f"\nTOTAL: {total_pass}/{len(CHECKS)} checks passing")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────

def dispatch(tool_name: str, tool_input: dict) -> str:
    match tool_name:
        case "list_files":
            return list_files(tool_input.get("path", "."))
        case "read_file":
            return read_file(tool_input.get("path", ""))
        case "search_code":
            return search_code(tool_input.get("path", "."), tool_input.get("pattern", ""))
        case "build_resource_graph":
            return build_resource_graph(tool_input.get("path", "."))
        case "run_cost_checks":
            return run_cost_checks(tool_input.get("path", "."))
        case _:
            return f"Error: unknown tool '{tool_name}'"
