r"""지시서 ↔ 기초 자료 대조(2026-09-05, 운영자 질문).

질문 원문: "과장하고 후킹하더라도 결국 논리는 맞아야해. 우리의 기초 자료와 전체 완성된
지시서의 설명내용이 일치하는지 한번 점검하는 작업도 있어??" — **없었다.**

실측으로 확인한 구멍:
  · selfcheck(대본↔Fact Sheet)는 engine/draft.py 에서만 돈다.
  · 지시서 LLM 은 나레이션을 다시 쓴다(실측 14개 중 3개, 전부 훅·도입부).
  · 운영자가 ⑤ 화면에서 손으로 고친 문장은 아무 검증도 안 거친다.
  · 지시서 경로에 나레이션 검증 호출이 0건이었다.

★ 이 검사는 LLM 을 쓰지 않는다 — 돈이 들지 않아 지시서를 만질 때마다 돌릴 수 있다.
  의미 수준의 과장은 selfcheck 가 본다. 층위가 다르고 둘 다 필요하다.
"""

from __future__ import annotations

from engine import directive_audit as da

FS = {
    "what_found": ["20개월령 암컷 생쥐에게 세마글루타이드를 투여했다"],
    "how": ["생쥐에게 매일 피하 주사했다"],
    "claims": [
        {"claim_id": "C01", "claim_ko": "중앙 수명이 742일이었다",
         "causal_strength": "association_only"},
        {"claim_id": "C02", "claim_ko": "치료군 중앙 수명은 834일이었다"},
    ],
}


def _cut(no, ko, **kw):
    return {"cut_no": no, "narration_ko": ko, "narration_en": "", **kw}


def test_a_number_that_is_nowhere_in_the_source_is_red():
    """★ 지어낸 수치가 가장 위험하다 — 화면에 나가면 되돌릴 수 없다."""
    r = da.audit({}, [_cut(1, "수명이 무려 5000일 늘었습니다.")], FS)
    reds = [f for f in r["findings"] if f["level"] == "red"]
    assert reds and reds[0]["code"] == "number_not_in_source"


def test_a_number_we_computed_ourselves_is_yellow_not_red():
    """★★ 우리 훅의 '92일'은 742→834 차이다. 지어낸 것과 같은 등급으로 부르면
    진짜 환각이 그 소음에 묻힌다. 그렇다고 감추지도 않는다 — 뺄셈이 틀릴 수 있다."""
    r = da.audit({}, [_cut(1, "92일 더 살았습니다.")], FS)
    codes = {f["code"] for f in r["findings"]}
    assert codes == {"number_derived_from_source"}
    assert r["stats"]["red"] == 0


def test_a_source_number_passes_clean():
    assert da.audit({}, [_cut(1, "중앙 수명 742일이었습니다.")], FS)["findings"] == []


def test_an_unknown_claim_reference_is_red():
    r = da.audit({}, [_cut(1, "결과입니다.", claim_ids=["C99"])], FS)
    assert any(f["code"] == "claim_id_unknown" for f in r["findings"])


def test_an_animal_result_told_as_a_human_result_is_flagged():
    """★ 동물 연구를 사람 얘기로 넘기는 것이 이 라인에서 가장 흔한 과장이다."""
    r = da.audit({}, [_cut(1, "우리도 92일 더 살 수 있습니다.")], FS)
    assert any(f["code"] == "animal_result_stated_for_humans" for f in r["findings"])


def test_a_limitation_sentence_about_humans_is_not_punished():
    """★★ 2026-09-05 오탐. "인간에게도 같은 효과가 나타날지는 아직 모른다"는 **옳게 쓴 문장**이다.
    옳게 쓴 것을 벌하면 운영자가 이 검사를 통째로 무시하게 된다."""
    r = da.audit({}, [_cut(1, "인간에게도 동일한 효과가 나타날지는 장기적인 임상 연구가 더 필요합니다.")], FS)
    assert not any(f["code"] == "animal_result_stated_for_humans" for f in r["findings"])
    r2 = da.audit({}, [_cut(1, "인간에게 효과가 있습니다.", evidence_role="caveat")], FS)
    assert not any(f["code"] == "animal_result_stated_for_humans" for f in r2["findings"])


def test_a_correlation_claim_stated_as_cause_is_flagged():
    r = da.audit({}, [_cut(1, "이 약 때문에 수명이 늘었습니다.", claim_ids=["C01"])], FS)
    assert any(f["code"] == "causal_overreach" for f in r["findings"])


def test_the_hook_is_audited_too():
    """★ 훅은 가장 많이 다시 쓰이고 가장 과장되기 쉬운 자리다 — 컷이 아니라서 빠지면 안 된다."""
    r = da.audit({"hook_ko": "수명이 5000일 늘어난 약!"}, [], FS)
    assert any(f["code"] == "hook_number_not_in_source" for f in r["findings"])


def test_overlay_card_numbers_are_audited():
    """화면 카드는 코드가 그린다 — 여기 지어낸 숫자가 들어가면 그대로 화면에 박힌다."""
    cut = _cut(1, "결과입니다.", overlay_plan=[{"type": "number_punch", "text": "+9999일"}])
    assert any(f["code"] == "number_not_in_source" for f in da.audit({}, [cut], FS)["findings"])


def test_it_never_calls_an_llm():
    """★ 무료여야 지시서를 만질 때마다 돌릴 수 있다."""
    import inspect
    src = inspect.getsource(da)
    for banned in ("call_json", "anthropic", "genai", "requests", "httpx"):
        assert banned not in src, banned
