# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-06-05

### Added

- **python-hcl2 AST parser** (`hcl_parser.py`) — replaces regex scanning with a proper HCL AST parser. Attribute values are now exact Python-typed values (`billing_mode == "PROVISIONED"`, `memory_size == 3008`, `compress is False`). Handles quoted values, nested blocks, and cross-file references correctly.

- **Plan-based analysis** (`plan_parser.py`) — run all 21 checks against `terraform show -json` output via `--plan <file>`. Variables are resolved, `for_each` is expanded, module internals are visible. No API key required — deterministic checks only. Produces a JSON report with `source`, `plan_path`, `tf_version`, `suppressed`, `warning_checks`, and `skipped_checks` fields.

- **Suppression mechanism** (`suppress.py`) — suppress expected findings via `.tfreview.yaml` or inline `# tfreview:ignore:C-014` comments. Suppressed checks are excluded from the score denominator and shown as `⊘ SKIP` in terminal and report output.

- **AWS-only scope disclosure** — tool now emits a warning when no `aws_*` resources are found in the target directory, making the scope limitation explicit rather than silent.

- **HTML report: expandable check rows** — click any check to reveal Claude's narrative, file references, and recommended fix inline. Per-check detail extracted from Claude's analysis via a second-pass parser.

- **HTML report: status breakdown** — FAIL / WARN / PASS / INFO / SKIP count cards replace the duplicate score gauge section.

- **HTML report: metadata strip** — hero section now shows file count, resource count, source/plan mode, Terraform version (plan mode), and model name. Populated via optional `metadata` dict in `generate_html()` / `save_report()`.

- **HTML report: copy button** on all code blocks (hover to reveal, uses Clipboard API).

- **SKIP check rendering** — suppressed checks displayed with `⊘ SKIP` badge and suppression reason inline.

### Changed

- `MAX_ITERATIONS` raised from 15 to 25 to handle larger repos without hitting the iteration limit before `run_cost_checks` completes.

- `run_cost_checks` now accepts `suppressions` and `parsed` parameters — suppressions exclude checks from the score denominator; `parsed` allows passing a pre-loaded plan result.

- `save_report()` and `generate_html()` accept an optional `metadata: dict` parameter for the new metadata strip.

- Savings badge edge case: shows "See full report below" instead of misleading "N/A · 0 issues found" when a run fails to complete.

### Fixed

- hcl2 v8 quirk: resource type/name labels include surrounding double-quotes — `_strip_quotes()` applied to all resource keys.
- hcl2 v8 quirk: string attribute values include surrounding double-quotes — `_normalize_value()` strips these recursively.
- C-001 check corrected from "any NAT Gateway = fail" to "count > 1 = fail" — a single centralized NAT Gateway is the correct pattern and should pass.
- Context pruning was discarding `run_pillar_checks` tool results, causing scores to drop to 0% on subsequent iterations.

---

## [0.1.0] — 2026-05-01

### Added

- Initial release.
- 21 deterministic cost checks across compute, storage, networking, database, and architecture patterns.
- Agent loop with 5 tools: `list_files`, `build_resource_graph`, `run_cost_checks`, `read_file`, `write_report`.
- HTML report with Tailwind CSS — score gauge, priority actions, per-check findings, full agent narrative.
- JSON report for CI/CD integration.
- `--fail-under` threshold flag for CI gates.
- `--quiet`, `--output-dir`, `--output-file` flags.
- GitHub Actions and GitLab CI example workflows.
- `examples/bad_infra/` (0% score) and `examples/good_infra/` (~95% score).

[0.2.0]: https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer/releases/tag/v0.1.0
