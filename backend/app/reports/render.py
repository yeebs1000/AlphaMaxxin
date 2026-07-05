"""Markdown → standalone HTML report page. Body-conversion logic ported from
gui.py's render_report_html (generic label bolding, table parsing, header
detection) with a trimmed CSS shell — synthesis now emits real markdown, so
the heuristics mostly just pass structure through."""
import datetime
import html as html_mod
import re

FIELD_LINE_RE = re.compile(
    r"^(?P<bullet>[-*]\s+)?(?P<label>[A-Z][A-Za-z0-9 /&.()'%-]{1,42}?)\s{0,4}:\s*(?P<rest>.*)$"
)
HEADER_LIKE_RE = re.compile(r"^[A-Z][A-Za-z0-9 ,/&'\-()]{1,55}\??$")


def _markdown_body_to_html(report_text: str) -> str:
    safe_text = html_mod.escape(report_text)

    lines = safe_text.split("\n")
    for i in range(len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("|") or stripped.startswith("#"):
            continue
        match = FIELD_LINE_RE.match(stripped)
        if not match:
            continue
        label = match.group("label").strip()
        if label.lower().startswith(("http", "https")):
            continue
        bullet = match.group("bullet") or ""
        lines[i] = f"{bullet}**{label}:** {match.group('rest').strip()}"
    safe_text = "\n".join(lines)
    safe_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe_text)

    def _looks_like_header(s: str) -> bool:
        if ":" in s or s.endswith(".") or "<strong>" in s:
            return False
        if not HEADER_LIKE_RE.match(s):
            return False
        return len(s.rstrip("?").split()) <= 8

    html_lines = []
    in_table = False
    pending_tag = None
    pending_text: list[str] = []

    def flush_pending():
        nonlocal pending_tag, pending_text
        if pending_tag and pending_text:
            content = " ".join(t.strip() for t in pending_text if t.strip())
            if content:
                html_lines.append(f"<{pending_tag}>{content}</{pending_tag}>")
        pending_tag = None
        pending_text = []

    for line in safe_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_pending()
            cells = [c.strip().strip("*") for c in stripped.split("|")[1:-1]]
            if all(set(c) <= set("- :") for c in cells):
                continue
            if not in_table:
                html_lines.append("<table>")
                in_table = True
                html_lines.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
            else:
                html_lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            html_lines.append("</table>")
            in_table = False

        if stripped.startswith("### "):
            flush_pending()
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            flush_pending()
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            flush_pending()
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("────") or stripped == "---":
            flush_pending()
        elif stripped.startswith("- ") or stripped.startswith("* "):
            flush_pending()
            pending_tag = "li"
            pending_text = [stripped[2:]]
        elif stripped == "":
            flush_pending()
            html_lines.append("<br>")
        else:
            num_match = re.match(r"^(\d+)\.\s+(.+)", stripped)
            if num_match:
                flush_pending()
                pending_tag = "li"
                pending_text = [num_match.group(2)]
            elif pending_tag is None and _looks_like_header(stripped):
                html_lines.append(f"<h3>{stripped}</h3>")
            elif stripped.startswith("<strong>"):
                flush_pending()
                html_lines.append(f"<p>{stripped}</p>")
            elif pending_tag in ("li", "p"):
                pending_text.append(stripped)
            else:
                pending_tag = "p"
                pending_text = [stripped]

    flush_pending()
    if in_table:
        html_lines.append("</table>")
    return "\n".join(html_lines)


# Ticker at the end of a title like "Lite — MSFT" gets a company logo next
# to the header (skipped for portfolio/watchlist/multi-ticker targets, where
# "ticker" isn't a single, clean symbol).
_TICKER_SUFFIX_RE = re.compile(r"—\s*([A-Z]{1,6})$")
_NOT_A_TICKER = {"PORTFOLIO", "WATCHLIST"}


def _logo_html(title: str) -> str:
    match = _TICKER_SUFFIX_RE.search(title.replace(".SI", "").upper())
    if not match or match.group(1) in _NOT_A_TICKER:
        return ""
    ticker = match.group(1)
    return (f'<img class="logo" src="https://financialmodelingprep.com/image-stock/{ticker}.png" '
            f'alt="{ticker} logo" onerror="this.style.display=\'none\'">')


def render_report_html(title: str, report_text: str) -> str:
    body = _markdown_body_to_html(report_text)
    generated = datetime.datetime.now().strftime("%B %d, %Y at %H:%M")
    safe_title = html_mod.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_title} | AlphaMaxxin</title>
<style>
  :root {{
    --bg: #0b0b0c; --panel: #17181a; --panel-2: #1d1e21;
    --border: rgba(255,255,255,.08); --border-strong: rgba(255,255,255,.16);
    --text: #f4f4f3; --muted: #a6a6a3;
    --brand: #e94560; --brand-bg: rgba(233,69,96,.14);
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', Inter, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.65; font-size: 15px; }}
  .header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px;
            padding: 28px 40px; border-bottom: 1px solid var(--border); }}
  .header h1 {{ font-size: 1.35rem; font-weight: 650; color: var(--text); }}
  .header .meta {{ color: var(--muted); font-size: 0.82rem; margin-top: 6px; }}
  .logo {{ height: 56px; width: 56px; border-radius: 10px; object-fit: contain;
          background: white; padding: 4px; flex-shrink: 0; }}
  .content {{ max-width: 860px; margin: 0 auto; padding: 32px 24px 72px; }}
  .content h1, .content h2 {{ color: var(--text); margin: 26px 0 10px;
    border-bottom: 1px solid var(--border); padding-bottom: 6px; font-size: 1.15rem; }}
  .content h3 {{ color: var(--text); margin: 18px 0 8px; font-size: 1.02rem; }}
  p, li {{ margin: 6px 0; color: var(--text); }}
  li {{ margin-left: 24px; }}
  strong {{ color: var(--text); }}
  table {{ border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 0.9rem;
          background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
          overflow: hidden; }}
  th {{ background: var(--panel-2); color: var(--muted); text-align: left;
       text-transform: uppercase; font-size: 0.72rem; letter-spacing: .3px; }}
  th, td {{ border-bottom: 1px solid var(--border); padding: 9px 12px; }}
  tr:last-child td {{ border-bottom: none; }}
  .footnote {{ color: var(--muted); font-size: 0.82rem; }}
  .disclaimer {{ margin-top: 40px; padding: 14px 18px; background: var(--brand-bg);
                border-left: 3px solid var(--brand); border-radius: 6px;
                font-size: 0.8rem; color: var(--muted); }}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>{safe_title}</h1>
    <div class="meta">AlphaMaxxin research report — generated {generated}</div>
  </div>
  {_logo_html(title)}
</div>
<div class="content">
{body}
<div class="disclaimer">AI-generated research, not financial advice. Numbers
come from the data feeds available at generation time and may be wrong,
delayed, or incomplete. You are solely responsible for your investment
decisions.</div>
</div>
</body>
</html>"""
