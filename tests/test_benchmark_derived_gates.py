"""벤치마크(시화호 편 105초)에서 나온 세 지표의 회귀 잠금 — 2026-09-04.

★ 이 파일의 숫자는 전부 **실측**이다. 지어낸 문턱이 하나도 없다:
    세계 밀도  벤치 0.57/분 · 좋았던 달 클립 지시서 0.86~1.25/분
               화면이 나빴던 성격조합 지시서 3.38~6.12/분  → 문턱 2.0/분
    축척       벤치는 광역(12.7km)에서 손바닥(물 한 컵)까지 3초. 우리 17/18 이 근접 0개
    수치 크기  벤치는 화면 폭 절반 이상. 우리 72px(13%)이고, number_punch 최장 28자였다

★★ 세 지표의 성격이 다르다는 것을 여기 박아 둔다:
   세계 밀도는 **판별력이 있다**(50% 만 걸린다 — 좋은 것은 통과한다).
   기전·축척은 거의 전부 걸린다 → 그래서 차단이 아니라 경고다
   ([[block-only-after-measuring-hit-rate]] 규율).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from engine import config
from engine import photo_contract as pc

DOCS = pathlib.Path("docs")
BAD = "review-2026-08-31/personality_pairing_photo_v6.json"   # 화면이 나빴던 실측 지시서


def _load(rel_or_name: str):
    p = DOCS / rel_or_name
    if not p.exists():
        hits = list(DOCS.rglob(pathlib.Path(rel_or_name).name))
        if not hits:
            pytest.skip(f"실측 지시서 없음: {rel_or_name}")
        p = hits[0]
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["header"], d["cuts"]


# ── 세계 밀도 ────────────────────────────────────────────────
def test_the_metric_separates_our_known_good_from_known_bad():
    """★★ 이 검사가 이 문턱의 존재 이유다 — 좋은 것을 벌하지 않아야 신호다."""
    bad_h, bad_c = _load(BAD)
    good_h, good_c = _load("moon_impactor_realdraft_v4.json")
    bad = pc.worlds_per_minute(bad_h.get("visual_sequences"), bad_h.get("total_estimated_sec"))
    good = pc.worlds_per_minute(good_h.get("visual_sequences"), good_h.get("total_estimated_sec"))
    assert bad > config.PHOTO_MAX_WORLDS_PER_MIN, bad
    assert good <= config.PHOTO_MAX_WORLDS_PER_MIN, good


def test_the_benchmark_itself_would_pass():
    """벤치(1세계 / 105초)가 자기 문턱에 걸리면 문턱이 틀린 것이다."""
    seqs = [{"world": {"world_id": "SIHWA_LAKE"}}]
    assert pc.worlds_per_minute(seqs, 105) <= config.PHOTO_MAX_WORLDS_PER_MIN


def test_the_name_does_not_collide_with_the_other_world_metric():
    """★ visual_sequence_contract 에 world_reset_rate 가 이미 있다(stage 기준, 다른 뜻).
    같은 이름으로 다른 숫자를 말하면 이 저장소가 반복해 겪은 이중 정의 사고가 된다."""
    from engine import visual_sequence_contract as vsc
    assert not hasattr(pc, "world_reset_rate")
    assert "world_reset_rate" in vsc.sequence_metrics([], 0, 0, 0, 0, 0, 0)


def test_a_single_world_video_is_never_flagged():
    assert pc.worlds_per_minute([{"world": {"world_id": "W"}}] * 3, 60) == 1.0


def test_missing_data_is_silent_not_zero_division():
    assert pc.worlds_per_minute([], 60) == 0.0
    assert pc.worlds_per_minute([{"world": {"world_id": "W"}}], 0) == 0.0


# ── 축척 사다리 ──────────────────────────────────────────────
def test_a_single_world_video_is_still_checked_for_scale():
    """★★ 2026-09-04 정정. 종전에는 "세계가 하나면 camera_base 도 하나"라며 검사를 건너뛰었다.
    그런데 프롬프트는 **세계를 하나로 유지하라**고 지시한다 — 두 규칙이 서로를 무력화해서
    근접 검사가 영영 돌지 않았다(실측: 세마글루타이드 지시서가 세계 1개라 통째로 생략).
    벤치마크가 하는 일이 "한 세계 안에서 축척을 바꾸는 것"이므로 검사도 stage 로 내렸다."""
    h = {"version_type": "photo", "hook_ko": "훅", "total_estimated_sec": 60,
         "visual_sequences": [{"world": {"world_id": "W", "camera_base": "top_down"},
                               "stages": [{"stage_id": "S1", "camera_base": "top_down"}]}]}
    cuts = [{"cut_no": i, "estimated_sec": 5, "visual_role": "REALITY",
             "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "설명", "narration_en": "text"} for i in range(1, 13)]
    assert "photo_no_close_scale" in pc.evaluate(h, cuts)["warnings"]


def test_a_close_stage_inside_one_world_satisfies_the_ladder():
    """★ 세계를 하나로 두면서 축척만 바꾸는 것 — 이것이 벤치마크의 문법이다."""
    h = {"version_type": "photo", "hook_ko": "훅", "total_estimated_sec": 60,
         "visual_sequences": [{"world": {"world_id": "W", "camera_base": "top_down"},
                               "stages": [{"stage_id": "S1", "camera_base": "top_down"},
                                          {"stage_id": "S2", "camera_base": "close_detail"}]}]}
    cuts = [{"cut_no": i, "estimated_sec": 5, "visual_role": "REALITY",
             "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "설명", "narration_en": "text"} for i in range(1, 13)]
    assert "photo_no_close_scale" not in pc.evaluate(h, cuts)["warnings"]


def test_a_video_cut_that_never_moves_is_flagged_regardless_of_tier():
    """★ 연출 계약은 invest 만 본다. 강등되면 검사가 빠지는데, **영상을 산 컷은 움직여야 한다.**"""
    h = {"version_type": "photo", "hook_ko": "훅", "total_estimated_sec": 60,
         "visual_sequences": [{"world": {"world_id": "W", "camera_base": "close_detail"}}]}
    cuts = [{"cut_no": i, "estimated_sec": 5, "visual_role": "REALITY",
             "visual_prompt": "a photo", "motion_prompt": "move",
             "narration_ko": "설명", "narration_en": "text"} for i in range(1, 13)]
    cuts[6]["motion_source"] = "video"
    cuts[6]["temporal_plan"] = [{"camera": "HOLD"}, {"camera": "HOLD"}]
    w = pc.evaluate(h, cuts)["warnings"]
    assert any(x.startswith("photo_video_cut_never_moves:7") for x in w), w
    cuts[6]["temporal_plan"] = [{"camera": "HOLD"}, {"camera": "DOLLY_IN"}]
    assert not any(x.startswith("photo_video_cut_never_moves")
                   for x in pc.evaluate(h, cuts)["warnings"])


def test_close_scale_fires_when_several_sequences_all_stay_far():
    h = {"version_type": "photo", "hook_ko": "훅", "total_estimated_sec": 60,
         "visual_sequences": [{"world": {"world_id": "A", "camera_base": "top_down"}},
                              {"world": {"world_id": "A", "camera_base": "eye_level_front"}}]}
    cuts = [{"cut_no": i, "estimated_sec": 5, "visual_role": "REALITY",
             "visual_prompt": "a photo", "motion_prompt": "hold",
             "narration_ko": "설명", "narration_en": "text"} for i in range(1, 13)]
    w = pc.evaluate(h, cuts)["warnings"]
    assert "photo_no_close_scale" in w
    h["visual_sequences"][1]["world"]["camera_base"] = config.PHOTO_CLOSE_CAMERA_BASE
    assert "photo_no_close_scale" not in pc.evaluate(h, cuts)["warnings"]


# ── 수치 펀치 ────────────────────────────────────────────────
def test_a_bare_number_is_one_line_and_a_summary_sentence_is_not():
    """실측한 두 극단을 그대로 박는다."""
    assert pc.overlay_text_lines("254MW") == 1
    assert pc.overlay_text_lines("+16.9%") == 1
    assert pc.overlay_text_lines("AI 데이터센터 ESS 수요 2030년까지 20배↑") > \
        config.OVERLAY_NUMBER_MAX_LINES


def test_the_font_actually_got_bigger():
    """72px 은 1080 폭에서 3자리 숫자가 13% 였다 — 카드였지 펀치가 아니었다."""
    assert config.OVERLAY_NUMBER_FONT_SIZE > config.OVERLAY_FONT_SIZE
    assert config.OVERLAY_NUMBER_FONT_SIZE >= 100


def test_the_width_math_uses_the_same_margin_the_renderer_writes():
    """★ 폭 계산과 ASS 스타일이 다른 마진을 쓰면 줄 수 추정이 조용히 틀린다."""
    from engine import subtitles
    import inspect
    assert "OVERLAY_SIDE_MARGIN_PX" in inspect.getsource(subtitles.build_ass)


# ── 되먹임이 코드 이름이 아니라 처방을 준다 ─────────────────
@pytest.mark.parametrize("code,needle", [
    ("photo_world_churn:3.4/분", "world_id 를"),
    ("photo_no_close_scale", "close_detail"),
    ("photo_number_punch_is_a_sentence:4", "evidence_card"),
    ("photo_narrative_no_mechanism:0<2", "과정을 말하는 컷"),
])
def test_every_new_warning_tells_the_model_how_to_fix_it(code, needle):
    """★ 이 저장소가 겪은 '차단은 하고 고치는 법은 안 줬다'의 재발 방지."""
    out = pc.feedback_prompt(["photo_hook_missing"], [code])
    assert needle in out, out


def test_all_new_codes_are_declared():
    for c in ("photo_world_churn", "photo_no_close_scale",
              "photo_number_punch_is_a_sentence", "photo_narrative_no_mechanism"):
        assert c in pc.WARNING_REASONS


def test_none_of_this_blocks_approval():
    """★★ 새 신호 넷 중 어느 것도 승인을 막지 않는다 — 실측 지시서로 확인.

    ★ 단언을 **이 문서화된 의도에 맞게 좁혔다**(2026-09-07). 종전에는 이 fixture 의
      `block_reasons` 가 통째로 비어 있을 것을 요구했다 — 그러면 이 넷과 무관한 차단 사유를
      새로 넣을 때마다 여기가 깨진다. 실제로 `photo_style_word_in_prompt`(화풍 어휘)를
      넣자 깨졌는데, 그것은 회귀가 아니라 **정상 동작**이다: 이 fixture 는 "화면이 나빴던
      실측 지시서"이고 world 넷이 전부 `background: blurred …`(렌즈 흐림)를 지시한다.
      그 어휘가 코드의 부정어를 이긴 것이 화풍 전환 실측 3회의 기록된 원인이다
      (`docs/핸드오프_화풍전환_2026-09-07.md` §3-②).
      넷이 경고로 남는지를 보는 것이 이 테스트의 일이고, 그 일은 그대로 한다.
    """
    h, c = _load(BAD)
    codes = {r.split(":", 1)[0] for r in pc.evaluate(h, c)["block_reasons"]}
    for c4 in ("photo_world_churn", "photo_no_close_scale",
               "photo_number_punch_is_a_sentence", "photo_narrative_no_mechanism"):
        assert c4 not in codes, f"{c4} 는 경고여야 하는데 승인을 막는다"
