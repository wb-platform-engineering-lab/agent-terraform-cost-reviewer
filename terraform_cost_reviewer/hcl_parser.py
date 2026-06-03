"""
HCL2-based parser for Terraform configuration files.

Replaces regex-based text scanning with a proper AST parser, enabling:
- Accurate attribute value extraction (actual Python types: bool, int, str)
- Reliable resource counting (not substring matching)
- Nested block traversal (e.g. default_cache_behavior.compress)
- Skip-rather-than-guess on dynamic expressions (${var.foo}, local.x)
- Per-file error isolation — one bad file doesn't abort the whole scan
"""

import os
from typing import Any

try:
    import hcl2
    HCL2_AVAILABLE = True
except ImportError:
    HCL2_AVAILABLE = False


# ─────────────────────────────────────────────
# ATTRIBUTE HELPERS
# ─────────────────────────────────────────────

def _is_expression(val: Any) -> bool:
    """Return True if a value is a Terraform expression we cannot evaluate statically."""
    if isinstance(val, str):
        return "${" in val or val.startswith("var.") or val.startswith("local.")
    return False


def get_attr(attrs: dict, *keys: str, default=None) -> Any:
    """
    Navigate nested attribute paths in parsed HCL, unwrapping single-item block lists.

    HCL blocks are represented by hcl2 as lists of dicts; single-item lists are unwrapped
    automatically so callers can treat them as plain dicts.

    Returns `default` when:
    - The path does not exist
    - The value is a Terraform expression (cannot be evaluated statically)
    - An intermediate value is not a dict

    Examples:
        get_attr(attrs, "memory_size")
        get_attr(attrs, "default_cache_behavior", "compress")
        get_attr(attrs, "stream_mode_details", "stream_mode")
    """
    current = attrs
    for key in keys:
        if not isinstance(current, dict):
            return default
        val = current.get(key)
        if val is None:
            return default
        # Unwrap single-item block lists
        if isinstance(val, list):
            if not val:
                return default
            if len(val) == 1:
                val = val[0]
            # Multi-item list at intermediate key: can't navigate further
        if _is_expression(val):
            return default
        current = val
    return current


def get_list_attr(attrs: dict, key: str) -> list:
    """
    Return a list-type block attribute, always as a list.
    Returns [] if not present or not a list.
    """
    val = attrs.get(key, [])
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val]
    return []


# ─────────────────────────────────────────────
# PARSER
# ─────────────────────────────────────────────

def parse_terraform_dir(path: str) -> dict:
    """
    Parse all .tf files in a directory tree using python-hcl2.

    Returns a structured dict:
    {
        "resources": {
            "aws_nat_gateway.main": {
                "type":  "aws_nat_gateway",
                "name":  "main",
                "file":  "main.tf",
                "attrs": { ... }   # actual Python values
            },
            ...
        },
        "data_sources": { ... },
        "variables":    { ... },
        "locals":       { ... },
        "parse_errors": ["relative/path.tf: error message", ...],
        "file_count":   N,
        "hcl2_available": True|False,
    }
    """
    result: dict = {
        "resources":      {},
        "data_sources":   {},
        "variables":      {},
        "locals":         {},
        "parse_errors":   [],
        "file_count":     0,
        "hcl2_available": HCL2_AVAILABLE,
    }

    if not HCL2_AVAILABLE:
        result["parse_errors"].append(
            "python-hcl2 not installed — run: pip install python-hcl2"
        )
        return result

    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in (".terraform", "__pycache__", "node_modules", ".git")
            ]
            for f in sorted(files):
                if not f.endswith(".tf"):
                    continue
                fpath = os.path.join(root, f)
                rel = os.path.relpath(fpath, path)
                result["file_count"] += 1

                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        config = hcl2.load(fh)
                    _extract_blocks(config, rel, result)
                except Exception as exc:
                    result["parse_errors"].append(f"{rel}: {exc}")

    except Exception as exc:
        result["parse_errors"].append(f"Directory walk error: {exc}")

    return result


def _strip_quotes(s: str) -> str:
    """Strip surrounding double-quotes from HCL label strings (e.g. '"aws_nat_gateway"' → 'aws_nat_gateway')."""
    return s.strip('"') if isinstance(s, str) else s


def _normalize_value(val: Any) -> Any:
    """
    Recursively strip surrounding double-quotes from string values returned by
    python-hcl2 >= v8, which preserves the HCL quoting in string literals
    (e.g. 'cpu = "4096"' → '"4096"' instead of '4096').

    Booleans and integers come through as native Python types and are left untouched.
    """
    if isinstance(val, str):
        # Only strip if it looks like a quoted string (starts AND ends with ")
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            return val[1:-1]
        return val
    if isinstance(val, list):
        return [_normalize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_value(v) for k, v in val.items()}
    return val


def _extract_blocks(config: dict, filename: str, result: dict) -> None:
    """Populate result with blocks found in one parsed .tf file."""

    # Resources: [{ '"aws_nat_gateway"': { '"main"': { attrs } } }]
    # python-hcl2 returns type/name labels with surrounding quotes since they
    # are quoted strings in HCL syntax (resource "type" "name" { ... }).
    for block in config.get("resource", []):
        if not isinstance(block, dict):
            continue
        for rtype_raw, instances in block.items():
            rtype = _strip_quotes(rtype_raw)
            if not isinstance(instances, dict):
                continue
            for rname_raw, attrs in instances.items():
                rname = _strip_quotes(rname_raw)
                key = f"{rtype}.{rname}"
                result["resources"][key] = {
                    "type":  rtype,
                    "name":  rname,
                    "file":  filename,
                    "attrs": _normalize_value(attrs) if isinstance(attrs, dict) else {},
                }

    # Data sources
    for block in config.get("data", []):
        if not isinstance(block, dict):
            continue
        for dtype_raw, instances in block.items():
            dtype = _strip_quotes(dtype_raw)
            if not isinstance(instances, dict):
                continue
            for dname_raw, attrs in instances.items():
                dname = _strip_quotes(dname_raw)
                key = f"data.{dtype}.{dname}"
                result["data_sources"][key] = {
                    "type":  dtype,
                    "name":  dname,
                    "file":  filename,
                    "attrs": attrs if isinstance(attrs, dict) else {},
                }

    # Variables
    for block in config.get("variable", []):
        if isinstance(block, dict):
            result["variables"].update(block)

    # Locals
    for block in config.get("locals", []):
        if isinstance(block, dict):
            result["locals"].update(block)


# ─────────────────────────────────────────────
# QUERY HELPERS
# ─────────────────────────────────────────────

def resources_of_type(parsed: dict, *rtypes: str) -> list:
    """Return all resource dicts whose type is in rtypes."""
    return [v for v in parsed["resources"].values() if v["type"] in rtypes]


def has_resource_type(parsed: dict, *rtypes: str) -> bool:
    """Return True if at least one resource of the given type(s) exists."""
    return any(v["type"] in rtypes for v in parsed["resources"].values())


def count_type(parsed: dict, rtype: str) -> int:
    """Return the number of resources of a given type."""
    return sum(1 for v in parsed["resources"].values() if v["type"] == rtype)


def by_type_index(parsed: dict) -> dict:
    """Return a dict mapping resource type → list of resource dicts."""
    idx: dict = {}
    for v in parsed["resources"].values():
        idx.setdefault(v["type"], []).append(v)
    return idx
