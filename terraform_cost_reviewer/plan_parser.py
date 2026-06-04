"""
Parser for terraform show -json output.

Produces the same resource dict format as hcl_parser.parse_terraform_dir,
enabling the same 21 checks to run against fully resolved plan values.

Key advantage over source parsing:
- Variable references are resolved  (var.storage_type → "gp3")
- for_each / count are expanded     (each instance appears separately)
- Module internals are visible      (child modules are recursed)
- No "expression skipped" gaps

Usage:
    # Generate plan JSON
    terraform plan -out=plan.tfplan
    terraform show -json plan.tfplan > plan.json

    # Run cost review against the plan
    terraform-cost-review . --plan plan.json
"""

import json
import os
from typing import Optional


def parse_plan_file(plan_path: str) -> dict:
    """
    Parse a terraform show -json plan file.

    Returns a dict in the same format as hcl_parser.parse_terraform_dir:
    {
        "resources":      { "aws_nat_gateway.main": { type, name, file, attrs } },
        "data_sources":   { ... },
        "parse_errors":   [ ... ],
        "file_count":     0,          # N/A for plan input
        "hcl2_available": True,
        "source":         "plan",
        "plan_path":      "/abs/path/to/plan.json",
        "tf_version":     "1.6.0",    # if present in plan
    }
    """
    result: dict = {
        "resources":      {},
        "data_sources":   {},
        "variables":      {},
        "locals":         {},
        "parse_errors":   [],
        "file_count":     0,
        "hcl2_available": True,
        "source":         "plan",
        "plan_path":      os.path.abspath(plan_path),
        "tf_version":     None,
    }

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except FileNotFoundError:
        result["parse_errors"].append(f"Plan file not found: {plan_path}")
        return result
    except json.JSONDecodeError as exc:
        result["parse_errors"].append(f"Invalid JSON in plan file: {exc}")
        return result
    except Exception as exc:
        result["parse_errors"].append(f"Could not read plan file: {exc}")
        return result

    result["tf_version"] = plan.get("terraform_version")

    # terraform show -json on a plan file uses "planned_values"
    # terraform show -json on a state file uses "values"
    # Support both.
    for key in ("planned_values", "values"):
        if key in plan:
            root = plan[key].get("root_module", {})
            _extract_module(root, result, module_address="")
            break

    # resource_changes fills in / overrides with the planned after-state.
    # This is the most accurate source: it includes all instances and the
    # final resolved attribute values that will be applied.
    if "resource_changes" in plan:
        _extract_changes(plan["resource_changes"], result)

    if not result["resources"] and not result["parse_errors"]:
        result["parse_errors"].append(
            "No resources found in plan output. "
            "Generate the plan with: terraform plan -out=plan.tfplan && "
            "terraform show -json plan.tfplan > plan.json"
        )

    return result


def _extract_module(module: dict, result: dict, module_address: str) -> None:
    """Recursively extract resources from a planned_values module block."""
    for res in module.get("resources", []):
        mode = res.get("mode", "managed")
        rtype = res.get("type", "")
        rname = res.get("name", "")
        address = res.get("address", f"{rtype}.{rname}")
        attrs = res.get("values", {})

        if not isinstance(attrs, dict):
            attrs = {}

        if mode == "data":
            key = _unique_key(result["data_sources"], f"data.{rtype}.{rname}", address)
            result["data_sources"][key] = {
                "type": rtype, "name": rname,
                "file": address, "attrs": attrs,
            }
        else:
            key = _unique_key(result["resources"], f"{rtype}.{rname}", address)
            result["resources"][key] = {
                "type":  rtype,
                "name":  rname,
                "file":  address,    # address is the best file-reference we have
                "attrs": attrs,
            }

    for child in module.get("child_modules", []):
        _extract_module(child, result, child.get("address", ""))


def _extract_changes(changes: list, result: dict) -> None:
    """
    Extract or update resources from resource_changes.

    resource_changes includes every managed resource in the plan.
    For resources being deleted, we skip them (no after state).
    For creates and updates, the "after" block has fully resolved values.
    """
    for change in changes:
        mode = change.get("mode", "managed")
        if mode == "data":
            continue

        actions = change.get("change", {}).get("actions", [])
        if actions == ["delete"]:
            continue

        after = change.get("change", {}).get("after") or {}
        if not isinstance(after, dict):
            after = {}

        rtype   = change.get("type", "")
        rname   = change.get("name", "")
        address = change.get("address", f"{rtype}.{rname}")

        if not rtype:
            continue

        simple_key = f"{rtype}.{rname}"
        if simple_key in result["resources"]:
            # Merge: plan "after" values are more authoritative than planned_values
            result["resources"][simple_key]["attrs"].update(after)
        else:
            key = _unique_key(result["resources"], simple_key, address)
            result["resources"][key] = {
                "type":  rtype,
                "name":  rname,
                "file":  address,
                "attrs": after,
            }


def _unique_key(store: dict, preferred: str, fallback: str) -> str:
    """Return preferred key if not taken, otherwise fall back to the full address."""
    return preferred if preferred not in store else fallback


def plan_summary(parsed: dict) -> str:
    """Return a one-line human-readable summary of a parsed plan."""
    n = len(parsed["resources"])
    src = os.path.basename(parsed.get("plan_path", "plan.json"))
    ver = parsed.get("tf_version") or "unknown"
    errs = len(parsed.get("parse_errors", []))
    err_note = f", {errs} parse error(s)" if errs else ""
    return f"{src} — {n} resources (Terraform {ver}{err_note})"
