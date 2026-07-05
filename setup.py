"""
AlphaMaxxin Setup Wizard
========================
Run this once after downloading/cloning the project:

    python setup.py

This script assumes you have never set this project up before and walks
through every step: checking Python, installing dependencies, creating your
personal .env file with API keys, and (optionally) launching the app at the
end. Nothing here is destructive -- it only writes to .env and only after
asking.

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
    if (version.major, version.minor) < (3, 10):
        print()
        print("WARNING: This project needs Python 3.10 or newer.")
        print("Download the latest version from https://www.python.org/downloads/")
        print("then run this script again.")
        sys.exit(1)
    print("OK -- Python version is fine.")


def step_install_dependencies():
    banner("STEP 2 of 5 -- Installing dependencies")
    print("This downloads the Python packages AlphaMaxxin needs to run.")
    print("It can take a few minutes the first time -- that's normal.\n")
    if not os.path.exists(REQUIREMENTS_PATH):
        print("WARNING: requirements.txt not found -- skipping.")
        print("(Did you download the whole repo, not just this file?)")
        return
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_PATH],
        cwd=HERE,
    )
    backend_reqs = os.path.join(HERE, "backend", "requirements-backend.txt")
    if result.returncode == 0 and os.path.exists(backend_reqs):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", backend_reqs],
            cwd=HERE,
        )
    if result.returncode != 0:
        print()
        print("WARNING: Something went wrong installing dependencies (see the error above).")
        print("Common fix: make sure you're connected to the internet, then re-run")
        print("this script. If it keeps failing, copy the error and ask for help.")
        if not ask_yes_no("\nContinue with setup anyway?", default_yes=False):
            sys.exit(1)
    else:
        print("\nOK -- dependencies installed.")


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
    print("Recommended minimum: get ONE of Claude or Gemini so the AI agents")
    print("actually have a brain to run on. Gemini has a free quota, so it's")
    print("the easiest place to start if you've never done this before.")
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

    lines = [f"{k}={v}" for k, v in new_values.items()]
    lines.append("")
    lines.append("# Moomoo has no API key -- auth happens by logging into the OpenD")
    lines.append("# gateway app with your moomoo account. Port 11111 is OpenD's default.")
    lines.append("MOOMOO_HOST=127.0.0.1")
    lines.append("MOOMOO_PORT=11111")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    got_any_llm = bool(new_values.get("ANTHROPIC_API_KEY") or new_values.get("GEMINI_API_KEY")
                        or new_values.get("OPENAI_API_KEY"))
    print()
    if got_any_llm:
        print("OK -- saved to .env. You have at least one LLM key, so the AI agents will work.")
    else:
        print("WARNING: saved to .env, but no LLM key was entered (Claude/Gemini/OpenAI).")
        print("The app will still launch, but clicking 'Run Master Orchestrator' or")
        print("any agent button won't produce a report until you add one. You can")
        print("re-run this script anytime to add keys later.")


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
        print("OK -- the moomoo-api Python package is installed (came with requirements.txt).")
    except ImportError:
        print("(moomoo-api package not found -- should have installed with Step 2.)")
    print("You don't need to do anything else right now -- set this up later if")
    print("you decide you want it.")


def step_frontend_build():
    """Build the web UI if Node.js is around and it hasn't been built yet."""
    dist = os.path.join(HERE, "frontend", "dist")
    frontend = os.path.join(HERE, "frontend")
    if os.path.isdir(dist) or not os.path.isdir(frontend):
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        subprocess.run([npm, "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print()
        print("NOTE: Node.js/npm not found, so the web UI can't be built yet.")
        print("Install Node.js from https://nodejs.org, then run:")
        print("    cd frontend && npm install && npm run build")
        print("(The backend API works without it; the browser UI needs it.)")
        return
    print()
    if ask_yes_no("Build the web interface now? (needs internet, ~1 min)", default_yes=True):
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=frontend)
        subprocess.run([npm, "run", "build"], cwd=frontend)


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
    step_install_dependencies()
    step_configure_env()
    step_moomoo_note()
    step_portfolio_check()
    step_frontend_build()

    banner("SETUP COMPLETE")
    print("To launch the app later, run:")
    print("    python run.py")
    print("from inside this folder (opens in your browser).")
    print()
    if ask_yes_no("Launch AlphaMaxxin right now?", default_yes=True):
        subprocess.run([sys.executable, os.path.join(HERE, "run.py")], cwd=HERE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup stopped. Run 'python setup.py' again anytime to continue.")
        sys.exit(0)
