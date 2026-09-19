"""지시서 단계 중복 문장 제거 + stage 영상 언어 공유 캐시 (2026-09-14 운영자 요청).

① "824개는 새로운 변이입니다"가 영상에서 두 번 나왔다 — 컷 3 끝 문장을 컷 4 가 통째로 되풀이.
   렌더가 끝난 뒤 영상을 잘라서야 고쳤다. 지시서 단계에서 무료로 막는다.
② 영어판을 만들려고 보니 시퀀스 렌더 경로에 캐시가 없어 Veo 클립을 다시 사야 했다(한 편 약 $5.5).
   화면은 언어와 무관하다 — stage 영상 캐시 키에 언어·나레이션을 넣지 않는다.
"""
import copy
import pathlib

from engine import directive as dv
from engine import render

RENDER_SRC = (pathlib.Path(__file__).resolve().parents[1] / "engine" / "render.py").read_text(encoding="utf-8")
DIRECTIVE_SRC = (pathlib.Path(__file__).resolve().parents[1] / "engine" / "directive.py").read_text(encoding="utf-8")

DUP = "이 중 무려 824개는 이전에 보고되지 않은 새로운 변이입니다."


# ── ① 중복 문장 ─────────────────────────────────────────────
def test_the_real_case_keeps_the_sentence_in_its_dedicated_cut():
    """컷 4 는 그 문장 전용(표지 강조·숫자 카드) → 컷 3 에서 뺀다."""
    cuts = [{"cut_no": 3, "narration_ko": "114만 명의 게놈을 분석해 1,260개를 식별했습니다. " + DUP},
            {"cut_no": 4, "narration_ko": DUP}]
    touched = dv._drop_repeated_narration(cuts)
    assert touched == ["3>4"]
    assert cuts[0]["narration_ko"] == "114만 명의 게놈을 분석해 1,260개를 식별했습니다."
    assert cuts[1]["narration_ko"] == DUP


def test_when_both_have_other_content_the_later_repeat_goes():
    cuts = [{"cut_no": 1, "narration_ko": "첫 문장입니다. " + DUP},
            {"cut_no": 2, "narration_ko": DUP + " 그 뒤 이야기입니다."}]
    dv._drop_repeated_narration(cuts)
    assert DUP in cuts[0]["narration_ko"]
    assert cuts[1]["narration_ko"] == "그 뒤 이야기입니다."


def test_it_never_leaves_a_silent_cut():
    cuts = [{"cut_no": 1, "narration_ko": DUP}, {"cut_no": 2, "narration_ko": DUP}]
    assert dv._drop_repeated_narration(cuts) == []
    assert cuts[0]["narration_ko"] == DUP and cuts[1]["narration_ko"] == DUP


def test_english_is_checked_on_its_own():
    en = "Of these, 824 were new variants never reported before."
    cuts = [{"cut_no": 3, "narration_ko": "가", "narration_en": "They found 1,260 variants. " + en},
            {"cut_no": 4, "narration_ko": "나", "narration_en": en}]
    assert dv._drop_repeated_narration(cuts) == ["3>4(en)"]
    assert cuts[0]["narration_en"] == "They found 1,260 variants."


def test_short_fragments_and_non_adjacent_cuts_are_left_alone():
    cuts = [{"cut_no": 1, "narration_ko": "네. 시작합니다."},
            {"cut_no": 2, "narration_ko": "네. 다음입니다."},
            {"cut_no": 3, "narration_ko": DUP + " 그리고요."},
            {"cut_no": 4, "narration_ko": "중간 문장입니다."},
            {"cut_no": 5, "narration_ko": DUP + " 마지막."}]
    assert dv._drop_repeated_narration(cuts) == []


def test_the_directive_calls_it_and_reports_it():
    assert "_drop_repeated_narration(cuts)" in DIRECTIVE_SRC
    assert "narration_repeat_removed:" in DIRECTIVE_SRC


# ── ② stage 영상 캐시 ────────────────────────────────────────
def _stage():
    cuts = [{"cut_no": 1, "visual_prompt": "a DNA model", "motion_prompt": "slow push",
             "narration_ko": "한국어", "narration_en": "English",
             "temporal_plan": [{"t0": 0, "t1": 4, "camera": "TRACK", "mutation": "", "entity_id": ""}]},
            {"cut_no": 2, "visual_prompt": "a brain model", "motion_prompt": "orbit",
             "narration_ko": "둘째", "narration_en": "second", "temporal_plan": []}]
    plan = {"stage_id": "S1", "indexes": [0, 1], "clips": [8.0, 4.0], "total_sec": 11.0}
    header = {"version_type": "photo", "global_style": "matte"}
    return plan, cuts, header


def test_stage_hash_ignores_language_narration_and_clip_split():
    plan, cuts, header = _stage()
    base = render.stage_video_hash(plan, cuts, header)
    c2 = copy.deepcopy(cuts)
    c2[0]["narration_ko"] = "완전히 다른 한국어 나레이션"
    c2[1]["narration_en"] = "A totally different English narration"
    p2 = dict(plan, clips=[6.0, 6.0], total_sec=12.4)
    assert render.stage_video_hash(p2, c2, header) == base, "언어·길이가 키에 들어가면 EN 이 영상을 다시 산다"


def test_stage_hash_changes_when_the_picture_changes():
    plan, cuts, header = _stage()
    base = render.stage_video_hash(plan, cuts, header)
    c2 = copy.deepcopy(cuts)
    c2[1]["visual_prompt"] = "a different scene"
    assert render.stage_video_hash(plan, c2, header) != base


def test_the_renderer_checks_the_cache_before_buying_and_stores_after():
    i_cache = RENDER_SRC.index("sv, c2 = _cached_stage_video(plan, cuts, header, work_dir, gi,")
    i_build = RENDER_SRC.index("sv, c2 = _build_stage_video(")
    i_store = RENDER_SRC.index("_store_stage_video(sv, plan, cuts, header, directive_id,")
    assert i_cache < i_build < i_store
