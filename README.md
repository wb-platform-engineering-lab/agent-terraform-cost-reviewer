# Terraform Cost Reviewer

An AI agent that reads your Terraform codebase and identifies **architectural cost anti-patterns** that standard security scanners like Checkov, tfsec, and Trivy cannot detect.

Powered by Claude (Haiku 4.5). Produces a scored HTML report with specific file references, estimated monthly savings, and concrete fixes.

---

## The Problem

Security scanners check resources in isolation:
> "This S3 bucket has no encryption" ✓/✗

They cannot reason about **cross-resource relationships** or **architectural patterns**:
> "Your Lambda is triggered by a CloudWatch schedule that polls SQS manually. At 1M messages/day this costs ~$14/mo in unnecessary Lambda invocations. Replace with `aws_lambda_event_source_mapping` — AWS polls for free."

That's the gap this tool fills.

---

## What It Catches (15 Checks)

All checks focus on cost inefficiencies that require understanding resource relationships — not just per-resource attributes.

| ID | Check | Type | Est. Saving |
|---|---|---|---|
| C-001 | NAT Gateway sprawl — multiple NAT GWs without centralized egress | Cross-resource | $100–500/mo per redundant GW |
| C-002 | Lambda in VPC with no S3/DynamoDB VPC endpoints (traffic via NAT) | Cross-resource | $20–300/mo |
| C-003 | Lambda polling SQS via CloudWatch schedule instead of event-driven trigger | Cross-resource | $10–200/mo |
| C-004 | CloudWatch log groups with no `retention_in_days` | Single-resource | $5–100/mo per group |
| C-005 | S3 buckets with no lifecycle configuration | Cross-resource | 20–80% S3 storage cost |
| C-006 | EBS or RDS volumes using `gp2` instead of `gp3` | Single-resource | 20% storage cost |
| C-007 | CloudFront distribution with `compress = false` | Single-resource | 20–80% bandwidth cost |
| C-008 | Fargate tasks hardcoded at `cpu = 4096` (maximum) | Single-resource | 30–70% Fargate cost |
| C-009 | Lambda functions at `memory_size = 3008` (maximum) | Single-resource | Up to 6x Lambda cost |
| C-010 | DynamoDB `PROVISIONED` mode with no auto-scaling target | Cross-resource | 40–80% DynamoDB cost |
| C-011 | Elastic IPs allocated without guaranteed association | Cross-resource | $3.65/mo per idle EIP |
| C-012 | Lambda connecting to RDS with no RDS Proxy | Cross-resource | 1–2 RDS instance size reduction |
| C-013 | No reserved capacity for stable long-running resources | Single-resource | 40–60% on RDS/ElastiCache |
| C-014 | Multi-AZ RDS enabled on apparent non-production environments | Single-resource | 50% RDS cost in non-prod |
| C-015 | Large S3 buckets without Intelligent-Tiering lifecycle rule | Single-resource | 40–68% on infrequent objects |

---

## How It Works

The agent runs 5 tools in sequence:

```
1. list_files          → discover all .tf files and module structure
2. build_resource_graph → parse HCL, extract resource relationships and cross-resource flags
3. run_cost_checks     → run all 15 automated regex checks
4. read_file           → targeted reads on files flagged by the graph (max 2)
5. write report        → cross-reference graph + checks into findings with file/line refs
```

### The Resource Graph

`build_resource_graph` is what separates this tool from Checkov. It parses all `.tf` files and emits cross-resource flags:

```
⚠️ RISK: Lambda + SQS + CloudWatch schedule found, but NO event_source_mapping
         — possible polling anti-pattern (C-003)

⚠️ RISK: Lambda + RDS found but NO aws_db_proxy
         — connection pool exhaustion risk (C-012)

⚠️ RISK: 3 NAT Gateways defined
         — review for centralized egress opportunity (C-001)

⚠️ RISK: S3 buckets defined but NO lifecycle configuration
         — objects may accumulate indefinitely (C-005)
```

This graph is what enables findings that cross file boundaries — something rule-based scanners structurally cannot do.

---

## Output

The agent produces:

1. **Terminal output** — findings per check as it runs
2. **HTML report** — saved as `cost_review_<target>_<timestamp>.html`

The HTML report includes:
- Overall score (X/15 checks passing)
- Executive summary with total estimated monthly savings
- Per-finding breakdown with file references, anti-pattern explanation, fix, and estimated saving
- Prioritized action list (top 3 highest-impact fixes)
- Full rendered report

### Example Finding

```
### [C-003] Lambda polling SQS via schedule (not event-driven)

File:         modules/compute/main.tf:34 + modules/events/main.tf:12
Anti-pattern: aws_cloudwatch_event_rule triggers Lambda every minute to poll SQS manually.
              At 1M messages/day: ~$14.40/mo in Lambda invocations + SQS API calls.
              With event-driven trigger: ~$0.40/mo total.
Fix:          Replace aws_cloudwatch_event_rule + aws_cloudwatch_event_target with:

              resource "aws_lambda_event_source_mapping" "sqs_trigger" {
                event_source_arn = aws_sqs_queue.jobs.arn
                function_name    = aws_lambda_function.processor.arn
                batch_size       = 10
              }

Est. saving:  ~$14/mo (scales with message volume)
```

---

## Versus Checkov / tfsec / Trivy

| Capability | Checkov | tfsec | This tool |
|---|---|---|---|
| Per-resource security checks | ✅ 1000+ rules | ✅ | ❌ not the focus |
| Cross-resource relationship reasoning | Partial (graph policies) | ❌ | ✅ core feature |
| Architectural cost anti-patterns | ❌ | ❌ | ✅ |
| Estimated savings per finding | ❌ | ❌ | ✅ |
| Understands polling vs. event-driven | ❌ | ❌ | ✅ |
| Detects missing resource (e.g. no RDS Proxy) | ❌ | ❌ | ✅ |
| HTML scored report | ❌ | ❌ | ✅ |

**This tool complements Checkov — run both.** Checkov catches security misconfigurations. This catches architectural cost inefficiencies.

---

## Quick Start

### Prerequisites

- Python 3.10+
- An Anthropic API key ([get one here](https://console.anthropic.com))

### Install

```bash
git clone https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer.git
cd agent-terraform-cost-reviewer
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
```

### Run

```bash
# Against the included bad example (triggers all 15 checks)
bash run.sh

# Against your own Terraform codebase
python3 agent.py ./path/to/your/terraform

# Against the good example (passes all checks)
python3 agent.py ./examples/good_infra
```

---

## Project Structure

```
agent-terraform-cost-reviewer/
├── agent.py                   — Agent loop, system prompt, token management
├── rubric.py                  — 15 cost checks with patterns and savings estimates
├── tools.py                   — Tool implementations:
│                                  list_files, read_file, search_code,
│                                  build_resource_graph, run_cost_checks
├── report.py                  — HTML report generator (Tailwind CSS + Font Awesome)
├── requirements.txt
├── run.sh                     — Demo script
└── examples/
    ├── bad_infra/main.tf      — Intentionally violates all 15 checks
    └── good_infra/main.tf     — Passes all 15 checks
```

---

## Examples

### `examples/bad_infra/` — What Bad Looks Like

```hcl
# C-001: 3 NAT Gateways, one per AZ
resource "aws_nat_gateway" "az_a" { ... }
resource "aws_nat_gateway" "az_b" { ... }
resource "aws_nat_gateway" "az_c" { ... }

# C-003: Scheduled Lambda polling SQS instead of event-driven
resource "aws_cloudwatch_event_rule" "poll_schedule" {
  schedule_expression = "rate(1 minute)"
}

# C-009: Lambda at max memory
resource "aws_lambda_function" "processor" {
  memory_size = 3008
}

# C-010: DynamoDB provisioned with no auto-scaling
resource "aws_dynamodb_table" "sessions" {
  billing_mode   = "PROVISIONED"
  read_capacity  = 100
  write_capacity = 100
  # no aws_appautoscaling_target
}

# C-004: Log groups with no retention
resource "aws_cloudwatch_log_group" "logs" {
  name = "/aws/lambda/processor"
  # retention_in_days not set — logs accumulate forever
}
```

### `examples/good_infra/` — What Good Looks Like

```hcl
# C-001: Single centralized NAT Gateway
resource "aws_nat_gateway" "main" { ... }

# C-002: VPC endpoints for S3 and DynamoDB
resource "aws_vpc_endpoint" "s3" { ... }
resource "aws_vpc_endpoint" "dynamodb" { ... }

# C-003: Event-driven SQS trigger
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10
}

# C-009: Lambda right-sized
resource "aws_lambda_function" "processor" {
  memory_size = 512
}

# C-010: DynamoDB on-demand
resource "aws_dynamodb_table" "sessions" {
  billing_mode = "PAY_PER_REQUEST"
}

# C-004: Log groups with retention
resource "aws_cloudwatch_log_group" "logs" {
  name              = "/aws/lambda/processor"
  retention_in_days = 30
}
```

---

## Configuration

Key settings in `agent.py`:

```python
MODEL            = "claude-haiku-4-5-20251001"  # fast and cheap for code review
MAX_ITERATIONS   = 15                            # max agent loop iterations
MAX_TOKENS_INPUT = 80_000                        # token budget before stopping
MAX_OUTPUT_TOKENS = 6144                         # max tokens per response
```

To use a more capable model for large or complex codebases:

```python
MODEL = "claude-sonnet-4-6"
```

---

## Limitations

- **Static analysis only** — reviews declared Terraform code, not live infrastructure state. Drift between code and deployed resources is not detected.
- **HCL parsing is regex-based** — works for standard Terraform patterns but may miss values inside complex expressions (`var.enable_x ? "gp2" : "gp3"`).
- **Module sources not fetched** — community modules (e.g. `terraform-aws-modules/rds/aws`) are referenced but their internals are not analyzed.
- **Savings estimates are approximate** — based on typical usage patterns, not your actual traffic or pricing tier.
- **Not a replacement for Checkov** — this tool finds architectural cost issues, not security misconfigurations.

---

## Related Projects

- [agent-waf-reviewer](https://github.com/wb-platform-engineering-lab/agent-waf-reviewer) — AI agent that reviews AI agent codebases against the Well-Architected Framework for AI Agents
- [Checkov](https://github.com/bridgecrewio/checkov) — Static analysis for IaC security (complementary, not competing)
- [Infracost](https://github.com/infracost/infracost) — Cost estimation for Terraform plan output (pre-deploy cost delta, not architectural review)

---

## License

MIT
