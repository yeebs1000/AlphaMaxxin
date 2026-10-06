"""Launch AlphaMaxxin: FastAPI backend + browser UI.

    python run.py            # start backend on 127.0.0.1:8000, open browser
    python run.py --check    # boot the app offline and exit (CI/setup smoke test)
"""
import os
import subprocess
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8000"


def main():
    project_python = os.path.join(HERE, ".venv", "Scripts" if os.name == "nt" else "bin",
                                 "python.exe" if os.name == "nt" else "python")
    if os.path.isfile(project_python) and os.path.normcase(os.path.abspath(sys.prefix)) != \
            os.path.normcase(os.path.join(HERE, ".venv")):
        raise SystemExit(subprocess.call([project_python, __file__, *sys.argv[1:]]))
    if "--check" in sys.argv:
        os.environ["ALPHAMAXXIN_OFFLINE"] = "1"
        sys.path.insert(0, HERE)
        from fastapi.testclient import TestClient
        from backend.app.main import create_app
        response = TestClient(create_app(), base_url=URL).get("/api/status")
        assert response.status_code == 200, response.text
        print("OK -- app boots offline, /api/status responds.")
        return

    dist = os.path.join(HERE, "frontend", "dist")
    if not os.path.isdir(dist):
        print("NOTE: frontend/dist not found -- the web UI hasn't been built.")
        print("Run:  cd frontend && npm ci && npm run build")
        print("The API will still start at " + URL + "/docs")

    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    result = subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=os.path.join(HERE, "backend"),
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
