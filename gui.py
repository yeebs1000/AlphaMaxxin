"""
AlphaMaxxin GUI v3.0 — Premium Dual-Theme with Portfolio Editor.
Features:
- All paid data/LLM APIs live and linked: Claude, Gemini, OpenAI, Finnhub,
  Alpha Vantage, moomoo OpenD (quotes, positions, order book, analyst data)
- Light / Dark theme toggle with smooth transitions
- Premium glassmorphism cards and gradient sidebar
- Tabbed interface: Dashboard + Portfolio Editor + Historical Chart + News Feed
- Predictive dropdown for ticker/company search (Yahoo Finance)
- HTML report rendered in the default browser (Bloomberg style)
- In-app portfolio editing with save-to-file
- All 32 agents from AGENTS_v3.0.md — institutional-concise report output
- Animated status indicators and progress bar
"""
import customtkinter as ctk
import threading
import asyncio
import os
import sys
import webbrowser
import datetime
import tkinter as tk
from tkinter import ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib
matplotlib.use('TkAgg')

# Note: customtkinter already calls SetProcessDpiAwareness(2) internally the
# moment any CTk/CTkToplevel window is created (see ScalingTracker.activate_
# high_dpi_awareness in its scaling_tracker.py) — an extra call here was tried
# and reverted: calling it again, earlier and outside that code path, shifted
# window placement off-monitor on a multi-monitor setup during testing.

try:
    from runner import (
        run_agent, get_metrics_sync, search_ticker, fetch_live_price,
        parse_portfolio_full, save_portfolio, sync_portfolio_from_moomoo
    )
except ImportError:
    async def run_agent(agent_name, analysis_target="Portfolio.md", active_agents=None, progress_callback=None):
        return f"System Stub: {agent_name} executed on {analysis_target}."
    def get_metrics_sync(target_input="Portfolio.md"):
        return {"regime": "STANDBY", "agg_score": 0.00, "overrides": "NONE", "holdings": [], "holdings_count": 0}
    def search_ticker(query, max_results=6):
        return []
    def fetch_live_price(query):
        return None
    def parse_portfolio_full(file_path=None):
        return []
    def save_portfolio(holdings, file_path=None):
        pass
    def sync_portfolio_from_moomoo(external_path=None, file_path=None):
        return {"success": False, "holdings": [], "error": "runner module unavailable"}

try:
    from news_fetcher import fetch_portfolio_news, format_news_for_llm
    _NEWS_AVAILABLE = True
except ImportError:
    _NEWS_AVAILABLE = False
    def fetch_portfolio_news(tickers, **kwargs):
        return []
    def format_news_for_llm(articles, **kwargs):
        return ""

try:
    from moomoo_client import MOOMOO_AVAILABLE as _MOOMOO_MODULE_AVAILABLE, get_moomoo_orderbook
except ImportError:
    _MOOMOO_MODULE_AVAILABLE = False
    def get_moomoo_orderbook(ticker, depth=10):
        return None

# =============================================================================
# Theme Palettes
# =============================================================================
THEMES = {
    "dark": {
        "bg_root":        "#0b0b1e",
        "bg_sidebar":     "#0f0f2a",
        "bg_card":        "#151538",
        "bg_card_hover":  "#1c1c4a",
        "bg_input":       "#1a1a40",
        "bg_header":      "#111130",
        "border":         "#282860",
        "border_light":   "#383878",
        "accent":         "#e94560",
        "accent_hover":   "#ff5a78",
        "accent_soft":    "#2d1525",
        "text_primary":   "#ffffff",       # Increased from #eeeef5 for legibility
        "text_secondary": "#a5adc6",       # Increased from #8b92b0 for legibility
        "text_muted":     "#7a81a8",       # Increased from #555880 for legibility
        "text_label":     "#cdd2ee",       # Increased from #a0a4c0 for legibility
        "emerald":        "#10B981",
        "emerald_soft":   "#0d2e22",
        "gold":           "#F59E0B",
        "crimson":        "#EF4444",
        "log_bg":         "#08081a",
        "log_text":       "#10B981",
        "tree_bg":        "#151538",
        "tree_fg":        "#ffffff",       # Increased from #eeeef5
        "tree_sel":       "#1c1c4a",
        "tree_heading_bg":"#1c1c38",       # Clean dark blue-grey instead of red
        "tree_heading_fg":"#ffffff",
        "tree_stripe":    "#1a1a42",
        "scrollbar":      "#282860",
        "scrollbar_hover":"#383878",
        "ctk_mode":       "Dark",
    },
    "light": {
        "bg_root":        "#f4f5f9",
        "bg_sidebar":     "#ffffff",
        "bg_card":        "#ffffff",
        "bg_card_hover":  "#f0f1f5",
        "bg_input":       "#f0f1f5",
        "bg_header":      "#f8f8fc",
        "border":         "#e0e2ea",
        "border_light":   "#d0d3dd",
        "accent":         "#d6365b",
        "accent_hover":   "#e94560",
        "accent_soft":    "#fce8ec",
        "text_primary":   "#1a1a2e",
        "text_secondary": "#5a5e78",
        "text_muted":     "#9498b0",
        "text_label":     "#5a5e78",
        "emerald":        "#059669",
        "emerald_soft":   "#d1fae5",
        "gold":           "#d97706",
        "crimson":        "#dc2626",
        "log_bg":         "#f8f8fc",
        "log_text":       "#1a1a2e",
        "tree_bg":        "#ffffff",
        "tree_fg":        "#1a1a2e",
        "tree_sel":       "#fce8ec",
        "tree_heading_bg":"#e2e8f0",       # Clean light grey instead of red
        "tree_heading_fg":"#1a1a2e",
        "tree_stripe":    "#fafbfd",
        "scrollbar":      "#d0d3dd",
        "scrollbar_hover":"#b0b4c0",
        "ctk_mode":       "Light",
    },
}


def wrap_text(text, limit=22):
    words = text.split(" ")
    lines = []
    curr_line = []
    curr_len = 0
    for w in words:
        if curr_len + len(w) + len(curr_line) > limit:
            lines.append(" ".join(curr_line))
            curr_line = [w]
            curr_len = len(w)
        else:
            curr_line.append(w)
            curr_len += len(w)
    if curr_line:
        lines.append(" ".join(curr_line))
    return "\n".join(lines)


# =============================================================================
# AGENT LIST (all 32 agents from v3.0)
# =============================================================================
ALL_AGENTS = [
    "US Macro Analyst",
    "APAC Macro Analyst",
    "China Market Agent",
    "Japan Market Agent",
    "Korea Market Agent",
    "EMEA / Rest-of-World Analyst",
    "Emerging Markets Analyst",
    "Fixed Income & Rates Agent",
    "FX & Commodities Agent",
    "Alternative Data Analyst",
    "Central Bank Text & NLP Sentiment Analyst",
    "Global Corporate Supply Chain Graph Mapper",
    "Digital Footprint & Developer Momentum Scanner",
    "Global Order Book & Liquidity Profiler",
    "Politician Portfolio Scanner",
    "Real-Time News Intelligence Agent",
    "Fundamental Analysis Agent",
    "Technical Analysis Agent",
    "Sector Analyst Agent",
    "Social Sentiment Scanner",
    "Catalyst & Event Calendar Agent",
    "IPO & Primary Markets Agent",
    "Private Capital & Corporate Activity Agent",
    "Machine Learning Alpha Extractor",
    "Quantitative Signal Aggregator",
    "Backtester & Simulation Validator",
    "Risk Management Agent",
    "Portfolio Construction Agent",
    "Investment Recommendation Agent",
    "Execution & Trade Management Agent",
    "CFD Funding & Cost Optimizer",
    "High-Conviction Stock & Options Screener",
]

# Layer labels for grouping in the UI
AGENT_LAYERS = {
    "LAYER 1 — DATA": ALL_AGENTS[0:16],
    "LAYER 2 — ANALYSIS": ALL_AGENTS[16:24],
    "LAYER 3 — SYNTHESIS": ALL_AGENTS[24:28],
    "LAYER 4 — OUTPUT": ALL_AGENTS[28:32],
}

# Friendly dropdown label -> real, currently-live API model id.
MODEL_ID_MAP = {
    "Gemini 2.5 Flash": "gemini-2.5-flash",
    "Gemini 3.0 Flash": "gemini-3-flash-preview",
    "Gemini 3.5 Flash": "gemini-3.5-flash",
    "Claude 3.5 Sonnet": "claude-3-5-sonnet-latest",
    "Claude 4.6 Sonnet": "claude-sonnet-4-6",
    "Claude 4.8 Opus": "claude-opus-4-8",
}


# =============================================================================
# HTML Report Renderer (unchanged from previous — preserves report formatting)
# =============================================================================
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

    lines = safe_text.split("\n")
    for i in range(len(lines)):
        line = lines[i].strip()
        for label in KNOWN_LABELS:
            pattern = r'^(?:\*\*|)?' + re.escape(label) + r'(?:\*\*|)?\s*:?\s*(.*)$'
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                rest_of_line = match.group(1).strip()
                if label.lower() == "price target":
                    rest_of_line = re.sub(r'\|\s*(Bull Case Target|Bear Case Limit)\s*:?\s*', r'| **\1:** ', rest_of_line, flags=re.IGNORECASE)
                    rest_of_line = re.sub(r'(Base Case Target)\s*:?\s*', r'**\1:** ', rest_of_line, flags=re.IGNORECASE)
                lines[i] = f"**{label}:** {rest_of_line}"
                break

    safe_text = "\n".join(lines)
    safe_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', safe_text)

    lines = safe_text.split("\n")
    html_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
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
        elif re.match(r'^SEVEN-SECTION COMPILED.*$', stripped, re.IGNORECASE) or re.match(r'^TEN-SECTION COMPILED.*$', stripped, re.IGNORECASE):
            html_lines.append(f'<h1 class="main-report-title">{stripped}</h1>')
        elif re.match(r'^INVESTMENT BRIEF ARCHITECTURE COMPILATION RUN:?$', stripped, re.IGNORECASE):
            html_lines.append(f'<h3 class="system-run-title">{stripped}</h3>')
        elif re.match(r'^SECTION \d+[a-b]?\s*[—\-:].*$', stripped, re.IGNORECASE):
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
    .header-left {{ flex: 1; }}
    .header-right {{ margin-left: 30px; }}
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
    strong {{ color: #0f0f23; font-weight: 700; }}
    li {{
        font-size: 14.5px;
        margin: 8px 0 8px 24px;
        color: #2d3436;
        line-height: 1.7;
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
    tr:nth-child(even) td {{ background: #fafbfc; }}
    tr:hover td {{ background: #fff5f5; }}
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
    AlphaMaxxin Portfolio Agent Network v3.0 &bull; All paid APIs linked &bull; Confidential &bull; For authorized recipients only
</div>
</body>
</html>"""


# =============================================================================
# Main Application
# =============================================================================

class SleekDropdown(ctk.CTkFrame):
    # Every open SleekDropdown popup, across all instances — lets the root window
    # close them all in one shot when it's moved/resized (see close_all_open()).
    _open_instances = set()

    @classmethod
    def close_all_open(cls):
        for inst in list(cls._open_instances):
            inst.close_dropdown()

    def __init__(self, master, values, command=None, font=("Segoe UI", 11), fg_color=None, text_color=None, hover_color=None, corner_radius=8, height=36, **kwargs):
        super().__init__(master, height=height, corner_radius=corner_radius, fg_color=fg_color, **kwargs)
        self.values = values
        self.command = command
        self.text_color = text_color
        self.hover_color = hover_color
        self.current_value = values[0] if values else ""
        self.dropdown_window = None

        self.btn = ctk.CTkButton(
            self, text=self.current_value, font=font, height=height - 4,
            fg_color="transparent", text_color=self.text_color,
            hover_color=self.hover_color, corner_radius=corner_radius,
            anchor="w", command=self.toggle_dropdown
        )
        self.btn.pack(fill="both", expand=True, padx=2, pady=2)

        self.arrow = ctk.CTkLabel(
            self.btn, text="▼", font=font, text_color=self.text_color,
            fg_color="transparent"
        )
        self.arrow.place(relx=1.0, rely=0.5, anchor="e", x=-12)
        
        # Ensure clicking the arrow or hovering over it affects the dropdown button correctly
        self.arrow.bind("<Button-1>", lambda e: self.toggle_dropdown())
        try:
            self.arrow.bind("<Enter>", lambda e: self.btn._on_enter())
            self.arrow.bind("<Leave>", lambda e: self.btn._on_leave())
        except AttributeError:
            pass

    def toggle_dropdown(self):
        if self.dropdown_window:
            self.close_dropdown()
            return
        
        self.dropdown_window = ctk.CTkToplevel(self)
        self.dropdown_window.overrideredirect(True)
        self.dropdown_window.attributes("-topmost", True)
        self.dropdown_window.configure(fg_color=self.cget("fg_color"))

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        width = max(self.winfo_width(), 350)  # Generous width to prevent agent clipping
        height_win = min(len(self.values) * 36 + 10, 250)
        self.dropdown_window.geometry(f"{width}x{height_win}+{x}+{y}")

        # Apple-style border and padding container (resolving dynamically based on system mode)
        mode = ctk.get_appearance_mode().lower()
        border_color = THEMES.get(mode, THEMES["dark"])["border"]
        container = ctk.CTkFrame(
            self.dropdown_window,
            fg_color=self.cget("fg_color"),
            border_width=1,
            border_color=border_color,
            corner_radius=8
        )
        container.pack(fill="both", expand=True)

        # Scrollable area to handle long lists (like all 31 agents)
        scroll_frame = ctk.CTkScrollableFrame(
            container,
            fg_color="transparent",
            corner_radius=8,
            label_text=""
        )
        scroll_frame.pack(fill="both", expand=True, padx=1, pady=1)

        btn_width = width - 40  # Force button canvas width to prevent clipping
        for val in self.values:
            b = ctk.CTkButton(
                scroll_frame, text=val, font=self.btn.cget("font"), height=32,
                width=btn_width,
                fg_color="transparent", text_color=self.text_color,
                hover_color=self.hover_color, anchor="w", corner_radius=6,
                command=lambda v=val: self.select_value(v)
            )
            b.pack(fill="x", padx=4, pady=1)

        self.dropdown_window.bind("<FocusOut>", lambda e: self.close_dropdown())
        self.dropdown_window.focus_set()
        SleekDropdown._open_instances.add(self)

    def select_value(self, value):
        self.current_value = value
        self.btn.configure(text=value)
        self.close_dropdown()
        if self.command:
            self.command(value)

    def close_dropdown(self):
        SleekDropdown._open_instances.discard(self)
        if self.dropdown_window:
            try:
                self.dropdown_window.destroy()
            except Exception:
                pass
            self.dropdown_window = None

    def get(self):
        return self.current_value
        
    def set(self, value):
        self.current_value = value
        self.btn.configure(text=value)

class PortfolioAgentApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.current_theme = "light"
        self.t = THEMES[self.current_theme]
        ctk.set_appearance_mode(self.t["ctk_mode"])
        ctk.set_default_color_theme("blue")

        self.title("AlphaMaxxin Portfolio Agent Network v3.0")
        self._set_app_icon()
        self._center_on_screen(1360, 820)
        self.minsize(1100, 700)
        self.configure(fg_color=self.t["bg_root"])

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.dropdown_frame = None
        self._autocomplete_timer = None
        self._progress_running = False

        # Any floating popup (ticker autocomplete, model dropdowns) is a separate
        # OS window positioned at an absolute screen coordinate — it has no way to
        # follow the main window, so it gets left stranded mid-air if you drag or
        # resize while one is open. Closing them on <Configure> is far simpler and
        # more reliable than trying to reposition a topmost popup in lockstep.
        self.bind("<Configure>", self._on_root_configure)

        self._build_ui()
        # Deferred via after(0,...) rather than called directly: this spawns a
        # background thread that calls self.after() from a worker thread once
        # its fetch resolves. If that resolves fast (now common — moomoo calls
        # are cached/fast-failing) it can fire before mainloop() has actually
        # started below, raising "RuntimeError: main thread is not in main
        # loop". Scheduling via after(0,...) guarantees the thread doesn't even
        # start until the loop is confirmed running.
        self.after(0, self.refresh_metrics_loop)

    def _set_app_icon(self):
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

    def _center_on_screen(self, width, height):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_root_configure(self, event):
        if event.widget is not self:
            return
        self.hide_dropdown()
        self.hide_hist_dropdown()
        SleekDropdown.close_all_open()

    # =========================================================================
    # Build entire UI (called once and on theme switch)
    # =========================================================================
    def _build_ui(self):
        # customtkinter's CTkScrollableFrame.destroy() never undoes the global
        # bind_all("<MouseWheel>"/Shift press/release, ...) it registers in
        # __init__ — every theme toggle (which tears down and recreates the
        # sidebar/dashboard/news scrollable frames) leaks 5 more dead handlers
        # that still fire — and raise/get silently swallowed — on every future
        # scroll, for the rest of the app's life. Since we're about to destroy
        # every existing scrollable frame and recreate fresh ones (which
        # re-register their own correct handlers in __init__), this is the one
        # safe moment to wipe all accumulated bindings at once.
        for seq in ("<MouseWheel>", "<KeyPress-Shift_L>", "<KeyPress-Shift_R>",
                    "<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>"):
            try:
                self.unbind_all(seq)
            except Exception:
                pass

        # Destroy old widgets if rebuilding
        for w in self.winfo_children():
            w.destroy()
        self.dropdown_frame = None
        self._create_sidebar()
        self._create_main_workspace()

    # =========================================================================
    # Theme switching
    # =========================================================================
    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.t = THEMES[self.current_theme]
        ctk.set_appearance_mode(self.t["ctk_mode"])
        self.configure(fg_color=self.t["bg_root"])
        self._build_ui()
        self.refresh_metrics_loop()

    # =========================================================================
    # Sidebar
    # =========================================================================
    def _create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self, width=280, corner_radius=0, fg_color=self.t["bg_sidebar"],
            border_width=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)

        row = 0

        # ── Brand header ──
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=row, column=0, padx=24, pady=(24, 0), sticky="ew")
        brand.grid_columnconfigure(0, weight=1)

        brand_top = ctk.CTkFrame(brand, fg_color="transparent")
        brand_top.pack(fill="x")
        brand_top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            brand_top, text="ALPHAMAXXIN",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=self.t["accent"]
        ).grid(row=0, column=0, sticky="w")

        # Theme toggle button
        theme_icon = "☀" if self.current_theme == "dark" else "🌙"
        self.btn_theme = ctk.CTkButton(
            brand_top, text=theme_icon, width=36, height=36,
            font=("Segoe UI", 16), corner_radius=18,
            fg_color=self.t["bg_input"], hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"], border_width=1,
            border_color=self.t["border"],
            command=self.toggle_theme)
        self.btn_theme.grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            brand, text="Portfolio Agent Network     v3.0",
            font=("Segoe UI", 10), text_color=self.t["text_muted"]
        ).pack(anchor="w", pady=(2, 0))

        # Accent line under brand
        row += 1
        accent_bar = ctk.CTkFrame(self.sidebar, fg_color=self.t["accent"], height=2, corner_radius=1)
        accent_bar.grid(row=row, column=0, sticky="ew", padx=24, pady=(14, 14))

        # ── Analysis Target section ──
        row += 1
        ctk.CTkLabel(
            self.sidebar, text="ANALYSIS TARGET",
            font=("Segoe UI", 9, "bold"), text_color=self.t["text_muted"]
        ).grid(row=row, column=0, padx=26, pady=(0, 4), sticky="w")

        row += 1
        self.target_input = ctk.CTkEntry(
            self.sidebar, placeholder_text="Ticker, company, or Portfolio.md",
            font=("Segoe UI", 12), height=38, corner_radius=8,
            fg_color=self.t["bg_input"], text_color=self.t["text_primary"],
            border_color=self.t["border"],
            placeholder_text_color=self.t["text_muted"])
        self.target_input.insert(0, "Portfolio.md")
        self.target_input.grid(row=row, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.target_input.bind("<KeyRelease>", self.on_target_key)

        # ── Run Orchestrator ──
        row += 1
        mo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        mo_frame.grid(row=row, column=0, padx=20, pady=(0, 6), sticky="ew")
        
        ctk.CTkLabel(
            mo_frame, text="MO Model:", 
            font=("Segoe UI", 11), text_color=self.t["text_muted"]
        ).pack(side="left", padx=(6, 4))
        
        self.mo_model_var = ctk.StringVar(value="Claude 4.6 Sonnet")
        self.mo_model_menu = ctk.CTkOptionMenu(
            mo_frame,
            variable=self.mo_model_var,
            values=[
                "Gemini 2.5 Flash",
                "Gemini 3.0 Flash",
                "Gemini 3.5 Flash",
                "Claude 3.5 Sonnet",
                "Claude 4.6 Sonnet",
                "Claude 4.8 Opus"
            ],
            font=("Segoe UI", 11, "bold"),
            height=24,
            corner_radius=4,
            fg_color=self.t["bg_sidebar"],
            button_color=self.t["bg_sidebar"],
            button_hover_color=self.t["bg_card_hover"],
            text_color=self.t["accent"],
            dropdown_fg_color=self.t["bg_card"],
            dropdown_text_color=self.t["text_primary"],
            dropdown_hover_color=self.t["bg_card_hover"]
        )
        self.mo_model_menu.pack(side="right", fill="x", expand=True)

        row += 1
        self.btn_compile = ctk.CTkButton(
            self.sidebar, text="▶   Run Master Orchestrator",
            font=("Segoe UI", 13, "bold"), height=42, corner_radius=8,
            fg_color=self.t["accent"], hover_color=self.t["accent_hover"],
            text_color="#FFFFFF",
            command=self.trigger_orchestrator)
        self.btn_compile.grid(row=row, column=0, padx=20, pady=(0, 6), sticky="ew")

        # ── Progress bar (hidden by default) ──
        row += 1
        self.progress_bar = ctk.CTkProgressBar(
            self.sidebar, height=3, corner_radius=2,
            fg_color=self.t["bg_input"],
            progress_color=self.t["accent"])
        self.progress_bar.grid(row=row, column=0, padx=20, pady=(0, 14), sticky="ew")
        self.progress_bar.set(0)

        # ── Divider ──
        row += 1
        ctk.CTkFrame(self.sidebar, fg_color=self.t["border"], height=1).grid(
            row=row, column=0, sticky="ew", padx=24, pady=(0, 12))

        # ── Agent Selector Header & Buttons ──
        row += 1
        ctk.CTkLabel(
            self.sidebar, text="AGENT CONFIGURATION",
            font=("Segoe UI", 9, "bold"), text_color=self.t["text_muted"]
        ).grid(row=row, column=0, padx=26, pady=(0, 4), sticky="w")

        row += 1
        actions_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        actions_frame.grid(row=row, column=0, padx=20, pady=(0, 8), sticky="ew")
        actions_frame.grid_columnconfigure((0, 2), weight=2)
        actions_frame.grid_columnconfigure(1, weight=3)

        btn_select_all = ctk.CTkButton(
            actions_frame, text="All", font=("Segoe UI", 10, "bold"),
            height=26, corner_radius=6,
            fg_color=self.t["bg_input"], text_color=self.t["text_secondary"],
            hover_color=self.t["bg_card_hover"],
            command=self.select_all_agents
        )
        btn_select_all.grid(row=0, column=0, padx=(0, 2), sticky="ew")

        btn_lite_preset = ctk.CTkButton(
            actions_frame, text="Lite Preset", font=("Segoe UI", 10, "bold"),
            height=26, corner_radius=6,
            fg_color=self.t["bg_input"], text_color=self.t["text_secondary"],
            hover_color=self.t["bg_card_hover"],
            command=self.select_lite_agents
        )
        btn_lite_preset.grid(row=0, column=1, padx=2, sticky="ew")

        btn_deselect_all = ctk.CTkButton(
            actions_frame, text="None", font=("Segoe UI", 10, "bold"),
            height=26, corner_radius=6,
            fg_color=self.t["bg_input"], text_color=self.t["text_secondary"],
            hover_color=self.t["bg_card_hover"],
            command=self.deselect_all_agents
        )
        btn_deselect_all.grid(row=0, column=2, padx=(2, 0), sticky="ew")

        # ── Scrollable Agent List ──
        row += 1
        self.sidebar.grid_rowconfigure(row, weight=1) # Let the agent list frame fill space!

        self.agent_scroll = ctk.CTkScrollableFrame(
            self.sidebar, fg_color="transparent",
            scrollbar_button_color=self.t["scrollbar"],
            scrollbar_button_hover_color=self.t["scrollbar_hover"])
        self.agent_scroll.grid(row=row, column=0, padx=16, pady=(0, 12), sticky="nsew")

        self.layer_vars = {}
        self.agent_vars = {}
        self.layer_checkboxes = {}
        self.layer_models = {}

        for layer_name, agents in AGENT_LAYERS.items():
            # Layer Header Frame
            layer_frame = ctk.CTkFrame(self.agent_scroll, fg_color="transparent")
            layer_frame.pack(fill="x", padx=4, pady=(12, 4))
            
            layer_var = ctk.BooleanVar(value=True)
            self.layer_vars[layer_name] = layer_var
            
            def make_toggle_command(lvl=layer_name, l_var=layer_var):
                def toggle():
                    val = l_var.get()
                    for agent in AGENT_LAYERS[lvl]:
                        self.agent_vars[agent].set(val)
                return toggle
                
            cb_layer = ctk.CTkCheckBox(
                layer_frame, text=layer_name, variable=layer_var,
                font=("Segoe UI", 10, "bold"), border_width=1,
                text_color=self.t["text_muted"],
                fg_color=self.t["accent"],
                hover_color=self.t["accent_hover"],
                checkbox_width=14, checkbox_height=14,
                corner_radius=0,
                command=make_toggle_command(layer_name, layer_var)
            )
            cb_layer.pack(side="left")
            self.layer_checkboxes[layer_name] = cb_layer
            
            # Model Dropdown
            model_options = [
                "Gemini 2.5 Flash",
                "Gemini 3.0 Flash",
                "Gemini 3.5 Flash",
                "Claude 3.5 Sonnet",
                "Claude 4.6 Sonnet",
                "Claude 4.8 Opus"
            ]

            # Default Layer 1 & 2 (data/analysis, run most often) to cheap Gemini Flash;
            # Layer 3 & 4 (synthesis/output) to the stronger-but-not-most-expensive Claude Sonnet.
            default_model = "Gemini 3.5 Flash" if "LAYER 1" in layer_name or "LAYER 2" in layer_name else "Claude 4.6 Sonnet"
            
            model_var = ctk.StringVar(value=default_model)
            self.layer_models[layer_name] = model_var
            
            model_menu = ctk.CTkOptionMenu(
                layer_frame,
                variable=model_var,
                values=model_options,
                font=("Segoe UI", 10, "bold"),
                height=20,
                width=115,
                corner_radius=0,
                fg_color=self.t["bg_sidebar"],
                button_color=self.t["bg_sidebar"],
                button_hover_color=self.t["bg_card_hover"],
                text_color=self.t["accent"],
                dropdown_fg_color=self.t["bg_card"],
                dropdown_text_color=self.t["text_primary"],
                dropdown_hover_color=self.t["bg_card_hover"]
            )
            model_menu.pack(side="right", padx=(0, 4))
            self.layer_checkboxes[layer_name] = cb_layer
            
            for agent in agents:
                row_frame = ctk.CTkFrame(self.agent_scroll, fg_color="transparent")
                row_frame.pack(fill="x", padx=4, pady=2)
                row_frame.grid_columnconfigure(0, weight=1)
                row_frame.grid_columnconfigure(1, weight=0)
                
                var = ctk.BooleanVar(value=True)
                self.agent_vars[agent] = var
                
                def make_agent_toggle_command(lvl=layer_name, l_var=layer_var):
                    def agent_toggle():
                        all_checked = all(self.agent_vars[a].get() for a in AGENT_LAYERS[lvl])
                        l_var.set(all_checked)
                    return agent_toggle
                
                wrapped_text = wrap_text(agent, limit=22)
                
                cb = ctk.CTkCheckBox(
                    row_frame, text=wrapped_text, variable=var,
                    font=("Segoe UI", 10), border_width=1,
                    text_color=self.t["text_primary"],
                    fg_color=self.t["accent"],
                    hover_color=self.t["accent_hover"],
                    checkbox_width=16, checkbox_height=16,
                    corner_radius=0,
                    command=make_agent_toggle_command(layer_name, layer_var)
                )
                cb.grid(row=0, column=0, sticky="w")

                # Standalone run button next to agent
                btn_run = ctk.CTkButton(
                    row_frame, text="▶", font=("Segoe UI", 10),
                    width=24, height=22, corner_radius=0,
                    fg_color=self.t["bg_input"], text_color=self.t["text_secondary"],
                    hover_color=self.t["bg_card_hover"],
                    command=lambda a=agent: self.trigger_single_agent_name(a)
                )
                btn_run.grid(row=0, column=1, sticky="e", padx=(4, 0))

        # ── Status Footer ──
        row += 1
        status_frame = ctk.CTkFrame(self.sidebar, fg_color=self.t["bg_card"],
                                    corner_radius=8, border_width=1,
                                    border_color=self.t["border"])
        status_frame.grid(row=row, column=0, padx=20, pady=(0, 20), sticky="ew")

        inner = ctk.CTkFrame(status_frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        self.status_dot = ctk.CTkLabel(
            inner, text="●", text_color=self.t["emerald"],
            font=("Segoe UI", 18))
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_string = ctk.CTkLabel(
            inner, text="SYSTEM READY",
            font=("Segoe UI", 10, "bold"), text_color=self.t["text_muted"])
        self.status_string.pack(side="left")

    def select_all_agents(self):
        for var in self.agent_vars.values():
            var.set(True)
        for var in self.layer_vars.values():
            var.set(True)
            
    def deselect_all_agents(self):
        for var in self.agent_vars.values():
            var.set(False)
        for var in self.layer_vars.values():
            var.set(False)

    def select_lite_agents(self):
        self.deselect_all_agents()
        lite_list = [
            "US Macro Analyst",
            "Fundamental Analysis Agent",
            "Technical Analysis Agent",
            "Risk Management Agent",
            "Investment Recommendation Agent"
        ]
        for agent in lite_list:
            if agent in self.agent_vars:
                self.agent_vars[agent].set(True)
        # Update layer checkboxes dynamically
        for layer_name, agents in AGENT_LAYERS.items():
            all_checked = all(self.agent_vars[a].get() for a in agents)
            if layer_name in self.layer_vars:
                self.layer_vars[layer_name].set(all_checked)

    def trigger_single_agent_name(self, agent_name):
        target = self.target_input.get().strip() or "Portfolio.md"
        if target.lower() not in ("portfolio.md", "portfolio"):
            self.log(f"Validating ticker: {target}...")
            self.set_working("Validating")
            threading.Thread(
                target=self._validate_and_run,
                args=(agent_name, target), daemon=True).start()
        else:
            self.log(f"Running {agent_name} on Portfolio.md...")
            self.set_working(agent_name)
            threading.Thread(
                target=self.worker,
                args=(agent_name, target), daemon=True).start()

    # =========================================================================
    # Main workspace
    # =========================================================================
    def _create_main_workspace(self):
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color=self.t["bg_root"])
        self.main_container.grid(row=0, column=1, sticky="nsew")
        self.main_container.grid_rowconfigure(0, weight=0) # Top nav
        self.main_container.grid_rowconfigure(1, weight=1) # Tab views container
        self.main_container.grid_columnconfigure(0, weight=1)

        # ── Top Navigation Bar ──
        self.top_nav = ctk.CTkFrame(
            self.main_container, height=54, corner_radius=0,
            fg_color=self.t["bg_header"], border_color=self.t["border"], border_width=0
        )
        self.top_nav.grid(row=0, column=0, sticky="ew")
        self.top_nav.grid_propagate(False)
        self.top_nav.grid_columnconfigure(0, weight=1)

        self.lbl_workspace_title = ctk.CTkLabel(
            self.top_nav, text="ALPHAMAXXIN PORTFOLIO WORKSPACE",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=self.t["text_primary"]
        )
        self.lbl_workspace_title.pack(side="left", padx=24, pady=12)

        # Segmented view selector
        self.tab_btn_frame = ctk.CTkFrame(self.top_nav, fg_color=self.t["bg_input"], corner_radius=8, height=36)
        self.tab_btn_frame.pack(side="right", padx=24, pady=9)

        self.btn_tab_dash = ctk.CTkButton(
            self.tab_btn_frame, text="📊  Dashboard",
            font=("Segoe UI", 11, "bold"), height=28, corner_radius=6,
            fg_color="transparent", hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"], width=100,
            command=lambda: self.switch_tab("dashboard"))
        self.btn_tab_dash.pack(side="left", padx=2, pady=4)

        self.btn_tab_edit = ctk.CTkButton(
            self.tab_btn_frame, text="📋  Portfolio Editor",
            font=("Segoe UI", 11, "bold"), height=28, corner_radius=6,
            fg_color="transparent", hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"], width=120,
            command=lambda: self.switch_tab("editor"))
        self.btn_tab_edit.pack(side="left", padx=2, pady=4)

        self.btn_tab_hist = ctk.CTkButton(
            self.tab_btn_frame, text="📈  Historical Chart",
            font=("Segoe UI", 11, "bold"), height=28, corner_radius=6,
            fg_color="transparent", hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"], width=130,
            command=lambda: self.switch_tab("history"))
        self.btn_tab_hist.pack(side="left", padx=2, pady=4)

        self.btn_tab_news = ctk.CTkButton(
            self.tab_btn_frame, text="📰  News Feed",
            font=("Segoe UI", 11, "bold"), height=28, corner_radius=6,
            fg_color="transparent", hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"], width=105,
            command=lambda: self.switch_tab("news"))
        self.btn_tab_news.pack(side="left", padx=2, pady=4)

        bottom_border = ctk.CTkFrame(self.top_nav, height=1, fg_color=self.t["border"])
        bottom_border.place(relx=0, rely=1.0, relwidth=1.0, anchor="sw")

        # Tab views container
        self.view_container = ctk.CTkFrame(self.main_container, corner_radius=0, fg_color="transparent")
        self.view_container.grid(row=1, column=0, sticky="nsew")
        self.view_container.grid_rowconfigure(0, weight=1)
        self.view_container.grid_columnconfigure(0, weight=1)

        self._create_dashboard_tab()
        self._create_editor_tab()
        self._create_history_tab()
        self._create_news_tab()
        self.switch_tab("dashboard")


    # ── Dashboard Tab ──
    def _create_dashboard_tab(self):
        self.dash_frame = ctk.CTkScrollableFrame(
            self.view_container, corner_radius=0, fg_color=self.t["bg_root"],
            scrollbar_button_color=self.t["scrollbar"],
            scrollbar_button_hover_color=self.t["scrollbar_hover"])
        self.dash_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # ── Welcome header ──
        header_card = ctk.CTkFrame(
            self.dash_frame, fg_color=self.t["accent_soft"],
            corner_radius=12, border_color=self.t["border"], border_width=1)
        header_card.grid(row=0, column=0, columnspan=4, padx=28, pady=(28, 16), sticky="ew")

        header_inner = ctk.CTkFrame(header_card, fg_color="transparent")
        header_inner.pack(fill="x", padx=24, pady=20)
        header_inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header_inner, text="AlphaMaxxin Research Terminal",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=self.t["text_primary"]
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header_inner, text="32-agent multi-layer investment intelligence system — all paid APIs linked",
            font=("Segoe UI", 13), text_color=self.t["text_secondary"]
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        badge = ctk.CTkLabel(
            header_inner, text="  v3.0  ",
            font=("Segoe UI", 10, "bold"), text_color="#FFF",
            fg_color=self.t["accent"], corner_radius=4)
        badge.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

        # ── Metric cards row 1 (4-across) ──
        cards_data = [
            ("PORTFOLIO VALUE", "$0.00", "val_portfolio", "emerald", "💰"),
            ("HOLDINGS COUNT", "0", "val_count", "text_primary", "📈"),
            ("MARKET BENCHMARK", "Loading...", "val_market", "accent", "🌍"),
            ("AGENT NETWORK", "v3.0 - 32 Agents", None, "accent", "📈"),
        ]

        for col, (label, default_val, attr_name, color_key, icon) in enumerate(cards_data):
            card = ctk.CTkFrame(
                self.dash_frame, fg_color=self.t["bg_card"], corner_radius=12,
                border_color=self.t["border"], border_width=1)
            card.grid(row=1, column=col,
                      padx=(28 if col == 0 else 8, 28 if col == 3 else 8),
                      pady=8, sticky="nsew")

            # Icon + label row
            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=20, pady=(18, 0))

            ctk.CTkLabel(top_row, text=icon, font=("Segoe UI", 22)).pack(side="left")
            
            if label == "MARKET BENCHMARK":
                self.market_dropdown = SleekDropdown(
                    top_row, values=[
                        "S&P 500 (^GSPC)", "Nasdaq (^IXIC)", "Dow Jones (^DJI)", "Russell 2000 (^RUT)",
                        "FTSE 100 (^FTSE)", "Nikkei 225 (^N225)", "Straits Times (^STI)", "Hang Seng Index (^HSI)",
                        "DAX Index (^GDAXI)", "CAC 40 (^FCHI)", "SSE Composite (000001.SS)", "Nifty 50 (^NSEI)", "S&P/ASX 200 (^AXJO)"
                    ],
                    font=("Segoe UI", 10, "bold"), height=26, corner_radius=6,
                    fg_color=self.t["bg_input"], text_color=self.t["text_primary"],
                    hover_color=self.t["bg_card_hover"],
                    command=self.on_market_change
                )
                self.market_dropdown.pack(side="left", padx=(8, 0))
                
                # Dynamic horizontal frame for benchmark price + percentage change badge
                price_frame = ctk.CTkFrame(card, fg_color="transparent")
                price_frame.pack(anchor="w", padx=20, pady=(8, 20), fill="x")
                
                self.val_market = ctk.CTkLabel(
                    price_frame, text=default_val,
                    font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
                    text_color=self.t["accent"])
                self.val_market.pack(side="left")
                
                self.val_market_change = ctk.CTkLabel(
                    price_frame, text="",
                    font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                    corner_radius=6)
                self.val_market_change.pack(side="left", padx=(10, 0), pady=(6, 0))
            else:
                val_label = ctk.CTkLabel(
                    card, text=default_val,
                    font=ctk.CTkFont(family="Segoe UI", size=24 if col == 3 else 28, weight="bold"),
                    text_color=self.t[color_key])
                val_label.pack(anchor="w", padx=20, pady=(8, 20))

                if attr_name:
                    setattr(self, attr_name, val_label)

        # ── Row 2: API Status + Portfolio Status ──
        self.regime_card = ctk.CTkFrame(
            self.dash_frame, fg_color=self.t["bg_card"], corner_radius=12,
            border_color=self.t["border"], border_width=1)
        self.regime_card.grid(row=2, column=0, columnspan=2, padx=(28, 8), pady=8, sticky="nsew")

        regime_top = ctk.CTkFrame(self.regime_card, fg_color="transparent")
        regime_top.pack(fill="x", padx=20, pady=(18, 0))
        ctk.CTkLabel(regime_top, text="📡", font=("Segoe UI", 22)).pack(side="left")
        ctk.CTkLabel(
            regime_top, text="PORTFOLIO STATUS",
            font=("Segoe UI", 9, "bold"), text_color=self.t["text_muted"]
        ).pack(side="left", padx=(8, 0))

        self.lbl_regime_val = ctk.CTkLabel(
            self.regime_card, text="Awaiting analysis...",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=self.t["text_primary"])
        self.lbl_regime_val.pack(anchor="w", padx=20, pady=(8, 20))

        # API card
        self.card_api = ctk.CTkFrame(
            self.dash_frame, fg_color=self.t["bg_card"], corner_radius=12,
            border_color=self.t["border"], border_width=1)
        self.card_api.grid(row=2, column=2, padx=(8, 28), pady=8, sticky="nsew")

        api_top = ctk.CTkFrame(self.card_api, fg_color="transparent")
        api_top.pack(fill="x", padx=20, pady=(18, 0))
        ctk.CTkLabel(api_top, text="🔑", font=("Segoe UI", 22)).pack(side="left")
        ctk.CTkLabel(
            api_top, text="PAID APIs — v3.0",
            font=("Segoe UI", 9, "bold"), text_color=self.t["text_muted"]
        ).pack(side="left", padx=(8, 0))

        has_anthropic = os.environ.get("ANTHROPIC_API_KEY")
        has_gemini = os.environ.get("GEMINI_API_KEY")
        has_openai = os.environ.get("OPENAI_API_KEY")
        has_finnhub = os.environ.get("FINNHUB_API_KEY")
        has_av = os.environ.get("ALPHAVANTAGE_API_KEY")
        has_moomoo = _MOOMOO_MODULE_AVAILABLE

        api_rows = [
            ("●", "Claude", self.t["emerald"]) if has_anthropic
            else ("○", "Claude — No key", self.t["crimson"]),
        ]
        if has_gemini:
            api_rows.append(("●", "Gemini", self.t["emerald"]))
        elif has_openai:
            api_rows.append(("●", "GPT-4o-mini", self.t["emerald"]))
        else:
            api_rows.append(("○", "Gemini/OpenAI — Not configured", self.t["crimson"]))

        api_rows.append(
            ("●", "Finnhub News", self.t["emerald"]) if has_finnhub
            else ("○", "Finnhub — No key", self.t["gold"])
        )
        api_rows.append(
            ("●", "Alpha Vantage Sentiment", self.t["emerald"]) if has_av
            else ("○", "Alpha Vantage — No key", self.t["gold"])
        )
        api_rows.append(
            ("●", "Moomoo Market Data", self.t["emerald"]) if has_moomoo
            else ("○", "Moomoo — moomoo-api not installed", self.t["gold"])
        )

        api_inner = ctk.CTkFrame(self.card_api, fg_color="transparent")
        api_inner.pack(anchor="w", padx=20, pady=(8, 18), fill="x")
        for dot, label, color in api_rows:
            row_f = ctk.CTkFrame(api_inner, fg_color="transparent")
            row_f.pack(anchor="w", pady=2, fill="x")
            ctk.CTkLabel(
                row_f, text=dot,
                font=("Segoe UI", 13), text_color=color
            ).pack(side="left")
            ctk.CTkLabel(
                row_f, text=f"  {label}",
                font=("Segoe UI", 12, "bold"), text_color=color
            ).pack(side="left")

        # ── System Log ──
        self.log_frame = ctk.CTkFrame(
            self.dash_frame, fg_color=self.t["bg_card"], corner_radius=12,
            border_color=self.t["border"], border_width=1)
        self.log_frame.grid(row=3, column=0, columnspan=4, padx=28, pady=(8, 28), sticky="ew")

        log_top = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_top.pack(fill="x", padx=20, pady=(18, 8))
        ctk.CTkLabel(log_top, text="⚙", font=("Segoe UI", 18)).pack(side="left")
        ctk.CTkLabel(
            log_top, text="SYSTEM LOG",
            font=("Segoe UI", 9, "bold"), text_color=self.t["text_muted"]
        ).pack(side="left", padx=(8, 0))

        self.console_text = ctk.CTkTextbox(
            self.log_frame, height=200,
            font=("Consolas", 12), corner_radius=8,
            fg_color=self.t["log_bg"], text_color=self.t["log_text"],
            wrap="word", border_color=self.t["border"], border_width=1)
        self.console_text.pack(fill="x", padx=16, pady=(0, 18))
        self.log("AlphaMaxxin v3.0 initialized. 32 agents loaded, all paid APIs linked. System ready.")

    def _create_editor_tab(self):
        self.editor_frame = ctk.CTkFrame(
            self.view_container, corner_radius=0, fg_color=self.t["bg_root"])
        self.editor_frame.grid_rowconfigure(1, weight=1)
        self.editor_frame.grid_columnconfigure(0, weight=1)

        # Header bar
        header = ctk.CTkFrame(
            self.editor_frame, fg_color=self.t["bg_card"], height=60,
            corner_radius=0, border_color=self.t["border"], border_width=0)
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(1, weight=1)

        header_left = ctk.CTkFrame(header, fg_color="transparent")
        header_left.grid(row=0, column=0, padx=28, pady=14, sticky="w")
        ctk.CTkLabel(
            header_left, text="📋", font=("Segoe UI", 22)
        ).pack(side="left")
        ctk.CTkLabel(
            header_left, text="  PORTFOLIO EDITOR",
            font=("Segoe UI", 15, "bold"), text_color=self.t["text_primary"]
        ).pack(side="left")

        btn_bar = ctk.CTkFrame(header, fg_color="transparent")
        btn_bar.grid(row=0, column=1, padx=28, pady=14, sticky="e")

        self.lbl_portfolio_total_editor = ctk.CTkLabel(
            btn_bar, text="Total Value: $0.00",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=self.t["emerald"])
        self.lbl_portfolio_total_editor.pack(side="left", padx=(0, 20))

        ctk.CTkButton(
            btn_bar, text="＋ Add", font=("Segoe UI", 11, "bold"),
            fg_color=self.t["emerald"], hover_color="#0EA870", text_color="#FFF",
            height=32, corner_radius=6, width=80,
            command=self.add_holding_row).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_bar, text="✕ Remove", font=("Segoe UI", 11),
            fg_color=self.t["crimson"], hover_color="#DC2626", text_color="#FFF",
            height=32, corner_radius=6, width=90,
            command=self.remove_selected_holding).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_bar, text="💾 Save", font=("Segoe UI", 11, "bold"),
            fg_color=self.t["accent"], hover_color=self.t["accent_hover"],
            text_color="#FFF", height=32, corner_radius=6, width=80,
            command=self.save_portfolio_from_editor).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_bar, text="↻ Reload", font=("Segoe UI", 11),
            fg_color=self.t["bg_input"], hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_secondary"],
            height=32, corner_radius=6, width=86,
            command=self.load_portfolio_into_editor).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_bar, text="⇄ Sync Moomoo", font=("Segoe UI", 11, "bold"),
            fg_color=self.t["gold"], hover_color="#D97706", text_color="#FFF",
            height=32, corner_radius=6, width=120,
            command=self.sync_portfolio_from_moomoo_clicked).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_bar, text="📊 Order Book", font=("Segoe UI", 11, "bold"),
            fg_color=self.t["accent"], hover_color=self.t["accent_hover"], text_color="#FFF",
            height=32, corner_radius=6, width=120,
            command=self.open_order_book_for_selected).pack(side="left")

        # Treeview
        tree_container = ctk.CTkFrame(
            self.editor_frame, fg_color=self.t["bg_root"])
        tree_container.grid(row=1, column=0, sticky="nsew", padx=28, pady=(16, 28))
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Portfolio.Treeview",
                        background=self.t["tree_bg"],
                        foreground=self.t["tree_fg"],
                        fieldbackground=self.t["tree_bg"],
                        borderwidth=0,
                        font=("Segoe UI", 12),
                        rowheight=38)
        style.configure("Portfolio.Treeview.Heading",
                        background=self.t["tree_heading_bg"],
                        foreground=self.t["tree_heading_fg"],
                        font=("Segoe UI", 11, "bold"),
                        borderwidth=0,
                        relief="flat")
        style.map("Portfolio.Treeview",
                  background=[("selected", self.t["tree_sel"])],
                  foreground=[("selected", self.t["tree_fg"])])
        style.map("Portfolio.Treeview.Heading",
                  background=[("active", self.t["accent_hover"])])

        # Sleek Apple-style scrollbar config
        style.layout("Portfolio.Vertical.TScrollbar", [
            ('Vertical.Scrollbar.trough', {
                'children': [
                    ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})
                ],
                'sticky': 'ns'
            })
        ])
        style.configure("Portfolio.Vertical.TScrollbar",
                        background=self.t["scrollbar"],
                        troughcolor=self.t["bg_root"],
                        bordercolor=self.t["bg_root"],
                        borderwidth=0,
                        thickness=8)
        style.map("Portfolio.Vertical.TScrollbar",
                  background=[("active", self.t["scrollbar_hover"]), ("pressed", self.t["accent"])])

        columns = ("currency", "company", "ticker", "quantity", "cost_price", "market_price", "current_value", "pl_pct")
        self.portfolio_tree = ttk.Treeview(
            tree_container, columns=columns, show="headings",
            style="Portfolio.Treeview", selectmode="browse")

        self.portfolio_tree.heading("currency", text="Currency")
        self.portfolio_tree.heading("company", text="Company")
        self.portfolio_tree.heading("ticker", text="Ticker")
        self.portfolio_tree.heading("quantity", text="Qty")
        self.portfolio_tree.heading("cost_price", text="Cost Price")
        self.portfolio_tree.heading("market_price", text="Market Price")
        self.portfolio_tree.heading("current_value", text="Current Value")
        self.portfolio_tree.heading("pl_pct", text="P&L %")

        self.portfolio_tree.column("currency", width=70, anchor="center")
        self.portfolio_tree.column("company", width=180, anchor="w")
        self.portfolio_tree.column("ticker", width=90, anchor="center")
        self.portfolio_tree.column("quantity", width=80, anchor="center")
        self.portfolio_tree.column("cost_price", width=110, anchor="center")
        self.portfolio_tree.column("market_price", width=110, anchor="center")
        self.portfolio_tree.column("current_value", width=120, anchor="center")
        self.portfolio_tree.column("pl_pct", width=100, anchor="center")

        scrollbar = ttk.Scrollbar(
            tree_container, orient="vertical",
            command=self.portfolio_tree.yview,
            style="Portfolio.Vertical.TScrollbar")
        self.portfolio_tree.configure(yscrollcommand=scrollbar.set)

        self.portfolio_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.portfolio_tree.bind("<Double-1>", self.on_tree_double_click)

        # Tag for alternating rows and P&L color tags
        self.portfolio_tree.tag_configure("stripe", background=self.t["tree_stripe"])
        self.portfolio_tree.tag_configure("green_text", foreground=self.t["emerald"])
        self.portfolio_tree.tag_configure("red_text", foreground=self.t["crimson"])
        self.portfolio_tree.tag_configure("default_text", foreground=self.t["tree_fg"])

        # Deferred for the same reason as the refresh_metrics_loop kickoff in
        # __init__ — this spawns per-row fetch threads that call self.after()
        # from worker threads; if one resolves before mainloop() starts, that
        # raises RuntimeError. after(0,...) guarantees mainloop is running first.
        self.after(0, self.load_portfolio_into_editor)

    # =========================================================================
    # Portfolio editor helpers
    # =========================================================================
    def load_portfolio_into_editor(self):
        for item in self.portfolio_tree.get_children():
            self.portfolio_tree.delete(item)

        holdings = parse_portfolio_full()
        for i, h in enumerate(holdings):
            qty = h["quantity"]
            qty_str = f"{qty:.1f}" if qty != int(qty) else str(int(qty))
            tags = ("stripe",) if i % 2 == 1 else ()
            item_id = self.portfolio_tree.insert("", "end", values=(
                h["currency"], h["company"], h["ticker"],
                qty_str, f"{h['cost_price']:.3f}", "Loading...", "Loading...", "Loading..."
            ), tags=tags)
            
            # Asynchronous fetch of live price
            threading.Thread(
                target=self._fetch_row_live_price,
                args=(item_id, h["ticker"], qty),
                daemon=True
            ).start()

    def _fetch_row_live_price(self, item_id, ticker, qty):
        try:
            live = fetch_live_price(ticker)
            if live and "price" in live:
                price = live["price"]
                cur_val = price * qty
                self.after(0, lambda: self._update_row_live_price(item_id, price, cur_val))
            else:
                self.after(0, lambda: self._update_row_live_price(item_id, None, None))
        except Exception:
            self.after(0, lambda: self._update_row_live_price(item_id, None, None))

    def _update_row_live_price(self, item_id, price, cur_val):
        try:
            if not self.portfolio_tree.exists(item_id):
                return
            vals = list(self.portfolio_tree.item(item_id, "values"))
            # Ensure vals has at least 8 elements to avoid IndexErrors
            while len(vals) < 8:
                vals.append("")
            if price is not None:
                vals[5] = f"${price:,.2f}"
                vals[6] = f"${cur_val:,.2f}"
            else:
                vals[5] = "N/A"
                vals[6] = "N/A"
                vals[7] = "N/A"
            
            # Dynamic tag configuration for coloring based on cost price vs market price comparison
            existing_tags = list(self.portfolio_tree.item(item_id, "tags"))
            # Preserve the alternating "stripe" tag, remove any previous color tags
            clean_tags = [t for t in existing_tags if t not in ("green_text", "red_text", "default_text")]
            
            if price is not None:
                try:
                    # Clean and parse cost price (e.g. from "$123.45" or "123.450")
                    cost_price_str = vals[4].replace("$", "").replace(",", "").strip()
                    cost_price = float(cost_price_str)
                    
                    if cost_price > 0:
                        pct_change = ((price - cost_price) / cost_price) * 100
                        vals[7] = f"{'+' if pct_change >= 0 else ''}{pct_change:.2f}%"
                    else:
                        vals[7] = "0.00%"
                        
                    if price > cost_price:
                        clean_tags.append("green_text")
                    elif price < cost_price:
                        clean_tags.append("red_text")
                    else:
                        clean_tags.append("default_text")
                except (ValueError, IndexError):
                    pass
            self.portfolio_tree.item(item_id, values=vals)
            self.portfolio_tree.item(item_id, tags=tuple(clean_tags))
        except Exception:
            pass

    def add_holding_row(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Add Holding")
        dialog.geometry("440x400")
        dialog.configure(fg_color=self.t["bg_sidebar"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.attributes("-topmost", True)

        fields = {}
        labels = [("Currency (SGD/USD)", "USD"), ("Company Name", ""),
                  ("Ticker", ""), ("Quantity", ""), ("Cost Price", "")]

        for i, (label, default) in enumerate(labels):
            ctk.CTkLabel(
                dialog, text=label, font=("Segoe UI", 12, "bold"),
                text_color=self.t["text_primary"]
            ).grid(row=i, column=0, padx=20, pady=(14 if i == 0 else 6, 2), sticky="w")
            entry = ctk.CTkEntry(
                dialog, font=("Segoe UI", 13), height=36, corner_radius=8,
                fg_color=self.t["bg_input"], text_color=self.t["text_primary"],
                border_color=self.t["border"])
            if default:
                entry.insert(0, default)
            entry.grid(row=i, column=1, padx=20,
                       pady=(14 if i == 0 else 6, 2), sticky="ew")
            fields[label] = entry

        dialog.grid_columnconfigure(1, weight=1)

        def on_save():
            currency = fields["Currency (SGD/USD)"].get().strip().upper() or "USD"
            company = fields["Company Name"].get().strip()
            ticker = fields["Ticker"].get().strip().upper()
            qty_str = fields["Quantity"].get().strip()
            cost_str = fields["Cost Price"].get().strip()
            if not company or not ticker:
                return
            try:
                qty = float(qty_str) if qty_str else 0
                cost = float(cost_str) if cost_str else 0
            except ValueError:
                return
            qty_display = f"{qty:.1f}" if qty != int(qty) else str(int(qty))
            
            existing_count = len(self.portfolio_tree.get_children())
            tags = ("stripe",) if existing_count % 2 == 1 else ()
            
            item_id = self.portfolio_tree.insert("", "end", values=(
                currency, company, ticker, qty_display, f"{cost:.3f}", "Loading...", "Loading...", "Loading..."
            ), tags=tags)
            
            # Asynchronous fetch of live price immediately after adding
            threading.Thread(
                target=self._fetch_row_live_price,
                args=(item_id, ticker, qty),
                daemon=True
            ).start()
            
            dialog.destroy()

        ctk.CTkButton(
            dialog, text="Add Holding", font=("Segoe UI", 13, "bold"),
            fg_color=self.t["accent"], hover_color=self.t["accent_hover"],
            text_color="#FFF", height=38, corner_radius=8,
            command=on_save
        ).grid(row=len(labels), column=0, columnspan=2,
               padx=20, pady=(20, 16), sticky="ew")

    def remove_selected_holding(self):
        selected = self.portfolio_tree.selection()
        if selected:
            self.portfolio_tree.delete(selected[0])

    def on_tree_double_click(self, event):
        item = self.portfolio_tree.identify_row(event.y)
        column = self.portfolio_tree.identify_column(event.x)
        if not item or not column:
            return
        col_idx = int(column.replace("#", "")) - 1
        col_names = ("currency", "company", "ticker", "quantity", "cost_price")
        if col_idx < 0 or col_idx >= len(col_names):
            return
        current_values = self.portfolio_tree.item(item, "values")
        current_val = current_values[col_idx]
        bbox = self.portfolio_tree.bbox(item, column)
        if not bbox:
            return
        entry = tk.Entry(
            self.portfolio_tree, font=("Segoe UI", 12),
            bg=self.t["bg_input"], fg=self.t["text_primary"],
            insertbackground=self.t["text_primary"],
            borderwidth=2, relief="solid",
            highlightcolor=self.t["accent"],
            highlightbackground=self.t["border"])
        entry.insert(0, current_val)
        entry.select_range(0, tk.END)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.focus_set()

        def save_edit(e=None):
            new_val = entry.get().strip()
            vals = list(current_values)
            while len(vals) < 8:
                vals.append("Loading...")
            vals[col_idx] = new_val
            self.portfolio_tree.item(item, values=vals)
            entry.destroy()
            
            # Re-fetch live price if ticker, qty, or cost_price was edited
            if col_idx in (2, 3, 4):
                try:
                    qty = float(vals[3].replace(",", ""))
                    ticker = vals[2].upper()
                    threading.Thread(
                        target=self._fetch_row_live_price,
                        args=(item, ticker, qty),
                        daemon=True
                    ).start()
                except ValueError:
                    pass

        def cancel_edit(e=None):
            entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<Escape>", cancel_edit)
        entry.bind("<FocusOut>", save_edit)

    def save_portfolio_from_editor(self):
        holdings = []
        for item in self.portfolio_tree.get_children():
            vals = self.portfolio_tree.item(item, "values")
            try:
                holdings.append({
                    "currency": vals[0],
                    "company": vals[1],
                    "ticker": vals[2],
                    "quantity": float(vals[3].replace(",", "")),
                    "cost_price": float(vals[4].replace(",", "")),
                })
            except (ValueError, IndexError):
                continue
        save_portfolio(holdings)
        self.log("✓ Portfolio.md saved successfully!")
        self.load_portfolio_into_editor()

    def sync_portfolio_from_moomoo_clicked(self):
        self.log("⇄ Syncing positions from moomoo OpenD...")
        threading.Thread(target=self._sync_portfolio_from_moomoo_worker, daemon=True).start()

    def _sync_portfolio_from_moomoo_worker(self):
        result = sync_portfolio_from_moomoo()
        self.after(0, lambda: self._on_moomoo_sync_done(result))

    def _on_moomoo_sync_done(self, result):
        if result["success"]:
            self.log(f"✓ Portfolio.md synced from moomoo — {len(result['holdings'])} holdings.")
            self.load_portfolio_into_editor()
        else:
            self.log(f"✗ Moomoo sync failed: {result['error']}")

    def open_order_book_for_selected(self):
        selection = self.portfolio_tree.selection()
        if not selection:
            self.log("Select a holding row first to view its order book.")
            return
        vals = self.portfolio_tree.item(selection[0], "values")
        ticker = vals[2] if len(vals) > 2 else None
        if not ticker:
            return
        if not _MOOMOO_MODULE_AVAILABLE:
            self.log("✗ Order book requires moomoo-api — not installed.")
            return
        self._open_order_book_window(ticker)

    def _open_order_book_window(self, ticker):
        win = ctk.CTkToplevel(self)
        win.title(f"Order Book — {ticker}")
        win.geometry("380x440")
        win.configure(fg_color=self.t["bg_sidebar"])
        win.transient(self)
        win.attributes("-topmost", True)

        ctk.CTkLabel(
            win, text=f"{ticker} — Market Depth", font=("Segoe UI", 15, "bold"),
            text_color=self.t["text_primary"]
        ).pack(pady=(16, 4))
        status_lbl = ctk.CTkLabel(
            win, text="Loading...", font=("Segoe UI", 10),
            text_color=self.t["text_muted"])
        status_lbl.pack(pady=(0, 8))

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        bid_col = ctk.CTkFrame(body, fg_color=self.t["bg_card"], corner_radius=8)
        bid_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ask_col = ctk.CTkFrame(body, fg_color=self.t["bg_card"], corner_radius=8)
        ask_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        ctk.CTkLabel(bid_col, text="BID", font=("Segoe UI", 11, "bold"),
                     text_color=self.t["emerald"]).pack(pady=(10, 4))
        ctk.CTkLabel(ask_col, text="ASK", font=("Segoe UI", 11, "bold"),
                     text_color=self.t["crimson"]).pack(pady=(10, 4))

        # Closing the window stops the auto-refresh loop via this flag.
        win._closed = False
        win.protocol("WM_DELETE_WINDOW", lambda: (setattr(win, "_closed", True), win.destroy()))

        def refresh():
            if win._closed:
                return
            threading.Thread(target=self._fetch_order_book, args=(win, ticker, bid_col, ask_col, status_lbl), daemon=True).start()
            win.after(2000, refresh)

        refresh()

    def _fetch_order_book(self, win, ticker, bid_col, ask_col, status_lbl):
        book = get_moomoo_orderbook(ticker, depth=10)
        if win._closed:
            return
        self.after(0, lambda: self._render_order_book(win, book, bid_col, ask_col, status_lbl))

    def _render_order_book(self, win, book, bid_col, ask_col, status_lbl):
        if win._closed:
            return
        for col in (bid_col, ask_col):
            for child in list(col.winfo_children())[1:]:  # keep the BID/ASK heading
                child.destroy()
        if book is None:
            status_lbl.configure(text="No data — not subscribed/entitled, or OpenD unreachable")
            return
        status_lbl.configure(text=f"Live — {book['code']} (auto-refreshing)")
        for level in book["bids"]:
            ctk.CTkLabel(
                bid_col, text=f"{level['price']:.3f}  ×  {level['volume']:.0f}",
                font=("Consolas", 12), text_color=self.t["text_primary"]
            ).pack(pady=1)
        for level in book["asks"]:
            ctk.CTkLabel(
                ask_col, text=f"{level['price']:.3f}  ×  {level['volume']:.0f}",
                font=("Consolas", 12), text_color=self.t["text_primary"]
            ).pack(pady=1)

    # =========================================================================
    # News Feed Tab
    # =========================================================================
    def _create_news_tab(self):
        """Build the 📰 News Feed tab — Bloomberg-style live news panel."""
        self.news_frame = ctk.CTkFrame(
            self.view_container, corner_radius=0, fg_color=self.t["bg_root"])
        self.news_frame.grid_rowconfigure(1, weight=1)
        self.news_frame.grid_columnconfigure(0, weight=1)

        # ── Header bar ──────────────────────────────────────────────────────
        news_header = ctk.CTkFrame(
            self.news_frame, fg_color=self.t["bg_card"], height=64,
            corner_radius=0, border_color=self.t["border"], border_width=0)
        news_header.grid(row=0, column=0, sticky="ew")
        news_header.grid_propagate(False)
        news_header.grid_columnconfigure(1, weight=1)

        # Left — title
        hdr_left = ctk.CTkFrame(news_header, fg_color="transparent")
        hdr_left.grid(row=0, column=0, padx=24, pady=14, sticky="w")
        ctk.CTkLabel(hdr_left, text="📰", font=("Segoe UI", 22)).pack(side="left")
        ctk.CTkLabel(
            hdr_left, text="  LIVE NEWS INTELLIGENCE",
            font=("Segoe UI", 15, "bold"), text_color=self.t["text_primary"]
        ).pack(side="left")

        # Status badge — provider info
        self._news_provider_label = ctk.CTkLabel(
            hdr_left, text="  Finnhub · Alpha Vantage · Yahoo Finance",
            font=("Segoe UI", 10), text_color=self.t["text_muted"]
        )
        self._news_provider_label.pack(side="left", padx=(12, 0))

        # Right — controls
        hdr_right = ctk.CTkFrame(news_header, fg_color="transparent")
        hdr_right.grid(row=0, column=1, padx=24, pady=14, sticky="e")

        # Last-updated label
        self._news_last_updated = ctk.CTkLabel(
            hdr_right, text="Not loaded",
            font=("Segoe UI", 10), text_color=self.t["text_muted"]
        )
        self._news_last_updated.pack(side="left", padx=(0, 16))

        # Ticker filter dropdown
        self._news_filter_var = ctk.StringVar(value="All Holdings")
        self._news_filter_dropdown = ctk.CTkOptionMenu(
            hdr_right,
            values=["All Holdings"],
            variable=self._news_filter_var,
            font=("Segoe UI", 11), height=30, corner_radius=6,
            fg_color=self.t["bg_input"],
            button_color=self.t["bg_input"],
            button_hover_color=self.t["bg_card_hover"],
            text_color=self.t["text_primary"],
            dropdown_fg_color=self.t["bg_card"],
            dropdown_text_color=self.t["text_primary"],
            dropdown_hover_color=self.t["bg_card_hover"],
            width=160,
            command=self._on_news_filter_change
        )
        self._news_filter_dropdown.pack(side="left", padx=(0, 10))

        # Refresh button
        ctk.CTkButton(
            hdr_right, text="↻  Refresh",
            font=("Segoe UI", 11, "bold"), height=30, corner_radius=6, width=90,
            fg_color=self.t["accent"], hover_color=self.t["accent_hover"],
            text_color="#FFF",
            command=self._force_refresh_news
        ).pack(side="left")

        # ── Scrollable news card list ────────────────────────────────────────
        self._news_scroll = ctk.CTkScrollableFrame(
            self.news_frame, corner_radius=0, fg_color=self.t["bg_root"],
            scrollbar_button_color=self.t["scrollbar"],
            scrollbar_button_hover_color=self.t["scrollbar_hover"]
        )
        self._news_scroll.grid(row=1, column=0, sticky="nsew")
        self._news_scroll.grid_columnconfigure(0, weight=1)

        # State
        self._all_news_articles: list = []
        self._news_last_fetch_ts: float = 0.0
        self._news_loading = False
        self._news_filtered: list = []
        self._news_rendered_count = 0
        self._news_load_more_btn = None

        # Loading placeholder
        self._news_placeholder = ctk.CTkLabel(
            self._news_scroll,
            text="Click ↻ Refresh to load live headlines\nor switch to this tab to auto-load.",
            font=("Segoe UI", 14), text_color=self.t["text_muted"]
        )
        self._news_placeholder.grid(row=0, column=0, pady=80)

        # Start background auto-refresh loop
        threading.Thread(target=self._news_auto_refresh_loop, daemon=True).start()

    def _news_auto_refresh_loop(self):
        """Background thread: refresh news every 5 minutes silently."""
        import time
        while True:
            time.sleep(300)  # 5 minutes
            try:
                self._do_refresh_news(force=True, silent=True)
            except Exception:
                pass

    def _maybe_refresh_news(self):
        """Fetch news if not loaded recently (debounce: 5 min)."""
        import time
        if time.monotonic() - self._news_last_fetch_ts > 300:
            self._do_refresh_news(force=False)

    def _force_refresh_news(self):
        """User-triggered refresh — always fetches."""
        self._do_refresh_news(force=True)

    def _on_news_filter_change(self, choice):
        """Re-render existing articles when filter changes (no API call)."""
        self._render_news_cards(self._all_news_articles)

    def _do_refresh_news(self, force=True, silent=False):
        """Fetch news in a background thread then render cards."""
        if self._news_loading:
            return
        self._news_loading = True

        if not silent:
            self.after(0, lambda: self._news_placeholder.configure(
                text="⏳ Fetching live headlines…"))
            self.after(0, lambda: self._news_placeholder.grid(row=0, column=0, pady=80))

        def _fetch():
            import time
            try:
                # Get current portfolio tickers
                metrics = get_metrics_sync()
                tickers = [h["ticker"] for h in metrics.get("holdings", [])]
                if not tickers:
                    self.after(0, lambda: self._news_placeholder.configure(
                        text="⚠  No portfolio holdings found.\nAdd holdings in the Portfolio Editor."))
                    return

                articles = fetch_portfolio_news(tickers, max_per_ticker=8, days=7)
                self._all_news_articles = articles
                self._news_last_fetch_ts = time.monotonic()

                # Update ticker filter dropdown
                ticker_options = ["All Holdings"] + sorted(set(a["ticker"] for a in articles))
                self.after(0, lambda opts=ticker_options: self._news_filter_dropdown.configure(values=opts))

                # Update last-updated label
                now_str = datetime.datetime.now().strftime("%H:%M:%S")
                self.after(0, lambda s=now_str: self._news_last_updated.configure(
                    text=f"Updated {s}"))

                # Render
                self.after(0, lambda: self._render_news_cards(articles))

            except Exception as e:
                self.after(0, lambda err=str(e): self._news_placeholder.configure(
                    text=f"⚠  Error fetching news:\n{err}"))
            finally:
                self._news_loading = False

        threading.Thread(target=_fetch, daemon=True).start()

    # Sentiment colour palette — module-level shape, built once per render pass
    # rather than reallocated per card.
    _NEWS_SENTIMENT_CFG_KEYS = ("bullish", "bearish", "neutral")
    _NEWS_PAGE_SIZE = 12  # cards rendered per batch — rendering all ~50 at once
    # (350+ individually-drawn rounded CTk widgets) was the main source of the
    # News tab's slow load and choppy scroll. Paginating keeps the live widget
    # count low; "Load More" appends another batch on demand.

    def _render_news_cards(self, articles: list):
        """Reset and render the first page of article cards into the scrollable
        news panel. Subsequent pages are appended by _render_more_news_cards."""
        for widget in self._news_scroll.winfo_children():
            widget.destroy()
        self._news_load_more_btn = None

        selected_filter = self._news_filter_var.get()
        if selected_filter and selected_filter != "All Holdings":
            filtered = [a for a in articles if a.get("ticker", "") == selected_filter]
        else:
            filtered = articles
        self._news_filtered = filtered[:60]  # hard cap — beyond this isn't useful to scan
        self._news_rendered_count = 0

        if not filtered:
            lbl = ctk.CTkLabel(
                self._news_scroll,
                text="No news articles found for the selected filter.\nTry refreshing or selecting a different ticker.",
                font=("Segoe UI", 14), text_color=self.t["text_muted"]
            )
            lbl.grid(row=0, column=0, pady=80)
            return

        self._render_more_news_cards()

    def _render_more_news_cards(self):
        """Render the next batch of up to _NEWS_PAGE_SIZE cards, replacing the
        trailing 'Load More' button (or padding) with the new batch + a fresh one."""
        if self._news_load_more_btn is not None:
            self._news_load_more_btn.destroy()
            self._news_load_more_btn = None

        sentiment_cfg = {
            "bullish":  {"icon": "📈", "text": "BULLISH",  "color": self.t["emerald"],  "bg": self.t.get("emerald_soft", "#0d2d1e")},
            "bearish":  {"icon": "📉", "text": "BEARISH",  "color": self.t["crimson"],  "bg": "#2e1212"},
            "neutral":  {"icon": "➖", "text": "NEUTRAL",  "color": self.t["text_muted"], "bg": self.t["bg_input"]},
        }

        start = self._news_rendered_count
        end = min(start + self._NEWS_PAGE_SIZE, len(self._news_filtered))

        for row_idx in range(start, end):
            art = self._news_filtered[row_idx]
            sentiment = art.get("sentiment", "neutral")
            cfg = sentiment_cfg.get(sentiment, sentiment_cfg["neutral"])
            ticker = art.get("ticker", "")
            title = art.get("title", "No title")
            source = art.get("source", "")
            rel_time = art.get("published_rel", "recently")
            url = art.get("url", "")
            summary = art.get("summary", "")
            score = art.get("sentiment_score", 0.0)

            # Card container — corner_radius kept low (6 vs the original 10) since
            # rounded-corner rendering cost is paid per widget, and this repeats
            # dozens of times per page.
            card = ctk.CTkFrame(
                self._news_scroll,
                fg_color=self.t["bg_card"],
                corner_radius=6,
                border_color=self.t["border"],
                border_width=1
            )
            card.grid(row=row_idx, column=0, padx=24, pady=(8, 0), sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            # ── Top row: ticker pill + sentiment badge + time ──
            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")
            top_row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                top_row, text=f"  {ticker}  ",
                font=("Segoe UI", 10, "bold"),
                fg_color=self.t["accent_soft"],
                text_color=self.t["accent"],
                corner_radius=3
            ).grid(row=0, column=0, sticky="w")

            score_txt = f" ({score:+.2f})" if score != 0.0 else ""
            ctk.CTkLabel(
                top_row,
                text=f"  {cfg['icon']} {cfg['text']}{score_txt}  ",
                font=("Segoe UI", 10, "bold"),
                fg_color=cfg["bg"],
                text_color=cfg["color"],
                corner_radius=3
            ).grid(row=0, column=1, sticky="w", padx=(8, 0))

            ctk.CTkLabel(
                top_row,
                text=f"{rel_time}  ·  {source}",
                font=("Segoe UI", 10),
                text_color=self.t["text_muted"]
            ).grid(row=0, column=2, sticky="e")

            # ── Headline (clickable, flat — no rounded-corner cost on hover bg) ──
            headline_btn = ctk.CTkButton(
                card,
                text=title,
                font=("Segoe UI", 13, "bold"),
                fg_color="transparent",
                hover_color=self.t["bg_card_hover"],
                text_color=self.t["text_primary"],
                anchor="w",
                corner_radius=0,
                command=lambda u=url: self._open_news_url(u) if u else None
            )
            headline_btn.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="ew")

            if summary:
                ctk.CTkLabel(
                    card, text=summary,
                    font=("Segoe UI", 11),
                    text_color=self.t["text_secondary"],
                    wraplength=800, anchor="w", justify="left"
                ).grid(row=2, column=0, padx=16, pady=(0, 12), sticky="ew")
            else:
                ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=2, column=0)

        self._news_rendered_count = end

        if end < len(self._news_filtered):
            remaining = len(self._news_filtered) - end
            self._news_load_more_btn = ctk.CTkButton(
                self._news_scroll,
                text=f"↓  Load more ({remaining} remaining)",
                font=("Segoe UI", 11, "bold"), corner_radius=6, height=34,
                fg_color=self.t["bg_input"], hover_color=self.t["bg_card_hover"],
                text_color=self.t["text_secondary"],
                command=self._render_more_news_cards
            )
            self._news_load_more_btn.grid(row=end, column=0, pady=16)
        else:
            ctk.CTkFrame(self._news_scroll, fg_color="transparent", height=24).grid(row=end, column=0)

    def _open_news_url(self, url: str):
        """Open a news article URL in the system browser."""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # =========================================================================
    # Tab switching
    # =========================================================================
    def switch_tab(self, tab_name):
        # Hide all frames
        all_frames = ["dash_frame", "editor_frame", "history_frame", "news_frame"]
        all_btns = {
            "dashboard": "btn_tab_dash", "editor": "btn_tab_edit",
            "history": "btn_tab_hist", "news": "btn_tab_news"
        }
        for f in all_frames:
            try:
                getattr(self, f).grid_forget()
            except AttributeError:
                pass

        # Reset all buttons
        for btn_attr in all_btns.values():
            try:
                getattr(self, btn_attr).configure(
                    fg_color="transparent",
                    text_color=self.t["text_secondary"],
                    border_width=0
                )
            except AttributeError:
                pass

        # Activate the selected tab
        if tab_name == "dashboard":
            self.dash_frame.grid(row=0, column=0, sticky="nsew")
            self.btn_tab_dash.configure(fg_color=self.t["bg_card"], text_color=self.t["text_primary"], border_width=1, border_color=self.t["border"])
        elif tab_name == "editor":
            self.editor_frame.grid(row=0, column=0, sticky="nsew")
            self.btn_tab_edit.configure(fg_color=self.t["bg_card"], text_color=self.t["text_primary"], border_width=1, border_color=self.t["border"])
            self.load_portfolio_into_editor()
        elif tab_name == "history":
            self.history_frame.grid(row=0, column=0, sticky="nsew")
            self.btn_tab_hist.configure(fg_color=self.t["bg_card"], text_color=self.t["text_primary"], border_width=1, border_color=self.t["border"])
        elif tab_name == "news":
            self.news_frame.grid(row=0, column=0, sticky="nsew")
            self.btn_tab_news.configure(fg_color=self.t["bg_card"], text_color=self.t["text_primary"], border_width=1, border_color=self.t["border"])
            # Trigger auto-fetch if not recently loaded
            self._maybe_refresh_news()


    def on_market_change(self, choice):
        # Trigger immediate refresh for market benchmark
        self.fetch_market_benchmark()

    def fetch_market_benchmark(self):
        try:
            choice = self.market_dropdown.get()
            import re
            match = re.search(r'\((.*?)\)', choice)
            if match:
                ticker = match.group(1)
                live = fetch_live_price(ticker)
                if live:
                    price = live["price"]
                    pct_change = live.get("change_pct", 0.0)
                    sign = "+" if pct_change >= 0 else ""
                    
                    change_fg = self.t["emerald"] if pct_change >= 0 else self.t["crimson"]
                    change_bg = self.t["emerald_soft"] if pct_change >= 0 else ("#2e1212" if self.current_theme == "dark" else "#fee2e2")
                    
                    self.after(0, lambda: self.val_market.configure(text=f"${price:,.2f}"))
                    self.after(0, lambda: self.val_market_change.configure(
                        text=f" {sign}{pct_change:.2f}% ",
                        text_color=change_fg,
                        fg_color=change_bg
                    ))
                else:
                    self.after(0, lambda: self.val_market.configure(text="N/A"))
                    self.after(0, lambda: self.val_market_change.configure(text="", fg_color="transparent"))
        except Exception:
            pass

    def _create_history_tab(self):
        self.history_frame = ctk.CTkFrame(
            self.view_container, corner_radius=0, fg_color=self.t["bg_root"])
        self.history_frame.grid_rowconfigure(1, weight=1)
        self.history_frame.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(
            self.history_frame, fg_color=self.t["bg_card"], height=60,
            corner_radius=0, border_color=self.t["border"], border_width=0)
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        
        ctk.CTkLabel(
            header, text="Historical Performance",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=self.t["text_primary"]).pack(side="left", padx=20, pady=16)

        # Content area
        content = ctk.CTkFrame(self.history_frame, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=28, pady=28)
        content.grid_columnconfigure(0, weight=1)
        
        search_card = ctk.CTkFrame(
            content, fg_color=self.t["bg_card"], corner_radius=12,
            border_color=self.t["border"], border_width=1)
        search_card.pack(fill="x", pady=(0, 20))
        
        search_inner = ctk.CTkFrame(search_card, fg_color="transparent")
        search_inner.pack(padx=20, pady=20, fill="x")
        
        ctk.CTkLabel(search_inner, text="Ticker Symbol:", font=("Segoe UI", 12, "bold"), text_color=self.t["text_primary"]).pack(side="left", padx=(0, 10))
        self.hist_input = ctk.CTkEntry(search_inner, width=200, height=36, corner_radius=8, font=("Segoe UI", 12), placeholder_text="Type to search...", fg_color=self.t["bg_input"], border_color=self.t["border"])
        self.hist_input.pack(side="left", padx=(0, 20))
        self.hist_input.bind("<KeyRelease>", self.on_hist_target_key)
        
        # Apple-inspired automatic updates on timeframe change
        self.hist_tf_dropdown = SleekDropdown(
            search_inner, values=["1M", "3M", "6M", "YTD", "1Y", "5Y"],
            font=("Segoe UI", 12, "bold"), height=36, corner_radius=8,
            fg_color=self.t["bg_input"], text_color=self.t["text_primary"], hover_color=self.t["bg_card_hover"],
            command=self.fetch_history
        )
        self.hist_tf_dropdown.pack(side="left", padx=10)
        
        btn_fetch = ctk.CTkButton(search_inner, text="Fetch & Chart", font=("Segoe UI", 12, "bold"), height=36, corner_radius=8, fg_color=self.t["accent"], hover_color=self.t["accent_hover"], text_color="#FFF", command=self.fetch_history)
        btn_fetch.pack(side="right")
        
        # Add canvas placeholder
        self.hist_canvas_widget = None
        
        # Result area
        self.hist_result_card = ctk.CTkFrame(
            content, fg_color=self.t["bg_card"], corner_radius=12,
            border_color=self.t["border"], border_width=1)
        self.hist_result_card.pack(fill="both", expand=True)
        
        self.lbl_hist_result = ctk.CTkLabel(self.hist_result_card, text="Enter a ticker to view historical performance.", font=("Segoe UI", 16), text_color=self.t["text_muted"])
        self.lbl_hist_result.pack(expand=True)

    def fetch_history(self, *args):
        ticker = self.hist_input.get().split("  —  ")[0].strip().upper()
        tf = self.hist_tf_dropdown.get()
        if not ticker:
            return
            
        # Clear previous elements
        for widget in self.hist_result_card.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass
        self.hist_canvas_widget = None
        
        self.lbl_hist_result = ctk.CTkLabel(self.hist_result_card, text=f"Fetching {tf} data for {ticker}...", font=("Segoe UI", 16), text_color=self.t["text_primary"])
        self.lbl_hist_result.pack(expand=True)
        
        def do_fetch():
            import urllib.request, urllib.parse, json, time, datetime
            
            ranges = {"1M": "1mo", "3M": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y", "5Y": "5y"}
            r = ranges.get(tf, "ytd")
            
            try:
                q = urllib.parse.quote(ticker)
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range={r}&interval=1d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    res = data["chart"]["result"]
                    if not res:
                        self.after(0, lambda: self.lbl_hist_result.configure(text=f"No data found for {ticker}."))
                        return
                        
                    meta = res[0]["meta"]
                    timestamps = res[0]["timestamp"]
                    adjclose = res[0]["indicators"]["adjclose"][0]["adjclose"]
                    
                    # Find first valid close
                    start_price = None
                    for p in adjclose:
                        if p is not None:
                            start_price = p
                            break
                    
                    end_price = meta.get("regularMarketPrice")
                    if not start_price or not end_price:
                        self.after(0, lambda: self.lbl_hist_result.configure(text=f"Incomplete data for {ticker}."))
                        return
                        
                    perf = ((end_price - start_price) / start_price) * 100
                    short_name = meta.get('shortName', ticker)
                    sign = "+" if perf >= 0 else ""
                    
                    # Dispatch chart drawing to the main GUI thread safely!
                    self.after(0, lambda: self._draw_performance_chart(
                        ticker, short_name, timestamps, adjclose, perf, start_price, end_price, sign, tf
                    ))
                    
            except Exception as e:
                self.after(0, lambda: self.lbl_hist_result.configure(text=f"Error fetching data: {e}", text_color=self.t["crimson"]))
                
        threading.Thread(target=do_fetch, daemon=True).start()

    def _draw_performance_chart(self, ticker, short_name, timestamps, adjclose, perf, start_price, end_price, sign, tf):
        # 1. Clear result card content
        for widget in self.hist_result_card.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass
        self.hist_canvas_widget = None
            
        # 2. Build header (Apple style)
        header_frame = ctk.CTkFrame(self.hist_result_card, fg_color="transparent")
        header_frame.pack(fill="x", padx=24, pady=(20, 10))
        
        lbl_name = ctk.CTkLabel(header_frame, text=short_name or ticker, font=("Segoe UI", 18, "bold"), text_color=self.t["text_primary"])
        lbl_name.pack(side="left", anchor="w")
        
        price_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        price_frame.pack(side="right", anchor="e")
        
        lbl_price = ctk.CTkLabel(price_frame, text=f"${end_price:.2f}", font=("Segoe UI", 16, "bold"), text_color=self.t["text_primary"])
        lbl_price.pack(side="left", padx=(0, 10))
        
        perf_bg = self.t["emerald_soft"] if perf >= 0 else "#fee2e2"
        perf_fg = self.t["emerald"] if perf >= 0 else self.t["crimson"]
        lbl_badge = ctk.CTkLabel(price_frame, text=f" {sign}{perf:.2f}% ", font=("Segoe UI", 11, "bold"), text_color=perf_fg, fg_color=perf_bg, corner_radius=6)
        lbl_badge.pack(side="left")
        
        # 3. Create chart frame
        chart_frame = ctk.CTkFrame(self.hist_result_card, fg_color="transparent")
        chart_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        # 4. Matplotlib drawing
        try:
            fig = Figure(figsize=(6, 3), dpi=100)
            ax = fig.add_subplot(111)
            
            # Configure subplot bounds to maximize the chart space and leave room for y-axis annotations
            fig.subplots_adjust(left=0.03, right=0.88, top=0.92, bottom=0.15)
            
            # Colors
            bg_color = self.t["bg_card"]
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            
            import datetime
            dates = [datetime.datetime.fromtimestamp(ts) for ts in timestamps]
            
            valid_pairs = [(d, p) for d, p in zip(dates, adjclose) if p is not None]
            if not valid_pairs:
                lbl_error = ctk.CTkLabel(chart_frame, text="No valid price history to chart.", font=("Segoe UI", 14), text_color=self.t["text_muted"])
                lbl_error.pack(expand=True)
                return
                
            dates_clean, prices_clean = zip(*valid_pairs)
            
            line_color = self.t["emerald"] if perf >= 0 else self.t["crimson"]
            ax.plot(dates_clean, prices_clean, color=line_color, linewidth=2.5)
            
            # Fill under line
            min_p = min(prices_clean)
            max_p = max(prices_clean)
            price_range = max_p - min_p if max_p != min_p else 1.0
            y_lim_min = min_p - price_range * 0.05
            y_lim_max = max_p + price_range * 0.16  # Extra room on top for dynamic info text header
            ax.set_ylim(y_lim_min, y_lim_max)
            
            ax.fill_between(dates_clean, prices_clean, y_lim_min, color=line_color, alpha=0.08)
            
            # Styling
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            
            ax.yaxis.tick_right()
            ax.yaxis.set_label_position("right")
            
            tick_color = self.t["text_secondary"]
            ax.tick_params(axis='x', colors=tick_color, labelsize=8)
            ax.tick_params(axis='y', colors=tick_color, labelsize=8)
            
            # Subtle grid lines on both axes (Bloomberg-style double-axis gridlines)
            ax.grid(True, which='both', color=self.t["border"], linestyle=':', linewidth=0.5)
            
            # Explicitly set x-axis limits to actual data range
            ax.set_xlim(min(dates_clean), max(dates_clean))
            
            # Format dates
            import matplotlib.dates as mdates
            if tf in ("1M", "3M", "6M"):
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
            elif tf in ("YTD", "1Y"):
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
            else: # 5Y
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
                
            # Autofit date rotation if needed
            fig.autofmt_xdate(rotation=0, ha='center')
            
            # 5. Interactive Hover / Tooltip Functionality
            x_coords = mdates.date2num(dates_clean)
            
            # Bloomberg crosshair: vertical and horizontal lines
            hover_vline = ax.axvline(color=self.t["accent"], linestyle=':', alpha=0.6, visible=False)
            hover_hline = ax.axhline(color=self.t["accent"], linestyle=':', alpha=0.6, visible=False)
            
            # Highlight dot on curve
            hover_point = ax.plot([], [], color=self.t["accent"], marker='o', markersize=6, zorder=5, visible=False)[0]
            
            # Date annotation on X-axis (bottom boundary, clip_on=False to show on border)
            hover_x_anno = ax.annotate(
                "", xy=(0, 0), xytext=(0, -10),
                textcoords="offset points",
                transform=ax.get_xaxis_transform(),
                bbox=dict(boxstyle="square,pad=0.3", fc=self.t["accent"], ec=self.t["accent"], lw=1, alpha=0.95),
                fontname="Segoe UI", fontsize=8, color="#FFFFFF", weight="bold",
                va="top", ha="center", visible=False, clip_on=False
            )
            
            # Price annotation on Y-axis (right boundary, clip_on=False to show on border)
            hover_y_anno = ax.annotate(
                "", xy=(1, 0), xytext=(10, 0),
                textcoords="offset points",
                transform=ax.get_yaxis_transform(),
                bbox=dict(boxstyle="square,pad=0.3", fc=self.t["accent"], ec=self.t["accent"], lw=1, alpha=0.95),
                fontname="Segoe UI", fontsize=8, color="#FFFFFF", weight="bold",
                va="center", ha="left", visible=False, clip_on=False
            )
            
            # Dynamic header text at the top-left of the chart (Bloomberg style)
            info_text = ax.text(
                0.01, 0.96, "", 
                transform=ax.transAxes, 
                fontname="Segoe UI", fontsize=10, weight="bold",
                color=self.t["text_primary"],
                va="top", ha="left",
                bbox=dict(boxstyle="square,pad=0.2", fc=bg_color, ec="none", alpha=0.8)
            )
            
            default_info = f"{short_name or ticker} ({tf})  •  Price: ${end_price:.2f}  •  Change: {sign}{perf:.2f}%"
            info_text.set_text(default_info)

            def on_hover(event):
                if event.inaxes == ax:
                    if event.xdata is None:
                        return
                    # Find closest index
                    idx = min(range(len(x_coords)), key=lambda i: abs(x_coords[i] - event.xdata))
                    x_val = dates_clean[idx]
                    y_val = prices_clean[idx]
                    
                    # Update crosshair position
                    hover_vline.set_xdata([x_val, x_val])
                    hover_vline.set_visible(True)
                    
                    hover_hline.set_ydata([y_val, y_val])
                    hover_hline.set_visible(True)
                    
                    # Update point position
                    hover_point.set_data([x_val], [y_val])
                    hover_point.set_visible(True)
                    
                    # Update bottom-axis date highlight
                    date_str = x_val.strftime("%b %d, %Y")
                    hover_x_anno.set_text(date_str)
                    hover_x_anno.xy = (x_val, 0)
                    hover_x_anno.set_visible(True)
                    
                    # Update right-axis price highlight
                    hover_y_anno.set_text(f"${y_val:.2f}")
                    hover_y_anno.xy = (1, y_val)
                    hover_y_anno.set_visible(True)
                    
                    # Update dynamic info text at top-left
                    hover_sign = "+" if y_val >= start_price else ""
                    hover_pct = ((y_val - start_price) / start_price) * 100
                    hover_info = f"{short_name or ticker}  •  Date: {date_str}  •  Price: ${y_val:.2f}  •  Return: {hover_sign}{hover_pct:.2f}%"
                    info_text.set_text(hover_info)
                    info_text.set_color(self.t["emerald"] if y_val >= start_price else self.t["crimson"])
                    
                    fig.canvas.draw_idle()
                else:
                    hide_annotations()

            def hide_annotations():
                if hover_vline.get_visible():
                    hover_vline.set_visible(False)
                    hover_hline.set_visible(False)
                    hover_point.set_visible(False)
                    hover_x_anno.set_visible(False)
                    hover_y_anno.set_visible(False)
                    info_text.set_text(default_info)
                    info_text.set_color(self.t["text_primary"])
                    fig.canvas.draw_idle()

            def on_leave(event):
                hide_annotations()

            # Connect event handlers to the canvas
            fig.canvas.mpl_connect('motion_notify_event', on_hover)
            fig.canvas.mpl_connect('axes_leave_event', on_leave)

            canvas = FigureCanvasTkAgg(fig, master=chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.hist_canvas_widget = canvas
            
        except Exception as e:
            lbl_error = ctk.CTkLabel(chart_frame, text=f"Failed to render chart: {e}", font=("Segoe UI", 14), text_color=self.t["crimson"])
            lbl_error.pack(expand=True)

    # =========================================================================
    # Logging
    # =========================================================================

    # =========================================================================
    # History Autocomplete
    # =========================================================================
    def on_hist_target_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            if event.keysym == "Escape":
                self.hide_hist_dropdown()
            elif event.keysym == "Return":
                self.fetch_history()
            return
        query = self.hist_input.get().strip()
        if len(query) < 2:
            self.hide_hist_dropdown()
            return
        if hasattr(self, '_hist_autocomplete_timer') and self._hist_autocomplete_timer:
            self.after_cancel(self._hist_autocomplete_timer)
        self._hist_autocomplete_timer = self.after(350, lambda: self._do_hist_autocomplete(query))

    def _do_hist_autocomplete(self, query):
        threading.Thread(target=self._fetch_and_show_hist, args=(query,), daemon=True).start()

    def _fetch_and_show_hist(self, query):
        results = search_ticker(query, max_results=6)
        suggestions = [f"{r['symbol']}  —  {r['name']}" for r in results]
        self.after(0, lambda: self.show_hist_dropdown(suggestions))

    def hide_hist_dropdown(self):
        if hasattr(self, 'hist_dropdown_frame') and self.hist_dropdown_frame:
            try:
                self.hist_dropdown_frame.destroy()
            except Exception:
                pass
            self.hist_dropdown_frame = None

    def show_hist_dropdown(self, suggestions):
        self.hide_hist_dropdown()
        if not suggestions:
            return
        self.hist_dropdown_frame = ctk.CTkToplevel(self)
        self.hist_dropdown_frame.overrideredirect(True)
        self.hist_dropdown_frame.attributes("-topmost", True)
        self.hist_dropdown_frame.configure(fg_color=self.t["bg_card"])

        self.update_idletasks()
        x = self.hist_input.winfo_rootx()
        y = self.hist_input.winfo_rooty() + self.hist_input.winfo_height() + 2
        width = max(self.hist_input.winfo_width(), 320)
        height = min(len(suggestions) * 36 + 10, 230)
        self.hist_dropdown_frame.geometry(f"{width}x{height}+{x}+{y}")

        # Apple-style border and padding container
        container = ctk.CTkFrame(
            self.hist_dropdown_frame,
            fg_color=self.t["bg_card"],
            border_width=1,
            border_color=self.t["border"],
            corner_radius=8
        )
        container.pack(fill="both", expand=True)

        btn_width = width - 24
        for s in suggestions:
            symbol = s.split("  —  ")[0] if "  —  " in s else s
            btn = ctk.CTkButton(
                container, text=s, font=("Segoe UI", 11),
                width=btn_width,
                fg_color="transparent", text_color=self.t["text_primary"],
                hover_color=self.t["bg_card_hover"], anchor="w", height=34,
                corner_radius=6,
                command=lambda t=s: self.select_hist_suggestion(t))
            btn.pack(fill="x", padx=4, pady=1)

        self.hist_dropdown_frame.bind("<FocusOut>", lambda e: self.hide_hist_dropdown())
        self.hist_dropdown_frame.focus_set()

    def select_hist_suggestion(self, text):
        self.hist_input.delete(0, "end")
        self.hist_input.insert(0, text)
        self.hide_hist_dropdown()
        # Automatically fetch chart upon selection!
        self.fetch_history()


    def log(self, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.console_text.configure(state="normal")
        self.console_text.insert("end", f"[{ts}]  {text}\n")
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def show_error(self, err_msg):
        import tkinter.messagebox
        tkinter.messagebox.showerror("Execution Error", str(err_msg), parent=self)
        self.log(f"✗ ERROR: {str(err_msg)}")

    # =========================================================================
    # Progress animation
    # =========================================================================
    def _start_progress(self):
        self._progress_running = True
        self._animate_progress(0.0)

    def _stop_progress(self):
        self._progress_running = False
        try:
            self.progress_bar.set(0)
        except Exception:
            pass

    def _animate_progress(self, val):
        if not self._progress_running:
            return
        try:
            new_val = val + 0.012
            if new_val > 0.92:
                new_val = 0.92  # Hold near end until complete
            self.progress_bar.set(new_val)
            self.after(120, lambda: self._animate_progress(new_val))
        except Exception:
            pass

    # =========================================================================
    # Autocomplete dropdown
    # =========================================================================
    def on_target_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            if event.keysym == "Escape":
                self.hide_dropdown()
            return
        query = self.target_input.get().strip()
        if len(query) < 2 or query.lower() in ("portfolio.md", "portfolio"):
            self.hide_dropdown()
            return
        if self._autocomplete_timer:
            self.after_cancel(self._autocomplete_timer)
        self._autocomplete_timer = self.after(350, lambda: self._do_autocomplete(query))

    def _do_autocomplete(self, query):
        threading.Thread(target=self._fetch_and_show, args=(query,), daemon=True).start()

    def _fetch_and_show(self, query):
        results = search_ticker(query, max_results=6)
        suggestions = [f"{r['symbol']}  —  {r['name']}" for r in results]
        self.after(0, lambda: self.show_dropdown(suggestions))

    def hide_dropdown(self):
        if self.dropdown_frame:
            try:
                self.dropdown_frame.destroy()
            except Exception:
                pass
            self.dropdown_frame = None

    def show_dropdown(self, suggestions):
        self.hide_dropdown()
        if not suggestions:
            return
        self.dropdown_frame = ctk.CTkToplevel(self)
        self.dropdown_frame.overrideredirect(True)
        self.dropdown_frame.attributes("-topmost", True)
        self.dropdown_frame.configure(fg_color=self.t["bg_card"])

        self.update_idletasks()
        x = self.target_input.winfo_rootx()
        y = self.target_input.winfo_rooty() + self.target_input.winfo_height() + 2
        width = max(self.target_input.winfo_width(), 320)
        height = min(len(suggestions) * 36 + 10, 230)
        self.dropdown_frame.geometry(f"{width}x{height}+{x}+{y}")

        # Apple-style border and padding container
        container = ctk.CTkFrame(
            self.dropdown_frame,
            fg_color=self.t["bg_card"],
            border_width=1,
            border_color=self.t["border"],
            corner_radius=8
        )
        container.pack(fill="both", expand=True)

        btn_width = width - 24
        for s in suggestions:
            symbol = s.split("  —  ")[0] if "  —  " in s else s
            btn = ctk.CTkButton(
                container, text=s, font=("Segoe UI", 11),
                width=btn_width,
                fg_color="transparent", text_color=self.t["text_primary"],
                hover_color=self.t["bg_card_hover"], anchor="w", height=34,
                corner_radius=6,
                command=lambda t=symbol: self.select_suggestion(t))
            btn.pack(fill="x", padx=4, pady=1)

        self.bind("<Button-1>", self._on_root_click, add="+")

    def _on_root_click(self, event):
        if self.dropdown_frame:
            try:
                dx = self.dropdown_frame.winfo_rootx()
                dy = self.dropdown_frame.winfo_rooty()
                dw = self.dropdown_frame.winfo_width()
                dh = self.dropdown_frame.winfo_height()
                if not (dx <= event.x_root <= dx + dw and dy <= event.y_root <= dy + dh):
                    self.hide_dropdown()
                    self.unbind("<Button-1>")
            except Exception:
                self.hide_dropdown()

    def select_suggestion(self, text):
        self.target_input.delete(0, "end")
        self.target_input.insert(0, text)
        self.hide_dropdown()
        try:
            self.unbind("<Button-1>")
        except Exception:
            pass

    # =========================================================================
    # Agent execution
    # =========================================================================
    def set_working(self, name):
        self.status_dot.configure(text_color=self.t["gold"])
        self.status_string.configure(text=f"RUNNING: {name.upper()}")
        self._start_progress()

    def trigger_orchestrator(self):
        target = self.target_input.get().strip() or "Portfolio.md"
        
        # Gather all selected active sub-agents
        selected = [agent for agent, var in self.agent_vars.items() if var.get()]
        if not selected:
            self.log("⚠ No agents selected! Automatically selecting all.")
            self.select_all_agents()
            selected = list(self.agent_vars.keys())

        # Build mapping of agent -> model based on layer UI selection
        agent_models_map = {}
        for layer_name, agents in AGENT_LAYERS.items():
            ui_model = self.layer_models[layer_name].get()
            api_model = MODEL_ID_MAP.get(ui_model, "gemini-3.5-flash")
            for agent in agents:
                agent_models_map[agent] = api_model

        # Add Master Orchestrator model from its dedicated dropdown
        mo_ui_model = self.mo_model_var.get()
        agent_models_map["Master Orchestrator"] = MODEL_ID_MAP.get(mo_ui_model, "claude-sonnet-4-6")

        # Show a brief confirmation in the log
        self.log(f"{'─'*40}")
        self.log(f"▶ MASTER ORCHESTRATOR — {len(selected)} agent(s) queued:")
        for a in selected:
            self.log(f"   • {a} ({agent_models_map.get(a)})")
        self.log(f"{'─'*40}")

        if target.lower() not in ("portfolio.md", "portfolio"):
            self.log(f"Validating ticker: {target}...")
            self.set_working("Validating")
            threading.Thread(
                target=self._validate_and_run_orchestrator,
                args=(target, selected, agent_models_map), daemon=True).start()
        else:
            self.set_working("Orchestrator")
            threading.Thread(
                target=self.worker,
                args=("Master Orchestrator", target, selected, agent_models_map), daemon=True).start()

    def _validate_and_run_orchestrator(self, target, selected_agents, agent_models_map):
        live = fetch_live_price(target)
        if live is None:
            self.after(0, lambda: self.show_error(
                f"Ticker '{target}' not found. Please enter a valid ticker symbol."))
            self.after(0, lambda: self.status_dot.configure(text_color=self.t["emerald"]))
            self.after(0, lambda: self.status_string.configure(text="SYSTEM READY"))
            self.after(0, self._stop_progress)
            return
        resolved = live["ticker"]
        name = live["name"]
        self.after(0, lambda: self.log(
            f"Resolved: {resolved} ({name}) @ ${live['price']:.2f} {live['currency']}"))
        self.after(0, lambda: self.set_working("Orchestrator"))
        self.worker("Master Orchestrator", resolved, selected_agents, agent_models_map)

    def _validate_and_run(self, agent_name, target):
        live = fetch_live_price(target)
        if live is None:
            self.after(0, lambda: self.show_error(
                f"Ticker '{target}' not found. Please enter a valid ticker symbol."))
            self.after(0, lambda: self.status_dot.configure(text_color=self.t["emerald"]))
            self.after(0, lambda: self.status_string.configure(text="SYSTEM READY"))
            self.after(0, self._stop_progress)
            return
        resolved = live["ticker"]
        name = live["name"]
        self.after(0, lambda: self.log(
            f"Resolved: {resolved} ({name}) @ ${live['price']:.2f} {live['currency']}"))
        self.after(0, lambda: self.set_working(agent_name))
        self.worker(agent_name, resolved)

    def show_report_in_browser(self, title, report_text):
        html_content = render_report_html(title, report_text)
        report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "" for c in title
        ).strip().replace(" ", "_")
        filename = f"{safe_title}_{timestamp}.html"
        filepath = os.path.join(report_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        webbrowser.open(f"file:///{filepath.replace(os.sep, '/')}")
        self.log(f"Report saved: {filename}")

    def worker(self, agent_name, target, active_agents=None, agent_models=None):
        def progress_callback(agent, status):
            """Called from the asyncio thread — must dispatch to main thread."""
            self.after(0, lambda a=agent, s=status: (
                self.log(f"  [{s}] {a}"),
                self.status_string.configure(text=f"RUNNING: {a.upper()[:28]}")
            ))

        try:
            res = asyncio.run(
                run_agent(
                    agent_name,
                    target,
                    active_agents=active_agents,
                    progress_callback=progress_callback if active_agents else None,
                    agent_models=agent_models
                )
            )
            if not res or not res.strip():
                self.after(0, lambda: self.show_error(
                    "Agent returned empty response. Check your API key."))
            else:
                self.after(0, lambda: self.log(
                    f"✓ SUCCESS: {agent_name} complete for {target}."))
                title = f"{agent_name} — {target}"
                self.after(0, lambda: self.show_report_in_browser(title, res))
        except ValueError as e:
            self.after(0, lambda: self.show_error(str(e)))
        except Exception as e:
            self.after(0, lambda: self.log(f"✗ CRITICAL ERROR: {str(e)}"))
            self.after(0, lambda: self.show_error(str(e)))
        finally:
            self.after(0, lambda: self.status_dot.configure(text_color=self.t["emerald"]))
            self.after(0, lambda: self.status_string.configure(text="SYSTEM READY"))
            self.after(0, self._stop_progress)
            self.after(0, lambda: self.progress_bar.set(1.0))
            self.after(800, self._stop_progress)

    # =========================================================================
    # Auto-refresh metrics
    # =========================================================================
    def refresh_metrics_loop(self):
        def _refresh():
            try:
                target = getattr(self, "target_input", None)
                target_val = target.get().strip() if target else "Portfolio.md"
                if target_val.lower() not in ("portfolio.md", "portfolio"):
                    self.after(0, lambda: self.lbl_regime_val.configure(
                        text=f"Single Ticker Mode: {target_val.upper()}"))
                    self.after(0, lambda: self.val_portfolio.configure(text="—"))
                    self.after(0, lambda: self.val_count.configure(text="—"))
                    return
                m = get_metrics_sync(target_val)
                if m:
                    self.after(0, lambda: self.lbl_regime_val.configure(
                        text=f"Portfolio loaded — {m.get('holdings_count', 0)} holdings"))
                    total = m.get("total_val_usd", 0)
                    self.after(0, lambda: self.val_portfolio.configure(
                        text=f"${total:,.2f}"))
                    try: self.after(0, lambda: self.lbl_portfolio_total_editor.configure(
                        text=f"Total Value: ${total:,.2f}"))
                    except: pass
                    self.after(0, lambda: self.val_count.configure(
                        text=str(m.get("holdings_count", 0))))
                    self.fetch_market_benchmark()
            except Exception:
                pass
        threading.Thread(target=_refresh, daemon=True).start()
        self.after(15000, self.refresh_metrics_loop)


if __name__ == "__main__":
    app = PortfolioAgentApp()
    app.mainloop()