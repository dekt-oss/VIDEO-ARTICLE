"""대본 한국어 다듬기 — **사실은 코드가 지킨다** (2026-09-10).

운영자 지시: "한국어 구조가 어색한게 없는지 한번더 대본리뷰한 후 생성하는 절차를 넣어야할듯합니다."

이 테스트가 고정하는 계약은 셋이다.
  ① 정상 교정은 통과한다 — 번역투를 걷어내고 같은 뜻의 다른 낱말로 바꾸는 것은 다듬기의 목적이다.
  ② **사실이 바뀌면 버린다** — 숫자·뜻의 갈래(방향·단서·부정)가 달라지면 원문을 그대로 둔다.
  ③ 씬을 고치면 `script_md` 도 함께 고친다 — ⑤ 지시서는 **둘 다** 입력으로 받는다.

★ ②가 핵심이다. "사실을 바꾸지 마라"는 프롬프트 문장만으로는 안 막힌다는 것이 이 저장소의
  반복된 실측이다(config.PHOTO_OPTICS_REWRITES 주석). 그래서 기계가 대조한다.
"""

from __future__ import annotations

import pytest

from engine import config, script_polish as sp


# ─────────────────────────────────────────────────────────────
# ① 정상 교정은 통과한다
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("before,after", [
    # 같은 뜻의 다른 낱말 — 부류(up)가 같으므로 통과한다.
    ("쥐 20마리에서 평균 30% 늘었습니다.", "쥐 20마리에서 평균 30% 증가했습니다."),
    # ★ 아래 셋은 **살아 있는 모델이 실제로 낸 교정**이다(2026-09-10 실측 5건 중).
    #   대칭 25% 문턱이었을 때 뒤의 둘이 거부됐다 — 정확히 우리가 원하던 교정인데.
    ("체중 감소에 대한 효과와 더불어 염증의 감소라고 하는 부분이 함께 관찰되어졌다.",
     "체중 감소 효과와 더불어 염증 감소가 함께 관찰되었습니다."),
    ("해당 약물의 투여에 의해서 유도되어진 대사적인 변화라고 하는 것은 92일이라고 하는"
     " 기간에 걸쳐서 지속되어지는 것으로 나타났습니다.",
     "약물 투여로 유도된 대사 변화는 92일 동안 지속되는 것으로 나타났습니다."),
    # ★ 이중피동 교정. `보이다` 를 어간으로만 보면 이것이 "단서가 생겼다"로 거부된다.
    ("연구진에 의하면 이러한 결과는 30% 정도의 염증 감소와 연관이 있는 것으로 보여집니다.",
     "연구진에 따르면 이러한 결과는 30% 정도의 염증 감소와 연관이 있는 것으로 보입니다."),
    # 번역투 제거. ★ 짧은 문장은 걷어내면 원래 짧아진다 — 비율로만 재면 이게 막힌다.
    ("이 연구에 대한 결과를 통해 확인되었습니다", "이 연구 결과로 확인했습니다"),
    # 아무것도 안 고친 경우.
    ("92일 더 오래 살았습니다", "92일 더 오래 살았습니다"),
])
def test_legitimate_polish_is_accepted(before, after):
    assert sp.rejection_reason(before, after) == ""


# ─────────────────────────────────────────────────────────────
# ② 사실이 바뀌면 버린다
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("before,after,reason", [
    ("30% 늘었습니다", "40% 늘었습니다", "polish_numbers_changed"),
    # 단위만 바뀌어도 다른 주장이다.
    ("30% 늘었습니다", "30배 늘었습니다", "polish_numbers_changed"),
    # 단서를 지우면 주장이 넓어진다.
    ("평균 30% 늘었습니다", "30% 늘었습니다", "polish_meaning_changed"),
    # 방향이 뒤집히면 결론이 정반대가 된다.
    ("염증이 줄었습니다", "염증이 늘었습니다", "polish_meaning_changed"),
    # 연관을 인과로 세우는 것 — 이 저장소가 가장 경계하는 자리다.
    ("연관이 있었습니다", "때문입니다", "polish_meaning_changed"),
    # 부정이 사라지는 것은 가장 조용한 사실 뒤집기다.
    ("차이가 없었습니다", "차이가 있었습니다", "polish_meaning_changed"),
    ("가나다라마바사", "", "polish_empty"),
    # 문장이 통째로 뭉개진 경우 — 줄기 보존율이 먼저 잡는다(길이보다 구체적인 사유다).
    ("일부 쥐에서 관찰된 이 변화는 매우 흥미로운 결과입니다", "일부 쥐 변화",
     "polish_content_dropped"),
    # ★ 이것이 보존율 검사가 있는 이유다: 숫자도 방향도 그대로인데 **발견 하나가 사라졌다.**
    #   숫자 검사도 뜻 검사도 이것을 통과시킨다.
    ("쥐 20마리에서 수명이 30% 늘었고, 인지 기능과 운동 능력도 함께 개선됐습니다.",
     "쥐 20마리에서 수명이 30% 늘었습니다.", "polish_content_dropped"),
    # 없던 설명을 덧붙이는 쪽은 조인다 — 지어내기가 그쪽으로 온다.
    ("염증이 줄었습니다", "염증이 줄었습니다. 이는 노화를 되돌릴 수 있다는 뜻으로,"
     " 인류의 오랜 꿈에 한 걸음 다가선 것입니다.", "polish_length_drift"),
])
def test_fact_drift_is_rejected(before, after, reason):
    assert sp.rejection_reason(before, after).startswith(reason)


def test_stem_retention_separates_polish_from_deletion():
    """★ 문턱(0.45)의 근거는 실측 분포다: 정당한 교정 53~82% vs 내용 삭제 29~33%."""
    assert sp.stem_retention(
        "해당 약물의 투여에 의해서 유도되어진 대사적인 변화라고 하는 것은 92일이라고 하는"
        " 기간에 걸쳐서 지속되어지는 것으로 나타났습니다.",
        "약물 투여로 유도된 대사 변화는 92일 동안 지속되는 것으로 나타났습니다.") >= 0.45
    assert sp.stem_retention(
        "쥐 20마리에서 수명이 30% 늘었고, 인지 기능과 운동 능력도 함께 개선됐습니다.",
        "쥐 20마리에서 수명이 30% 늘었습니다.") < 0.45


def test_rejected_scene_keeps_the_original_sentence():
    """거부는 **원문을 지키는 것**이지 씬을 비우는 것이 아니다."""
    scenes = [{"scene": 1, "narration_ko": "평균 30% 늘었습니다"},
              {"scene": 2, "narration_ko": "둘째 문장입니다"}]
    report = sp.apply_polish(scenes, {"scenes": [
        {"scene": 1, "narration_ko": "30% 늘었습니다"},          # 단서 삭제 → 버린다
        {"scene": 2, "narration_ko": "두 번째 문장입니다"},       # 정상 → 적용
    ]})
    assert report["applied"] == [2]
    assert report["rejected"][0]["scene"] == 1
    assert scenes[0]["narration_ko"] == "평균 30% 늘었습니다"
    assert scenes[1]["narration_ko"] == "두 번째 문장입니다"


def test_polish_does_not_call_the_model_when_nothing_is_awkward():
    """어색한 씬이 없으면 LLM 을 부르지 않는다(비용 0). 부르면 이 테스트가 폭발한다."""
    def _boom(*a, **k):  # pragma: no cover - 불리면 안 된다
        raise AssertionError("어색한 씬이 없는데 LLM 을 불렀다")

    original = sp.call_json
    sp.call_json = _boom
    try:
        out = sp.polish([{"scene": 1, "narration_ko": "가"}],
                        {"scenes": [{"scene": 1, "korean_natural": True}]})
    finally:
        sp.call_json = original
    assert out == {"ran": False, "reason": "no_awkward_scene"}


def test_awkward_scenes_reads_the_selfcheck_axis():
    check = {"scenes": [{"scene": 3, "korean_natural": False},
                        {"scene": 4, "korean_natural": True},
                        {"scene": 5}]}          # 축이 없으면 자연스러운 것으로 본다
    assert sp.awkward_scenes(check) == [3]


# ─────────────────────────────────────────────────────────────
# ③ 읽기용 대본도 함께 고친다
# ─────────────────────────────────────────────────────────────
def test_script_md_is_updated_with_the_same_edit():
    """씬만 고치면 `script_md` 와 어긋난다 — ⑤ 지시서는 둘 다 입력으로 받는다."""
    md = "앞 문단\n\n둘째 문장입니다\n\n뒤 문단"
    out, hit = sp.rewrite_script_md(md, [("둘째 문장입니다", "두 번째 문장입니다")])
    assert hit == 1
    assert "두 번째 문장입니다" in out
    assert "둘째 문장입니다" not in out
    assert "앞 문단" in out and "뒤 문단" in out


def test_script_md_is_left_alone_when_the_sentence_is_not_found():
    """못 찾으면 손대지 않는다 — 형식이 고정이 아니라 자리로 맞추면 엉뚱한 곳을 덮는다."""
    md = "앞 문단\n\n다른 문장\n\n뒤 문단"
    out, hit = sp.rewrite_script_md(md, [("없는 문장", "새 문장")])
    assert hit == 0
    assert out == md


# ─────────────────────────────────────────────────────────────
# 자기검증 축이 **사실 판정과 섞이지 않는가**
# ─────────────────────────────────────────────────────────────
def test_korean_axis_warns_but_never_blocks():
    """문장 축은 경고다. 승인·커버리지 어디에도 닿지 않는다."""
    from engine import selfcheck

    out = selfcheck.normalize_selfcheck({"scenes": [
        {"scene": 1, "grounded": True, "korean_natural": False,
         "awkward_spans": ["연구에 대한"], "fluency_issues": ["translationese", "없는종류"]},
    ]})
    assert "korean_awkward#1" in out["warnings"]
    assert out["block_reasons"] == []
    assert out["approval_blocked"] is False
    assert out["all_grounded"] is True
    # 닫힌 목록 바깥의 종류는 버린다.
    assert out["scenes"][0]["fluency_issues"] == ["translationese"]
    assert out["scenes"][0]["awkward_spans"] == ["연구에 대한"]


def test_korean_axis_runs_without_a_claim_ledger():
    """원장이 없는 옛 초안도 한국어는 똑같이 어색할 수 있다 — 이 축은 원장 바깥에 있다."""
    from engine import selfcheck

    out = selfcheck.normalize_selfcheck({"scenes": [{"scene": 2, "korean_natural": False}]})
    assert "korean_awkward#2" in out["warnings"]


def test_fluency_kinds_are_a_closed_list():
    """되먹임이 무엇을 고칠지 알려면 종류가 닫혀 있어야 한다."""
    assert "translationese" in config.SELFCHECK_FLUENCY_KINDS
    assert len(set(config.SELFCHECK_FLUENCY_KINDS)) == len(config.SELFCHECK_FLUENCY_KINDS)
