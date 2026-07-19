"""Telegram: topic->thread_id routing, offline (httpx mocked, no network)."""
from app.notify import telegram


def test_topic_thread_id_lookup(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOPIC_OPPORTUNIST", "42")
    monkeypatch.delenv("TELEGRAM_TOPIC_PORTFOLIO", raising=False)
    assert telegram._topic_thread_id("opportunist") == "42"
    assert telegram._topic_thread_id("portfolio") is None
    assert telegram._topic_thread_id(None) is None


def test_send_message_includes_thread_id_when_mapped(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOPIC_PORTFOLIO", "7")
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResp()

    monkeypatch.setattr(telegram.httpx, "post", fake_post)
    telegram.send_message("hi", token="t", chat_id="-100", topic="portfolio")
    assert captured["message_thread_id"] == 7


def test_send_message_omits_thread_id_without_mapping(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOPIC_SCANNER", raising=False)
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResp()

    monkeypatch.setattr(telegram.httpx, "post", fake_post)
    telegram.send_message("hi", token="t", chat_id="-100", topic="scanner")
    assert "message_thread_id" not in captured
