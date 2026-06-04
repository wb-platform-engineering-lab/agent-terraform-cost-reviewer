"""
terraform-cost-reviewer CLI

Reviews a Terraform codebase for cost architectural anti-patterns —
cross-resource inefficiencies that Checkov and standard security scanners miss.

Usage (after pip install):
    terraform-cost-review <path>
    terraform-cost-review <path> --fail-under 80
    terraform-cost-review <path> --fail-under 80 --quiet --output-dir reports/

Usage (from source):
    python3 agent.py <path>
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

import anthropic

from . import __version__
from . import tools as t
from . import report as r

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MODEL = "claude-haiku-4-5-20251001"
MAX_ITERATIONS = 15
MAX_TOKENS_INPUT = 80_000
MAX_OUTPUT_TOKENS = 6144

SYSTEM_PROMPT = """You are an expert AWS cost architect reviewing a Terraform codebase for cost inefficiencies.

Your focus is EXCLUSIVELY on architectural cost anti-patterns that standard security scanners (Checkov, tfsec) cannot detect — particularly cross-resource relationships and hidden cost drivers.

You review against 21 cost checks across these categories:
- NAT Gateway sprawl and VPC traffic routing
- Event-driven vs. polling architecture patterns (Lambda/SQS)
- Storage waste (log retention, S3 lifecycle, EBS volume types, ECR image accumulation)
- Over-provisioned compute (Fargate, Lambda memory, Kinesis fixed shards)
- Database cost patterns (DynamoDB provisioning, RDS Proxy, Multi-AZ in non-prod)
- Orphaned/idle resources (Elastic IPs, unused capacity)
- Workflow and API costs (Step Functions STANDARD vs EXPRESS, API Gateway caching)
- Spot/mixed capacity opportunities (ECS/EKS Spot instances)

Your review process — follow this order strictly:
1. Call list_files to discover the Terraform module structure
2. Call build_resource_graph to extract the resource relationship map and cross-resource flags
3. Call run_cost_checks to run all 21 automated checks
4. Call read_file on at most 2 specific files flagged by the graph (only if needed to confirm a finding)
5. STOP calling tools. Write the final report immediately.

CRITICAL: After run_cost_checks returns, write the report. Do NOT keep calling read_file.

Your final report must include:
- An executive summary: total estimated monthly savings opportunity
- A finding per failing check with:
  * Specific file reference (from the resource graph)
  * What the anti-pattern is and why it costs money
  * Concrete fix (exact Terraform attribute or resource to add/change)
  * Estimated monthly saving
- A prioritized action list (top 3 highest-impact fixes)
- An overall score (X/21 checks passing)

Format each finding clearly:
### [C-XXX] Finding Name
**File:** path/to/file.tf
**Anti-pattern:** description
**Fix:** exact change
**Est. saving:** $X/mo

Only report what you observed. Do not hallucinate findings or savings estimates.
Focus on real, actionable savings — not theoretical edge cases.
"""


# ─────────────────────────────────────────────
# Pre-flight validation
# ─────────────────────────────────────────────

def _count_tf_files(path: str) -> int:
    count = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".terraform"]
        count += sum(1 for f in files if f.endswith(".tf"))
    return count


# ─────────────────────────────────────────────
# Spinner (shown only in quiet mode)
# ─────────────────────────────────────────────

class _Spinner:
    """Simple terminal spinner for quiet mode so users know the tool is alive."""

    def __init__(self, message: str):
        self._msg = message
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not self._stop.is_set():
            print(f"\r{frames[i % len(frames)]}  {self._msg}", end="", flush=True)
            i += 1
            time.sleep(0.1)
        print("\r" + " " * (len(self._msg) + 5) + "\r", end="", flush=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join()


# ─────────────────────────────────────────────
# Agent loop
# ─────────────────────────────────────────────

_TRIM_KEEP = 400


def _prune_context(messages: list, read_file_ids: set) -> None:
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    for i, msg in enumerate(messages):
        if i == last_user or msg["role"] != "user":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if (isinstance(item, dict)
                    and item.get("type") == "tool_result"
                    and item.get("tool_use_id") in read_file_ids):
                text = item.get("content", "")
                if isinstance(text, str) and len(text) > _TRIM_KEEP:
                    item["content"] = text[:_TRIM_KEEP] + f"\n... [trimmed — {len(text)} chars total]"


def run_review(target_path: str, quiet: bool = False) -> str:
    try:
        client = anthropic.Anthropic()
    except anthropic.AuthenticationError:
        print("Error: invalid ANTHROPIC_API_KEY — check your key at console.anthropic.com", file=sys.stderr)
        sys.exit(2)

    goal = f"""Review the Terraform codebase at: {os.path.abspath(target_path)}

Identify all cost architectural anti-patterns — especially cross-resource inefficiencies
that Checkov cannot detect. Produce a complete cost review with specific findings,
file references, concrete fixes, and estimated monthly savings per issue."""

    messages = [{"role": "user", "content": goal}]
    total_tokens = 0
    iteration = 0
    read_file_ids: set = set()
    partial_text: list = []

    if not quiet:
        print(f"\n{'═'*60}")
        print(f"  Terraform Cost Reviewer  v{__version__}")
        print(f"  Target: {os.path.abspath(target_path)}")
        print(f"{'═'*60}\n")

    spinner_ctx = _Spinner("Running cost review… (this takes ~60s)") if quiet else None

    try:
        if spinner_ctx:
            spinner_ctx.__enter__()

        while iteration < MAX_ITERATIONS:
            iteration += 1
            _prune_context(messages, read_file_ids)

            try:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=SYSTEM_PROMPT,
                    tools=t.DEFINITIONS,
                    messages=messages,
                )
            except anthropic.AuthenticationError:
                print("\nError: invalid ANTHROPIC_API_KEY — check your key at console.anthropic.com", file=sys.stderr)
                sys.exit(2)
            except anthropic.RateLimitError:
                print("\nError: Anthropic rate limit reached — wait a moment and retry.", file=sys.stderr)
                sys.exit(2)
            except anthropic.APIStatusError as e:
                print(f"\nError: Anthropic API error ({e.status_code}): {e.message}", file=sys.stderr)
                sys.exit(2)
            except anthropic.APIConnectionError:
                print("\nError: could not reach Anthropic API — check your internet connection.", file=sys.stderr)
                sys.exit(2)

            total_tokens += response.usage.input_tokens + response.usage.output_tokens
            if not quiet:
                print(f"[iter {iteration}] stop_reason={response.stop_reason}  tokens={total_tokens:,}")

            if total_tokens > MAX_TOKENS_INPUT:
                return f"[Token budget exceeded at iteration {iteration}] Partial review available."

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        partial_text.append(block.text)
                return "\n".join(partial_text) if partial_text else "Review complete — no text response generated."

            if response.stop_reason == "max_tokens":
                for block in response.content:
                    if hasattr(block, "text"):
                        partial_text.append(block.text)
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": "Please continue your response."})
                continue

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if not quiet:
                        print(f"         tool: {block.name}({list(block.input.keys())})")
                    result = t.dispatch(block.name, block.input)
                    if block.name == "read_file":
                        read_file_ids.add(block.id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if not tool_results:
                continue

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    finally:
        if spinner_ctx:
            spinner_ctx.__exit__(None, None, None)

    return f"Review did not complete within {MAX_ITERATIONS} iterations."


# ─────────────────────────────────────────────
# Plan-based review (deterministic, no Claude)
# ─────────────────────────────────────────────

def run_plan_review(plan_path: str, target_path: str, quiet: bool = False) -> dict:
    """
    Run the 21 cost checks against a terraform show -json plan file.

    Returns a structured results dict. No API key required — purely deterministic.
    """
    from .plan_parser import parse_plan_file, plan_summary
    from .suppress import load_suppressions
    from .hcl_parser import by_type_index
    from .rubric import CHECKS
    from . import tools as t

    parsed = parse_plan_file(plan_path)
    sups = load_suppressions(target_path)

    if not quiet:
        print(f"\n{'═'*60}")
        print(f"  Terraform Cost Reviewer  v{__version__}  [plan mode]")
        print(f"  Plan:   {os.path.abspath(plan_path)}")
        print(f"  Target: {os.path.abspath(target_path)}")
        print(f"{'═'*60}")
        print(f"  {plan_summary(parsed)}")
        if parsed["parse_errors"]:
            for e in parsed["parse_errors"]:
                print(f"  ⚠  {e}")
        if sups:
            print(f"  Suppressions active: {', '.join(sorted(sups.keys()))}")
        print()

    checks_output = t.run_cost_checks(target_path, suppressions=sups, parsed=parsed)

    if not quiet:
        print(checks_output)

    byt = by_type_index(parsed)
    active = [c for c in CHECKS if c["id"] not in sups]
    suppressed = [c for c in CHECKS if c["id"] in sups]
    total_pass = 0
    failing, warning, skipped_ids = [], [], []

    for check in active:
        status_key, _ = t._evaluate_check(check["id"], byt)
        if status_key == "pass":
            total_pass += 1
        elif status_key == "fail":
            failing.append(check["id"])
        elif status_key == "warn":
            warning.append(check["id"])

    for check in suppressed:
        skipped_ids.append(check["id"])

    denom = len(active)
    score_pct = int(total_pass / denom * 100) if denom else 0
    grade = "PASS" if score_pct >= 75 else ("AT RISK" if score_pct >= 40 else "FAIL")

    return {
        "score_pct":       score_pct,
        "grade":           grade,
        "passing":         total_pass,
        "total":           denom,
        "suppressed":      len(skipped_ids),
        "source":          "plan",
        "plan_file":       os.path.abspath(plan_path),
        "tf_version":      parsed.get("tf_version"),
        "failing_checks":  failing,
        "warning_checks":  warning,
        "skipped_checks":  skipped_ids,
        "savings_label":   "N/A — use Infracost for precise cost deltas",
        "action_items":    [],
    }


# ─────────────────────────────────────────────
# JSON summary
# ─────────────────────────────────────────────

def _write_json_summary(review_text: str, target_path: str, html_path: str, output_dir: str, base_name: str | None = None) -> str:
    data = r.parse_report(review_text)
    score = data["overall_score"] or (0, 21)
    score_pct = int(score[0] / score[1] * 100) if score[1] else 0
    savings = data.get("savings_summary", {})

    failing = [c["id"] for p in data["pillars"] for c in p["checks"] if c["status"] == "fail"]
    warning = [c["id"] for p in data["pillars"] for c in p["checks"] if c["status"] == "warn"]
    grade = "PASS" if score_pct >= 75 else ("AT RISK" if score_pct >= 40 else "FAIL")

    summary = {
        "score_pct":      score_pct,
        "passing":        score[0],
        "total":          score[1],
        "grade":          grade,
        "savings_label":  savings.get("label", "N/A"),
        "failing_checks": failing,
        "warning_checks": warning,
        "action_items":   data["action_items"],
        "html_report":    os.path.basename(html_path),
    }

    if base_name:
        stem = base_name
    else:
        target_name = os.path.basename(os.path.abspath(target_path))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"cost_review_{target_name}_{ts}"

    json_path = os.path.join(output_dir, f"{stem}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return json_path


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="terraform-cost-review",
        description="Terraform cost architecture reviewer — finds cross-resource cost anti-patterns.",
    )
    parser.add_argument("target", help="Path to Terraform codebase directory")
    parser.add_argument(
        "--fail-under", type=int, default=None, metavar="N",
        help="Exit 1 if the score is below N%% (e.g. --fail-under 80). Default: always exit 0.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress progress output. Shows a spinner instead. Only prints the CI summary line.",
    )
    parser.add_argument(
        "--output-dir", default=".", metavar="DIR",
        help="Directory to write HTML + JSON reports. Default: current directory.",
    )
    parser.add_argument(
        "--output-file", default=None, metavar="NAME",
        help="Base filename for reports (without extension). Default: cost_review_<name>_<timestamp>.",
    )
    parser.add_argument(
        "--plan", default=None, metavar="FILE",
        help=(
            "Path to terraform show -json output (plan.json). "
            "Enables plan-based analysis: variable references and for_each are fully resolved. "
            "Runs deterministic checks only — no AI narration, no API key required. "
            "Generate with: terraform plan -out=plan.tfplan && terraform show -json plan.tfplan > plan.json"
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)

    # ── Validate target directory ─────────────────────────────────────
    if not os.path.isdir(args.target):
        print(f"Error: '{args.target}' is not a directory", file=sys.stderr)
        sys.exit(2)

    os.makedirs(args.output_dir, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────
    # PLAN MODE — deterministic, no Claude, no API key required
    # ─────────────────────────────────────────────────────────────────
    if args.plan:
        if not os.path.isfile(args.plan):
            print(f"Error: plan file '{args.plan}' not found.", file=sys.stderr)
            sys.exit(2)

        results = run_plan_review(args.plan, args.target, quiet=args.quiet)

        # Write JSON report
        base = args.output_file or "cost-review-plan"
        json_path = os.path.join(args.output_dir, f"{base}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        score_pct = results["score_pct"]
        suppressed_note = f"  suppressed={results['suppressed']}" if results["suppressed"] else ""
        print(
            f"\n[cost-review] score={score_pct}%  "
            f"passing={results['passing']}/{results['total']}  "
            f"failures={len(results['failing_checks'])}"
            f"{suppressed_note}  "
            f"source=plan  json={json_path}"
        )

        if args.fail_under is not None and score_pct < args.fail_under:
            print(
                f"[cost-review] FAILED — score {score_pct}% is below threshold {args.fail_under}%",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(0)

    # ─────────────────────────────────────────────────────────────────
    # SOURCE MODE — AI-assisted review via Claude agent loop
    # ─────────────────────────────────────────────────────────────────

    # Validate API key (only needed for source mode)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY is not set.\n"
            "Export it with: export ANTHROPIC_API_KEY=your-key\n"
            "Get a key at: https://console.anthropic.com\n"
            "Tip: for plan-based analysis without an API key, use --plan plan.json",
            file=sys.stderr,
        )
        sys.exit(2)

    tf_count = _count_tf_files(args.target)
    if tf_count == 0:
        print(
            f"Error: no .tf files found in '{args.target}'.\n"
            f"Point terraform-cost-review at a directory containing Terraform code.",
            file=sys.stderr,
        )
        sys.exit(2)

    if not args.quiet:
        print(f"Found {tf_count} .tf file(s) — starting review…")

    review = run_review(args.target, quiet=args.quiet)

    if not args.quiet:
        print(f"\n{'═'*60}")
        print("  COST REVIEW REPORT")
        print(f"{'═'*60}\n")
        print(review)

    html_path = r.save_report(review, args.target, output_dir=args.output_dir, base_name=args.output_file)
    json_path = _write_json_summary(review, args.target, html_path, output_dir=args.output_dir, base_name=args.output_file)

    data = r.parse_report(review)
    score = data["overall_score"] or (0, 21)
    score_pct = int(score[0] / score[1] * 100) if score[1] else 0
    savings = data.get("savings_summary", {})
    failing_count = sum(1 for p in data["pillars"] for c in p["checks"] if c["status"] == "fail")

    print(
        f"\n[cost-review] score={score_pct}%  "
        f"passing={score[0]}/{score[1]}  "
        f"failures={failing_count}  "
        f"savings={savings.get('label', 'N/A')}  "
        f"html={html_path}  json={json_path}"
    )

    if args.fail_under is not None and score_pct < args.fail_under:
        print(
            f"[cost-review] FAILED — score {score_pct}% is below threshold {args.fail_under}%",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.exit(0)
