"""실사형: 스틸 복사 재사용 금지 + 연구 대상 화면 상한 + TTS +20% (운영자 지시 2026-09-05).

실측(세마글루타이드 렌더 c43d87a4):
  · 14컷 중 8컷이 reuse_* → 렌더가 그 컷의 visual_prompt 를 **생성기에 보내지도 않고**
    앞 컷 스틸을 복사했다. 컷2~4 같은 두 쥐 20초, 컷8~12 같은 구체 32초,
    컷14 '빈 복도' 지시가 컷13 쥐 우리로 나갔다.
  · 쥐가 86초 중 42초(49%).
운영자: "동일한 그림은 통일성 전략이지, 사진 띄워놓고 나레이션 읽으라고 한 적 없다."
통일성은 참조 조건 생성이 맡는다(살아 있다). 죽인 것은 같은 파일을 두 번 트는 경로다.
"""

from __future__ import annotations

import inspect

from engine import config, directive, render
from engine import photo_contract as pc


def _cut(no, prompt, sec=5, **kw):
    return {"cut_no": no, "narration_ko": "말", "narration_en": "t", "visual_role": "REALITY",
            "visual_prompt": prompt, "motion_prompt": "move", "estimated_sec": sec, **kw}


# ── 재사용 금지 ─────────────────────────────────────────────
def test_photo_normalizer_turns_every_reuse_strategy_into_new_asset():
    obj = {"header": {"version_type": "photo", "hook_ko": "훅"},
           "cuts": [_cut(1, "a", asset_strategy="new_asset"),
                    _cut(2, "b", asset_strategy="reuse_with_state_change", base_asset_ref="1"),
                    _cut(3, "c", asset_strategy="reuse_crop", base_asset_ref="2")]}
    out = directive.normalize_directive(obj, "photo")
    assert [c["asset_strategy"] for c in out["cuts"]] == ["new_asset"] * 3


def test_other_versions_keep_reuse():
    """만화식 등은 계약이 다르다 — 실사형만 바꾼다."""
    obj = {"header": {"version_type": "comic"},
           "cuts": [_cut(1, "a"), _cut(2, "b", asset_strategy="reuse_crop", base_asset_ref="1")]}
    out = directive.normalize_directive(obj, "comic")
    assert out["cuts"][1]["asset_strategy"] == "reuse_crop"


def test_render_never_takes_the_copy_path_for_photo_even_on_old_directives():
    """★ 정규화만 고치면 저장된 옛 지시서가 다시 같은 사진 20초를 만든다."""
    src = inspect.getsource(render._obtain_still)
    assert '!= "photo"' in src and "_reuse_base_image(" in src


def test_the_prompt_tells_the_model_reuse_is_ignored():
    g = directive.VERSION_GUIDANCE["photo"]
    assert "같은 사진을 두 번 틀지 마라" in g and "항상 new_asset" in g


# ── 연구 대상 화면 상한 ───────────────────────────────────────
def _eval(cuts):
    return pc.evaluate({"version_type": "photo", "hook_ko": "훅",
                        "total_estimated_sec": sum(c["estimated_sec"] for c in cuts)}, cuts)


def test_a_mouse_heavy_video_is_flagged():
    """실측 그대로: 절반이 쥐면 경고."""
    cuts = [_cut(i, "two aged mice on a bench") for i in range(1, 8)] +            [_cut(i, "a cell cutaway") for i in range(8, 15)]
    r = _eval(cuts)
    assert r["stats"]["subject_share"] == 0.5
    assert any(w.startswith("photo_subject_dominates") for w in r["warnings"])


def test_a_short_subject_appearance_passes():
    cuts = [_cut(1, "two aged mice", sec=3)] + [_cut(i, "a cell cutaway") for i in range(2, 15)]
    assert not any(w.startswith("photo_subject_dominates") for w in _eval(cuts)["warnings"])


def test_the_share_is_weighted_by_cut_length_not_cut_count():
    """쥐 컷 1개가 40초면 그게 화면을 먹는 것이다 — 개수로 세면 놓친다."""
    cuts = [_cut(1, "a mouse", sec=40)] + [_cut(i, "a cell", sec=2) for i in range(2, 12)]
    assert any(w.startswith("photo_subject_dominates") for w in _eval(cuts)["warnings"])


def test_subject_regex_actually_matches():
    """★ 히어독이 \b 를 백스페이스로 바꿔 게이트가 0.0 을 냈다(2026-09-05). 다시는 안 되게."""
    import re
    assert chr(8) not in inspect.getsource(pc), "소스에 백스페이스 문자가 있다"
    cuts = [_cut(1, "Two aged mice side by side", sec=10), _cut(2, "a pen", sec=10)]
    assert _eval(cuts)["stats"]["subject_share"] == 0.5


# ── TTS ─────────────────────────────────────────────────────
def test_tts_rate_is_what_the_operator_last_asked_for():
    """9/3 +5% → 9/5 +20%(운영자) → 9/12 +10%(운영자: "나레이션을 좀 자연스럽게").

    값 자체가 아니라 **운영자가 마지막에 말한 값인지**를 지킨다.
    """
    assert config.EDGE_TTS_RATE == "+10%"
