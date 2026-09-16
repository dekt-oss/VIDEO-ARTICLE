"""작업 B(영상 정책·이중 캡) 통합 테스트 — 명세 §8.5 DoD.

- image_only 씬 영상 호출 0.
- 초수·금액 이중 캡을 통과해야만 Veo 를 호출한다(Preflight, directive 정규화 시점).
- Veo 가 "생성됐으나(과금) 산출물을 못 쓴" 경우(VeoBilledRejection) 스틸로 폴백하되 실효 비용은
  원장에 남는다(미채택 영상 비용도 실효비용에 포함).
"""

from __future__ import annotations

import engine.render as render
from engine.providers.video import VeoBilledRejection


def test_veo_billed_rejection_falls_back_but_records_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(render.config, "VIDEO_PROVIDER", "veo")

    ledger: list[dict] = []
    monkeypatch.setattr(render.cost_ledger, "record", lambda attempt: ledger.append(attempt))
    monkeypatch.setattr(render.db, "get_render_asset", lambda *a, **kw: None)

    def fake_generate_clip(cut, header, out_path, duration, lang="ko", start_image=None):
        raise VeoBilledRejection("veo: 다운로드가 mp4 아님(size=10)", clip_sec=render.config.VEO_CLIP_SEC)

    monkeypatch.setattr(render.video_provider, "generate_clip", fake_generate_clip)

    cut = {"cut_no": 1, "visual_prompt": "lab"}
    header = {"version_type": "hybrid", "global_style": "clean"}
    clip_path = str(tmp_path / "cut1.mp4")
    start_image = str(tmp_path / "cut1.png")
    with open(start_image, "wb") as f:
        f.write(b"\x89PNG")

    ok, _key, cost = render._gen_veo_clip(cut, header, clip_path, start_image, directive_id="dir1")

    assert ok is False                                # 스틸로 폴백해야 함
    expected = render.config.VEO_CLIP_SEC * render.config.VEO_COST_PER_SEC_USD
    assert cost == expected                           # 폴백해도 실효 비용은 0 이 아님(§8.5)
    assert len(ledger) == 1
    assert ledger[0]["status"] == "failed"
    assert ledger[0]["error_class"] == "billed_rejection"
    assert float(ledger[0]["actual_cost_usd"]) == expected  # 실패해도 과금분은 원장에 남는다


def test_veo_plain_failure_is_free(tmp_path, monkeypatch):
    # 생성 자체가 안 된 실패(submit/poll 단계)는 여전히 비용 0.
    monkeypatch.setattr(render.config, "VIDEO_PROVIDER", "veo")
    ledger: list[dict] = []
    monkeypatch.setattr(render.cost_ledger, "record", lambda attempt: ledger.append(attempt))
    monkeypatch.setattr(render.db, "get_render_asset", lambda *a, **kw: None)

    def fake_generate_clip(cut, header, out_path, duration, lang="ko", start_image=None):
        raise RuntimeError("veo submit 500")

    monkeypatch.setattr(render.video_provider, "generate_clip", fake_generate_clip)

    cut = {"cut_no": 2, "visual_prompt": "lab"}
    header = {"version_type": "hybrid"}
    ok, _key, cost = render._gen_veo_clip(
        cut, header, str(tmp_path / "c2.mp4"), str(tmp_path / "s2.png"), directive_id="dir1")

    assert ok is False and cost == 0.0
    # ★ 계약이 바뀌었다(v3 §8-4 P3-c): 미과금 실패도 **원장에는 남긴다.**
    #   예전엔 아무것도 안 남겨서 "이 컷은 영상이 아니라 스틸이다"와 Veo 실패율(폴백률 지표)이
    #   로그에만 있었다. 비용이 0 이라는 사실은 그대로다 — 행이 생기되 청구액이 0 이다.
    assert len(ledger) == 1
    row = ledger[0]
    assert row["status"] == "fallback"
    assert row["error_class"] == "RuntimeError"
    assert float(row["billed_units"]) == 0.0
    assert float(row["actual_cost_usd"]) == 0.0     # 미과금 실패는 여전히 공짜다
