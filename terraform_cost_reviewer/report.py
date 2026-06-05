"""
Converts the agent's text review into a professional HTML report.
Uses Tailwind CSS + Font Awesome.
Handles markdown output from the agent (###, **, tables, code blocks).
"""

import os
import re
from datetime import datetime


# ─────────────────────────────────────────────
# Markdown → clean HTML
# ─────────────────────────────────────────────

def md_to_html(text: str) -> str:
    """Convert agent markdown output to clean HTML."""
    lines = text.split("\n")
    html = []
    in_code = False
    in_table = False
    code_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if s.startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                in_code = False
                escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html.append(
                    f'<div class="relative group my-3">'
                    f'<pre class="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto font-mono leading-relaxed">{escaped}</pre>'
                    f'<button onclick="copyPre(this)" class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs px-2 py-1 rounded">'
                    f'<i class="fas fa-copy mr-1"></i>Copy</button>'
                    f'</div>'
                )
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if s.startswith("|") and s.endswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", s):
                i += 1
                continue
            if not in_table:
                in_table = True
                html.append('<div class="overflow-x-auto my-3"><table class="w-full text-sm border-collapse">')
                cells = [c.strip() for c in s.strip("|").split("|")]
                html.append("<thead><tr>" + "".join(
                    f'<th class="px-3 py-2 bg-gray-100 dark:bg-gray-700 font-semibold text-left border border-gray-200 dark:border-gray-600 text-xs uppercase tracking-wider">{_inline(c)}</th>'
                    for c in cells
                ) + "</tr></thead><tbody>")
            else:
                cells = [c.strip() for c in s.strip("|").split("|")]
                html.append("<tr>" + "".join(
                    f'<td class="px-3 py-2 border border-gray-100 dark:border-gray-700 align-top">{_inline(c)}</td>'
                    for c in cells
                ) + "</tr>")
            i += 1
            continue
        else:
            if in_table:
                html.append("</tbody></table></div>")
                in_table = False

        if re.match(r"^[-─═]{3,}$", s):
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.+)", s)
        if m:
            level = len(m.group(1))
            content = _inline(m.group(2))
            sizes = {1: "text-2xl font-black", 2: "text-xl font-bold", 3: "text-base font-bold", 4: "text-sm font-semibold"}
            cls = sizes.get(level, "text-sm font-semibold")
            mt = "mt-6" if level <= 2 else "mt-4"
            html.append(f'<h{level} class="{cls} {mt} mb-2 text-gray-900 dark:text-white">{content}</h{level}>')
            i += 1
            continue

        if s.startswith(">"):
            content = _inline(s.lstrip("> ").strip())
            html.append(
                f'<blockquote class="border-l-4 border-blue-400 bg-blue-50 dark:bg-blue-900/20 px-4 py-2 my-3 text-sm text-gray-700 dark:text-gray-300 rounded-r-lg">{content}</blockquote>'
            )
            i += 1
            continue

        if re.match(r"^[-*]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(_inline(re.sub(r"^[-*]\s+", "", lines[i].strip())))
                i += 1
            html.append(
                '<ul class="list-disc pl-5 space-y-1 my-2 text-sm text-gray-700 dark:text-gray-300">'
                + "".join(f"<li>{it}</li>" for it in items)
                + "</ul>"
            )
            continue

        if re.match(r"^\d+[.)]\s+", s):
            items = []
            while i < len(lines) and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                items.append(_inline(re.sub(r"^\d+[.)]\s+", "", lines[i].strip())))
                i += 1
            html.append(
                '<ol class="list-decimal pl-5 space-y-1 my-2 text-sm text-gray-700 dark:text-gray-300">'
                + "".join(f"<li>{it}</li>" for it in items)
                + "</ol>"
            )
            continue

        if re.match(r"^---+$", s) or re.match(r"^===+$", s):
            html.append('<hr class="border-gray-200 dark:border-gray-700 my-4"/>')
            i += 1
            continue

        if not s:
            html.append('<div class="h-2"></div>')
            i += 1
            continue

        html.append(f'<p class="text-sm text-gray-700 dark:text-gray-300 mb-2">{_inline(s)}</p>')
        i += 1

    if in_table:
        html.append("</tbody></table></div>")
    if in_code and code_lines:
        escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html.append(f'<pre class="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto my-3 font-mono">{escaped}</pre>')

    return "\n".join(html)


def _inline(text: str) -> str:
    """Convert inline markdown: bold, italic, code, links, status badges."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    text = text.replace("✅ PASS", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800">✅ PASS</span>')
    text = text.replace("❌ FAIL", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800">❌ FAIL</span>')
    text = text.replace("⚠️ WARN", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-yellow-100 text-yellow-800">⚠️ WARN</span>')
    text = text.replace("ℹ️ INFO", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-800">ℹ️ INFO</span>')
    text = text.replace("⊘ SKIP", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-gray-100 text-gray-600">⊘ SKIP</span>')

    text = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-gray-900 dark:text-white">\1</strong>', text)
    text = re.sub(r"\*(.+?)\*",     r'<em class="italic">\1</em>', text)
    text = re.sub(r"`([^`]+)`",     r'<code class="bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-xs px-1.5 py-0.5 rounded font-mono">\1</code>', text)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" class="text-blue-500 hover:underline">\1</a>', text)

    return text


# ─────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────

def _extract_narratives(text: str) -> dict:
    """
    Second-pass extraction of per-check narrative blocks.
    Captures everything between ### [C-XXX] headers.
    """
    result: dict = {}
    current_id = None
    current_lines: list = []

    for line in text.split("\n"):
        m = re.match(r"#{1,4}\s*\**\s*\[?(C-\d+)\]?\s*\**\s*(.+)", line.strip())
        if m:
            if current_id and current_lines:
                result[current_id] = "\n".join(current_lines).strip()
            current_id = m.group(1)
            current_lines = []
        elif current_id:
            current_lines.append(line)

    if current_id and current_lines:
        result[current_id] = "\n".join(current_lines).strip()

    return result


def parse_report(text: str) -> dict:
    """
    Parse the cost review report into structured data.
    Handles C-XXX check IDs grouped into a single Cost Optimization pillar.
    """
    checks: list = []
    overall_score = None
    action_items: list = []
    seen_ids: set = set()
    in_actions = False
    last_check_idx = None

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue

        # ── Overall score ────────────────────────────────────────────
        if not overall_score:
            m = (
                re.search(r"(\d+)\s*/\s*(\d+)\s+checks?\s+pass", s, re.IGNORECASE)
                or re.search(r"TOTAL[^\d]*(\d+)\s*/\s*(\d+)", s)
                or re.search(r"\*\*(\d+)\s*/\s*(\d+)\s+checks?\s+pass", s, re.IGNORECASE)
                or re.search(r"(\d+)\s*/\s*(\d+)\s+passing", s, re.IGNORECASE)
            )
            if m:
                overall_score = (int(m.group(1)), int(m.group(2)))

        # ── Narrative section header: ### [C-001] Name ───────────────
        m = re.match(r"#{1,4}\s*\**\s*\[?(C-\d+)\]?\s*\**\s*(.+)", s)
        if m:
            check_id = m.group(1)
            name = re.sub(r"[\*\[\]]", "", m.group(2)).strip().strip("*").strip()
            if check_id not in seen_ids:
                seen_ids.add(check_id)
                checks.append({"status": "fail", "id": check_id, "name": name,
                                "recommendation": None, "detail_md": ""})
                last_check_idx = len(checks) - 1
            continue

        # ── Inline check status: ❌ FAIL [C-001] Name ────────────────
        m = re.match(r"(❌|⚠️|✅|ℹ️|⊘)\s*(FAIL|WARN|PASS|INFO|SKIP)\s+\[?(C-\d+)\]?\s*(.*)", s)
        if m:
            _, status_str, check_id, name = m.group(1), m.group(2), m.group(3), m.group(4)
            name = re.sub(r"\[cross-resource\]", "", name).strip()
            if check_id not in seen_ids:
                seen_ids.add(check_id)
                checks.append({"status": status_str.lower(), "id": check_id,
                                "name": name or check_id, "recommendation": None, "detail_md": ""})
                last_check_idx = len(checks) - 1
            continue

        # ── Table row: | C-001 | desc | … ───────────────────────────
        if s.startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", s):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and re.match(r"C-\d+", cells[0]):
                check_id = re.match(r"C-\d+", cells[0]).group(0)
                name = cells[1] if len(cells) > 1 else check_id
                row_text = " ".join(cells)
                if   "❌" in row_text or "FAIL" in row_text: cstatus = "fail"
                elif "⚠️" in row_text or "WARN" in row_text: cstatus = "warn"
                elif "✅" in row_text or "PASS" in row_text: cstatus = "pass"
                elif "⊘"  in row_text or "SKIP" in row_text: cstatus = "skip"
                else: cstatus = "fail"
                saving = next((c for c in reversed(cells) if c and c != "—"), None)
                if check_id not in seen_ids:
                    seen_ids.add(check_id)
                    checks.append({"status": cstatus, "id": check_id, "name": name,
                                   "recommendation": saving if saving != name else None,
                                   "detail_md": ""})
                    last_check_idx = len(checks) - 1
            continue

        # ── Est. saving line ─────────────────────────────────────────
        if last_check_idx is not None and re.search(r"est\.?\s*sav", s, re.IGNORECASE):
            saving = re.sub(r"\*+|💰", "", s).strip()
            checks[last_check_idx]["recommendation"] = saving
            amt = re.search(r"~?\$[\d,]+(?:[–\-][\d,]+)?(?:/mo)?", saving)
            if amt:
                checks[last_check_idx]["saving_raw"] = amt.group(0)
            continue

        # ── Action items ─────────────────────────────────────────────
        if re.search(r"(top \d|priority order|highest.impact|prioritized action|quick wins?)", s, re.IGNORECASE):
            in_actions = True
            continue
        if in_actions:
            if re.match(r"^#{1,2}\s", s) and not re.match(r"^###", s):
                in_actions = False
            m = re.match(r"#{1,4}\s*\**\s*(?:\d+[.):\-—\s]+)\**(.+)", s)
            if m:
                action = re.sub(r"\*+", "", m.group(1)).strip()
                if len(action) > 5:
                    action_items.append(action)
            elif re.match(r"^\d+[.)]\s+", s):
                action = re.sub(r"^\d+[.)]\s+", "", s)
                if len(action) > 5:
                    action_items.append(action)

    # ── Attach narrative detail to checks (second pass) ───────────────
    narratives = _extract_narratives(text)
    for check in checks:
        if check["id"] in narratives:
            check["detail_md"] = narratives[check["id"]]

    # ── Build pillar ─────────────────────────────────────────────────
    passing = sum(1 for c in checks if c["status"] == "pass")
    total = overall_score[1] if overall_score and overall_score[1] > len(checks) else (len(checks) or 15)
    has_fail = any(c["status"] == "fail" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    pillar_status = "fail" if has_fail else ("warn" if has_warn else "pass")

    pillar = {
        "num": "1", "name": "Cost Optimization",
        "status": pillar_status, "pass": passing, "total": total,
        "checks": checks,
    }

    if not overall_score:
        overall_score = (passing, total) if total else (0, 15)

    savings_summary = _aggregate_savings(text, checks)

    return {
        "pillars": [pillar],
        "overall_score": overall_score,
        "action_items": action_items[:5],
        "savings_summary": savings_summary,
        "raw": text,
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

PILLAR_ICONS  = {"1": "fa-coins"}
PILLAR_COLORS = {"1": "#10b981"}


def _status_classes(status: str):
    return {
        "pass": ("bg-emerald-500 text-white", "text-emerald-500", "bg-emerald-500"),
        "fail": ("bg-red-500 text-white",     "text-red-500",     "bg-red-500"),
        "warn": ("bg-amber-400 text-white",   "text-amber-500",   "bg-amber-400"),
        "info": ("bg-blue-500 text-white",    "text-blue-500",    "bg-blue-500"),
        "skip": ("bg-gray-400 text-white",    "text-gray-400",    "bg-gray-400"),
    }.get(status, ("bg-gray-400 text-white", "text-gray-500", "bg-gray-400"))


# ─────────────────────────────────────────────
# Components
# ─────────────────────────────────────────────

def _stats_row(checks: list) -> str:
    """FAIL / WARN / PASS / INFO / SKIP count cards."""
    counts: dict = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    cfg = [
        ("fail", "FAIL", "border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20",
         "text-red-600 dark:text-red-400", "fa-circle-xmark text-red-400"),
        ("warn", "WARN", "border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20",
         "text-amber-600 dark:text-amber-400", "fa-triangle-exclamation text-amber-400"),
        ("pass", "PASS", "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20",
         "text-emerald-600 dark:text-emerald-400", "fa-circle-check text-emerald-400"),
        ("info", "INFO", "border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20",
         "text-blue-600 dark:text-blue-400", "fa-circle-info text-blue-400"),
        ("skip", "SKIP", "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800",
         "text-gray-500 dark:text-gray-400", "fa-ban text-gray-400"),
    ]
    cards = []
    for key, label, card_cls, count_cls, icon_cls in cfg:
        n = counts.get(key, 0)
        dim = " opacity-30" if n == 0 else ""
        cards.append(
            f'<div class="flex-1 min-w-[68px] border rounded-xl p-3 text-center{dim} {card_cls}">'
            f'<i class="fas {icon_cls} text-xs mb-1 block"></i>'
            f'<div class="text-2xl font-black {count_cls} leading-none">{n}</div>'
            f'<div class="text-xs font-semibold text-gray-400 mt-1">{label}</div>'
            f'</div>'
        )
    return f'<div class="flex gap-2 flex-wrap">{"".join(cards)}</div>'


def _check_row(c: dict) -> str:
    """Single expandable check row."""
    status = c["status"]
    cfg = {
        "pass": ("fa-circle-check text-emerald-500", "bg-emerald-100 text-emerald-800", "PASS"),
        "fail": ("fa-circle-xmark text-red-500",     "bg-red-100 text-red-800",         "FAIL"),
        "warn": ("fa-triangle-exclamation text-amber-500", "bg-amber-100 text-amber-800", "WARN"),
        "info": ("fa-circle-info text-blue-500",     "bg-blue-100 text-blue-800",        "INFO"),
        "skip": ("fa-ban text-gray-400",             "bg-gray-100 text-gray-500",        "SKIP"),
    }
    icon_cls, badge_cls, label = cfg.get(status, cfg["info"])

    # Build detail content from narrative or saving line
    detail_html = ""
    if c.get("detail_md"):
        detail_html = md_to_html(c["detail_md"])
    elif c.get("recommendation"):
        rec = c["recommendation"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rec = re.sub(r"`([^`]+)`",
            r'<code class="bg-gray-100 dark:bg-gray-700 text-xs px-1 rounded font-mono">\1</code>', rec)
        detail_html = f'<p class="text-sm text-gray-600 dark:text-gray-400">{rec}</p>'

    has_detail = bool(detail_html)

    # Suppression reason shown inline for SKIP rows
    skip_note = ""
    if status == "skip" and c.get("recommendation"):
        note = c["recommendation"].replace("&", "&amp;")
        skip_note = f'<span class="text-xs text-gray-400 italic ml-1 truncate max-w-[200px]">{note}</span>'

    chevron = (
        f'<i class="fas fa-chevron-down text-gray-300 text-xs flex-shrink-0 '
        f'transition-transform duration-200 check-chevron -rotate-90"></i>'
        if has_detail else ""
    )

    if has_detail:
        header = (
            f'<button onclick="toggleCheck(this)" '
            f'class="flex items-center gap-3 px-4 py-3 w-full text-left '
            f'hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">'
        )
        header_close = "</button>"
    else:
        header = '<div class="flex items-center gap-3 px-4 py-3">'
        header_close = "</div>"

    detail_block = ""
    if has_detail:
        detail_block = (
            f'<div class="check-detail border-t border-gray-50 dark:border-gray-700/50 '
            f'px-4 pb-4" style="display:none">'
            f'<div class="pt-3 pl-12 space-y-1">{detail_html}</div>'
            f'</div>'
        )

    return (
        f'<div class="border-b border-gray-50 dark:border-gray-700/50 last:border-0">'
        f'{header}'
        f'<i class="fas {icon_cls} flex-shrink-0"></i>'
        f'<span class="inline-flex items-center justify-center px-2 py-0.5 rounded-full '
        f'text-xs font-bold {badge_cls} flex-shrink-0 w-11">{label}</span>'
        f'<span class="font-mono text-xs text-gray-400 flex-shrink-0 w-12">{c["id"]}</span>'
        f'<span class="text-sm text-gray-800 dark:text-gray-200 flex-1 min-w-0">{c["name"]}</span>'
        f'{skip_note}'
        f'{chevron}'
        f'{header_close}'
        f'{detail_block}'
        f'</div>'
    )


def _score_card(score, score_pct, score_color_hex, grade, grade_cls, target_name, timestamp):
    r, circ = 40, 251.2
    offset = circ - (score_pct / 100) * circ
    return (
        f'<div class="bg-white dark:bg-gray-800 rounded-2xl p-6 shadow-sm flex flex-col items-center h-full">'
        f'<h2 class="text-sm font-bold text-gray-500 uppercase tracking-wider mb-4">Overall Score</h2>'
        f'<div class="w-36 h-36 relative">'
        f'<svg class="-rotate-90" viewBox="0 0 100 100">'
        f'<circle cx="50" cy="50" r="{r}" stroke="#e5e7eb" stroke-width="10" fill="none"/>'
        f'<circle cx="50" cy="50" r="{r}" stroke="{score_color_hex}" stroke-width="10" '
        f'stroke-dasharray="{circ}" stroke-dashoffset="{offset:.1f}" stroke-linecap="round" fill="none"/>'
        f'</svg>'
        f'<div class="absolute inset-0 flex flex-col items-center justify-center">'
        f'<div class="text-xs text-gray-500">Score</div>'
        f'<div class="text-2xl font-bold text-gray-900 dark:text-white">{score_pct}%</div>'
        f'<span class="mt-1 px-3 py-1 rounded-full text-xs font-semibold {grade_cls}">{grade}</span>'
        f'</div></div>'
        f'<div class="mt-4 text-center">'
        f'<div class="font-semibold text-gray-700 dark:text-gray-200 text-sm">{target_name}</div>'
        f'<div class="text-xs text-gray-400 mt-1">{score[0]}/{score[1]} checks passing</div>'
        f'<div class="text-xs text-gray-400 mt-0.5">{timestamp}</div>'
        f'</div></div>'
    )


def _action_items(items):
    if not items:
        return ""
    rows = ""
    urgencies = [
        ("High",   "bg-red-100 text-red-700",        "fa-circle-exclamation text-red-500"),
        ("Medium", "bg-yellow-100 text-yellow-700",   "fa-triangle-exclamation text-yellow-500"),
        ("Low",    "bg-emerald-100 text-emerald-700", "fa-circle-check text-emerald-500"),
    ]
    for i, item in enumerate(items[:5]):
        label, badge_cls, icon_cls = urgencies[min(i, 2)]
        clean = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
        clean = re.sub(r"`([^`]+)`",
            r'<code class="bg-gray-100 text-gray-700 text-xs px-1 rounded font-mono">\1</code>', clean)
        rows += (
            f'<div class="flex items-start gap-4 p-4 border-b border-gray-100 dark:border-gray-700 last:border-0">'
            f'<div class="w-8 h-8 rounded-full bg-gray-900 flex items-center justify-center '
            f'text-white text-sm font-bold flex-shrink-0 mt-0.5">{i+1}</div>'
            f'<div class="flex-1 min-w-0">'
            f'<div class="text-sm text-gray-800 dark:text-gray-200 mb-1.5">{clean}</div>'
            f'<span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full {badge_cls}">'
            f'<i class="fas {icon_cls} text-xs"></i>{label} priority</span>'
            f'</div></div>'
        )
    return rows


def _pillar_detail_sections(pillars):
    sections = ""
    for p in pillars:
        icon  = PILLAR_ICONS.get(p["num"], "fa-circle")
        color = PILLAR_COLORS.get(p["num"], "#2563eb")
        badge_cls, text_cls, _ = _status_classes(p["status"])
        pct = int(p["pass"] / p["total"] * 100) if p["total"] else 0

        checks_html = "".join(_check_row(c) for c in p["checks"])
        if not checks_html:
            checks_html = '<p class="text-sm text-gray-400 py-4 px-4">No individual checks recorded.</p>'

        sections += (
            f'<div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="pillar-{p["num"]}">'
            # Header
            f'<div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700" '
            f'style="border-left:4px solid {color}">'
            f'<div class="flex items-center gap-3">'
            f'<div class="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0" style="background:{color}">'
            f'<i class="fas {icon} text-sm text-white"></i></div>'
            f'<div><div class="font-bold text-gray-900 dark:text-white">Pillar {p["num"]} — {p["name"]}</div>'
            f'<div class="text-xs text-gray-400">{p["pass"]}/{p["total"]} checks passing</div></div>'
            f'</div>'
            f'<div class="flex items-center gap-3">'
            f'<div class="w-20 bg-gray-100 dark:bg-gray-700 rounded-full h-2 hidden sm:block">'
            f'<div class="h-2 rounded-full" style="width:{pct}%;background:{color}"></div></div>'
            f'<span class="text-sm font-bold {text_cls} w-8 text-right">{pct}%</span>'
            f'<span class="text-xs font-bold px-2 py-1 rounded-full {badge_cls}">{p["status"].upper()}</span>'
            f'</div></div>'
            # Stats row
            f'<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">'
            f'{_stats_row(p["checks"])}</div>'
            # Check rows
            f'<div>{checks_html}</div>'
            f'</div>'
        )
    return sections


def _nav_items(pillars):
    items = ""
    for p in pillars:
        icon    = PILLAR_ICONS.get(p["num"], "fa-circle")
        dot_cls = {"pass": "text-emerald-500", "fail": "text-red-500", "warn": "text-yellow-400"}.get(p["status"], "text-gray-400")
        di      = {"pass": "fa-circle-check", "fail": "fa-circle-xmark", "warn": "fa-triangle-exclamation"}.get(p["status"], "fa-circle")
        items += (
            f'<a href="#pillar-{p["num"]}" class="flex items-center gap-2 px-3 py-2 rounded-lg '
            f'text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">'
            f'<i class="fas {di} {dot_cls} text-xs w-3 flex-shrink-0"></i>'
            f'<i class="fas {icon} text-xs w-3 text-gray-600 flex-shrink-0"></i>'
            f'<span class="truncate">P{p["num"]} — {p["name"]}</span></a>'
        )
    return items


# ─────────────────────────────────────────────
# Savings aggregation
# ─────────────────────────────────────────────

def _aggregate_savings(text: str, checks: list) -> dict:
    pattern = re.compile(
        r"~?\$\s*([\d,]+(?:\.\d+)?)\s*(?:[–\-]\s*([\d,]+(?:\.\d+)?))?(?:\s*/mo|\s*per month)?",
        re.IGNORECASE,
    )
    low_total, high_total, found = 0, 0, 0
    seen_positions: set = set()

    for m in pattern.finditer(text):
        pos_bucket = m.start() // 50
        if pos_bucket in seen_positions:
            continue
        seen_positions.add(pos_bucket)
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", "")) if m.group(2) else lo
        if lo < 1 or lo > 50_000:
            continue
        low_total += lo
        high_total += hi
        found += 1

    failing = sum(1 for c in checks if c.get("status") == "fail")

    if found == 0 or low_total == 0:
        return {"label": "N/A", "count": failing}

    def _fmt(n):
        return f"${n/1000:.1f}k" if n >= 1000 else f"${int(n)}"

    label = (f"{_fmt(low_total)}/mo" if abs(high_total - low_total) < 5
             else f"{_fmt(low_total)}–{_fmt(high_total)}/mo")

    return {"low": int(low_total), "high": int(high_total), "label": label, "count": failing}


# ─────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────

def generate_html(report_text: str, target_path: str, metadata: dict | None = None) -> str:
    data = parse_report(report_text)
    timestamp = datetime.now().strftime("%B %d, %Y · %H:%M")
    target_abs = os.path.abspath(target_path)
    target_name = os.path.basename(target_abs)
    meta = metadata or {}

    score = data["overall_score"] or (0, 1)
    score_pct = int(score[0] / score[1] * 100) if score[1] else 0

    if score_pct >= 75:
        score_color_hex, grade, grade_cls = "#16a34a", "PASS", "bg-emerald-100 text-emerald-800"
    elif score_pct >= 40:
        score_color_hex, grade, grade_cls = "#fb923c", "AT RISK", "bg-orange-100 text-orange-700"
    else:
        score_color_hex, grade, grade_cls = "#dc2626", "FAIL", "bg-red-100 text-red-800"

    savings       = data.get("savings_summary", {})
    savings_label = savings.get("label", "N/A")
    savings_count = savings.get("count", 0)

    if savings_label == "N/A" and savings_count == 0 and score_pct < 75:
        savings_sub = "See full report below"
    elif savings_count == 0:
        savings_sub = "No issues found"
    else:
        savings_sub = f"{savings_count} issue{'s' if savings_count != 1 else ''} found"

    # Metadata strip
    meta_parts = []
    if meta.get("file_count"):
        meta_parts.append(f'<span><i class="fas fa-file-code mr-1 text-gray-500"></i>{meta["file_count"]} files</span>')
    if meta.get("resource_count"):
        meta_parts.append(f'<span><i class="fas fa-cube mr-1 text-gray-500"></i>{meta["resource_count"]} resources</span>')
    source = meta.get("source")
    if source == "plan":
        meta_parts.append('<span><i class="fas fa-diagram-project mr-1 text-gray-500"></i>plan mode</span>')
        if meta.get("tf_version"):
            meta_parts.append(f'<span><i class="fas fa-code-branch mr-1 text-gray-500"></i>tf {meta["tf_version"]}</span>')
    elif source == "hcl":
        meta_parts.append('<span><i class="fas fa-file-lines mr-1 text-gray-500"></i>source mode</span>')
    model_name = meta.get("model", "claude-haiku-4-5")
    meta_parts.append(f'<span><i class="fas fa-robot mr-1 text-gray-500"></i>{model_name}</span>')
    meta_strip = (f'<div class="flex flex-wrap gap-4 text-xs text-gray-400 mt-3">'
                  + " ".join(meta_parts) + "</div>")

    # All checks (flattened) for top-level stats
    all_checks = [c for p in data["pillars"] for c in p["checks"]]

    score_card_html  = _score_card(score, score_pct, score_color_hex, grade, grade_cls, target_name, timestamp)
    actions_html     = _action_items(data["action_items"])
    detail_html      = _pillar_detail_sections(data["pillars"])
    nav_html         = _nav_items(data["pillars"])
    full_report_html = md_to_html(report_text)
    top_stats_html   = _stats_row(all_checks)

    actions_block = ""
    if actions_html:
        actions_block = (
            f'<div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="actions">'
            f'<div class="flex items-center gap-3 px-6 py-4 border-b border-gray-100 dark:border-gray-700 bg-gray-900">'
            f'<i class="fas fa-bullseye text-white"></i>'
            f'<h3 class="text-white font-semibold">Priority Actions</h3></div>'
            f'{actions_html}</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Terraform Cost Review — {target_name}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.7.2/css/all.min.css"/>
</head>
<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-white">
<div class="flex min-h-screen">

  <!-- SIDEBAR -->
  <aside class="w-72 bg-gray-950 flex flex-col border-r border-gray-800 fixed top-0 left-0 h-screen overflow-y-auto z-10">
    <div class="p-5 border-b border-gray-800">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-full bg-emerald-600 flex items-center justify-center shadow flex-shrink-0">
          <i class="fas fa-coins text-white"></i>
        </div>
        <div>
          <div class="text-sm font-bold text-white">Cost Reviewer</div>
          <div class="text-xs text-gray-500">Terraform Architecture</div>
        </div>
      </div>
    </div>
    <nav class="flex-1 p-4 space-y-0.5">
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-1 pb-2">Overview</div>
      <a href="#summary" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-chart-pie text-xs w-4 text-gray-500"></i><span>Executive Summary</span>
      </a>
      <a href="#actions" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-bullseye text-xs w-4 text-gray-500"></i><span>Priority Actions</span>
      </a>
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-3 pb-2">Cost Checks</div>
      {nav_html}
      <div class="text-xs font-bold uppercase tracking-widest text-gray-600 px-3 pt-3 pb-2">Details</div>
      <a href="#raw" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
        <i class="fas fa-file-lines text-xs w-4 text-gray-500"></i><span>Full Analysis</span>
      </a>
    </nav>
    <div class="p-4 border-t border-gray-800 text-xs text-gray-600">
      <a href="https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer" class="hover:text-gray-400 transition">
        <i class="fab fa-github mr-1"></i>agent-terraform-cost-reviewer
      </a>
    </div>
  </aside>

  <!-- MAIN -->
  <main class="flex-1 ml-72 p-6 lg:p-10 space-y-8">

    <!-- HERO -->
    <div class="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl p-8 shadow-sm" id="summary">
      <div class="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 mb-2">
            <i class="fas fa-coins text-emerald-500"></i>
            <span class="text-xs font-bold text-emerald-500 uppercase tracking-wider">Terraform Cost Architecture Review</span>
          </div>
          <h1 class="text-2xl font-black mb-3 text-gray-900 dark:text-white">Cost Optimization Report</h1>
          <div class="flex items-center gap-2 bg-gray-100 dark:bg-gray-700 rounded-lg px-3 py-1.5 w-fit mb-1">
            <i class="fas fa-folder-open text-gray-400 text-xs"></i>
            <code class="text-gray-600 dark:text-gray-300 text-xs truncate max-w-md">{target_abs}</code>
          </div>
          {meta_strip}
        </div>
        <div class="flex-shrink-0 flex flex-col sm:flex-row gap-4">
          <div class="bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-2xl p-6 text-center min-w-[140px]">
            <div class="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Score</div>
            <div class="text-5xl font-black" style="color:{score_color_hex}">{score_pct}%</div>
            <div class="text-gray-400 text-xs mt-1">{score[0]}/{score[1]} checks</div>
            <span class="mt-2 inline-block px-4 py-1 rounded-full text-sm font-bold {grade_cls}">{grade}</span>
          </div>
          <div class="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-2xl p-6 text-center min-w-[140px]">
            <div class="text-xs text-emerald-600 dark:text-emerald-400 uppercase tracking-wider font-semibold mb-1">Est. Monthly Savings</div>
            <div class="text-3xl font-black text-emerald-600 dark:text-emerald-400 mt-1">{savings_label}</div>
            <div class="text-emerald-500 text-xs mt-2 flex items-center justify-center gap-1">
              <i class="fas fa-piggy-bank"></i><span>{savings_sub}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- SCORE + BREAKDOWN -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div>{score_card_html}</div>
      <div class="lg:col-span-2 bg-white dark:bg-gray-800 rounded-2xl p-6 shadow-sm">
        <h2 class="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4">Check Breakdown</h2>
        {top_stats_html}
        <p class="text-xs text-gray-400 mt-4">Click any check row below to see the full finding, file reference, and recommended fix.</p>
      </div>
    </div>

    <!-- PRIORITY ACTIONS -->
    {actions_block}

    <!-- DETAILED FINDINGS -->
    <div>
      <h2 class="text-xs font-bold text-gray-500 dark:text-gray-400 mb-4 flex items-center gap-2 uppercase tracking-wider">
        <i class="fas fa-magnifying-glass"></i> Detailed Findings
      </h2>
      <div class="space-y-4">{detail_html}</div>
    </div>

    <!-- FULL ANALYSIS -->
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="raw">
      <button type="button"
        class="w-full flex justify-between items-center px-6 py-4 text-left font-semibold text-gray-900 dark:text-white border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition focus:outline-none"
        onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('i.chevron').classList.toggle('rotate-180')">
        <span class="flex items-center gap-2 text-sm">
          <i class="fas fa-file-lines text-gray-400"></i>Claude's Full Analysis
        </span>
        <i class="fas fa-chevron-down text-gray-400 chevron transition-transform duration-300"></i>
      </button>
      <div class="hidden px-6 py-6">
        {full_report_html}
      </div>
    </div>

    <!-- FOOTER -->
    <div class="text-center text-xs text-gray-400 pt-4 pb-8 border-t border-gray-100 dark:border-gray-700">
      Generated by <a href="https://github.com/wb-platform-engineering-lab/agent-terraform-cost-reviewer" class="text-blue-500 hover:underline">agent-terraform-cost-reviewer</a>
      · {model_name} · {timestamp}
    </div>
  </main>
</div>

<script>
  function toggleCheck(btn) {{
    const detail = btn.nextElementSibling;
    const chevron = btn.querySelector('.check-chevron');
    if (!detail) return;
    const isHidden = detail.style.display === 'none';
    detail.style.display = isHidden ? 'block' : 'none';
    if (chevron) chevron.classList.toggle('-rotate-90', !isHidden);
  }}

  function copyPre(btn) {{
    const pre = btn.previousElementSibling;
    navigator.clipboard.writeText(pre.textContent).then(() => {{
      btn.innerHTML = '<i class="fas fa-check mr-1"></i>Copied';
      setTimeout(() => btn.innerHTML = '<i class="fas fa-copy mr-1"></i>Copy', 2000);
    }});
  }}

  const sections = document.querySelectorAll('[id^="pillar-"], #summary, #actions, #raw');
  const links = document.querySelectorAll('aside nav a');
  const obs = new IntersectionObserver(entries => {{
    entries.forEach(e => {{
      if (e.isIntersecting) {{
        links.forEach(l => l.classList.remove('bg-gray-800','text-white'));
        const a = document.querySelector(`aside nav a[href="#${{e.target.id}}"]`);
        if (a) a.classList.add('bg-gray-800','text-white');
      }}
    }});
  }}, {{rootMargin:'-20% 0px -70% 0px'}});
  sections.forEach(s => obs.observe(s));
</script>
</body>
</html>"""


def save_report(report_text: str, target_path: str, output_dir: str = ".",
                base_name: str | None = None, metadata: dict | None = None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = os.path.basename(os.path.abspath(target_path))
    filename = f"{base_name}.html" if base_name else f"cost_review_{target_name}_{timestamp}.html"
    output_path = os.path.join(output_dir, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(generate_html(report_text, target_path, metadata=metadata))
    return output_path
