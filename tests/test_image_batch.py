"""작업 A(이미지 Batch) 테스트 — 명세 §7. 네트워크 없음(fake provider/DB).

- key 매핑: build_batch_key 결정론, 요청→응답 라운드트립.
- 페이로드 해시: 동일 컷 목록 → 동일 해시(중복 제출 방지 근거), 프롬프트 변경 → 해시 변경.
- 결과 파싱: fetch_batch_results 가 문서상 모호한 응답 구조에서도 key→이미지/에러를 뽑아낸다.
- 오케스트레이션: 캐시된 컷은 Batch 대상에서 제외, 중복 제출 방지, 폴링 → 캐시 적재 + 원장(batch 단가).
"""

from __future__ import annotations

import base64

from engine import assemble, config, image_batch
from engine.providers import image as image_provider


def _cut(cut_no=1, **kw):
    base = {"cut_no": cut_no, "visual_prompt": "a cat", "effects": [],
            "scene_kind": "comic_panel"}
    base.update(kw)
    return base


def test_build_batch_key_deterministic():
    assert image_provider.build_batch_key("dir1", 3) == "dir1__cut3"
    assert image_provider.build_batch_key("dir1", 3) == image_provider.build_batch_key("dir1", 3)
    assert image_provider.build_batch_key("dir1", 3) != image_provider.build_batch_key("dir1", 4)


def test_build_batch_requests_maps_key_to_prompt():
    header = {"version_type": "image_sequence", "global_style": "clean"}
    cuts = [_cut(1, visual_prompt="a robot"), _cut(2, visual_prompt="a tree")]
    reqs = image_provider.build_batch_requests("dir1", cuts, header)
    assert reqs[0]["metadata"]["key"] == "dir1__cut1"
    assert "a robot" in reqs[0]["request"]["contents"][0]["parts"][0]["text"]
    assert reqs[1]["metadata"]["key"] == "dir1__cut2"


def test_batch_payload_hash_deterministic_and_sensitive_to_prompt():
    header = {"version_type": "image_sequence", "global_style": "clean"}
    reqs_a = image_provider.build_batch_requests("dir1", [_cut(1, visual_prompt="a cat")], header)
    reqs_a2 = image_provider.build_batch_requests("dir1", [_cut(1, visual_prompt="a cat")], header)
    reqs_b = image_provider.build_batch_requests("dir1", [_cut(1, visual_prompt="a dog")], header)
    assert image_provider.batch_payload_hash(reqs_a) == image_provider.batch_payload_hash(reqs_a2)
    assert image_provider.batch_payload_hash(reqs_a) != image_provider.batch_payload_hash(reqs_b)


def test_fetch_batch_results_parses_success_and_error():
    img_b64 = base64.b64encode(b"\x89PNG-fake").decode()
    poll_response = {"done": True, "state": "SUCCEEDED", "raw": {
        "response": {"dest": {"inlinedResponses": [
            {"metadata": {"key": "dir1__cut1"},
             "response": {"candidates": [{"content": {"parts": [
                 {"inlineData": {"data": img_b64}}]}}]}},
            {"metadata": {"key": "dir1__cut2"}, "error": {"message": "safety filter"}},
        ]}}
    }}
    out = image_provider.fetch_batch_results(poll_response)
    assert out["dir1__cut1"] == (img_b64, None)
    assert out["dir1__cut2"][0] is None and "safety" in out["dir1__cut2"][1]


def test_fetch_batch_results_alt_nesting_batch_dest():
    # 문서상 모호한 두 번째 후보 경로(response.batch.dest)도 파싱돼야 함.
    img_b64 = base64.b64encode(b"\x89PNG-fake2").decode()
    poll_response = {"done": True, "state": "SUCCEEDED", "raw": {
        "response": {"batch": {"dest": {"inlined_responses": [
            {"metadata": {"key": "dir1__cut1"},
             "response": {"candidates": [{"content": {"parts": [
                 {"inline_data": {"data": img_b64}}]}}]}},
        ]}}}
    }}
    out = image_provider.fetch_batch_results(poll_response)
    assert out["dir1__cut1"] == (img_b64, None)


def test_fetch_batch_results_raises_on_operation_error():
    import pytest
    poll_response = {"done": True, "raw": {"error": {"message": "quota exceeded"}}}
    with pytest.raises(RuntimeError):
        image_provider.fetch_batch_results(poll_response)


# ── 오케스트레이션 (fake DB/provider) ────────────────────────────
def test_submit_skips_cached_cuts(monkeypatch):
    header = {"version_type": "image_sequence", "global_style": "clean"}
    cuts = [_cut(1), _cut(2)]
    directive = {"id": "dir1", "header": header, "cuts": cuts}
    monkeypatch.setattr(image_batch.db, "get_directive", lambda did: directive)

    cached_hash = assemble.content_hash(cuts[0], header)
    monkeypatch.setattr(image_batch.db, "get_render_asset",
                        lambda did, cut_no, t: {"content_hash": cached_hash} if cut_no == 1 else None)
    monkeypatch.setattr(image_batch.db, "find_active_batch_job", lambda did, h: None)

    captured = {}

    def fake_submit(requests, display_name, model):
        captured["requests"] = requests
        captured["model"] = model
        return "batches/abc123"

    monkeypatch.setattr(image_batch.image_provider, "submit_batch", fake_submit)
    monkeypatch.setattr(image_batch.db, "insert_image_batch_job", lambda row: "job1")

    job_names = image_batch.submit_for_directive("dir1")
    job_name = job_names[0] if job_names else None
    assert job_name == "batches/abc123"
    # 컷 1은 이미 캐시(READY) → Batch 대상에서 제외, 컷 2만 제출.
    assert len(captured["requests"]) == 1
    assert captured["requests"][0]["metadata"]["key"] == "dir1__cut2"


def test_submit_returns_none_when_all_cached(monkeypatch):
    header = {"version_type": "image_sequence"}
    cuts = [_cut(1)]
    directive = {"id": "dir1", "header": header, "cuts": cuts}
    monkeypatch.setattr(image_batch.db, "get_directive", lambda did: directive)
    cached_hash = assemble.content_hash(cuts[0], header)
    monkeypatch.setattr(image_batch.db, "get_render_asset",
                        lambda did, cut_no, t: {"content_hash": cached_hash})
    assert image_batch.submit_for_directive("dir1") == []


def test_submit_dedup_reuses_existing_job(monkeypatch):
    header = {"version_type": "image_sequence"}
    cuts = [_cut(1)]
    directive = {"id": "dir1", "header": header, "cuts": cuts}
    monkeypatch.setattr(image_batch.db, "get_directive", lambda did: directive)
    monkeypatch.setattr(image_batch.db, "get_render_asset", lambda *a, **kw: None)
    monkeypatch.setattr(image_batch.db, "find_active_batch_job",
                        lambda did, h: {"provider_job_id": "batches/existing"})

    called = {"submit": False}
    monkeypatch.setattr(image_batch.image_provider, "submit_batch",
                        lambda *a, **kw: called.__setitem__("submit", True) or "batches/new")

    job_names = image_batch.submit_for_directive("dir1")
    job_name = job_names[0] if job_names else None
    assert job_name == "batches/existing"
    assert called["submit"] is False  # 중복 제출 안 함(§7.3)


# ── 자동 제출 게이트(submit_for_approved) ────────────────────────
def test_submit_for_approved_noop_when_mode_realtime(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GENERATION_MODE", "realtime")
    monkeypatch.setattr(config, "IMAGE_PROVIDER", "gemini")
    called = {"listed": False}
    monkeypatch.setattr(image_batch.db, "list_recent_approved_directives",
                        lambda limit: called.__setitem__("listed", True) or [])
    assert image_batch.submit_for_approved() == 0
    assert called["listed"] is False  # 게이트에서 즉시 반환 — DB 조회조차 안 함


def test_submit_for_approved_noop_when_provider_not_gemini(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GENERATION_MODE", "batch")
    monkeypatch.setattr(config, "IMAGE_PROVIDER", "placeholder")
    assert image_batch.submit_for_approved() == 0


def test_submit_for_approved_submits_when_gated_on(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GENERATION_MODE", "batch")
    monkeypatch.setattr(config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(image_batch.db, "list_recent_approved_directives",
                        lambda limit: [{"id": "dir1"}, {"id": "dir2"}])
    submitted = []
    monkeypatch.setattr(image_batch, "submit_for_directive",
                        lambda did: submitted.append(did) or f"batches/{did}")
    n = image_batch.submit_for_approved()
    assert n == 2 and submitted == ["dir1", "dir2"]


def test_submit_for_approved_one_failure_does_not_block_others(monkeypatch):
    monkeypatch.setattr(config, "IMAGE_GENERATION_MODE", "batch")
    monkeypatch.setattr(config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(image_batch.db, "list_recent_approved_directives",
                        lambda limit: [{"id": "dir1"}, {"id": "dir2"}])

    def fake_submit(did):
        if did == "dir1":
            raise RuntimeError("boom")
        return "batches/dir2"

    monkeypatch.setattr(image_batch, "submit_for_directive", fake_submit)
    assert image_batch.submit_for_approved() == 1  # dir1 실패해도 dir2 는 제출됨


def test_poll_once_ingests_and_records_batch_pricing(tmp_path, monkeypatch):
    header = {"version_type": "image_sequence"}
    cut = _cut(1, visual_prompt="a lab")
    directive = {"id": "dir1", "header": header, "cuts": [cut]}
    key = image_provider.build_batch_key("dir1", 1)
    img_b64 = base64.b64encode(b"\x89PNG-batch").decode()

    monkeypatch.setattr(image_batch.db, "claim_pending_batch_jobs",
                        lambda limit: [{"id": "job1", "directive_id": "dir1",
                                       "provider_job_id": "batches/abc"}])
    monkeypatch.setattr(image_batch.image_provider, "poll_batch",
                        lambda name: {"done": True, "state": "SUCCEEDED", "raw": {
                            "response": {"dest": {"inlinedResponses": [
                                {"metadata": {"key": key},
                                 "response": {"candidates": [{"content": {"parts": [
                                     {"inlineData": {"data": img_b64}}]}}]}}]}}}})
    monkeypatch.setattr(image_batch.db, "get_directive", lambda did: directive)

    uploaded = {}
    monkeypatch.setattr(image_batch.db, "upload_render",
                        lambda path, dest, ct: uploaded.setdefault("dest", dest) or "https://fake/x.png")
    cached_rows = []
    monkeypatch.setattr(image_batch.db, "upsert_render_asset", lambda row: cached_rows.append(row))
    ledger = []
    monkeypatch.setattr(image_batch.cost_ledger, "record", lambda a: ledger.append(a))
    job_updates = []
    monkeypatch.setattr(image_batch.db, "update_image_batch_job",
                        lambda job_id, **kw: job_updates.append((job_id, kw)))

    n = image_batch.poll_once()
    assert n == 1
    assert len(cached_rows) == 1 and cached_rows[0]["cut_no"] == 1
    assert len(ledger) == 1
    assert ledger[0]["generation_mode"] == "batch"
    assert ledger[0]["unit_type"] == "image_batch"
    # Batch 단가(표준의 50%) — config.PRICING 스냅샷 그대로.
    assert ledger[0]["actual_cost_usd"] == f"{config.PRICING[config.IMAGE_MODEL]['image_batch']:.6f}"
    assert job_updates[-1][1]["status"] == "succeeded"


def test_poll_once_not_done_yet_leaves_job_running(monkeypatch):
    monkeypatch.setattr(image_batch.db, "claim_pending_batch_jobs",
                        lambda limit: [{"id": "job1", "directive_id": "dir1",
                                       "provider_job_id": "batches/abc"}])
    monkeypatch.setattr(image_batch.image_provider, "poll_batch",
                        lambda name: {"done": False, "state": "RUNNING", "raw": {}})
    job_updates = []
    monkeypatch.setattr(image_batch.db, "update_image_batch_job",
                        lambda job_id, **kw: job_updates.append((job_id, kw)))
    image_batch.poll_once()
    assert job_updates == [("job1", {"status": "running"})]
