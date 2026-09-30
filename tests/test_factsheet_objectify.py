"""Fact Sheet 요약 객관화 (2026-09-30 운영자: "팩트 시트에서는 최대한 객관화해서 수집합시다").

요약 칸(what_found)은 claims 와 달리 원문 대조가 없어서, 추출 단계의 과장("주요 원인")이 그 뒤 모든 검사에
"근거"로 들어갔다. 요약 줄마다 판정 모델에게 원문(초록·검증된 인용·관련 원문 구절)이 뒷받침하는지 묻고,
문턱 이상이면 요약에서 뺀다(기록은 남긴다). 판정이 죽으면 아무것도 안 뺀다.
"""

from __future__ import annotations

from engine import config, decide, factsheet, factsheet_check as fc


def _on(monkeypatch, value):
    sent = []
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "_post", lambda body: sent.append(body) or {
        "model": "jev", "usage": {"input_tokens": 1},
        "answers": {k: {"noul": value(body["state"])} for k in body["questions"]}})
    return sent


FS = {"what_found": ["인간 활동이 전 세계 물 저장량 변화의 주요 원인이다.", "해상도를 5~10배 높였다."],
      "claims": [{"claim_id": "C01", "claim_ko": "호주 제외 대륙에서 공간 변동의 상당 부분", "causal_strength": "association_only",
                  "source_quote": "humans account for a significant share"}]}


def test_an_overstated_summary_line_is_dropped_and_recorded(monkeypatch):
    _on(monkeypatch, lambda st: 0.9 if "주요 원인" in st.split("NARRATION:")[-1] else 0.1)
    out = fc.objectify_summaries({**FS, "what_found": list(FS["what_found"])}, "abstract text")
    assert out["what_found"] == ["해상도를 5~10배 높였다."]
    assert out["summary_check"]["dropped"][0]["text"].startswith("인간 활동이")
    assert out["summary_check"]["threshold"] == config.FACTSHEET_SUMMARY_DROP_MIN


def test_full_text_passages_reach_the_judge(monkeypatch):
    """실측: 초록만 주면 본문에만 있는 '5~10배'가 근거 없음으로 걸렸다 — 관련 원문 구절을 같이 보낸다."""
    sent = _on(monkeypatch, lambda st: 0.1)
    full = "x" * 3000 + " producing a map at 5 to 10 times the spatial resolution " + "y" * 3000
    fc.objectify_summaries({"what_found": ["해상도를 5~10배 높였다."], "claims": []}, "abs", full)
    assert "5 to 10 times" in sent[0]["state"]


def test_a_dead_judge_drops_nothing(monkeypatch):
    monkeypatch.setattr(decide, "enabled", lambda: True)
    monkeypatch.setattr(decide, "_post", lambda body: None)
    out = fc.objectify_summaries({**FS, "what_found": list(FS["what_found"])}, "abs")
    assert out["what_found"] == FS["what_found"]
    assert out["summary_check"]["checked"] == 0


def test_off_means_untouched():
    fs = {**FS, "what_found": list(FS["what_found"])}
    assert fc.objectify_summaries(fs, "abs") is fs and "summary_check" not in fs


def test_the_extraction_prompts_ask_for_the_source_strength():
    from engine import report_factsheet
    assert "객관화" in factsheet.FACTSHEET_SYSTEM and "주요 원인" in factsheet.FACTSHEET_SYSTEM
    assert "객관화" in report_factsheet.FACTSHEET_SYSTEM and "전망으로" in report_factsheet.FACTSHEET_SYSTEM
