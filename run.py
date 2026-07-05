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
    if "--check" in sys.argv:
        os.environ["ALPHAMAXXIN_OFFLINE"] = "1"
        sys.path.insert(0, HERE)
        from fastapi.testclient import TestClient
        from backend.app.main import create_app
        response = TestClient(create_app()).get("/api/status")
        assert response.status_code == 200, response.text
        print("OK -- app boots offline, /api/status responds.")
        return

    dist = os.path.join(HERE, "frontend", "dist")
    if not os.path.isdir(dist):
        print("NOTE: frontend/dist not found -- the web UI hasn't been built.")
        print("Run:  cd frontend && npm install && npm run build")
        print("The API will still start at " + URL + "/docs")

    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=os.path.join(HERE, "backend"),
    )


if __name__ == "__main__":
    main()
