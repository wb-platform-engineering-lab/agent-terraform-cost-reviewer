"""
Tool definitions and implementations for agent-terraform-cost-reviewer.

Tools give the agent the ability to read, search, and graph-analyze
a Terraform codebase for cost anti-patterns.
"""

import os
import re
import json


# ─────────────────────────────────────────────
# DEFINITIONS
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
            "resource relationships (e.g. Lambda→SQS, Lambda→RDS, NAT Gateway count, VPC endpoints)."
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
    Parse all .tf files and extract a cost-focused resource relationship graph.
    Returns a compact summary of resources and their relationships.
    """
    if ".." in path:
        return "Error: invalid path"

    # Collect all tf content with file tracking
    resources = {}     # type.name -> {attrs, file, lineno}
    all_content = ""

    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".terraform"]
            for f in sorted(files):
                if not f.endswith(".tf"):
                    continue
                fpath = os.path.join(root, f)
                rel = os.path.relpath(fpath, path)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    all_content += f"\n# FILE: {rel}\n" + content
                    # Extract resource blocks
                    for m in re.finditer(
                        r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', content
                    ):
                        rtype, rname = m.group(1), m.group(2)
                        key = f"{rtype}.{rname}"
                        resources[key] = {"file": rel, "attrs": {}}
                except Exception:
                    pass
    except Exception as e:
        return f"Error walking path: {e}"

    if not resources:
        return "No Terraform resource blocks found."

    # Extract key cost-relevant attributes from all content
    cost_attrs = {
        "multi_az":            r"multi_az\s*=\s*(true|false)",
        "instance_class":      r'instance_class\s*=\s*"([^"]+)"',
        "instance_type":       r'instance_type\s*=\s*"([^"]+)"',
        "billing_mode":        r'billing_mode\s*=\s*"([^"]+)"',
        "cpu":                 r'cpu\s*=\s*"?(\d+)"?',
        "memory":              r'memory\s*=\s*"?(\d+)"?',
        "memory_size":         r"memory_size\s*=\s*(\d+)",
        "compress":            r"compress\s*=\s*(true|false)",
        "retention_in_days":   r"retention_in_days\s*=\s*(\d+)",
        "volume_type":         r'type\s*=\s*"(gp2|gp3|io1|io2)"',
        "desired_count":       r"desired_count\s*=\s*(\d+)",
        "num_cache_nodes":     r"num_cache_nodes\s*=\s*(\d+)",
    }

    # Count resource types for quick summary
    type_counts = {}
    for key in resources:
        rtype = key.split(".")[0]
        type_counts[rtype] = type_counts.get(rtype, 0) + 1

    # Build graph output
    lines = [f"Resource Graph — {len(resources)} resources across {len(type_counts)} types\n"]

    # Key cost resources summary
    cost_resource_types = [
        "aws_nat_gateway", "aws_vpc_endpoint", "aws_lambda_function",
        "aws_lambda_event_source_mapping", "aws_cloudwatch_event_rule",
        "aws_db_instance", "aws_rds_cluster", "aws_db_proxy",
        "aws_dynamodb_table", "aws_appautoscaling_target",
        "aws_ecs_task_definition", "aws_ecs_service",
        "aws_cloudwatch_log_group", "aws_s3_bucket",
        "aws_s3_bucket_lifecycle_configuration",
        "aws_cloudfront_distribution", "aws_eip", "aws_eip_association",
        "aws_elasticache_cluster", "aws_elasticache_replication_group",
        "aws_sfn_state_machine", "aws_api_gateway_rest_api", "aws_api_gateway_stage",
        "aws_ecr_repository", "aws_ecr_lifecycle_policy",
        "aws_kinesis_stream", "aws_ecs_service", "aws_ecs_capacity_provider",
        "aws_eks_node_group",
    ]

    lines.append("=== Cost-Relevant Resources ===")
    for rtype in cost_resource_types:
        count = type_counts.get(rtype, 0)
        if count > 0:
            instances = [k for k in resources if k.startswith(rtype + ".")]
            lines.append(f"  {rtype}: {count} instance(s)")
            for inst in instances[:5]:
                lines.append(f"    - {inst}  [{resources[inst]['file']}]")

    lines.append("\n=== All Resource Type Counts ===")
    for rtype, count in sorted(type_counts.items()):
        lines.append(f"  {rtype}: {count}")

    # Extract key attribute values from full content
    lines.append("\n=== Key Cost Attributes Found ===")
    for attr_name, pattern in cost_attrs.items():
        found = re.findall(pattern, all_content, re.IGNORECASE)
        if found:
            unique_vals = list(dict.fromkeys(found))[:5]
            lines.append(f"  {attr_name}: {', '.join(str(v) for v in unique_vals)}")

    # Cross-resource relationship flags
    lines.append("\n=== Cross-Resource Flags ===")

    has_lambda           = "aws_lambda_function" in type_counts
    has_esm              = "aws_lambda_event_source_mapping" in type_counts
    has_schedule         = "aws_cloudwatch_event_rule" in type_counts
    has_sqs              = "aws_sqs_queue" in type_counts
    has_rds              = "aws_db_instance" in type_counts or "aws_rds_cluster" in type_counts
    has_rds_proxy        = "aws_db_proxy" in type_counts
    nat_count            = type_counts.get("aws_nat_gateway", 0)
    has_vpc_endpoint     = "aws_vpc_endpoint" in type_counts
    has_dynamo           = "aws_dynamodb_table" in type_counts
    has_autoscaling      = "aws_appautoscaling_target" in type_counts
    has_eip              = "aws_eip" in type_counts
    has_eip_assoc        = "aws_eip_association" in type_counts
    has_s3               = "aws_s3_bucket" in type_counts
    has_s3_lifecycle     = "aws_s3_bucket_lifecycle_configuration" in type_counts
    has_log_groups       = "aws_cloudwatch_log_group" in type_counts
    has_sfn              = "aws_sfn_state_machine" in type_counts
    has_sfn_express      = bool(re.search(r'type\s*=\s*"EXPRESS"', all_content, re.IGNORECASE))
    has_api_gw_stage     = "aws_api_gateway_stage" in type_counts
    has_api_caching      = bool(re.search(r"cache_cluster_enabled\s*=\s*true", all_content, re.IGNORECASE))
    has_ecr              = "aws_ecr_repository" in type_counts
    has_ecr_lifecycle    = "aws_ecr_lifecycle_policy" in type_counts
    has_kinesis          = "aws_kinesis_stream" in type_counts
    has_kinesis_ondemand = bool(re.search(r'stream_mode\s*=\s*"ON_DEMAND"', all_content, re.IGNORECASE))
    has_ecs_service      = "aws_ecs_service" in type_counts
    has_spot             = bool(re.search(r'FARGATE_SPOT|spot_price|mixed_instances_policy|capacity_type\s*=\s*"SPOT"', all_content, re.IGNORECASE))

    if has_lambda and has_sqs and has_schedule and not has_esm:
        lines.append("  ⚠️  RISK: Lambda + SQS + CloudWatch schedule found, but NO event_source_mapping — possible polling anti-pattern (C-003)")
    if has_lambda and has_rds and not has_rds_proxy:
        lines.append("  ⚠️  RISK: Lambda + RDS found but NO aws_db_proxy — connection pool exhaustion risk (C-012)")
    if nat_count > 1:
        lines.append(f"  ⚠️  RISK: {nat_count} NAT Gateways defined — review for centralized egress opportunity (C-001)")
    if has_lambda and not has_vpc_endpoint:
        lines.append("  ⚠️  RISK: Lambda resources found but NO VPC endpoints — S3/DynamoDB traffic may route through NAT (C-002)")
    if has_dynamo and not has_autoscaling:
        lines.append("  ⚠️  RISK: DynamoDB table found but NO auto-scaling target — may be paying for unused provisioned capacity (C-010)")
    if has_eip and not has_eip_assoc:
        lines.append("  ⚠️  RISK: Elastic IPs defined with no explicit association — may be idle EIPs incurring charges (C-011)")
    if has_s3 and not has_s3_lifecycle:
        lines.append("  ⚠️  RISK: S3 buckets defined but NO lifecycle configuration — objects may accumulate indefinitely (C-005)")
    if not has_log_groups:
        lines.append("  ℹ️  No explicit CloudWatch log groups defined — retention policies may not be set (C-004)")
    if has_sfn and not has_sfn_express:
        lines.append("  ⚠️  RISK: Step Functions state machine found without EXPRESS type — STANDARD is expensive at high volume (C-016)")
    if has_api_gw_stage and not has_api_caching:
        lines.append("  ⚠️  RISK: API Gateway stage found but NO caching enabled — every request invokes Lambda (C-017)")
    if has_ecr and not has_ecr_lifecycle:
        lines.append("  ⚠️  RISK: ECR repository found but NO lifecycle policy — images accumulate indefinitely (C-019)")
    if has_kinesis and not has_kinesis_ondemand:
        lines.append("  ⚠️  RISK: Kinesis stream with fixed shards — consider ON_DEMAND mode for variable traffic (C-020)")
    if has_ecs_service and not has_spot:
        lines.append("  ⚠️  RISK: ECS service found but NO Spot capacity provider — missing 60-70% compute savings (C-021)")

    return "\n".join(lines)


def run_cost_checks(path: str) -> str:
    """Run all rubric checks against the Terraform codebase and return structured findings."""
    from .rubric import CHECKS

    # Collect all Terraform source
    all_code = ""
    file_count = 0
    file_map = {}  # filename -> content

    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".terraform"]
            for f in sorted(files):
                if f.endswith(".tf"):
                    fpath = os.path.join(root, f)
                    rel = os.path.relpath(fpath, path)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                            content = fh.read()
                        all_code += f"\n# === {rel} ===\n" + content
                        file_map[rel] = content
                        file_count += 1
                    except Exception:
                        pass
    except Exception as e:
        return f"Error reading codebase: {e}"

    if not all_code:
        return "No Terraform files found."

    findings = []
    total_pass = 0

    for check in CHECKS:
        passed = False
        flagged = False

        # Check for good patterns (any match = pass)
        if check["patterns"]:
            for pat in check["patterns"]:
                if re.search(pat, all_code, re.IGNORECASE):
                    passed = True
                    break

        # Check for anti-patterns (any match = flag)
        for pat in check["anti_patterns"]:
            if re.search(pat, all_code, re.IGNORECASE):
                flagged = True
                break

        if flagged:
            status = "❌ FAIL"
        elif check["patterns"] and not passed:
            status = {"FAIL": "❌ FAIL", "WARN": "⚠️  WARN", "INFO": "ℹ️  INFO"}[check["severity"]]
        else:
            status = "✅ PASS"
            total_pass += 1

        findings.append({
            "id": check["id"],
            "name": check["name"],
            "status": status,
            "description": check["description"],
            "cross_resource": check["cross_resource"],
            "est_saving": check["est_saving"],
        })

    lines = [f"Cost checks ({file_count} .tf files scanned)\n"]
    fail_count = sum(1 for f in findings if "FAIL" in f["status"])
    warn_count = sum(1 for f in findings if "WARN" in f["status"])

    lines.append(f"Results: {total_pass}/{len(CHECKS)} passing  |  {fail_count} FAIL  |  {warn_count} WARN\n")

    for f in findings:
        cross = " [cross-resource]" if f["cross_resource"] else ""
        lines.append(f"{f['status']} [{f['id']}] {f['name']}{cross}")
        if "FAIL" in f["status"] or "WARN" in f["status"]:
            desc = f["description"][:140] + ("…" if len(f["description"]) > 140 else "")
            lines.append(f"    → {desc}")
            lines.append(f"    💰 Est. saving: {f['est_saving']}")

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
