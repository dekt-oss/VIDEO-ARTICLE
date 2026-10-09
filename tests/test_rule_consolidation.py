"""규칙 통합 2·3단계 — 실사형 프롬프트는 한 자리, 코드가 정할 칸은 코드가 (2026-09-28).

운영자 결정: "규칙 통합하고 정리. 뼈대 묶고 코드 정리한 다음 개선 방향은 다시 고민."
실측 근거: docs/규칙통합_분석_2026-09-28.md — 규칙 글 29~32k자(★150), 컷 41칸 중 엔진 소비자 0인 칸 다수,
지시서 한 장 경고 중앙값 56.

★ 이 파일이 지키는 것:
  ① 규칙 글이 다시 불어나지 않는다(길이·★ 예산).
  ② 코드가 정하는 칸을 모델에게 다시 묻지 않는다(스키마에 없다).
  ③ 두 공장이 같은 계약을 쓴다.
  ④ 영상/스틸·scene_kind 는 코드가 정하고 그 결정이 기록에 남는다.
"""

from __future__ import annotations

import inspect

from engine import config, directive as dv, photo_contract as pc, photo_prompt as pp, report_directive as rd

# ── ① 예산 ─────────────────────────────────────────────────────
RULES_MAX_CHARS = 18_500     # 통합 직후 15.8k / 16.1k(스키마 6k 포함). 종전 29.5k / 32.0k.
#   2026-10-08 +500: 운영자 지시 화면 규칙(세포 눈높이·카메라만 금지·stage 묶기·사건형 첫 컷)을 줄일 만큼 줄여 넣은 몫.
RULES_MAX_STARS = 20         # 종전 137 / 165. ★ 는 강조가 아니라 "예외"의 표시여야 한다.


def _rules(factory: str) -> str:
    return pp.system_prompt(factory) + pp.guidance(factory)


def test_the_photo_rules_stay_inside_the_budget():
    for f in ("paper", "report"):
        text = _rules(f)
        assert len(text) <= RULES_MAX_CHARS, (f, len(text))
        assert text.count("★") <= RULES_MAX_STARS, (f, text.count("★"))


def test_each_topic_lives_in_exactly_one_section():
    """같은 뜻이 여러 절에 흩어지면 규칙이 서로 부딪친다 — 절 제목은 한 번씩만."""
    g = pp.guidance("report")
    for title in ("[첫 3초", "[컷]", "[세계 — 시퀀스]", "[화면 구성", "[도해 — MECHANISM", "[화면 그래픽 금지",
                  "[움직임]", "[카드 — overlay_plan]", "[리포트의 원리", "[출력 스키마]"):
        # 절 제목은 줄 머리에만 — 본문이 다른 절을 가리키는 것("[화면 그래픽 금지]가 정한다")은 정의가 아니다.
        assert g.count(chr(10) + title) == 1, (title, g.count(chr(10) + title))
    assert "[리포트의 원리" not in pp.guidance("paper")


# ── ② 코드가 정하는 칸은 묻지 않는다 ─────────────────────────────
DEAD_CUT_FIELDS = ("crop", "tone_grade", "asset_strategy", "base_asset_ref", "visual_reuse_group", "state_change",
                   "style_anchor_ref", "novelty_event", "render_notes", "motion_value", "bgm_cue", "transition",
                   "loop_safe", "effects", "scene_kind", "motion_source", "visual_type")
DEAD_HEADER_FIELDS = ("hook_type", "hook_reframe_angle", "hook_promise_check", "science_reliability", "cta_type",
                      "loop_match", "retention_plan", "series_id", "global_style", "aspect_ratio", "cta_ko")


def test_the_photo_schema_does_not_ask_for_fields_the_code_decides():
    for f in ("paper", "report"):
        schema = pp.output_schema(f)
        for field in DEAD_CUT_FIELDS + DEAD_HEADER_FIELDS:
            assert f'"{field}"' not in schema, (f, field)
    # 살아 있는 칸은 그대로 묻는다.
    for field in ("narration_ko", "answers_ko", "staging_ko", "visual_prompt", "mechanism", "overlay_plan",
                  "temporal_plan", "motion_prompt", "visual_role", "beat", "evidence_role", "source_facts"):
        assert f'"{field}"' in pp.output_schema("paper"), field
    assert '"claim_ids"' in pp.output_schema("paper") and '"reasoning_id"' in pp.output_schema("report")


def test_normalize_still_fills_the_dropped_fields_with_defaults():
    """스키마에서 뺐다고 저장 모양이 바뀌면 렌더·화면이 깨진다 — 정규화가 기본값으로 채운다."""
    obj = {"header": {"hook_ko": "a", "hook_en": "b", "total_estimated_sec": 20},
           "cuts": [{"cut_no": 1, "narration_ko": "질문?", "narration_en": "q", "estimated_sec": 3,
                     "visual_prompt": "x", "visual_role": "REALITY"}]}
    d = dv.normalize_directive(obj, "photo", cut_max_sec=8)
    cut = d["cuts"][0]
    for field in ("crop", "tone_grade", "asset_strategy", "effects", "transition", "loop_safe", "motion_source",
                  "scene_kind", "novelty_event", "render_notes"):
        assert field in cut, field
    assert cut["asset_strategy"] == "new_asset" and cut["transition"] == config.DEFAULT_TRANSITION
    # 안 묻는 헤더 칸은 backfilled 로 남아 판정되지 않는다.
    assert "hook_promise_check" in d["header"]["backfilled_fields"]
    assert not any(w.startswith(("hook_promise_unpaid", "bold_hook_on_weak_evidence", "no_novelty_event"))
                   for w in d["header"]["mode_warnings"]), d["header"]["mode_warnings"]


# ── ③ 두 공장이 같은 계약 ────────────────────────────────────────
def test_both_factories_share_the_contract_and_only_the_factory_block_differs():
    paper, report = pp.guidance("paper"), pp.guidance("report")
    for block in (pp.HOOK_CUT_RULE, pp.CUT_RULES, pp.WORLD_RULES, pp.STAGING_CONTRACT, pp.MECHANISM_RULES,
                  pp.SCREEN_GRAPHIC_BAN_GUIDANCE, pp.MOTION_RULES, pp.SEQUENCE_SCHEMA):
        assert block in paper and block in report
    assert pp.REPORT_MECHANISM_RULES in report and pp.REPORT_MECHANISM_RULES not in paper
    assert dv.VERSION_GUIDANCE["photo"] == paper and rd.PHOTO_CONTRACT == report
    # 옛 이름은 재수출이다 — 리포트 라인·테스트가 이 이름으로 부른다.
    assert dv.STAGING_CONTRACT is pp.STAGING_CONTRACT and dv.SEQUENCE_SCHEMA is pp.SEQUENCE_SCHEMA


def test_the_photo_system_prompt_is_the_consolidated_one_in_both_generators():
    assert "DIRECTIVE_SYSTEM_PHOTO if version_type == \"photo\" else DIRECTIVE_SYSTEM_BASE" in inspect.getsource(dv)
    assert "REPORT_DIRECTIVE_SYSTEM_PHOTO if version_type == \"photo\" else REPORT_DIRECTIVE_SYSTEM" in inspect.getsource(rd)
    assert "컴플라이언스 금지" in rd.REPORT_DIRECTIVE_SYSTEM_PHOTO and "OO증권에 따르면" in rd.REPORT_DIRECTIVE_SYSTEM_PHOTO
    assert config.EVIDENCE_RULES_SHARED in dv.DIRECTIVE_SYSTEM_PHOTO
    # 만화식·나열식은 종전 프롬프트 그대로다(회귀 없음).
    assert "[버전=만화식 comic]" in dv.VERSION_GUIDANCE["comic"]


# ── ④ 코드가 정한다: scene_kind · 영상/스틸 ──────────────────────
def test_scene_kind_comes_from_the_role():
    assert pc.scene_kind_for_role("MECHANISM") == "motion_graphic"
    assert pc.scene_kind_for_role("REALITY") == "broll_stock"
    assert pc.scene_kind_for_role("") == "broll_stock"


def _cuts(roles: str):
    return [{"cut_no": i + 1, "visual_role": "MECHANISM" if ch == "M" else "REALITY"} for i, ch in enumerate(roles)]


def test_video_goes_to_mechanism_cuts_first_then_hook_and_ending():
    cuts = _cuts("RRMMMRRR")
    got = pc.assign_motion_sources(cuts)
    assert got == [1, 3, 4, 5, 8]
    assert [c["motion_source"] for c in cuts] == ["video", "still", "video", "video", "video", "still", "still", "video"]


def test_video_never_exceeds_the_cap_and_mechanism_wins_over_the_ending(monkeypatch):
    monkeypatch.setattr(config, "PHOTO_VIDEO_CUTS_MAX", 4)
    cuts = _cuts("RMMMMMR")
    got = pc.assign_motion_sources(cuts)
    assert len(got) == 4 and got == [2, 3, 4, 5]        # 도해 컷이 상한을 다 쓰면 훅·마무리는 스틸


def test_the_router_verdict_counts_as_mechanism_even_without_the_label():
    cuts = [{"cut_no": 1}, {"cut_no": 2, "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE"}}, {"cut_no": 3}]
    assert pc.assign_motion_sources(cuts) == [1, 2, 3]


def test_labelled_mechanism_cuts_beat_world_cuts_for_the_video_budget(monkeypatch):
    """★ 첫 실측(발뒤꿈치 편, 2026-09-28): 라우터가 컷 1~14 를 전부 '이어지는 세계'로 보자 실사 컷 1~5 가 영상
    8개를 다 써 버리고 정작 도해 컷 10·11·14·15 가 스틸이 됐다. 도해가 먼저, 훅·마무리 다음, 세계 컷은 남을 때만."""
    monkeypatch.setattr(config, "PHOTO_VIDEO_CUTS_MAX", 8)
    roles = "RRRRRRRMMMMRRMMRR"
    cuts = [{"cut_no": i + 1, "visual_role": "MECHANISM" if ch == "M" else "REALITY",
             "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE" if i < 15 else "REALITY"}}
            for i, ch in enumerate(roles)]
    got = pc.assign_motion_sources(cuts)
    assert got == [1, 8, 9, 10, 11, 14, 15, 17]       # 도해 6 + 훅 + 마무리 = 8. 세계 컷 2~7 은 남는 자리가 없다


def test_the_floor_is_filled_with_neighbours_so_the_i2v_chain_stays_joined(monkeypatch):
    monkeypatch.setattr(config, "PHOTO_VIDEO_CUTS_MIN", 4)
    cuts = _cuts("RRRRRR")                                # 도해 없음 → 훅·마무리 둘뿐 → 이웃으로 채운다
    got = pc.assign_motion_sources(cuts)
    assert len(got) == 4 and 1 in got and 6 in got
    assert got == [1, 2, 3, 6]                            # 낮은 번호의 이웃부터 — 훅 쪽 연쇄가 길어진다


def test_the_decision_is_recorded_in_the_header_not_silent():
    obj = {"header": {"hook_ko": "a", "hook_en": "b"},
           "cuts": [{"cut_no": i, "narration_ko": f"문장{i}", "narration_en": "s", "estimated_sec": 4,
                     "visual_prompt": "p", "visual_role": "MECHANISM" if i in (2, 3) else "REALITY"}
                    for i in range(1, 6)]}
    d = dv.normalize_directive(obj, "photo", cut_max_sec=8)
    by_code = d["header"]["visual_routing"]["video_cuts_by_code"]
    assert by_code == [1, 2, 3, 5]
    assert [c["motion_source"] for c in d["cuts"]] == ["video", "video", "video", "still", "video"]
    assert [c["scene_kind"] for c in d["cuts"]] == ["broll_stock", "motion_graphic", "motion_graphic", "broll_stock", "broll_stock"]
