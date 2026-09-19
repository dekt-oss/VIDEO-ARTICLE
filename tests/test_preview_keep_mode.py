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
                     "mutations": [{"entity_id": "beam", "operation": "HIGHLIGHT",
                                    "property": "glow", "visible_change": True}]},
                ]},
            ],
        },
        "cuts": [
            {"cut_no": n, "visual_role": "MECHANISM", "motion_source": "video",
             "visual_prompt": f"scene {n}", "estimated_sec": 6,
             "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE"}}
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
