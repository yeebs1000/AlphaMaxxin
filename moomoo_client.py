# Legacy shim - the real module lives in backend/app/brokers/ (single copy for v1 GUI and v2 backend).
from backend.app.brokers.moomoo_client import *  # noqa: F401,F403
