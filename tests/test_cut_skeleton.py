"""결정론적 컷 골격 (2026-08-29 리뷰 §6).

지키는 것: **컷 수와 리듬이 대본 scenes 개수에 종속되지 않는다.** 실측(2026-08-28)에서 대본이
씬 6~7개를 내자 지시서도 8컷이 됐고, 계약이 "40~50초면 10~14컷"이라고 해도 LLM 이 스스로 줄였다.
이제 코드가 문장 경계로 칸을 먼저 만든다.
"""

from __future__ import annotations

from engine import config, cut_skeleton as cs
from engine import directive as dv

SCRIPT = """# 제목

옥시토신을 투여했습니다. 그 결과 신뢰 행동이 15% 늘었습니다.
- 다만 이 효과는 원래 남을 잘 믿지 않는 남성에게서만 확인됐습니다.
정보 제공 목적이며 투자 권유가 아닙니다.
"""


def test_sentences_ignore_markdown_and_disclaimer():
    out = cs.sentences(SCRIPT)
    assert any("옥시토신" in s for s in out)
    assert not any("제목" == s for s in out)
    assert not any("투자 권유" in s for s in out), "면책은 컷이 아니라 하단 자막이다"
    assert all(not s.startswith("-") for s in out), "머리표가 남으면 나레이션이 아니다"


def test_cut_count_comes_from_sentences_not_scene_count():
    """대본 씬이 몇 개든 칸 수는 문장에서 나온다."""
    skeleton = cs.build(SCRIPT)
    assert len(skeleton) == len(cs.sentences(SCRIPT))
    assert [c["cut_no"] for c in skeleton] == list(range(1, len(skeleton) + 1))


def test_long_sentence_is_split_at_a_meaning_boundary():
    long_one = ("다만 이 결과는 원래 남을 잘 믿지 않는 남성에게서만 확인됐고, "
                "다른 집단에는 적용되지 않습니다.")
    parts = cs.build(long_one)
    assert len(parts) >= 2, "긴 문장은 쪼개져야 한다"
    # 글자수로 자르지 않는다 — 경계 뒤 조각이 말이 되는지(쉼표·연결어미)로 자른다.
    assert parts[0]["sentence"].endswith(("고", "며", "지만", "는데")) or "," not in long_one


def test_unsplittable_long_sentence_is_left_alone():
    """자를 곳이 없으면 억지로 자르지 않는다 — 말이 끊기면 나레이션이 망가진다."""
    blob = "가" * 200
    assert len(cs.build(blob)) == 1


def test_estimated_sec_respects_the_floor():
    for c in cs.build(SCRIPT):
        assert c["estimated_sec"] >= config.CUT_MIN_SEC


def test_skeleton_block_is_empty_without_sentences():
    assert cs.skeleton_block([]) == ""
    assert cs.skeleton_block(cs.build("")) == ""


def test_skeleton_block_forbids_merging_cuts():
    block = cs.skeleton_block(cs.build(SCRIPT))
    assert "칸 수를 줄이지 마라" in block
    assert "합치거나 빼지 마라" in block


def test_photo_prompt_carries_the_skeleton():
    prompt = dv.directive_user_prompt({"script_md": SCRIPT, "fact_sheet": {},
                                       "video_prompts": [], "video_flow": {}}, "photo")
    assert "[컷 골격" in prompt


def test_other_versions_do_not_get_the_skeleton():
    """만화식은 컷 리듬 계약이 다르다 — 실사형에만 건다(관련 없는 버전을 건드리지 않는다)."""
    prompt = dv.directive_user_prompt({"script_md": SCRIPT, "fact_sheet": {},
                                       "video_prompts": [], "video_flow": {}}, "comic")
    assert "[컷 골격" not in prompt


# ─────────────────────────────────────────────────────────────
# 2026-08-29 실측: 골격 11칸을 줬는데 모델이 7컷을 냈다
# ─────────────────────────────────────────────────────────────
def test_shortfall_is_flagged_when_model_merges_cuts():
    """지시는 검사되지 않으면 지켜지지 않는다 — 골격 준수를 코드가 센다."""
    skeleton = [{"cut_no": i} for i in range(1, 12)]
    assert cs.shortfall(skeleton, [{}] * 7).startswith("photo_skeleton_shortfall")
    assert cs.shortfall(skeleton, [{}] * 9) == "", "관용 범위 안이면 통과"
    assert cs.shortfall([], [{}] * 3) == "", "골격이 없으면 검사 대상이 아니다"


def test_generate_blocks_when_skeleton_is_not_followed(monkeypatch):
    """모델이 칸을 합치면 승인이 막히고 재생성 사유에 들어간다."""
    from engine import directive as dv

    long_script = " ".join(f"문장 번호 {i} 입니다." for i in range(1, 13))
    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        return {"header": {"hook_ko": "훅", "total_estimated_sec": 40},
                "cuts": [{"cut_no": i, "scene_kind": "comic_panel", "narration_ko": "문장",
                          "narration_en": "s", "estimated_sec": 4, "visual_role": "REALITY",
                          "visual_prompt": "documentary photo of a lab bench",
                          "source_facts": ["what_found[0]"]} for i in range(1, 5)]}

    monkeypatch.setattr(dv, "call_json", fake_call_json)
    out = dv.generate({"script_md": long_script, "fact_sheet": {}, "video_prompts": [],
                       "video_flow": {}}, "photo")
    assert any(r.startswith("photo_skeleton_shortfall") for r in out["header"]["block_reasons"])
    assert out["header"]["approval_blocked"] is True
    assert len(calls) == 2, "위반이면 1회 재생성한다"


def test_prompt_names_the_escape_route_for_undiagrammable_sentences():
    """메타분석 문장에서 모델이 추상 3D 로 도망가던 것을 프롬프트가 이름 붙여 막는다."""
    from engine import directive as dv

    guidance = dv.VERSION_GUIDANCE["photo"]
    assert "도해할 물리적 대상이 없는 문장" in guidance
    assert "추상 3D 로 도망가지 마라" in guidance
    # 게이트가 실제로 거부하는 어휘를 프롬프트가 **이름으로** 알려 준다.
    for word in ("abstract", "data visualization", "floating particles"):
        assert word in guidance, f"금지 어휘가 프롬프트에 명시되지 않았다: {word}"


def test_a_connective_never_becomes_its_own_cut():
    """★ 실측 2026-08-29: "즉, 이 결과는 …" 이 쉼표에서 갈려 **컷 = "즉," (3초)** 가 나왔다.

    접속사 하나로 컷을 만들면 화면이 3초 동안 아무 말도 하지 않는다. 조금 긴 컷이 낫다.
    """
    script = ("즉, 이 결과는 원래 의심이 많은 남성에 한정된 것입니다.\n"
              "하지만 이들에게만큼은 옥시토신이 신뢰를 높인다는 강력한 증거가 확인된 셈입니다.")
    bones = cs.build(script, version_type="photo")
    assert bones
    for b in bones:
        assert len(b["sentence"]) >= config.CUT_SKELETON_MIN_CHARS, b
    assert not any(b["sentence"].strip().rstrip(",") in ("즉", "하지만") for b in bones)
