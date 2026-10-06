"""
AlphaMaxxin Setup Wizard
========================
Run this once after downloading/cloning the project:

    python setup.py

This script assumes you have never set this project up before and walks
through every step: checking Python, installing dependencies, creating your
personal .env file with API keys, and (optionally) launching the app at the
end. It installs packages inside the project's .venv and preserves existing
portfolio/configuration files unless you choose to update them.

You do NOT need to understand what any of this means to run it. Just answer
the prompts. Pressing Enter on an "optional" question skips it.

Note: output is plain ASCII on purpose (no special symbols/checkmarks) --
the default Windows command prompt often can't display them and would
crash this script for exactly the beginners it's meant to help.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
REQUIREMENTS_PATH = os.path.join(HERE, "requirements.txt")
PORTFOLIO_PATH = os.path.join(HERE, "Portfolio.md")

# (env var name, human label, signup URL, required?, one-line explanation)
API_KEYS = [
    ("ANTHROPIC_API_KEY", "Claude (Anthropic)",
     "https://console.anthropic.com/settings/keys",
     False,
     "Powers the higher-tier analysis/synthesis agents. Paid, but cheap for occasional use."),
    ("GEMINI_API_KEY", "Gemini (Google)",
     "https://aistudio.google.com/apikey",
     False,
     "Powers the cheap default-tier agents. Has a free quota -- good first key to get."),
    ("OPENAI_API_KEY", "OpenAI",
     "https://platform.openai.com/api-keys",
     False,
     "Optional fallback LLM if you don't want Claude or Gemini."),
    ("FINNHUB_API_KEY", "Finnhub",
     "https://finnhub.io/register",
     False,
     "Live news headlines + sentiment. Free tier is enough to start."),
    ("ALPHAVANTAGE_API_KEY", "Alpha Vantage",
     "https://www.alphavantage.co/support/#api-key",
     False,
     "Additional news/sentiment source, used alongside Finnhub."),
    ("FRED_API_KEY", "FRED (Federal Reserve data)",
     "https://fred.stlouisfed.org/docs/api/api_key.html",
     False,
     "US macro data (rates, CPI, jobs) for the Macro analyst. Works without a key too, just slower."),
]

BROKER_PACKAGES = [("Moomoo/OpenD", "moomoo-api"), ("IBKR", "ib_async"),
                   ("Tiger", "tigeropen")]


def ensure_project_environment():
    """Run setup in this project's virtual environment, creating it once."""
    venv_dir = os.path.join(HERE, ".venv")
    if os.path.normcase(os.path.realpath(sys.prefix)) == os.path.normcase(os.path.realpath(venv_dir)):
        return
    python = os.path.join(venv_dir, "Scripts" if os.name == "nt" else "bin",
                          "python.exe" if os.name == "nt" else "python")
    if not os.path.isfile(python):
        print("Creating the project's isolated Python environment (.venv)...")
        subprocess.run([sys.executable, "-m", "venv", venv_dir], cwd=HERE, check=True)
    result = subprocess.run([python, os.path.join(HERE, "setup.py"), *sys.argv[1:]], cwd=HERE)
    raise SystemExit(result.returncode)


def banner(text):
    print()
    print("=" * 70)
    print(text)
    print("=" * 70)


def ask_yes_no(question, default_yes=True):
    suffix = " [Y/n] " if default_yes else " [y/N] "
    answer = input(question + suffix).strip().lower()
    if answer == "":
        return default_yes
    return answer.startswith("y")


def step_check_python():
    banner("STEP 1 of 5 -- Checking your Python version")
    version = sys.version_info
    print(f"Found Python {version.major}.{version.minor}.{version.micro}")
    if (version.major, version.minor) < (3, 11):
        print()
        print("WARNING: This project needs Python 3.11 or newer.")
        print("Download the latest version from https://www.python.org/downloads/")
        print("then run this script again.")
        sys.exit(1)
    print("OK -- Python version is fine.")


def step_install_dependencies():
    banner("STEP 2 of 5 -- Installing dependencies")
    print("This downloads the Python packages AlphaMaxxin needs to run.")
    print("It can take a few minutes the first time -- that's normal.\n")
    backend_reqs = os.path.join(HERE, "backend", "requirements-backend.txt")
    for path in (REQUIREMENTS_PATH, backend_reqs):
        if not os.path.isfile(path):
            print(f"Required file not found: {path}. Download the complete repository.")
            raise SystemExit(1)
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", path],
                       cwd=HERE, check=True)
    print("\nOK -- core dependencies installed inside .venv.")
    print("Broker SDKs are optional. Install only the sources you intend to use.")
    for label, package in BROKER_PACKAGES:
        if ask_yes_no(f"Install the optional {label} broker SDK?", default_yes=False):
            subprocess.run([sys.executable, "-m", "pip", "install", package],
                           cwd=HERE, check=True)


def _load_existing_env() -> dict:
    existing = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
    return existing


def step_configure_env():
    banner("STEP 3 of 5 -- Setting up your API keys")
    print("AlphaMaxxin uses a few outside services for AI analysis and live news.")
    print("Every key below is FREE to sign up for, and every one is OPTIONAL --")
    print("the app will run without any of them, just with fewer features.")
    print()
    print("Choose one supported AI provider: Claude, Gemini, OpenAI, or a local")
    print("OpenAI-compatible endpoint. New model defaults follow configured keys;")
    print("saved per-role choices stay unchanged and can be edited in Settings.")
    print()
    print("Your keys are saved only to a local '.env' file on this computer --")
    print("they are never uploaded anywhere by this script.")
    print()
    print("(Note: the key will be visible as you type it. That's normal --")
    print("you're the only one who can see this window.)")

    existing = _load_existing_env()
    if existing:
        print(f"\nFound an existing .env with {len(existing)} key(s) already saved.")
        if not ask_yes_no("Walk through the key setup again anyway?", default_yes=False):
            return

    new_values = dict(existing)
    for env_var, label, url, required, explanation in API_KEYS:
        print()
        print(f"--- {label} ({'required' if required else 'optional'}) ---")
        print(explanation)
        print(f"Get a free key here: {url}")
        current = existing.get(env_var, "")
        if current:
            print("(Already set -- press Enter to keep it, or paste a new key to replace it)")
        prompt = f"Paste your {label} key and press Enter (or just Enter to skip): "
        value = input(prompt).strip()
        if value:
            new_values[env_var] = value
        elif current:
            new_values[env_var] = current  # keep existing, didn't type a new one

    new_values.setdefault("MOOMOO_HOST", "127.0.0.1")
    new_values.setdefault("MOOMOO_PORT", "11111")
    lines = [f"{k}={v}" for k, v in new_values.items()]
    lines.append("")
    lines.append("# Moomoo has no API key -- auth happens by logging into the OpenD")
    lines.append("# gateway app with your moomoo account. Port 11111 is OpenD's default.")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    got_any_llm = bool(new_values.get("ANTHROPIC_API_KEY") or new_values.get("GEMINI_API_KEY")
                      or new_values.get("OPENAI_API_KEY") or new_values.get("LOCAL_LLM_BASE_URL"))
    print()
    if got_any_llm:
        print("OK -- saved to .env. An AI provider is configured; check model IDs")
        print("and provider access in Settings before running a report.")
    else:
        print("Saved to .env without an AI provider. The app and deterministic")
        print("analysis can run; model-generated commentary needs a configured")
        print("provider. Re-run setup to add keys, or configure a local endpoint.")


def step_moomoo_note():
    banner("STEP 4 of 5 -- About live trading data (moomoo) -- optional")
    print("AlphaMaxxin can pull LIVE stock prices, your real positions, and order")
    print("book depth from moomoo, a brokerage. This is entirely optional:")
    print()
    print("  - Without it: prices come from Yahoo Finance instead. Everything else")
    print("    in the app works normally.")
    print("  - With it: you need the separate 'OpenD' gateway app installed and")
    print("    running, logged into your own moomoo account. Get it from")
    print("    https://www.moomoo.com/download/OpenAPI")
    print()
    try:
        import moomoo  # noqa: F401
        print("OK -- the optional moomoo-api Python package is installed.")
    except ImportError:
        print("(Optional moomoo-api SDK not installed; choose it in Step 2 if needed.)")
    print("You don't need to do anything else right now -- set this up later if")
    print("you decide you want it.")


def step_frontend_build():
    """Install from the lockfile and stop setup if installation/build fails."""
    frontend = os.path.join(HERE, "frontend")
    if not os.path.isdir(frontend):
        print("frontend/ is missing. Download the complete repository.")
        raise SystemExit(1)
    if not ask_yes_no("Build the web interface now? (needs Node.js and internet)", default_yes=True):
        print("Web interface build skipped. The API can run; build the UI before using the browser app.")
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        subprocess.run([npm, "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print()
        print("NOTE: Node.js/npm not found, so the web UI can't be built yet.")
        print("Install Node.js from https://nodejs.org, then run:")
        print("    cd frontend && npm ci && npm run build")
        print("(The backend API works without it; the browser UI needs it.)")
        raise SystemExit(1)
    print()
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)


def step_portfolio_check():
    banner("STEP 5 of 5 -- Your portfolio file")
    if os.path.exists(PORTFOLIO_PATH):
        print(f"OK -- found {PORTFOLIO_PATH}")
        print("This is the file the app reads your holdings from. Edit it directly,")
        print("or use the in-app Portfolio Editor tab once the app is running.")
        return
    print("No Portfolio.md found -- creating a starter template you can edit.")
    starter = (
        "# Investment Portfolio\n\n"
        "> Add your real holdings here, or use the in-app Portfolio Editor.\n\n"
        "---\n\n"
        "## US Equities & ETFs (USD)\n\n"
        "| Company | Ticker | Quantity | Current Price | Cost Price | Market Value | Total P/L |\n"
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |\n"
        "| **Example Inc** | EX | 1 | 0.00 | 0.00 | 0.00 | 0.00 |\n"
        "| **Total (USD)** | | | | | **0.00** | **0.00** |\n"
    )
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        f.write(starter)
    print(f"OK -- created {PORTFOLIO_PATH}. Replace the example row with your own holdings.")


def main():
    banner("ALPHAMAXXIN SETUP WIZARD")
    print("This will get the app ready to run on this computer. It takes about")
    print("5 minutes, mostly waiting for downloads. You can stop anytime with Ctrl+C")
    print("and re-run this script later to pick up where you left off.")

    step_check_python()
    ensure_project_environment()
    step_install_dependencies()
    step_configure_env()
    step_moomoo_note()
    step_portfolio_check()
    step_frontend_build()

    banner("SETUP COMPLETE")
    print("To launch the app later, run:")
    print("    start.bat  (Windows) or ./start.sh  (Mac/Linux)")
    print(f'    "{sys.executable}" run.py  (project .venv interpreter)')
    print("from inside this folder (opens in your browser).")
    print()
    if ask_yes_no("Launch AlphaMaxxin right now?", default_yes=True):
        subprocess.run([sys.executable, os.path.join(HERE, "run.py")], cwd=HERE, check=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup stopped. Run 'python setup.py' again anytime to continue.")
        sys.exit(0)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"\nSetup stopped: {error}")
        print("Resolve the failed step shown above, then run setup again.")
        sys.exit(1)
