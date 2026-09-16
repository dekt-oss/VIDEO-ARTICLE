"""초안 뒤 지시서를 **같은 실행에서** 잇는다 (0046 · 설계안_초안지시서_통합발주_v2 §3).

운영자 지시(2026-09-11): "초안 생성이랑 작업지시서를 하나로 합쳐 초안 생성에서 바로 스타일을
고를 수 있게." 초안 요청이 `version_types` 를 실으면 워커가 초안을 저장한 뒤 그 버전들의
지시서를 이어서 만든다.

이 테스트가 고정하는 계약:
  ① 미허용 버전은 걸러진다 — 워커까지 가면 VERSION_GUIDANCE 가 기본 버전으로 조용히 갈아치운다.
  ② 지시서 실패는 초안을 실패로 만들지 않는다 — 초안 요청은 done, 지시서 행만 error.
  ③ 플래그를 끄면 version_types 를 무시한다(옛 동선).
  ④ 리포트 라인도 같은 계약이고, 재검사(recheck)에서는 잇지 않는다.

LLM·DB 는 전부 스텁이다.
"""

from __future__ import annotations

import pytest

from engine import config, db, draft, report_db, report_draft


# ─────────────────────────────────────────────────────────────
# ① 버전 거르기
# ─────────────────────────────────────────────────────────────
def test_requested_versions_filters_and_dedupes():
    assert draft.requested_versions({"version_types": ["photo", "bogus", "photo", "comic"]}) == [
        "photo", "comic"]
    assert draft.requested_versions({"version_types": "photo"}) == ["photo"]   # 문자열 하나도
    assert draft.requested_versions({"version_types": None}) == []
    assert draft.requested_versions({}) == []


def test_flag_off_ignores_versions(monkeypatch):
    monkeypatch.setattr(config, "DRAFT_CHAINS_DIRECTIVE", False)
    assert draft.requested_versions({"version_types": ["photo"]}) == []
    assert report_draft.requested_versions({"version_types": ["photo"]}) == []


# ─────────────────────────────────────────────────────────────
# ② 연쇄 — 논문 라인
# ─────────────────────────────────────────────────────────────
class _Log:
    def __init__(self):
        self.draft_done: list[tuple[str, str]] = []
        self.dir_inserted: list[tuple[str, str]] = []
        self.dir_updated: list[tuple[str, str, str | None]] = []
        self.generated: list[tuple[str, str]] = []


def _wire_paper(monkeypatch, fail_versions: set[str] = frozenset()) -> _Log:
    log = _Log()
    monkeypatch.setattr(db, "claim_draft_requests", lambda limit=5: [
        {"id": "req-1", "paper_id": "paper-1", "version_types": ["photo", "comic"]}])
    monkeypatch.setattr(db, "update_draft_request",
                        lambda rid, status, error=None: log.draft_done.append((rid, status)))
    monkeypatch.setattr(draft, "process_paper", lambda pid: {"paper_id": pid})

    def _insert(pid, v):
        log.dir_inserted.append((pid, v))
        return f"dreq-{v}"
    monkeypatch.setattr(db, "insert_directive_request", _insert)
    monkeypatch.setattr(db, "update_directive_request",
                        lambda rid, status, error=None: log.dir_updated.append((rid, status, error)))

    from engine import directive as directive_mod

    def _gen(pid, v):
        log.generated.append((pid, v))
        if v in fail_versions:
            raise RuntimeError(f"{v} 지시서 실패")
        return {"version_type": v}
    monkeypatch.setattr(directive_mod, "process_paper", _gen)
    return log


def test_poll_once_chains_every_requested_version(monkeypatch):
    log = _wire_paper(monkeypatch)
    assert draft.poll_once() == 1
    assert log.generated == [("paper-1", "photo"), ("paper-1", "comic")]
    assert log.dir_inserted == [("paper-1", "photo"), ("paper-1", "comic")]
    assert [(r, s) for r, s, _ in log.dir_updated] == [("dreq-photo", "done"), ("dreq-comic", "done")]
    assert log.draft_done == [("req-1", "done")]


def test_directive_failure_does_not_fail_the_draft(monkeypatch):
    """★ 초안은 이미 저장됐다. 지시서 하나가 죽어도 초안 요청은 done 이고, 죽은 버전의
    요청 행만 error 로 남아 ⑤ 에서 다시 누를 수 있다."""
    log = _wire_paper(monkeypatch, fail_versions={"photo"})
    draft.poll_once()
    assert log.draft_done == [("req-1", "done")]
    updated = {r: (s, e) for r, s, e in log.dir_updated}
    assert updated["dreq-photo"][0] == "error" and "photo 지시서 실패" in (updated["dreq-photo"][1] or "")
    assert updated["dreq-comic"] == ("done", None)
    assert log.generated == [("paper-1", "photo"), ("paper-1", "comic")]   # 뒤 버전은 계속 만든다


def test_no_versions_means_old_behaviour(monkeypatch):
    log = _wire_paper(monkeypatch)
    monkeypatch.setattr(db, "claim_draft_requests", lambda limit=5: [{"id": "req-2", "paper_id": "paper-2"}])
    draft.poll_once()
    assert log.generated == [] and log.dir_inserted == []
    assert log.draft_done == [("req-2", "done")]


# ─────────────────────────────────────────────────────────────
# ④ 리포트 라인 — 같은 계약, 재검사에서는 잇지 않는다
# ─────────────────────────────────────────────────────────────
def _wire_report(monkeypatch, mode: str) -> _Log:
    log = _Log()
    monkeypatch.setattr(report_db, "claim_report_draft_requests", lambda limit=5: [
        {"id": "rreq-1", "report_id": "rep-1", "mode": mode, "instruction": "",
         "version_types": ["comic"]}])
    monkeypatch.setattr(report_db, "update_report_draft_request",
                        lambda rid, status, error=None: log.draft_done.append((rid, status)))
    monkeypatch.setattr(report_draft, "process_report", lambda rid, instruction="": {"report_id": rid})
    monkeypatch.setattr(report_draft, "recheck_compliance", lambda rid: {"blocked": False})

    def _insert(rid, v):
        log.dir_inserted.append((rid, v))
        return f"rdreq-{v}"
    monkeypatch.setattr(report_db, "insert_report_directive_request", _insert)
    monkeypatch.setattr(report_db, "update_report_directive_request",
                        lambda rid, status, error=None: log.dir_updated.append((rid, status, error)))

    from engine import report_directive
    monkeypatch.setattr(report_directive, "process_report",
                        lambda rid, v: log.generated.append((rid, v)) or {"version_type": v})
    return log


def test_report_draft_chains_directive(monkeypatch):
    log = _wire_report(monkeypatch, mode="draft")
    assert report_draft.poll_once() == 1
    assert log.generated == [("rep-1", "comic")]
    assert log.dir_updated == [("rdreq-comic", "done", None)]
    assert log.draft_done == [("rreq-1", "done")]


def test_report_recheck_never_chains(monkeypatch):
    """운영자가 손으로 고친 대본을 기계가 새 지시서로 덮어쓰면 안 된다."""
    log = _wire_report(monkeypatch, mode="recheck")
    report_draft.poll_once()
    assert log.generated == [] and log.dir_inserted == []
    assert log.draft_done == [("rreq-1", "done")]


@pytest.mark.parametrize("mod", [draft, report_draft])
def test_both_lines_share_the_version_filter(mod):
    """두 공장이 같은 허용 목록을 본다 — 한쪽만 버전을 늘리는 일이 이 저장소에서 반복됐다."""
    assert mod.requested_versions({"version_types": list(config.VIDEO_VERSIONS) + ["x"]}) == list(
        config.VIDEO_VERSIONS)
