"""Reports completing together remain separately readable."""
import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.reports import store


def test_reports_completed_in_same_second_have_distinct_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "datetime", SimpleNamespace(datetime=SimpleNamespace(
        now=lambda: datetime.datetime(2026, 10, 6, 12, 0))))
    first = store.save_report({"preset": "Lite", "target_label": "A", "sections": {}}, str(tmp_path))
    second = store.save_report({"preset": "Lite", "target_label": "B", "sections": {}}, str(tmp_path))
    assert first != second
    assert store.load_report(first, str(tmp_path))["target_label"] == "A"
    assert store.load_report(second, str(tmp_path))["target_label"] == "B"
    assert {entry["id"] for entry in store.list_reports(str(tmp_path))} == {first, second}


def test_save_and_delete_cannot_restore_a_deleted_report_to_the_index(tmp_path, monkeypatch):
    original_id = store.save_report({"preset": "Lite", "sections": {}}, str(tmp_path))
    original_list = store.list_reports
    captured, release, deleted = threading.Event(), threading.Event(), threading.Event()

    def pause_after_save_reads_index(*args, **kwargs):
        rows = original_list(*args, **kwargs)
        if threading.current_thread().name.startswith("save"):
            captured.set()
            assert release.wait(5)
        return rows

    def delete():
        try:
            return store.delete_report(original_id, str(tmp_path))
        finally:
            deleted.set()

    monkeypatch.setattr(store, "list_reports", pause_after_save_reads_index)
    with ThreadPoolExecutor(1, thread_name_prefix="save") as saver, ThreadPoolExecutor(1) as deleter:
        saving = saver.submit(store.save_report, {"preset": "Lite", "sections": {}}, str(tmp_path))
        try:
            assert captured.wait(5)
            deleting = deleter.submit(delete)
            deleted.wait(1)  # unlocked deletion finishes while save holds a stale index
        finally:
            release.set()
        new_id = saving.result(timeout=5)
        assert deleting.result(timeout=5) is True
    assert {e["id"] for e in original_list(str(tmp_path))} == {new_id}
    assert store.load_report(original_id, str(tmp_path)) is None


def test_failed_atomic_index_write_preserves_previous_index(tmp_path, monkeypatch):
    store.save_report({"preset": "Lite", "sections": {}}, str(tmp_path))
    path = tmp_path / "index.json"
    original = path.read_bytes()

    def fail_replace(*args):
        raise OSError("index replacement failed")

    monkeypatch.setattr(store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="index replacement failed"):
        store._index_add(str(tmp_path), {"id": "next"})
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["index.json"]


@pytest.mark.parametrize("contents", ['[{"id":"old"}', '{"id":"old"}', '[{}]'])
def test_corrupt_index_cannot_be_replaced_or_deleted(tmp_path, contents):
    rid = store.save_report({"preset": "Lite", "sections": {}}, str(tmp_path))
    index = tmp_path / "index.json"
    index.write_text(contents)
    for operation in (lambda: store._index_add(str(tmp_path), {"id": "new"}),
                      lambda: store.delete_report(rid, str(tmp_path))):
        with pytest.raises(ValueError, match="index"):
            operation()
        assert index.read_text() == contents
        assert store.load_report(rid, str(tmp_path)) is not None
