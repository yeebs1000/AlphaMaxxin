"""Telegram push — one function, sends a plain-text message via the Bot API.
Credentials come from env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID). Used only by
the digest (a real send), never in tests — tests pass a fake sender.
httpx is already a project dependency, so no new package."""
import os

import httpx

_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX = 4096  # Telegram's hard per-message limit


def send_message(text: str, token: str | None = None, chat_id: str | None = None,
                 timeout: float = 15.0) -> dict:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    resp = httpx.post(_API.format(token=token),
                      json={"chat_id": chat_id, "text": text[:_MAX],
                            "disable_web_page_preview": True},
                      timeout=timeout)
    resp.raise_for_status()
    return resp.json()
