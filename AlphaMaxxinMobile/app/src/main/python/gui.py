"""
AlphaMaxxin GUI — Clean rewrite.
Features:
- Predictive dropdown for ticker/company search using Yahoo Finance
- HTML report rendered in the default browser (Bloomberg/Morningstar style)
- Error popups for invalid tickers
"""
# import customtkinter as ctk
import threading
import asyncio
import os
import sys
import webbrowser
import tempfile
import datetime

try:
    from runner import run_agent, get_metrics_sync, search_ticker, fetch_live_price
except ImportError:
    async def run_agent(agent_name, analysis_target="Portfolio.md"):
        return f"System Stub: {agent_name} executed on {analysis_target}."
    def get_metrics_sync(target_input="Portfolio.md"):
        return {"regime": "STANDBY", "agg_score": 0.00, "overrides": "NONE", "holdings": [], "holdings_count": 0}
    def search_ticker(query, max_results=6):
        return []
    def fetch_live_price(query):
        return None

# ctk.set_appearance_mode("Light")
# ctk.set_default_color_theme("blue")


def render_report_html(title: str, report_text: str) -> str:
    """Convert markdown-ish report text to a beautiful HTML page."""
    import html as html_mod
    import re
    safe_text = html_mod.escape(report_text)

    KNOWN_LABELS = [
        "Investment Thesis", "Entry Range", "Price Target", "Stop Level", "Risk/Reward",
        "Instrument", "Structure", "Options Details", "Conviction Tier", "Composite Score",
        "Position Size", "Signal Sources", "Conflicting Lines", "Key Threats", "Catalyst Watch",
        "Direction", "Time Horizon", "Sleeve", "Geography", "Asset Class", "Ticker / Name",
        "Field Content", "Exit Conditions", "Loss Exit", "Time Exit"
    ]

    # Pre-process lines to ensure labels are formatted clearly without colons and with bolding
    lines = safe_text.split("\n")
    for i in range(len(lines)):
        line = lines[i].strip()
        for label in KNOWN_LABELS:
            pattern = r'^(?:\*\*|)?' + re.escape(label) + r'(?:\*\*|)?\s*:?\s*(.*)$'
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                rest_of_line = match.group(1).strip()
                # Special handling for Price Target inline fields
                if label.lower() == "price target":
                    rest_of_line = re.sub(r'\|\s*(Bull Case Target|Bear Case Limit)\s*:?\s*', r'| **\1:** ', rest_of_line, flags=re.IGNORECASE)
                    rest_of_line = re.sub(r'(Base Case Target)\s*:?\s*', r'**\1:** ', rest_of_line, flags=re.IGNORECASE)
                lines[i] = f"**{label}:** {rest_of_line}"
                break
    
    safe_text = "\n".join(lines)

    # Convert markdown patterns to HTML
    # Bold: **text**
    safe_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe_text)
    
    lines = safe_text.split("\n")
    html_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        # Table rows
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip().strip('*') for c in stripped.split("|")[1:-1]]
            if all(set(c) <= set("- :") for c in cells):
                continue
            if not in_table:
                html_lines.append('<table>')
                in_table = True
                html_lines.append('<tr>' + ''.join(f'<th>{c}</th>' for c in cells) + '</tr>')
            else:
                html_lines.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')
            continue
        else:
            if in_table:
                html_lines.append('</table>')
                in_table = False

        if stripped.startswith("### "):
            html_lines.append(f'<h3>{stripped[4:]}</h3>')
        elif stripped.startswith("## "):
            html_lines.append(f'<h2>{stripped[3:]}</h2>')
        elif stripped.startswith("# "):
            html_lines.append(f'<h2 class="h1-equivalent">{stripped[2:]}</h2>')
        elif re.match(r'^SEVEN-SECTION COMPILED.*$', stripped, re.IGNORECASE):
            html_lines.append(f'<h1 class="main-report-title">{stripped}</h1>')
        elif re.match(r'^INVESTMENT BRIEF ARCHITECTURE COMPILATION RUN:?$', stripped, re.IGNORECASE):
            html_lines.append(f'<h3 class="system-run-title">{stripped}</h3>')
        elif re.match(r'^SECTION \d+[\s—\-:].*$', stripped, re.IGNORECASE):
            html_lines.append(f'<h2 class="section-title">{stripped}</h2>')
        elif stripped.startswith("────") or stripped == "---":
            pass
        elif stripped.startswith("*(") or (stripped.startswith("*") and stripped.endswith(")*")):
            clean = stripped.strip("*")
            html_lines.append(f'<p class="footnote">*{clean}*</p>')
        elif stripped.startswith("- ") or stripped.startswith("* "):
            html_lines.append(f'<li>{stripped[2:]}</li>')
        elif stripped == "":
            html_lines.append('<br>')
        else:
            num_match = re.match(r'^(\d+)\.\s+(.+)', stripped)
            if num_match:
                html_lines.append(f'<li>{num_match.group(2)}</li>')
            else:
                html_lines.append(f'<p>{line}</p>')

    if in_table:
        html_lines.append('</table>')

    body_content = "\n".join(html_lines)
    today = datetime.datetime.now().strftime("%B %d, %Y at %H:%M")

    # Extract ticker for logo (e.g. "Master Orchestrator — AAPL")
    ticker_match = re.search(r'—\s+([A-Z0-9]+)$', title.replace(".SI", ""))
    logo_html = ""
    if ticker_match and ticker_match.group(1) not in ("Portfolio", "MD", "Portfolio.md"):
        ticker = ticker_match.group(1)
        logo_html = f'<img src="https://financialmodelingprep.com/image-stock/{ticker}.png" alt="{ticker} Logo" style="height: 72px; width: 72px; border-radius: 8px; object-fit: contain; background: white; padding: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);" onerror="this.style.display=\'none\'">'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | AlphaMaxxin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Source+Serif+4:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background: #f8f9fa;
        color: #1a1a2e;
        line-height: 1.7;
        padding: 0;
    }}
    .header {{
        background: linear-gradient(135deg, #0f0f23 0%, #1a1a3e 50%, #16213e 100%);
        color: white;
        padding: 40px 60px;
        border-bottom: 4px solid #e94560;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .header-left {{
        flex: 1;
    }}
    .header-right {{
        margin-left: 30px;
    }}
    .header h1 {{
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 38px;
        font-weight: 700;
        margin-bottom: 8px;
        letter-spacing: -0.5px;
        color: #ffffff;
    }}
    .header .subtitle {{
        font-size: 13px;
        color: #8892b0;
        font-weight: 400;
        text-transform: uppercase;
        letter-spacing: 2px;
    }}
    .header .date {{
        font-size: 12px;
        color: #64748b;
        margin-top: 12px;
    }}
    .badge {{
        display: inline-block;
        background: #e94560;
        color: white;
        padding: 4px 12px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 12px;
    }}
    .content {{
        max-width: 950px;
        margin: 0 auto;
        padding: 50px 60px 80px;
    }}
    .main-report-title {{
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 30px;
        font-weight: 800;
        color: #e94560;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin: 60px 0 30px;
        padding-bottom: 20px;
        border-bottom: 3px solid #e94560;
    }}
    .system-run-title {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        font-weight: 700;
        color: #64748b;
        margin: 20px 0 10px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}
    .section-title {{
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 22px;
        font-weight: 700;
        color: #e94560;
        margin: 50px 0 20px;
        padding-bottom: 10px;
        border-bottom: 2px solid #e94560;
        text-transform: uppercase;
    }}
    .h1-equivalent {{
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 26px;
        font-weight: 700;
        color: #e94560;
        margin: 40px 0 20px;
        padding-bottom: 10px;
        border-bottom: 2px solid #e94560;
    }}
    h2 {{
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 20px;
        font-weight: 700;
        color: #e94560;
        margin: 45px 0 20px;
        padding-bottom: 10px;
        border-bottom: 2px solid #e94560;
    }}
    h3 {{
        font-family: 'Inter', sans-serif;
        font-size: 16px;
        font-weight: 700;
        color: #e94560;
        margin: 32px 0 12px;
        text-transform: uppercase;
        letter-spacing: 1px;
        border-bottom: 2px solid #e94560;
        padding-bottom: 6px;
    }}
    p {{
        font-size: 15px;
        margin: 14px 0;
        color: #2d3436;
        line-height: 1.8;
    }}
    strong {{
        color: #0f0f23;
        font-weight: 700;
    }}
    li {{
        font-size: 14.5px;
        margin: 8px 0 8px 24px;
        color: #2d3436;
        line-height: 1.7;
    }}
    hr.thin {{
        border: none;
        border-top: 1px solid #dfe6e9;
        margin: 24px 0;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 24px 0;
        font-size: 14px;
        background: white;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }}
    th {{
        background: #e94560;
        color: #fff;
        text-align: left;
        padding: 12px 16px;
        font-weight: 600;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    td {{
        padding: 12px 16px;
        border-bottom: 1px solid #f0f0f0;
        color: #2d3436;
    }}
    tr:nth-child(even) td {{
        background: #fafbfc;
    }}
    tr:hover td {{
        background: #fff5f5;
    }}
    .footnote {{
        font-size: 13px;
        color: #7f8c8d;
        font-style: italic;
        margin-top: 10px;
        line-height: 1.5;
    }}
    .footer {{
        text-align: center;
        padding: 30px;
        font-size: 12px;
        color: #999;
        border-top: 1px solid #eee;
        margin-top: 50px;
    }}
    br {{ display: block; margin: 8px 0; content: ""; }}
    @media print {{
        .header {{ background: #1a1a2e !important; -webkit-print-color-adjust: exact; }}
        body {{ padding: 0; }}
    }}
</style>
</head>
<body>
<div class="header">
    <div class="header-left">
        <div class="subtitle">AlphaMaxxin Research</div>
        <h1>{title}</h1>
        <div class="date">Generated: {today}</div>
        <div class="badge">Investment Research Report</div>
    </div>
    <div class="header-right">
        {logo_html}
    </div>
</div>
<div class="content">
{body_content}
</div>
<div class="footer">
    AlphaMaxxin Portfolio Agent Network v2.2 &bull; Confidential &bull; For authorized recipients only
</div>
</body>
</html>"""



