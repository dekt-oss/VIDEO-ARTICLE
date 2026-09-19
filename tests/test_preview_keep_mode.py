"""`--keep` — 한 번 사서 최종본에 그대로 쓰는 모드 (scripts/preview_sequence.py, 2026-09-19).

무엇이 문제였나: 미리보기는 컷 번호를 1..N 으로 **다시 매긴다**. 그래서 (지시서, 컷번호)로
잡는 에셋 캐시를 쓸 수 없었고(본 지시서의 다른 컷과 키가 겹친다), 일부러 캐시를 껐다.
대가는 **돌릴 때마다 다시 사는 것**이다 — 실제로 계획의 3배를 쓴 적이 있다.

`--keep` 은 번호를 그대로 둔다. 그러면 여기서 만든 그림이 나중에 편 전체를 렌더할 때
**그대로 들어간다**. 그 약속이 성립하려면 캐시 키 세 조각이 본 렌더와 **똑같아야** 한다:
`(directive_id, cut_no)` · `content_hash` · `reference_key`. 하나라도 어긋나면 돈을 두 번
내고도 "캐시를 켰는데 왜 또 사지"가 된다 — 조용히 깨지는 종류라 여기서 못박는다.
"""

from __future__ import annotations

import copy
import pathlib

import pytest

from engine import assemble, sequence_render
from scripts.preview_sequence import slice_keep
from scripts.mini_render import slice_directive

SRC = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "preview_sequence.py"
       ).read_text(encoding="utf-8")


_STAGE_OF = {5: "SEQ_A_S1_setup", 6: "SEQ_A_S2_change", 7: "SEQ_A_S2_change"}


def _directive() -> dict:
    """컷 5·6·7 을 쓰는 시퀀스 하나. S2 는 S1 을 이어받는다(참조 키가 생긴다)."""
    return {
        "version_type": "photo",
        "header": {
            "version_type": "photo",
            "global_style": "matte CG",
            "visual_sequences": [
                {"sequence_id": "SEQ_A", "sequence_role": "MECHANISM_SEQUENCE", "stages": [
                    {"stage_id": "SEQ_A_S1_setup", "continuity_mode": "NEW_WORLD",
                     "cut_refs": [5]},
                    {"stage_id": "SEQ_A_S2_change", "continuity_mode": "MUTATE_STATE",
                     "continuity_from": "SEQ_A_S1_setup", "cut_refs": [6, 7],
                     "camera_operation": "HOLD",
                     # GROW 는 **의미 변화**다 — 전·후 분할 스틸의 조건이다
                     #   (HIGHLIGHT 같은 강조는 조건이 아니다, visual_sequence.stage_changes_state).
                     "mutations": [{"entity_id": "beam", "operation": "GROW",
                                    "property": "width", "visible_change": True}]},
                ]},
            ],
        },
        "cuts": [
            {"cut_no": n, "visual_role": "MECHANISM", "motion_source": "video",
             "visual_prompt": f"scene {n}", "estimated_sec": 6,
             # ★ stage 묶음은 **컷의 `stage_ref`** 로 정해진다(stage_render.stage_of) —
             #   header 의 cut_refs 가 아니다. 둘 다 있어야 렌더가 실제로 도는 모습이 된다.
             "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE",
                                      "stage_ref": _STAGE_OF[n]}}
            for n in (5, 6, 7)
        ],
    }


# ── ① 번호를 지킨다 = 캐시 키의 절반 ───────────────────────────────
def test_keep_mode_does_not_renumber_the_cuts():
    mini = slice_keep(_directive(), "SEQ_A", 4, want_video=True)
    assert [c["cut_no"] for c in mini["cuts"]] == [5, 6, 7]


def test_the_old_slicer_does_renumber_which_is_why_it_could_not_cache():
    """옛 모드를 나무라는 것이 아니라 **왜 캐시를 껐는지**를 기록해 둔다 —
    이 사실을 잊고 옛 모드에 캐시를 켜면 본 렌더가 엉뚱한 그림을 물려받는다."""
    mini = slice_directive(_directive(), "SEQ_A", 4, want_video=True)
    assert [c["cut_no"] for c in mini["cuts"]] != [5, 6, 7]


def test_keep_mode_renders_every_cut_of_the_stage_not_just_one():
    """최종본에 들어갈 컷을 사는 것이므로 stage 가 맡은 컷을 전부 만든다
    (옛 모드는 연속성만 재면 됐으므로 stage 당 하나로 줄였다)."""
    mini = slice_keep(_directive(), "SEQ_A", 4, want_video=True)
    assert {c["cut_no"] for c in mini["cuts"]} == {5, 6, 7}
    assert len(slice_directive(_directive(), "SEQ_A", 4, want_video=True)["cuts"]) == 2


# ── ② 캐시 키가 본 렌더와 같다 ─────────────────────────────────────
def _decide(directive: dict, cut_no: int) -> dict:
    header = directive["header"]
    cut = next(c for c in directive["cuts"] if int(c["cut_no"]) == cut_no)
    return sequence_render.reference_decision(
        cut, header, {"SEQ_A_S1_setup": "/tmp/s1.png"}, generation_mode="realtime")


def test_the_reference_key_matches_what_the_full_render_will_compute():
    """★★ 이것이 `--keep` 의 전부다. `reference_key` 가 어긋나면 `content_hash` 가 달라지고
    본 렌더가 캐시를 **못 맞힌다** — 돈을 두 번 낸다.

    ★ 그래서 slice_keep 은 `visual_sequence.normalize_all` 을 **태우지 않는다**.
      `sequence_render.stage_index` 가 지시서의 날것 stage 를 읽기 때문이다 — 정규화가
      `state_after_computed` 같은 필드를 붙이면 키가 달라진다.
    """
    full = _directive()
    mini = slice_keep(copy.deepcopy(full), "SEQ_A", 4, want_video=True)
    for no in (6, 7):
        a, b = _decide(full, no), _decide(mini, no)
        assert b["kind"] == a["kind"] == "reference"
        assert b["reference_key"] == a["reference_key"] != ""


def test_the_content_hash_matches_too():
    full = _directive()
    mini = slice_keep(copy.deepcopy(full), "SEQ_A", 4, want_video=True)
    for no in (5, 6, 7):
        cf = next(c for c in full["cuts"] if c["cut_no"] == no)
        cm = next(c for c in mini["cuts"] if c["cut_no"] == no)
        key = _decide(full, no)["reference_key"]
        assert (assemble.content_hash(cm, mini["header"], reference_key=key)
                == assemble.content_hash(cf, full["header"], reference_key=key))


def test_a_missing_sequence_fails_loudly():
    with pytest.raises(SystemExit):
        slice_keep(_directive(), "SEQ_NOPE", 4, want_video=True)


# ── ③ 가짜 그림이 캐시에 앉지 않는다 ───────────────────────────────
def test_keep_refuses_to_run_with_free_or_reuse():
    """캐시는 "이 그림이 이 컷의 정본"이라는 선언이다. placeholder 회색 판이나 다른
    지시서에서 빌려 온 그림을 그 자리에 앉히면 **아무도 모르게** 최종본에 들어간다."""
    assert "if args.keep and (args.free or args.reuse):" in SRC
    assert "raise SystemExit" in SRC.split("if args.keep and (args.free or args.reuse):")[1][:400]


def test_the_cache_switch_is_the_directive_id_and_only_keep_passes_it():
    """`render._gen_still` 의 캐시 스위치는 `bool(directive_id)` 하나다 — 옛 모드가
    실수로 이것을 넘기면 renumber 된 그림이 본 지시서의 캐시를 덮어쓴다."""
    assert "directive_id=(args.directive_id if args.keep else None)" in SRC
    assert "render_job_kind=kind" in SRC


def test_it_tells_the_operator_which_factory_and_whether_it_will_be_kept():
    """리포트 지시서를 논문 표에 쓰면 FK 위반이다 — 어느 공장인지 도구가 알고 말해야 한다."""
    assert 'kind = "report"' in SRC and 'kind = "paper"' in SRC
    assert '"factory": kind, "cached": bool(args.keep)' in SRC


# ── ④ 비용을 사실대로 말한다 ───────────────────────────────────────
def test_the_estimate_counts_stage_videos_not_cut_videos():
    """★ 옛 셈(`mini_render.estimate`)은 **컷 단위**였다 — `motion_source == "video"` 인
    컷마다 Veo 하나. 실사형 렌더는 **stage 단위**라 둘이 어긋난다:
      · stage 는 `motion_source` 를 읽지 않는다 — 스틸 컷만 있는 stage 도 영상을 산다
      · 전·후 분할 스틸로 나가는 stage 는 영상을 **아예 안 산다**
    실측(리포트 SEQ_R01)에서 두 오차가 서로 반대라 총액이 우연히 비슷했다. 그래서 더 위험하다.
    """
    from decimal import Decimal

    from engine import config, stage_render
    from scripts.preview_sequence import estimate_plan
    from scripts.mini_render import estimate

    d = _directive()
    # 컷5(=S1, NEW_WORLD)는 still 로 둔다 — 컷 단위 셈은 여기서 영상을 0으로 센다.
    d["cuts"][0]["motion_source"] = "still"
    mini = slice_keep(d, "SEQ_A", 4, want_video=True)
    assert stage_render.enabled(mini["header"]), "이 픽스처는 stage 모드여야 의미가 있다"

    total, lines = estimate_plan(mini)
    joined = "\n".join(lines)
    # S1 은 스틸 컷만 있는데도 stage 영상을 산다 — 컷 단위 셈은 이것을 놓친다.
    assert "SEQ_A_S1_setup 영상 $0.3" in joined, joined
    # S2 는 MUTATE_STATE + 의미 변화 + 이어받기 → 전·후 분할 스틸이라 영상을 안 산다.
    assert joined.count("영상 $0  (전·후 분할 스틸") == 2, joined
    # 그림 3장 + S1 영상 한 편. 컷 단위 셈은 이 구성을 못 만든다.
    assert total == Decimal("0.402000") + Decimal("0.300000"), total
    assert total != estimate(slice_directive(_directive(), "SEQ_A", 4, want_video=True))


def test_the_estimate_is_itemised_so_the_operator_sees_what_is_being_bought():
    """총액 하나만 찍으면 '왜 이 값이지'를 물을 수 없다 — 이 도구는 발주 직전에 읽힌다."""
    from scripts.preview_sequence import estimate_plan

    _, lines = estimate_plan(slice_keep(_directive(), "SEQ_A", 4, want_video=True))
    assert sum(1 for ln in lines if "그림 $" in ln) == 3, "컷마다 그림 한 줄"
    assert any("영상 $" in ln for ln in lines)
    assert all(ln.startswith("  ") for ln in lines)


# ── ⑤ 화면 테두리도 공장을 따라간다 ────────────────────────────────
def test_the_preview_uses_the_right_series_title_and_disclaimer():
    """★ 2026-09-19 실측: 증권 리포트 미리보기 세 컷에 **"하루 논문 한 편"** 이 떠 있었고
    리포트가 반드시 달아야 하는 **면책 자막이 없었다**. 미리보기의 존재 이유는 "최종본이
    이렇게 나온다"를 보여 주는 것이라, 테두리가 다르면 그 자리에서 거짓말을 한다."""
    from engine import config
    from scripts.preview_sequence import frame_text

    title, footer = frame_text("report", {"broker": "유진투자증권"}, "ko")
    assert title == config.REPORT_SERIES_TITLE
    assert "하루 논문" not in title
    assert "유진투자증권" in footer and config.REPORT_DISCLAIMER_TEXT in footer

    title, footer = frame_text("paper", {}, "ko")
    assert title == config.SERIES_TITLE
    assert footer == "", "논문 라인에는 면책 바가 없다(종전 그대로)"


def test_the_disclaimer_comes_from_the_render_worker_not_a_second_copy():
    """문구를 여기에 다시 적으면 본 렌더와 미리보기가 **다른 면책**을 달게 된다."""
    assert "report_render._disclaimer_footer(" in SRC


# ── ⑥ 나레이션 길이는 글자 수로 센다(모델이 적은 숫자가 아니라) ────
def test_narration_seconds_come_from_the_text_not_the_model_guess():
    """★★ 2026-09-19 첫 실물 렌더 실측. 컷2 는 `estimated_sec=5` 라고 적혀 있었는데 실제
    나레이션은 **6.8초**였다. 그 1.8초가 Veo 티어를 6초→8초로 밀어, 도구가 **$0.702 라고
    말해 놓고 $0.802 를 썼다.** 글자 수 추정은 6.2초로 같은 티어를 골랐다.

    "기계가 확실히 아는 것은 기계가 적는다" — 글자 수는 확실하고, 모델의 초 단위 추정은 아니다.
    """
    from engine import config
    from scripts.preview_sequence import narration_sec

    cut = {"estimated_sec": 5,
           "narration_ko": "유진투자증권에 따르면, 이 우주 인터넷이 기존 전파 방식의 한계에 부딪히고 있습니다."}
    sec = narration_sec(cut, "ko")
    assert sec == len(cut["narration_ko"]) / config.STORY_SPEAK_CHARS_PER_SEC
    assert sec > 5, "모델이 적은 5초보다 길다 — 이 차이가 티어를 밀었다"
    # 실측된 6.8초와 같은 Veo 티어를 골라야 한다(그것이 이 함수의 존재 이유다).
    from engine import stage_render
    assert stage_render.plan_clips(sec) == stage_render.plan_clips(6.8)


def test_it_falls_back_to_estimated_sec_only_when_there_is_no_narration():
    from scripts.preview_sequence import narration_sec

    assert narration_sec({"estimated_sec": 7}, "ko") == 7.0
    assert narration_sec({}, "ko") == 0.0


def test_the_estimate_no_longer_reads_estimated_sec_for_stage_videos():
    """stage 영상 길이에 `estimated_sec` 이 다시 들어오면 같은 과소평가가 재발한다."""
    body = SRC.split("def estimate_plan")[1].split("def frame_text")[0]
    assert "narration_sec(c," in body
    assert 'durs = [float(c.get("estimated_sec")' not in body
