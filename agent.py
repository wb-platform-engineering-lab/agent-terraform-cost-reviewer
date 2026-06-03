"""
agent-terraform-cost-reviewer

Reviews a Terraform codebase for cost architectural anti-patterns —
cross-resource inefficiencies that Checkov and standard security scanners miss.

Usage:
    python3 agent.py ./path/to/terraform
    python3 agent.py ./examples/bad_infra
    python3 agent.py ./examples/good_infra
"""

import os
import sys
import anthropic
import tools as t
import report as r

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MODEL = "claude-haiku-4-5-20251001"
MAX_ITERATIONS = 15
MAX_TOKENS_INPUT = 80_000
MAX_OUTPUT_TOKENS = 6144

SYSTEM_PROMPT = """You are an expert AWS cost architect reviewing a Terraform codebase for cost inefficiencies.

Your focus is EXCLUSIVELY on architectural cost anti-patterns that standard security scanners (Checkov, tfsec) cannot detect — particularly cross-resource relationships and hidden cost drivers.

You review against 15 cost checks across these categories:
- NAT Gateway sprawl and VPC traffic routing
- Event-driven vs. polling architecture patterns (Lambda/SQS)
- Storage waste (log retention, S3 lifecycle, EBS volume types)
- Over-provisioned compute (Fargate, Lambda memory)
- Database cost patterns (DynamoDB provisioning, RDS Proxy, Multi-AZ in non-prod)
- Orphaned/idle resources (Elastic IPs, unused capacity)

Your review process — follow this order strictly:
1. Call list_files to discover the Terraform module structure
2. Call build_resource_graph to extract the resource relationship map and cross-resource flags
3. Call run_cost_checks to run all 15 automated checks
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
- An overall score (X/15 checks passing)

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
# Agent loop
# ─────────────────────────────────────────────

_TRIM_KEEP = 400


def _prune_context(messages: list, read_file_ids: set) -> None:
    """Trim read_file tool results in old turns to keep context lean."""
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


def run_review(target_path: str) -> str:
    client = anthropic.Anthropic()

    goal = f"""Review the Terraform codebase at: {os.path.abspath(target_path)}

Identify all cost architectural anti-patterns — especially cross-resource inefficiencies
that Checkov cannot detect. Produce a complete cost review with specific findings,
file references, concrete fixes, and estimated monthly savings per issue."""

    messages = [{"role": "user", "content": goal}]
    total_tokens = 0
    iteration = 0
    read_file_ids: set = set()
    partial_text: list = []

    print(f"\n{'═'*60}")
    print(f"  Terraform Cost Reviewer")
    print(f"  Target: {os.path.abspath(target_path)}")
    print(f"{'═'*60}\n")

    while iteration < MAX_ITERATIONS:
        iteration += 1
        _prune_context(messages, read_file_ids)

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            tools=t.DEFINITIONS,
            messages=messages,
        )

        total_tokens += response.usage.input_tokens + response.usage.output_tokens
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

    return f"Review did not complete within {MAX_ITERATIONS} iterations."


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agent.py <path-to-terraform-codebase>")
        print("       python3 agent.py ./examples/bad_infra")
        print("       python3 agent.py ./examples/good_infra")
        sys.exit(1)

    target = sys.argv[1]
    if not os.path.isdir(target):
        print(f"Error: '{target}' is not a directory")
        sys.exit(1)

    review = run_review(target)

    print(f"\n{'═'*60}")
    print("  COST REVIEW REPORT")
    print(f"{'═'*60}\n")
    print(review)

    output_path = r.save_report(review, target, output_dir=".")
    print(f"\n{'═'*60}")
    print(f"  HTML report saved: {output_path}")
    print(f"{'═'*60}")
