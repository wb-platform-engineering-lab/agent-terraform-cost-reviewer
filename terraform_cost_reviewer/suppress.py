"""
Suppression loader for terraform-cost-reviewer.

Two suppression methods are supported:

1. .tfreview.yaml in the Terraform root directory
   ------------------------------------------------
   suppress:
     - id: C-014
       reason: "Multi-AZ intentional — staging mirrors prod for DR drills"
     - id: C-013
       reason: "Reserved instances managed via FinOps system, not in Terraform"

2. Inline comments in .tf files
   ------------------------------------------------
   resource "aws_db_instance" "staging" {
     multi_az = true  # tfreview:ignore:C-014 intentional for DR testing
   }

   The inline comment suppresses that check ID globally (not just per-resource).
   This matches the behaviour of tfsec:ignore and checkov:skip.

Both methods can be combined. The union of all suppressions is applied.
"""

import os
import re
from typing import Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# Matches: # tfreview:ignore:C-014  or  # tfreview:ignore:C-014 optional reason
_INLINE_RE = re.compile(r"#\s*tfreview:ignore:(C-\d+)(?:\s+(.+))?", re.IGNORECASE)


def load_suppressions(path: str) -> dict[str, Optional[str]]:
    """
    Load all suppressed check IDs for a given Terraform directory.

    Returns a dict mapping check_id → reason string (or None if no reason given).
    Empty dict means no suppressions are active.
    """
    suppressions: dict[str, Optional[str]] = {}
    suppressions.update(_from_yaml(path))
    suppressions.update(_from_inline_comments(path))
    return suppressions


def _from_yaml(path: str) -> dict[str, Optional[str]]:
    config_path = os.path.join(path, ".tfreview.yaml")
    if not os.path.isfile(config_path):
        return {}
    if not _YAML_AVAILABLE:
        print(
            f"Warning: {config_path} found but pyyaml is not installed — "
            "suppression file will be ignored. Run: pip install pyyaml",
            flush=True,
        )
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        result: dict[str, Optional[str]] = {}
        for entry in config.get("suppress", []):
            if isinstance(entry, dict) and "id" in entry:
                result[str(entry["id"]).upper()] = entry.get("reason") or None
            elif isinstance(entry, str):
                result[entry.upper()] = None
        return result
    except Exception as exc:
        print(f"Warning: could not parse {config_path}: {exc}", flush=True)
        return {}


def _from_inline_comments(path: str) -> dict[str, Optional[str]]:
    result: dict[str, Optional[str]] = {}
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d not in (".terraform", "__pycache__")
            ]
            for f in files:
                if not f.endswith(".tf"):
                    continue
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            m = _INLINE_RE.search(line)
                            if m:
                                cid = m.group(1).upper()
                                reason = m.group(2).strip() if m.group(2) else None
                                result[cid] = reason
                except Exception:
                    pass
    except Exception:
        pass
    return result
