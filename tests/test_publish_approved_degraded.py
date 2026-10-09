"""업로드 워커도 대시보드와 같은 기준 — 완료, 또는 사람 확인(degraded)+승인(2026-10-09). 네트워크 없음."""

from engine.publish import publishable


def test_done_and_approved_degraded_are_publishable():
    assert publishable({"status": "done", "output_url": "u"})
    assert publishable({"status": "degraded", "output_url": "u", "degraded_approved_at": "2026-10-09T00:00:00Z"})


def test_unapproved_degraded_failed_or_missing_file_are_not():
    assert not publishable({"status": "degraded", "output_url": "u"})
    assert not publishable({"status": "failed", "output_url": "u"})
    assert not publishable({"status": "done", "output_url": ""})
    assert not publishable(None)
