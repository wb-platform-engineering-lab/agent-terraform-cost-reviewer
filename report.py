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
    """Convert agent markdown output to clean HTML — no raw ### or ** visible."""
    lines = text.split("\n")
    html = []
    in_code = False
    in_table = False
    code_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # Fenced code block
        if s.startswith("```"):
            if not in_code:
                in_code = True
                code_lines = []
            else:
                in_code = False
                escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html.append(
                    f'<pre class="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto my-3 font-mono leading-relaxed">{escaped}</pre>'
                )
                code_lines = []
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Table row detection
        if s.startswith("|") and s.endswith("|"):
            # Skip separator rows like |---|---|
            if re.match(r"^\|[\s\-:|]+\|$", s):
                i += 1
                continue
            # First table row → start table
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

        # Skip pure separator lines
        if re.match(r"^[-─═]{3,}$", s):
            i += 1
            continue

        # Headings
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

        # Blockquote
        if s.startswith(">"):
            content = _inline(s.lstrip("> ").strip())
            html.append(
                f'<blockquote class="border-l-4 border-blue-400 bg-blue-50 dark:bg-blue-900/20 px-4 py-2 my-3 text-sm text-gray-700 dark:text-gray-300 rounded-r-lg">{content}</blockquote>'
            )
            i += 1
            continue

        # Bullet list
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

        # Numbered list
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

        # Horizontal rule
        if re.match(r"^---+$", s) or re.match(r"^===+$", s):
            html.append('<hr class="border-gray-200 dark:border-gray-700 my-4"/>')
            i += 1
            continue

        # Empty line
        if not s:
            html.append('<div class="h-2"></div>')
            i += 1
            continue

        # Paragraph
        html.append(f'<p class="text-sm text-gray-700 dark:text-gray-300 mb-2">{_inline(s)}</p>')
        i += 1

    if in_table:
        html.append("</tbody></table></div>")
    if in_code and code_lines:
        escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html.append(f'<pre class="bg-gray-900 text-green-300 text-xs rounded-xl p-4 overflow-x-auto my-3 font-mono">{escaped}</pre>')

    return "\n".join(html)


def _inline(text: str) -> str:
    """Convert inline markdown: bold, italic, code, links, emoji status."""
    # Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Status emojis → badges
    text = text.replace("✅ PASS", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800">✅ PASS</span>')
    text = text.replace("❌ FAIL", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-800">❌ FAIL</span>')
    text = text.replace("⚠️ WARN", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-yellow-100 text-yellow-800">⚠️ WARN</span>')
    text = text.replace("ℹ️ INFO", '<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 text-blue-800">ℹ️ INFO</span>')

    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r'<strong class="font-semibold text-gray-900 dark:text-white">\1</strong>', text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r'<em class="italic">\1</em>', text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r'<code class="bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-xs px-1.5 py-0.5 rounded font-mono">\1</code>', text)
    # Links
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" class="text-blue-500 hover:underline">\1</a>', text)

    return text


# ─────────────────────────────────────────────
# Parser — extracts structured data from text
# ─────────────────────────────────────────────

def _pillar_num_from_line(s: str):
    """Extract pillar number (1-6) from a heading line — handles all known formats."""
    # "### Pillar 1 —" or "## Pillar 1:"
    m = re.match(r"#{0,4}\s*\**\s*Pillar\s*([1-6])\b", s)
    if m:
        return m.group(1)
    # "#### **P1: Name" or "#### P1 — Name"
    m = re.match(r"#{1,4}\s*\**\s*P([1-6])\s*[:\-—–]", s)
    if m:
        return m.group(1)
    # "### 1. **Governance & Control**" or "### 1. Security — FAIL"
    m = re.match(r"#{1,4}\s*\**([1-6])[.)]\s", s)
    if m:
        return m.group(1)
    return None


def parse_report(text: str) -> dict:
    """
    Parse the cost review report into structured data.
    Handles C-XXX check IDs grouped into a single Cost Optimization pillar.
    """
    checks = []
    overall_score = None
    action_items = []
    seen_ids = set()
    in_actions = False
    last_check_idx = None  # index into checks[] for appending recommendations

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

        # ── Section header: ### **[C-001] Name** or ### [C-001] Name ─
        m = re.match(r"#{1,4}\s*\**\s*\[?(C-\d+)\]?\s*\**\s*(.+)", s)
        if m:
            check_id = m.group(1)
            name = re.sub(r"[\*\[\]]", "", m.group(2)).strip().strip("*").strip()
            if check_id not in seen_ids:
                seen_ids.add(check_id)
                checks.append({
                    "status": "fail",   # finding sections are failures
                    "id": check_id,
                    "name": name,
                    "recommendation": None,
                })
                last_check_idx = len(checks) - 1
            continue

        # ── Inline check from run_cost_checks: ❌ FAIL [C-001] Name ──
        m = re.match(r"(❌|⚠️|✅|ℹ️)\s*(FAIL|WARN|PASS|INFO)\s+\[?(C-\d+)\]?\s*(.*)", s)
        if m:
            emoji, status_str, check_id, name = m.group(1), m.group(2), m.group(3), m.group(4)
            name = re.sub(r"\[cross-resource\]", "", name).strip()
            if check_id not in seen_ids:
                seen_ids.add(check_id)
                checks.append({
                    "status": status_str.lower(),
                    "id": check_id,
                    "name": name or check_id,
                    "recommendation": None,
                })
                last_check_idx = len(checks) - 1
            continue

        # ── Table row summary: | C-001 | Description | file | saving ─
        if s.startswith("|") and not re.match(r"^\|[\s\-:|]+\|$", s):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and re.match(r"C-\d+", cells[0]):
                check_id = re.match(r"C-\d+", cells[0]).group(0)
                name = cells[1] if len(cells) > 1 else check_id
                # Determine status from emoji in any cell
                row_text = " ".join(cells)
                if "❌" in row_text or "FAIL" in row_text:
                    cstatus = "fail"
                elif "⚠️" in row_text or "WARN" in row_text:
                    cstatus = "warn"
                elif "✅" in row_text or "PASS" in row_text:
                    cstatus = "pass"
                else:
                    cstatus = "fail"  # table rows are findings → fail
                # Saving estimate (last non-empty cell)
                saving = next((c for c in reversed(cells) if c and c != "—"), None)
                if check_id not in seen_ids:
                    seen_ids.add(check_id)
                    checks.append({
                        "status": cstatus,
                        "id": check_id,
                        "name": name,
                        "recommendation": saving if saving != name else None,
                    })
                    last_check_idx = len(checks) - 1
            continue

        # ── Est. saving line → attach to last check ──────────────────
        if last_check_idx is not None and re.search(r"est\.?\s*sav", s, re.IGNORECASE):
            saving = re.sub(r"\*+|💰", "", s).strip()
            checks[last_check_idx]["recommendation"] = saving
            continue

        # ── Action items ─────────────────────────────────────────────
        if re.search(r"(top \d|priority order|highest.impact|prioritized action|quick wins?)", s, re.IGNORECASE):
            in_actions = True
            continue
        if in_actions:
            # Stop at new major sections
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

    # ── Build single Cost Optimization pillar ────────────────────────
    passing = sum(1 for c in checks if c["status"] == "pass")
    total   = len(checks) if checks else 15
    has_fail = any(c["status"] == "fail" for c in checks)
    has_warn = any(c["status"] == "warn" for c in checks)
    pillar_status = "fail" if has_fail else ("warn" if has_warn else "pass")

    pillar = {
        "num": "1",
        "name": "Cost Optimization",
        "status": pillar_status,
        "pass": passing,
        "total": total,
        "checks": checks,
    }

    # ── Fallback overall score ────────────────────────────────────────
    if not overall_score:
        overall_score = (passing, total) if total else (0, 15)

    return {
        "pillars": [pillar],
        "overall_score": overall_score,
        "action_items": action_items[:5],
        "raw": text,
    }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

PILLAR_ICONS = {
    "1": "fa-coins",
}
PILLAR_COLORS = {
    "1": "#10b981",  # emerald — cost / savings
}

def _status_classes(status: str):
    return {
        "pass": ("bg-emerald-500 text-white",  "text-emerald-500", "bg-emerald-500"),
        "fail": ("bg-red-500 text-white",      "text-red-500",     "bg-red-500"),
        "warn": ("bg-amber-400 text-white",    "text-amber-500",   "bg-amber-400"),
        "info": ("bg-blue-500 text-white",     "text-blue-500",    "bg-blue-500"),
    }.get(status, ("bg-gray-400 text-white", "text-gray-500", "bg-gray-400"))


# ─────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────

def _score_card(score, score_pct, score_color_hex, grade, grade_cls, target_name, timestamp):
    r, c = 40, 251.2
    offset = c - (score_pct / 100) * c
    return f"""
    <div class="bg-white dark:bg-gray-800 rounded-2xl p-6 shadow-sm flex flex-col items-center">
      <h2 class="text-lg font-bold mb-4 text-gray-900 dark:text-white">Overall Score</h2>
      <div class="w-36 h-36 relative">
        <svg class="-rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="{r}" stroke="#e5e7eb" stroke-width="10" fill="none"/>
          <circle cx="50" cy="50" r="{r}" stroke="{score_color_hex}"
            stroke-width="10" stroke-dasharray="{c}" stroke-dashoffset="{offset:.1f}"
            stroke-linecap="round" fill="none"/>
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <div class="text-xs text-gray-500">Score</div>
          <div class="text-2xl font-bold text-gray-900 dark:text-white">{score_pct}%</div>
          <span class="mt-1 px-3 py-1 rounded-full text-xs font-semibold {grade_cls}">{grade}</span>
        </div>
      </div>
      <div class="mt-4 text-center">
        <div class="font-semibold text-gray-700 dark:text-gray-200 text-sm">{target_name}</div>
        <div class="text-xs text-gray-400 mt-1">{score[0]}/{score[1]} checks passing</div>
        <div class="text-xs text-gray-400 mt-0.5">{timestamp}</div>
      </div>
    </div>"""


def _pillar_summary_cards(pillars):
    cards = ""
    for p in pillars:
        badge_cls, text_cls, _ = _status_classes(p["status"])
        pct = int(p["pass"] / p["total"] * 100) if p["total"] else 0
        bar_color = {"pass": "bg-emerald-500", "fail": "bg-red-500", "warn": "bg-yellow-400"}.get(p["status"], "bg-gray-400")
        icon = PILLAR_ICONS.get(p["num"], "fa-circle")
        color = PILLAR_COLORS.get(p["num"], "#2563eb")
        cards += f"""
        <div class="bg-white dark:bg-gray-800 rounded-2xl p-5 shadow-sm">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2">
              <div class="w-8 h-8 rounded-xl flex items-center justify-center" style="background:{color}">
                <i class="fas {icon} text-xs text-white"></i>
              </div>
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">Pillar {p["num"]}</span>
            </div>
            <span class="text-xs font-semibold px-2 py-0.5 rounded-full {badge_cls}">{p["status"].upper()}</span>
          </div>
          <div class="font-semibold text-gray-900 dark:text-white text-sm mb-3 leading-snug">{p["name"]}</div>
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="text-gray-400">{p["pass"]}/{p["total"]} passing</span>
            <span class="font-bold {text_cls}">{pct}%</span>
          </div>
          <div class="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2">
            <div class="h-2 rounded-full" style="width:{pct}%;background:{color}"></div>
          </div>
        </div>"""
    return cards


def _action_items(items):
    if not items:
        return ""
    rows = ""
    urgencies = [
        ("High",   "bg-red-100 text-red-700",     "fa-circle-exclamation text-red-500"),
        ("Medium", "bg-yellow-100 text-yellow-700","fa-triangle-exclamation text-yellow-500"),
        ("Low",    "bg-emerald-100 text-emerald-700","fa-circle-check text-emerald-500"),
    ]
    for i, item in enumerate(items[:5]):
        label, badge_cls, icon_cls = urgencies[min(i, 2)]
        clean_item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
        clean_item = re.sub(r"`([^`]+)`", r'<code class="bg-gray-100 text-gray-700 text-xs px-1 rounded font-mono">\1</code>', clean_item)
        rows += f"""
        <div class="flex items-start gap-4 p-4 border-b border-gray-100 dark:border-gray-700 last:border-0">
          <div class="w-8 h-8 rounded-full bg-gray-900 flex items-center justify-center text-white text-sm font-bold flex-shrink-0 mt-0.5">{i+1}</div>
          <div class="flex-1 min-w-0">
            <div class="text-sm text-gray-800 dark:text-gray-200 mb-1.5">{clean_item}</div>
            <span class="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full {badge_cls}">
              <i class="fas {icon_cls} text-xs"></i>{label} priority
            </span>
          </div>
        </div>"""
    return rows


def _pillar_detail_sections(pillars):
    sections = ""
    for p in pillars:
        icon = PILLAR_ICONS.get(p["num"], "fa-circle")
        color = PILLAR_COLORS.get(p["num"], "#2563eb")
        badge_cls, text_cls, _ = _status_classes(p["status"])
        pct = int(p["pass"] / p["total"] * 100) if p["total"] else 0
        bar_color = {"pass": "bg-emerald-500", "fail": "bg-red-500", "warn": "bg-yellow-400"}.get(p["status"], "bg-gray-400")

        checks_html = ""
        for c in p["checks"]:
            cb, ct, _ = _status_classes(c["status"])
            ci = {
                "pass": "fa-circle-check text-emerald-500",
                "fail": "fa-circle-xmark text-red-500",
                "warn": "fa-triangle-exclamation text-yellow-500",
                "info": "fa-circle-info text-blue-500",
            }.get(c["status"], "fa-circle text-gray-400")

            rec = ""
            if c["recommendation"] and c["recommendation"] != "—":
                clean_rec = re.sub(r"\*\*(.+?)\*\*", r"\1", c["recommendation"])
                clean_rec = re.sub(r"`([^`]+)`",
                    r'<code class="bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-xs px-1 rounded font-mono">\1</code>',
                    clean_rec)
                rec = f'<div class="mt-1.5 pl-16 flex items-start gap-2 text-xs text-gray-500 dark:text-gray-400"><i class="fas fa-arrow-right text-red-400 mt-0.5 flex-shrink-0"></i><span>{clean_rec}</span></div>'

            checks_html += f"""
            <div class="py-3 border-b border-gray-50 dark:border-gray-700/50 last:border-0">
              <div class="flex items-center gap-3 flex-wrap">
                <i class="fas {ci} flex-shrink-0"></i>
                <span class="text-xs font-bold px-2 py-0.5 rounded-full {cb} min-w-[44px] text-center">{c["status"].upper()}</span>
                <span class="font-mono text-xs text-gray-400 min-w-[52px]">{c["id"]}</span>
                <span class="text-sm text-gray-800 dark:text-gray-200">{c["name"]}</span>
              </div>
              {rec}
            </div>"""

        if not checks_html:
            checks_html = '<p class="text-sm text-gray-400 py-3">No individual checks recorded.</p>'

        sections += f"""
        <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="pillar-{p["num"]}">
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700" style="border-left:4px solid {color}">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0" style="background:{color}">
                <i class="fas {icon} text-sm text-white"></i>
              </div>
              <div>
                <div class="font-bold text-gray-900 dark:text-white">Pillar {p["num"]} — {p["name"]}</div>
                <div class="text-xs text-gray-400">{p["pass"]}/{p["total"]} checks passing</div>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <div class="w-20 bg-gray-100 dark:bg-gray-700 rounded-full h-2 hidden sm:block">
                <div class="{bar_color} h-2 rounded-full" style="width:{pct}%"></div>
              </div>
              <span class="text-sm font-bold {text_cls} w-8 text-right">{pct}%</span>
              <span class="text-xs font-bold px-2 py-1 rounded-full {badge_cls}">{p["status"].upper()}</span>
            </div>
          </div>
          <div class="px-6 py-1">{checks_html}</div>
        </div>"""
    return sections


def _nav_items(pillars):
    items = ""
    for p in pillars:
        icon = PILLAR_ICONS.get(p["num"], "fa-circle")
        dot_cls = {"pass": "text-emerald-500", "fail": "text-red-500", "warn": "text-yellow-400"}.get(p["status"], "text-gray-400")
        di = {"pass": "fa-circle-check", "fail": "fa-circle-xmark", "warn": "fa-triangle-exclamation"}.get(p["status"], "fa-circle")
        items += f"""
        <a href="#pillar-{p["num"]}" class="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-white transition text-sm">
          <i class="fas {di} {dot_cls} text-xs w-3 flex-shrink-0"></i>
          <i class="fas {icon} text-xs w-3 text-gray-600 flex-shrink-0"></i>
          <span class="truncate">P{p["num"]} — {p["name"]}</span>
        </a>"""
    return items


# ─────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────

def generate_html(report_text: str, target_path: str) -> str:
    data = parse_report(report_text)
    timestamp = datetime.now().strftime("%B %d, %Y · %H:%M")
    target_abs = os.path.abspath(target_path)
    target_name = os.path.basename(target_abs)

    score = data["overall_score"] or (0, 1)
    score_pct = int(score[0] / score[1] * 100) if score[1] else 0

    if score_pct >= 75:
        score_color_hex, grade = "#16a34a", "PASS"
        grade_cls = "bg-emerald-100 text-emerald-800"
    elif score_pct >= 40:
        score_color_hex, grade = "#fb923c", "AT RISK"
        grade_cls = "bg-orange-100 text-orange-700"
    else:
        score_color_hex, grade = "#dc2626", "FAIL"
        grade_cls = "bg-red-100 text-red-800"

    score_card_html    = _score_card(score, score_pct, score_color_hex, grade, grade_cls, target_name, timestamp)
    summary_cards_html = _pillar_summary_cards(data["pillars"])
    actions_html       = _action_items(data["action_items"])
    detail_html        = _pillar_detail_sections(data["pillars"])
    nav_html           = _nav_items(data["pillars"])
    full_report_html   = md_to_html(report_text)

    actions_block = ""
    if actions_html:
        actions_block = f"""
        <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="actions">
          <div class="flex items-center gap-3 px-6 py-4 border-b border-gray-100 dark:border-gray-700 bg-gray-900">
            <i class="fas fa-bullseye text-white"></i>
            <h3 class="text-white font-semibold">Priority Actions</h3>
          </div>
          {actions_html}
        </div>"""

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
        <i class="fas fa-file-lines text-xs w-4 text-gray-500"></i><span>Full Report</span>
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
      <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
        <div>
          <div class="flex items-center gap-2 mb-2">
            <i class="fas fa-coins text-emerald-500"></i>
            <span class="text-xs font-bold text-emerald-500 uppercase tracking-wider">Terraform Cost Architecture Review</span>
          </div>
          <h1 class="text-2xl font-black mb-3 text-gray-900 dark:text-white">Cost Optimization Report</h1>
          <div class="flex items-center gap-2 bg-gray-100 dark:bg-gray-700 rounded-lg px-3 py-1.5 w-fit mb-3">
            <i class="fas fa-folder-open text-gray-400 text-xs"></i>
            <code class="text-gray-600 dark:text-gray-300 text-xs">{target_abs}</code>
          </div>
          <div class="text-gray-400 text-sm">
            <i class="fas fa-clock mr-1"></i>{timestamp}
            &nbsp;·&nbsp;
            <i class="fas fa-robot mr-1"></i>claude-haiku-4-5
          </div>
        </div>
        <div class="flex-shrink-0 bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-2xl p-6 text-center min-w-[150px]">
          <div class="text-5xl font-black" style="color:{score_color_hex}">{score_pct}%</div>
          <div class="text-gray-400 text-xs mt-1">{score[0]}/{score[1]} checks</div>
          <span class="mt-2 inline-block px-4 py-1 rounded-full text-sm font-bold {grade_cls}">{grade}</span>
        </div>
      </div>
    </div>

    <!-- SCORE + PILLAR CARDS -->
    <div class="grid grid-cols-1 lg:grid-cols-4 gap-5">
      {score_card_html}
      <div class="lg:col-span-3 grid grid-cols-2 lg:grid-cols-3 gap-4">
        {summary_cards_html}
      </div>
    </div>

    <!-- PRIORITY ACTIONS -->
    {actions_block}

    <!-- DETAILED FINDINGS -->
    <div>
      <h2 class="text-base font-bold text-gray-700 dark:text-gray-300 mb-4 flex items-center gap-2 uppercase tracking-wider text-xs">
        <i class="fas fa-magnifying-glass"></i> Detailed Findings
      </h2>
      <div class="space-y-4">{detail_html}</div>
    </div>

    <!-- FULL REPORT — rendered markdown, no raw text -->
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm overflow-hidden" id="raw">
      <button type="button"
        class="w-full flex justify-between items-center px-6 py-4 text-left font-semibold text-gray-900 dark:text-white border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition focus:outline-none"
        onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('i.chevron').classList.toggle('rotate-180')">
        <span class="flex items-center gap-2 text-sm">
          <i class="fas fa-file-lines text-gray-400"></i>Full Agent Report
        </span>
        <i class="fas fa-chevron-down text-gray-400 chevron transition-transform duration-300"></i>
      </button>
      <div class="hidden px-6 py-6">
        {full_report_html}
      </div>
    </div>

    <!-- FOOTER -->
    <div class="text-center text-xs text-gray-400 pt-4 pb-8 border-t border-gray-100 dark:border-gray-700">
      Generated by <a href="https://github.com/wb-platform-engineering-lab/agent-waf-reviewer" class="text-blue-500 hover:underline">agent-waf-reviewer</a>
      · claude-sonnet-4-6 · {timestamp}
    </div>
  </main>
</div>

<script>
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


def save_report(report_text: str, target_path: str, output_dir: str = ".") -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = os.path.basename(os.path.abspath(target_path))
    filename = f"cost_review_{target_name}_{timestamp}.html"
    output_path = os.path.join(output_dir, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(generate_html(report_text, target_path))
    return output_path
