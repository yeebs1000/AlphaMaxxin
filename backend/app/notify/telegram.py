"""Telegram push — one function, sends a plain-text message via the Bot API.
Credentials come from env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID). Used only by
the digest (a real send), never in tests — tests pass a fake sender.
httpx is already a project dependency, so no new package.

Forum-group topic routing: pass topic="portfolio" / "opportunist" / etc and
it maps to TELEGRAM_TOPIC_<LABEL> (a Telegram message_thread_id, see
discover_topics() below). No env var set for that label → falls back to the
group's General topic, so this works before you've configured any topics.

    python -m app.notify.telegram   # prints chat_id + thread_id per topic
                                     # seen recently — send one message in
                                     # each topic first, then run this.
"""
import os

import httpx

_API = "https://api.telegram.org/bot{token}/{method}"
_MAX = 4096  # Telegram's hard per-message limit


def _topic_thread_id(topic: str | None) -> str | None:
    if not topic:
        return None
    return os.environ.get(f"TELEGRAM_TOPIC_{topic.upper()}")


def send_message(text: str, token: str | None = None, chat_id: str | None = None,
                 timeout: float = 15.0, topic: str | None = None) -> dict:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    payload = {"chat_id": chat_id, "text": text[:_MAX],
              "disable_web_page_preview": True}
    thread_id = _topic_thread_id(topic)
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    resp = httpx.post(_API.format(token=token, method="sendMessage"),
                      json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def discover_topics(token: str | None = None) -> list[dict]:
    """Dump recent updates as {chat_id, thread_id, preview} — run once after
    posting a message in each topic to read off its thread id for .env."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    resp = httpx.get(_API.format(token=token, method="getUpdates"), timeout=15.0)
    resp.raise_for_status()
    seen = []
    for update in resp.json().get("result", []):
        msg = update.get("message") or {}
        if "chat" not in msg:
            continue
        seen.append({
            "chat_id": msg["chat"]["id"],
            "thread_id": msg.get("message_thread_id"),
            "preview": (msg.get("text")
                       or msg.get("forum_topic_created", {}).get("name")
                       or "")[:60],
        })
    return seen


if __name__ == "__main__":
    from ..config import load_env
    load_env()
    for row in discover_topics():
        print(f"chat_id={row['chat_id']} thread_id={row['thread_id']} "
              f"— {row['preview']!r}")
