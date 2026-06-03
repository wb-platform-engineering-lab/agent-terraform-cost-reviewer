# Terraform Cost Reviewer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Powered by Claude](https://img.shields.io/badge/Powered%20by-Claude%20Haiku%204.5-blueviolet.svg)](https://www.anthropic.com)
[![Checks](https://img.shields.io/badge/cost%20checks-21-green.svg)](#what-it-catches-21-checks)
[![CI](https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer/actions/workflows/cost-review.yml/badge.svg)](https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer/actions/workflows/cost-review.yml)

An AI agent that reads your Terraform codebase and identifies **architectural cost anti-patterns** that standard security scanners like Checkov, tfsec, and Trivy cannot detect.

Powered by Claude Haiku 4.5. Produces a scored HTML report with specific file references, estimated monthly savings, and concrete fixes — across **21 checks** covering compute, storage, networking, database, and architecture patterns.

---

## The Problem

Security scanners check resources in isolation:
> "This S3 bucket has no encryption" ✓/✗

They cannot reason about **cross-resource relationships** or **architectural patterns**:
> "Your Lambda is triggered by a CloudWatch schedule that polls SQS manually. At 1M messages/day this costs ~$14/mo in unnecessary Lambda invocations. Replace with `aws_lambda_event_source_mapping` — AWS polls for free."

That's the gap this tool fills.

---

## What It Catches (21 Checks)

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
| C-016 | Step Functions `STANDARD` type for high-volume workflows (vs `EXPRESS`) | Cross-resource | 10–1000x cost reduction |
| C-017 | API Gateway stage with caching disabled — every request hits Lambda | Cross-resource | 50–90% Lambda invocations |
| C-018 | SQS short polling (`receive_wait_time_seconds = 0`) — empty API calls billed | Single-resource | $5–50/mo per high-traffic queue |
| C-019 | ECR repository without lifecycle policy — images accumulate indefinitely | Cross-resource | $10–200/mo per busy pipeline |
| C-020 | Kinesis Data Stream with fixed shard count instead of On-Demand mode | Single-resource | 40–80% Kinesis cost |
| C-021 | ECS/EKS workloads using on-demand only — no Spot capacity provider | Cross-resource | 40–70% compute cost |

---

## Quick Start

### Prerequisites

- Python 3.10+
- An Anthropic API key ([get one here](https://console.anthropic.com))

> **Cost:** a typical run uses ~15k–40k tokens with Haiku 4.5 — roughly **$0.01–0.05 per scan**.

### Install

```bash
# From GitHub
pip install git+https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer.git

# From source
git clone https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer.git
cd agent-terraform-cost-reviewer
pip install .

# macOS with Homebrew Python (externally managed environment)
python3 -m venv .venv && source .venv/bin/activate
pip install .
```

### Configure

```bash
export ANTHROPIC_API_KEY=your-key-here
```

### Run

```bash
# Review a Terraform codebase
terraform-cost-review ./path/to/your/terraform

# Fail CI if score drops below 80%
terraform-cost-review ./terraform --fail-under 80

# Quiet mode + save report to a directory
terraform-cost-review ./terraform --quiet --output-dir reports/

# Fixed output filename (predictable artifact paths in CI)
terraform-cost-review ./terraform --output-dir reports/ --output-file cost-review

# Check version
terraform-cost-review --version

# Run against the included examples
terraform-cost-review ./examples/bad_infra   # → 0/21 (all anti-patterns)
terraform-cost-review ./examples/good_infra  # → ~19/21 (near-perfect)
```

---

## How It Works

The agent runs 5 tools in sequence:

```
1. list_files           → discover all .tf files and module structure
2. build_resource_graph → parse HCL, extract resource relationships and cross-resource flags
3. run_cost_checks      → run all 21 automated checks against the codebase
4. read_file            → targeted reads on files flagged by the graph (max 2)
5. write report         → cross-reference graph + checks into findings with file/line refs
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

This graph enables findings that cross file boundaries — something rule-based scanners structurally cannot do.

---

## Output

Each run produces:

1. **Terminal output** — live findings per check as the agent runs
2. **HTML report** — richly formatted, saved to `--output-dir` if specified
3. **JSON summary** — machine-readable artifact for CI/CD integration

### HTML Report

The HTML report includes:
- Overall score and grade (PASS / AT RISK / FAIL)
- Estimated total monthly savings across all findings
- Per-finding breakdown: file references, anti-pattern explanation, fix, and estimated saving
- Prioritized action list (top 3 highest-impact fixes)

### JSON Output

The JSON report (`cost-review.json`) is written alongside the HTML report and is suitable for CI/CD parsing:

```json
{
  "score_pct": 43,
  "grade": "FAIL",
  "passing": 9,
  "failing": 12,
  "total": 21,
  "savings_label": "$200–1200/mo",
  "failing_checks": ["C-001", "C-003", "C-004", "C-005", "C-009", "C-010"],
  "action_items": [
    "Consolidate 3 NAT Gateways to a single centralized egress (C-001) — saves $200–500/mo",
    "Replace CloudWatch schedule polling with aws_lambda_event_source_mapping (C-003) — saves $14/mo",
    "Add retention_in_days to all CloudWatch log groups (C-004) — saves $5–100/mo"
  ],
  "target": "./terraform",
  "generated_at": "2026-01-15T10:23:45"
}
```

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

## CI/CD Integration

### GitHub Actions

Add `.github/workflows/cost-review.yml` to your repository:

```yaml
name: Terraform Cost Review

on:
  pull_request:
    paths: ["**.tf", "**.tfvars"]
  push:
    branches: [main]
    paths: ["**.tf", "**.tfvars"]
  workflow_dispatch:

jobs:
  cost-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: pyproject.toml

      - run: pip install git+https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer.git
      - run: mkdir -p reports/

      - name: Run cost review
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: terraform-cost-review . --quiet --output-dir reports/ --output-file cost-review --fail-under 70

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: cost-review-${{ github.run_number }}
          path: reports/
          retention-days: 30
```

Required secret: `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).

A fully-featured workflow with automatic PR comments is included at [`.github/workflows/cost-review.yml`](.github/workflows/cost-review.yml).

### GitLab CI

Add to your `.gitlab-ci.yml`:

```yaml
terraform-cost-review:
  stage: test
  image: python:3.11-slim
  before_script:
    - pip install git+https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer.git --quiet
    - mkdir -p reports/
  script:
    - terraform-cost-review . --quiet --output-dir reports/ --output-file cost-review --fail-under 70
  artifacts:
    when: always
    paths: [reports/]
    expire_in: 30 days
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes: ["**/*.tf", "**/*.tfvars"]
```

Required CI/CD variable: `ANTHROPIC_API_KEY` (Settings → CI/CD → Variables, mark as Masked).

A fully-featured pipeline with automatic MR notes is included at [`.gitlab-ci.yml`](.gitlab-ci.yml).

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Review completed successfully (or score ≥ `--fail-under` threshold) |
| `1` | Score below `--fail-under` threshold, or fatal error (missing API key, no .tf files found) |

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
| HTML scored report + JSON artifact | ❌ | ❌ | ✅ |

**This tool complements Checkov — run both.** Checkov catches security misconfigurations. This catches architectural cost inefficiencies.

---

## Project Structure

```
agent-terraform-cost-reviewer/
├── pyproject.toml                        — Package definition and entry point
├── Makefile                              — make install / make demo / make test
├── agent.py                              — Backward-compat shim (python3 agent.py still works)
├── terraform_cost_reviewer/              — Installable package
│   ├── __init__.py                       — Version
│   ├── cli.py                            — Agent loop, CLI flags, error handling
│   ├── rubric.py                         — 21 cost checks with patterns and savings estimates
│   ├── tools.py                          — list_files, read_file, build_resource_graph, run_cost_checks
│   └── report.py                         — HTML + JSON report generator (Tailwind CSS)
└── examples/
    ├── bad_infra/main.tf                 — Violates all 21 checks (score: 0%)
    └── good_infra/main.tf                — Passes all checks (score: ~90%)
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

Key settings in `terraform_cost_reviewer/cli.py`:

```python
MODEL             = "claude-haiku-4-5-20251001"  # fast and cheap for code review
MAX_ITERATIONS    = 15                            # max agent loop iterations
MAX_TOKENS_INPUT  = 80_000                        # token budget before stopping
MAX_OUTPUT_TOKENS = 6144                          # max tokens per response
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
