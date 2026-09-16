"""출력 절단 감지 (실측 사고 2026-08-03).

무엇이 있었나: 리포트 초안 3건이 연속으로 이렇게 죽었다.

    Expecting ',' delimiter: line 693 column 8 (char 19194)
    Expecting ',' delimiter: line 694 column 6 (char 19167)
    Expecting ',' delimiter: line 683 column 8 (char 18907)

모델이 이상한 JSON 을 낸 것이 아니라 **출력이 max_tokens(6144)에서 잘린** 것이었다
(19K자 ≈ 6144토큰). 잘림을 판정하는 곳이 없어서 잘린 조각이 파서로 내려갔고, 운영자에게는
암호 같은 오류만 남았다. 게다가 재시도가 같은 자리에서 똑같이 잘려 시간과 돈만 썼다.
"""

from __future__ import annotations

import pytest

from engine import config, llm


class _Resp:
    def __init__(self, text: str, stop_reason: str):
        self.stop_reason = stop_reason
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _Client:
    def __init__(self, resp): self.messages = type("M", (), {"create": lambda _s, **kw: resp})()


def test_truncated_anthropic_output_raises_a_named_error():
    """잘림은 파싱 실패와 **다른 예외**여야 한다 — 원인도 처방도 다르다."""
    with pytest.raises(llm.OutputTruncatedError) as ei:
        llm._create(_Client(_Resp('{"a": 1', "max_tokens")),
                    model="claude-opus-4-8", system="s", user="u", max_tokens=6144)
    assert "6144" in str(ei.value), "얼마에서 잘렸는지가 안 보이면 상한을 얼마로 올릴지 모른다"
    assert "상한을 올려야" in str(ei.value)


def test_normal_stop_reason_returns_text():
    got = llm._create(_Client(_Resp('{"a": 1}', "end_turn")),
                      model="claude-opus-4-8", system="s", user="u", max_tokens=6144)
    assert got == '{"a": 1}'


def test_truncation_is_not_swallowed_by_the_json_retry_loop(monkeypatch):
    """★ 급소: call_json 이 이것을 JSONParseError 로 잡아 재시도하면, 같은 자리에서 또 잘려
    비용만 두 배가 되고 운영자는 여전히 원인을 못 본다."""
    calls = {"n": 0}

    def _boom(*a, **kw):
        calls["n"] += 1
        raise llm.OutputTruncatedError("출력이 max_tokens(10)에서 잘렸다 — 상한을 올려야 한다")

    monkeypatch.setattr(llm, "_create", _boom)
    monkeypatch.setattr(llm, "_client", lambda: object())
    with pytest.raises(llm.OutputTruncatedError):
        llm.call_json(model="claude-opus-4-8", system="s", user="u")
    assert calls["n"] == 1, "잘림은 재시도 대상이 아니다(같은 자리에서 또 잘린다)"


def test_gemini_truncation_is_detected_too():
    """엣지 폴백이 gemini 를 쓴다 — 한쪽만 감지하면 경로에 따라 진단이 달라진다."""
    import inspect

    src = inspect.getsource(llm._gemini_create)
    assert '"MAX_TOKENS"' in src
    assert "OutputTruncatedError" in src


# ── 상한 자체 ────────────────────────────────────────────────
def test_script_cap_is_large_enough_for_a_full_script():
    """실측 절단 지점이 6144 였다. 대본 1편은 씬 6~7개 × 한/영 나레이션·프롬프트라 필드가 많고,
    근거가 풍부한 리포트일수록 길어진다 — 데이터가 좋은 편일수록 먼저 죽는 역설이 있었다."""
    assert config.LLM_SCRIPT_MAX_TOKENS >= 12288
    assert config.LLM_SCRIPT_MAX_TOKENS > 6144


def test_script_callers_use_the_config_cap():
    """상한을 상수로 뽑아 놓고 호출부가 리터럴을 쓰면 올려도 안 올라간다."""
    import inspect

    from engine import report_directive, report_scriptgen

    for fn in (report_scriptgen.generate, report_directive._generate_once):
        src = inspect.getsource(fn)
        assert "LLM_SCRIPT_MAX_TOKENS" in src, f"{fn.__qualname__}: 상한이 하드코딩돼 있다"
        assert "6144" not in src


# ── Codex 리뷰 #88 반영 3건 ──────────────────────────────────
def test_context_window_overflow_is_also_truncation():
    """★ 절단 사유가 둘이고 **처방이 정반대**다. 입력이 넘쳐 죽었는데 출력 상한만 올리면
    오히려 더 빨리 넘는다. 원문 주입(§4-2)으로 입력이 최대 4만 자 늘어난 뒤라 실제로 닿을 수 있다.
    """
    with pytest.raises(llm.OutputTruncatedError) as ei:
        llm._create(_Client(_Resp('{"a": 1', "model_context_window_exceeded")),
                    model="claude-opus-4-8", system="s", user="u", max_tokens=16384)
    msg = str(ei.value)
    assert "입력을 줄여야" in msg
    assert "역효과" in msg, "출력 상한을 올리라고 잘못 안내하면 안 된다"


def test_the_two_truncation_reasons_prescribe_opposite_fixes():
    """문구가 같으면 갈라 둔 의미가 없다."""
    def _msg(reason):
        try:
            llm._create(_Client(_Resp("x", reason)), model="m", system="s", user="u",
                        max_tokens=999)
        except llm.OutputTruncatedError as exc:
            return str(exc)
        return ""

    out_cap = _msg("max_tokens")
    ctx = _msg("model_context_window_exceeded")
    assert "출력 상한을 올려야" in out_cap and "입력을 줄여야" not in out_cap
    assert "입력을 줄여야" in ctx and "출력 상한을 올려야" not in ctx


def test_stop_reasons_exist_in_the_installed_sdk():
    """★ 리뷰가 알려준 값을 그대로 믿지 않고 설치된 SDK 에서 확인한다. 오타면 이 검사가
    통째로 무의미해진다(영원히 안 걸리는 분기)."""
    from anthropic.types.stop_reason import StopReason
    import typing

    literals = set(typing.get_args(StopReason))
    assert {"max_tokens", "model_context_window_exceeded"} <= literals, literals


def test_gemini_error_reports_the_effective_cap():
    """★ 2.5-pro 는 maxOutputTokens 를 max(요청, 32768)로 덮어쓴다. 인자를 그대로 적으면
    운영자가 상한을 그 아래로 올려도 아무 변화가 없다 — 처방이 헛돈다."""
    import inspect

    src = inspect.getsource(llm._gemini_create)
    assert "gen_config['maxOutputTokens']" in src or 'gen_config["maxOutputTokens"]' in src
    assert "maxOutputTokens({max_tokens})" not in src, "인자를 그대로 적으면 실효 상한과 다르다"


def test_edge_twin_has_the_same_truncation_contract():
    """대시보드 폴백 경로가 같은 사고를 반복하면 안 된다(REPORT_DRAFT_EDGE_FALLBACK)."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "class OutputTruncatedError" in edge
    assert "model_context_window_exceeded" in edge
    assert '"MAX_TOKENS"' in edge
    assert "SCRIPT_MAX_TOKENS" in edge
    # 코드 줄에 옛 상한이 남아 있으면 안 된다(주석의 설명은 허용).
    code = [ln for ln in edge.splitlines() if not ln.strip().startswith(("//", "*", "/*"))]
    assert not any("6144" in ln for ln in code), "엣지가 아직 옛 상한을 쓴다"
    # 절단이 재시도·폴백에 삼켜지지 않는지.
    assert edge.count("if (err instanceof OutputTruncatedError) throw err;") >= 3


# ── Fact Sheet 추출 상한 (실측 2026-08-03, 운영 진단이 알려준 것) ──
def test_factsheet_cap_is_raised_too():
    """★ 새 진단이 내 가정을 정정했다. 대본이 아니라 **추출**이 먼저 잘리고 있었다:

        출력이 maxOutputTokens(8192)에서 잘렸다 — 상한을 올려야 한다 (model=gemini-2.5-flash)

    8192 는 LLM_MAX_TOKENS 기본값이고, report_factsheet.extract 가 max_tokens 를 안 넘겨
    그 기본값을 쓰고 있었다. 전문 주입으로 Fact Sheet 가 두꺼워지면서 넘친 것이다.
    """
    assert config.LLM_FACTSHEET_MAX_TOKENS > config.LLM_MAX_TOKENS
    assert config.LLM_FACTSHEET_MAX_TOKENS >= 12288


def test_factsheet_extract_passes_the_cap():
    """상수만 만들고 호출부가 안 넘기면 기본값(8192)이 그대로 쓰인다 — 이번 사고가 정확히 그것이었다."""
    import inspect

    from engine import report_factsheet

    assert "config.LLM_FACTSHEET_MAX_TOKENS" in inspect.getsource(report_factsheet.extract)


def test_edge_factsheet_cap_matches():
    """엣지는 2048 이었다 — 워커(8192)보다도 작아 전문 주입 뒤에는 확실히 잘린다."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "FACTSHEET_MAX_TOKENS" in edge
    code = [ln for ln in edge.splitlines() if not ln.strip().startswith(("//", "*", "/*"))]
    assert not any("), 2048)" in ln for ln in code), "엣지가 아직 2048 을 쓴다"


# ── 상한이 아니라 계약을 묶는다 (실측: 16384 에서도 잘렸다) ──
def test_number_facts_have_a_hard_cap():
    """★ 상한만으로는 안 풀렸다. 8192 → 16384 로 올려도 같은 자리에서 잘렸고, 그 호출은
    64초 걸렸다. 16384 토큰이면 약 39,000자인데 원문은 11,996자다 — 정직한 추출이 원문의
    3배가 될 수는 없으므로 모델이 **반복 생성**한 것이다. number_facts 가 상한 없는
    배열이라 끝없이 뽑아낼 여지가 있었다."""
    from engine import report_factsheet as rf

    assert config.FACTSHEET_MAX_NUMBER_FACTS > 0
    out = rf.normalize_factsheet({"number_facts": [{"display": f"n{i}"} for i in range(80)]})
    assert len(out["number_facts"]) == config.FACTSHEET_MAX_NUMBER_FACTS
    assert len(out["numbers"]) == config.FACTSHEET_MAX_NUMBER_FACTS, "파생 필드도 함께 잘려야 한다"


def test_the_cap_is_stated_in_the_prompt_too():
    """코드로만 자르면 모델은 계속 길게 쓴다 — 토큰과 시간은 그대로 낭비된다.
    프롬프트가 먼저 막고, 코드가 못 믿어서 다시 막는 이중 구조다."""
    from engine import report_factsheet as rf

    assert "{MAX_FACTS}" not in rf.FACTSHEET_SYSTEM, "치환이 안 됐다(플레이스홀더가 그대로다)"
    assert f"최대 {config.FACTSHEET_MAX_NUMBER_FACTS}개" in rf.FACTSHEET_SYSTEM
    assert "반복하지 마라" in rf.FACTSHEET_SYSTEM


def test_edge_twin_shares_the_fact_cap():
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "MAX_NUMBER_FACTS" in edge
    assert "facts.length = MAX_NUMBER_FACTS" in edge, "엣지는 프롬프트만 있고 강제가 없다"
    assert '.replace("{MAX_FACTS}", String(MAX_NUMBER_FACTS))' in edge


# ── 리뷰 #90 반영: 상한이 도달조차 못 하던 문제 ────────────────
def test_truncated_factsheet_is_salvaged_not_lost():
    """★ P1 지적: 절단은 파싱보다 **먼저** 일어나므로, normalize 단계의 개수 상한은
    이미 온전한 응답만 다듬을 뿐 실제 실패를 막지 못했다. 안전망이 죽어 있었다."""
    bad = ('{"company":"삼성전기","number_facts":['
           '{"fact_id":"a","display":"목표주가 200만원"},'
           '{"fact_id":"b","display":"PER 19배"},'
           '{"fact_id":"c","disp')
    got = llm.salvage_json(bad)
    assert got["company"] == "삼성전기"
    assert [f["display"] for f in got["number_facts"]] == ["목표주가 200만원", "PER 19배"], \
        "반쪽 요소가 섞이면 쓰레기 사실이 화면에 나갈 수 있다"


def test_salvage_handles_truncation_inside_a_string():
    got = llm.salvage_json('{"company":"X","number_facts":[{"fact_id":"a","display":"목표주가 200')
    assert got["company"] == "X"


def test_salvage_refuses_when_there_is_nothing_to_save():
    with pytest.raises(llm.JSONParseError):
        llm.salvage_json("완전히 깨진 응답")


def test_salvage_is_off_by_default():
    """★ 대본에 이걸 켜면 씬이 잘린 불완전한 대본이 통과한다. 명시적으로 켠 곳만 쓴다."""
    import inspect

    src = inspect.getsource(llm.call_json)
    assert "salvage_truncated: bool = False" in src

    from engine import report_factsheet, report_scriptgen

    assert "salvage_truncated=True" in inspect.getsource(report_factsheet.extract)
    assert "salvage_truncated" not in inspect.getsource(report_scriptgen.generate), \
        "대본은 앞부분만 살리면 안 된다"


def test_semantic_duplicates_are_dropped_before_the_cap():
    """★ P2 지적: 앞에서부터 자르기만 하면 반복 20개가 상한을 채우고 정작 필요한
    목표주가·실적이 버려진다. 의미 중복 제거가 **상한보다 먼저** 돌아야 한다."""
    from engine import report_factsheet as rf

    facts = ([{"metric": "영업이익", "value": 860, "unit": "억", "period": "2026F",
               "display": "영업이익 860억"}] * 30
             + [{"metric": "목표주가", "value": 200, "unit": "만원", "display": "목표주가 200만원"}])
    out = rf.normalize_factsheet({"number_facts": facts})
    displays = [f["display"] for f in out["number_facts"]]
    assert "목표주가 200만원" in displays, "반복에 밀려 중요한 사실이 잘렸다"
    assert displays.count("영업이익 860억") == 1


def test_salvage_stubs_are_dropped():
    """살리기 잔해(`{"fact_id":"c"}`)가 사실인 척 화면에 나가면 안 된다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"fact_id": "real", "metric": "PER", "value": 19, "display": "PER 19배"},
        {"fact_id": "c"},
    ]})
    assert [f["fact_id"] for f in out["number_facts"]] == ["real"]


def test_descriptive_facts_survive_dedup():
    """metric·value 가 없는 서술형 사실까지 중복으로 묶어 버리면 근거가 사라진다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"fact_id": "d1", "display": "LTA 계약 체결"},
        {"fact_id": "d2", "display": "FC-BGA 고객사 지원"},
    ]})
    assert len(out["number_facts"]) == 2


# ── 리뷰 #90 2차: 잘린 시트가 리스크를 삼키지 않게 ──────────────
def test_number_facts_is_last_in_the_schema():
    """★ P1 지적: number_facts 중간에서 잘리면 그 **뒤** 키들이 통째로 사라진다. 예전 순서로는
    opinion·basis·risks 가 뒤에 있어서, 살린 시트가 risks=[] 가 되고 대본 프롬프트의
    "risks 가 비면 리스크 씬을 건너뛰라" 규칙이 발동해 **리스크 없는 금융 영상**이 나간다.
    상한 없는 배열을 맨 뒤로 보내면 정상 절단에서 필수 절이 먼저 확보된다."""
    from engine import report_factsheet as rf

    sp = rf.FACTSHEET_SYSTEM
    for key in ('"opinion"', '"basis"', '"risks"'):
        assert sp.index(key) < sp.index('"number_facts"'), f"{key} 가 number_facts 뒤에 있다"


def test_edge_schema_order_matches():
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    head = edge[:edge.index("const SCRIPT_SYSTEM")]
    for key in ('"opinion"', '"basis"', '"risks"'):
        assert head.index(key) < head.index('"number_facts"'), f"엣지: {key} 순서가 다르다"


def test_salvaged_sheet_missing_required_sections_is_rejected():
    """빈 배열과 **키 부재**는 의미가 정반대다 — 전자는 '리포트에 없다', 후자는 '잘려서 안 나왔다'.
    후자를 통과시키면 조용한 품질 저하가 된다. 시끄럽게 실패해야 한다."""
    from engine import report_factsheet as rf

    with pytest.raises(llm.JSONParseError) as ei:
        rf._require_complete({"company": "x", "number_facts": []})
    assert "risks" in str(ei.value)

    rf._require_complete({"opinion": "", "basis": [], "risks": []})   # 빈 값은 통과


def test_extract_guards_the_salvaged_sheet():
    import inspect

    from engine import report_factsheet as rf

    assert "_require_complete(obj" in inspect.getsource(rf.extract)
    assert "salvaged=" in inspect.getsource(rf.extract), "살린 경우에만 엄격 검사"


def test_scope_and_basis_distinguish_facts():
    """★ P2 지적: 전사 실적 100억과 사업부 컨센서스 100억은 같은 수치지만 **다른 사실**이고
    귀속·인용도 다르다. 묶어 버리면 뒤엣것이 근거째 사라진다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "영업이익", "value": 100, "unit": "억", "scope": "company",
         "basis": "actual", "display": "전사 영업이익 100억"},
        {"metric": "영업이익", "value": 100, "unit": "억", "scope": "segment",
         "basis": "consensus", "display": "사업부 컨센서스 100억"},
    ]})
    assert len(out["number_facts"]) == 2


# ── 리뷰 #90 3차: 인용 없는 반쪽 수치가 살아남던 문제 ──────────
def test_salvage_drops_half_written_facts():
    """★ P1 실측: 중첩 필드(source_refs 의 quote) 한가운데서 잘리면 이미 닫힌 comparator 의
    `}` 도 자를 곳이 되어, **인용 없는 금융 수치**가 살아남았다:

        {"fact_id":"b","metric":"PER","value":19,"comparator":{…}}   ← source_refs 없음

    근거 없는 수치가 화면에 나가는 것이 §5 Evidence Contract 가 막으려는 바로 그것이다.
    """
    bad = ('{"company":"삼성전기","opinion":"매수","basis":[],"risks":["수요 둔화"],'
           '"number_facts":['
           '{"fact_id":"a","metric":"목표주가","value":200,"display":"목표주가 200만원",'
           '"source_refs":[{"quote":"목표주가를 200만원으로"}]},'
           '{"fact_id":"b","metric":"PER","value":19,'
           '"comparator":{"basis":"10년평균","value":"19배"},'
           '"source_refs":[{"quote":"동사의 10년 평균 PER')
    got = llm.salvage_json(bad)

    ids = [f["fact_id"] for f in got["number_facts"]]
    assert ids == ["a"], f"반쪽 fact 가 살아남았다: {ids}"
    assert got["risks"] == ["수요 둔화"], "필수 절은 지켜져야 한다"
    assert got["opinion"] == "매수"


def test_salvage_still_keeps_complete_facts():
    """반쪽을 버리느라 온전한 것까지 버리면 살리기의 의미가 없다."""
    got = llm.salvage_json(
        '{"company":"X","number_facts":[{"fact_id":"a","display":"목표주가 200만원"},'
        '{"fact_id":"b","display":"PER 19배"},{"fact_id":"c","disp')
    assert [f["display"] for f in got["number_facts"]] == ["목표주가 200만원", "PER 19배"]


def test_comparator_distinguishes_claims():
    """★ P2: 같은 PER 19배라도 '컨센서스 대비'와 '전년 대비'는 다른 주장이고 인용도 다르다.
    report_evidence.conflict_groups 도 comparator.basis 를 유효 basis 로 취급한다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "PER", "value": 19, "comparator": {"basis": "컨센서스", "value": "18배"},
         "display": "PER 19배(컨센서스 대비)"},
        {"metric": "PER", "value": 19, "comparator": {"basis": "전년", "value": "22배"},
         "display": "PER 19배(전년 대비)"},
        {"metric": "PER", "value": 19, "comparator": {"basis": "컨센서스", "value": "18배"},
         "display": "진짜 중복"},
    ]})
    displays = [f["display"] for f in out["number_facts"]]
    assert len(displays) == 2 and "진짜 중복" not in displays


def test_edge_dedupes_before_capping():
    """엣지도 상한 **전에** 의미 중복을 지운다 — 안 그러면 대시보드 초안만 중복 20개가 된다."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    dedup_at = edge.index("keyAt")
    cap_at = edge.index("facts.length = MAX_NUMBER_FACTS")
    assert dedup_at < cap_at, "엣지가 중복 제거보다 먼저 자른다"
    assert "c.basis" in edge, "엣지 키에 comparator 가 빠졌다"


# ── 리뷰 #90 4차: 중복 제거가 근거를 지우던 문제 ────────────────
def test_dedupe_keeps_the_cited_version():
    """★ 실측 결함: 먼저 온 것을 무조건 남기면, 앞엣것에 인용이 없고 뒤엣것에 있을 때
    **유일하게 근거 있는 판본**을 버린다. 그러면 인용 없는 수치가 화면에 남는다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"fact_id": "x", "metric": "PER", "value": 19, "display": "인용없음", "source_refs": []},
        {"fact_id": "y", "metric": "PER", "value": 19, "display": "인용있음",
         "source_refs": [{"quote": "동사의 10년 평균 PER 는 19배다"}]},
    ]})
    kept = out["number_facts"]
    assert len(kept) == 1
    assert kept[0]["display"] == "인용있음"
    assert kept[0]["source_refs"], "근거 있는 쪽이 남아야 한다"


def test_value_less_facts_are_distinguished_by_description():
    """★ 계약 두 건이 똑같이 metric='계약', value=null 이어도 서술이 다르면 다른 사건이다.
    ★★ 그렇다고 통째로 중복 판정에서 빼면(예전 동작) **똑같은 서술 20개**가 상한을 채워
       뒤의 목표주가·실적을 밀어낸다. 서술로 구분해 반복만 지운다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": (
        [{"metric": "계약", "value": None, "display": "A사와 LTA 체결"},
         {"metric": "계약", "value": None, "display": "B사 FC-BGA 지원"}]
        + [{"metric": "계약", "value": None, "display": "A사와 LTA 체결"}] * 10)})
    assert [f["display"] for f in out["number_facts"]] == ["A사와 LTA 체결", "B사 FC-BGA 지원"]


def test_metricless_numbers_are_distinguished_by_description():
    """★ metric 이 비고 값이 같은 두 사실(둘 다 10%)은 수치만으로 구분이 안 된다 —
    영업이익률 10% 와 배당성향 10% 는 다른 사실이다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "", "value": 10, "unit": "%", "display": "영업이익률 10%"},
        {"metric": "", "value": 10, "unit": "%", "display": "배당성향 10%"},
        {"metric": "", "value": 10, "unit": "%", "display": "영업이익률 10%"},
    ]})
    assert [f["display"] for f in out["number_facts"]] == ["영업이익률 10%", "배당성향 10%"]


def test_well_identified_numbers_ignore_description():
    """반대로 metric·value 가 뚜렷하면 표현이 달라도 같은 사실이다 — 그게 이 중복 제거의 목적이다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "PER", "value": 19, "unit": "x", "display": "PER 19배"},
        {"metric": "PER", "value": 19, "unit": "x", "display": "19배의 PER"},
    ]})
    assert len(out["number_facts"]) == 1


def test_unit_and_period_aliases_collapse():
    """'억' 과 '억원' 이 다른 키가 되면 표현만 바꾼 반복이 상한을 잡아먹는다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "영업이익", "value": 860, "unit": "억", "period": "2026년", "display": "첫번째"},
        {"metric": "영업이익", "value": 860, "unit": "억원", "period": "2026", "display": "별칭중복"},
    ]})
    assert [f["display"] for f in out["number_facts"]] == ["첫번째"]


def test_salvaged_sheet_without_any_fact_is_rejected():
    """★ what/basis 가 길어 **첫 fact 안에서** 잘리면 살리기가 risks 뒤까지 물러나
    number_facts 자체가 없는 객체가 나온다. 그대로 두면 hard_blocks 가 빈 목록에 아무 차단도
    안 걸어 **숫자 근거 0개짜리 초안**이 진행된다."""
    from engine import report_factsheet as rf

    with pytest.raises(llm.JSONParseError):
        rf._require_complete({"opinion": "", "basis": [], "risks": []}, salvaged=True)


def test_complete_sheet_with_no_facts_is_allowed():
    """온전한 응답에는 이 검사를 걸지 않는다 — 수치가 원래 없는 리포트(시황 메시지)가 있다."""
    from engine import report_factsheet as rf

    rf._require_complete({"opinion": "", "basis": [], "risks": []}, salvaged=False)


def test_salvage_marks_the_object():
    """살렸는지를 호출자가 알아야 더 엄격한 검사를 걸 수 있다."""
    import inspect

    assert "SALVAGED_MARK" in inspect.getsource(llm.call_json)
    from engine import report_factsheet as rf

    assert "SALVAGED_MARK" in inspect.getsource(rf.extract)


def test_edge_mirrors_the_canonicalization():
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "function normalizeUnit" in edge and "function normalizePeriod" in edge
    assert '"억": "억원"' in edge, "단위 표가 파이썬과 갈렸다"
    assert "weak ? squash(String(f.display" in edge, \
        "엣지가 식별력 약한 사실을 서술로 구분하지 않는다"


def test_subannual_periods_stay_distinct():
    """★ 내가 직전 라운드에서 만든 회귀. report_evidence.normalize_period 는 **근거 대조용**이라
    1H26·2H26 을 둘 다 '26' 으로 접는다. 그걸 중복 판정에 쓰면 상·하반기 실적이 같은 값일 때
    하나가 근거째 사라진다. 별칭만 접고 구분은 지키는 전용 함수를 따로 둔다."""
    from engine import report_evidence as ev, report_factsheet as rf

    assert ev.normalize_period("1H26") == ev.normalize_period("2H26"), "전제 확인"
    assert rf._canon_period("1H26") != rf._canon_period("2H26")
    assert rf._canon_period("2026.07") != rf._canon_period("2026.12")
    assert rf._canon_period("2026년") == rf._canon_period("2026")   # 순수 별칭은 접힌다

    out = rf.normalize_factsheet({"number_facts": [
        {"metric": "영업이익", "value": 1900, "unit": "억", "period": "1H26", "display": "상반기"},
        {"metric": "영업이익", "value": 1900, "unit": "억", "period": "2H26", "display": "하반기"},
        {"metric": "영업이익", "value": 1900, "unit": "억원", "period": "2026년", "display": "연간"},
        {"metric": "영업이익", "value": 1900, "unit": "억", "period": "2026", "display": "연간중복"},
    ]})
    assert [f["display"] for f in out["number_facts"]] == ["상반기", "하반기", "연간"]


def test_edge_period_canon_matches():
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "PURE_YEAR_RE" in edge
    assert "PERIOD_RULES" not in edge, "근거 대조용 규칙을 중복 판정에 쓰면 안 된다"


def test_dedupe_ignores_unusably_short_citations():
    """★ 리스트가 비었는지만 보면, 인용이 있긴 한데 대조가 무의미할 만큼 짧은 경우를
    '근거 있음'으로 세어 **진짜 인용을 가진 뒤엣것**을 버린다.
    원문 대조는 attach_evidence 가 나중에 하지만(여기엔 원문이 없다), 길이만으로 걸러지는
    것은 여기서 걸러 잘못 버릴 확률을 줄인다."""
    from engine import report_factsheet as rf

    out = rf.normalize_factsheet({"number_facts": [
        {"fact_id": "x", "metric": "PER", "value": 19, "display": "짧은인용",
         "source_refs": [{"quote": "19"}]},
        {"fact_id": "y", "metric": "PER", "value": 19, "display": "진짜인용",
         "source_refs": [{"quote": "동사의 10년 평균 PER 는 19배다"}]},
    ]})
    assert [f["display"] for f in out["number_facts"]] == ["진짜인용"]


def test_usable_refs_counts_only_long_enough_quotes():
    from engine import report_factsheet as rf

    assert rf._usable_refs({"source_refs": [{"quote": "짧"}]}) == 0
    assert rf._usable_refs({"source_refs": [{"quote": "가" * config.EVIDENCE_QUOTE_MIN_CHARS}]}) == 1
    assert rf._usable_refs({"source_refs": "not a list"}) == 0
    assert rf._usable_refs({}) == 0


def test_edge_prefers_cited_duplicates_too():
    """★ 트윈 정합: 파이썬만 '인용 있는 쪽 우선'으로 고치면 대시보드 경로는 여전히
    유일하게 근거 있는 판본을 버린다. 같은 리포트가 경로에 따라 다른 근거로 영상이 된다."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "usableRefs" in edge, "엣지가 인용 유무를 안 본다"
    assert "QUOTE_MIN_CHARS" in edge
    assert "f.fact_id = kept[prev].fact_id" in edge, "교체 시 참조가 깨진다"
    # 단순 first-wins 필터가 남아 있으면 안 된다.
    assert "seenKeys.has(key)) return false" not in edge


# ── 리뷰 #90 9차: 상한이 근거를 버리지 않게, 중복 판정이 주체를 지우지 않게 ──────
def test_comparator_value_aliases_collapse():
    """★ P2 지적: 최상위 unit 은 정본으로 접으면서 comparator.value 만 날문자열로 두면,
    '860억' 과 '860억원' 이 다른 키가 되어 표기만 바꾼 반복이 상한을 잡아먹는다."""
    from engine import report_factsheet as rf

    def fact(comp_value):
        return {"metric": "영업이익", "value": 900.0, "unit": "억원", "period": "2026",
                "scope": "company", "comparator": {"basis": "전년", "value": comp_value}}

    assert rf._semantic_key(fact("860억")) == rf._semantic_key(fact("860억원"))
    assert rf._semantic_key(fact("860억")) != rf._semantic_key(fact("760억원"))


def test_segment_facts_keep_their_subject():
    """★ P2 지적: 스키마에 사업부 이름을 담을 필드가 없다(scope 는 company|segment|market).
    두 사업부가 같은 수치를 내면 base 키가 같아져 뒤엣것이 인용째 사라진다."""
    from engine import report_factsheet as rf

    def seg(fid, display):
        return {"fact_id": fid, "metric": "매출", "value": 100.0, "unit": "억원",
                "period": "2026", "scope": "segment", "display": display}

    kept = rf._dedupe_semantic([seg("a", "반도체 매출 100억원"),
                                seg("b", "디스플레이 매출 100억원")])
    assert [f["fact_id"] for f in kept] == ["a", "b"], "다른 사업부가 중복으로 지워졌다"
    # 같은 사업부를 그대로 반복한 것은 여전히 접힌다 — 상한을 채우지 못하게.
    same = rf._dedupe_semantic([seg("a", "반도체 매출 100억원"),
                                seg("b", "반도체 매출 100억원")])
    assert len(same) == 1


def test_cap_rescues_the_only_cited_fact():
    """★ P2 지적: 앞 20개가 전부 인용 없는 고유 사실이고 21번째에만 인용이 있으면,
    위치로 자른 결과가 no_fact_has_source_ref 로 시트를 통째로 막는다 — 근거가 있었는데도."""
    from engine import config
    from engine import report_factsheet as rf

    quote = "가" * (config.EVIDENCE_QUOTE_MIN_CHARS + 5)
    facts = [{"fact_id": f"n{i}", "metric": f"지표{i}", "value": float(i),
              "unit": "억원", "period": "2026", "display": f"지표{i} {i}억원"}
             for i in range(config.FACTSHEET_MAX_NUMBER_FACTS + 3)]
    facts[-1]["source_refs"] = [{"quote": quote}]

    out = rf.normalize_factsheet({"number_facts": facts})

    assert len(out["number_facts"]) == config.FACTSHEET_MAX_NUMBER_FACTS
    assert any(rf._usable_refs(f) for f in out["number_facts"]), \
        "유일하게 인용 있는 사실이 상한에 잘려 나갔다"
    # 순서는 흔들지 않는다 — 맨 뒤 한 자리만 바꾼다.
    assert [f["fact_id"] for f in out["number_facts"]][:3] == ["n0", "n1", "n2"]


def test_cap_does_not_reshuffle_when_citations_already_survive():
    """구조를 지킨다: 상한 안에 인용이 이미 있으면 아무것도 바꾸지 않는다."""
    from engine import config
    from engine import report_factsheet as rf

    quote = "나" * (config.EVIDENCE_QUOTE_MIN_CHARS + 5)
    facts = [{"fact_id": f"n{i}", "metric": f"지표{i}", "value": float(i),
              "unit": "억원", "period": "2026", "display": f"지표{i} {i}억원"}
             for i in range(config.FACTSHEET_MAX_NUMBER_FACTS + 3)]
    facts[0]["source_refs"] = [{"quote": quote}]
    facts[-1]["source_refs"] = [{"quote": quote}]

    out = rf.normalize_factsheet({"number_facts": facts})
    assert [f["fact_id"] for f in out["number_facts"]] == \
        [f"n{i}" for i in range(config.FACTSHEET_MAX_NUMBER_FACTS)]


def test_edge_twin_has_the_same_three_fixes():
    """★ 트윈 정합: 세 가지가 파이썬에만 있으면 같은 리포트가 경로에 따라 다른 사실로 영상이 된다."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "canonCompValue" in edge, "엣지가 comparator 값 별칭을 안 접는다"
    assert 'scope !== "company"' in edge, "엣지가 사업부 주체를 안 본다"
    assert "cut.find((f: any) => usableRefs(f) > 0)" in edge, "엣지 상한이 인용을 안 구한다"


# ── 리뷰 #90 10차: 인용의 실재까지 보고 고른다 ──────────────────────────
def _packet(text):
    """원문 packet 최소 형태 — 순위 판정은 chunks 가 아니라 text 를 본다."""
    return {"text": text, "chunks": [{"chunk_id": "c0", "text": text}]}


def test_usable_refs_rejects_quotes_absent_from_the_source():
    """★ P2 지적: 길이만 보면 지어낸 긴 인용이 '근거 있음'으로 통과한다."""
    from engine import config
    from engine import report_factsheet as rf

    real = "2028년 합산 영업이익은 13조 원을 넘어설 것으로 전망한다"
    fake = "이 회사는 곧 세계 1위가 될 것이라고 단언한다" + "가" * config.EVIDENCE_QUOTE_MIN_CHARS
    src = "리포트 본문. " + real + " 이하 생략."

    assert rf._usable_refs({"source_refs": [{"quote": real}]}, src) == 1
    assert rf._usable_refs({"source_refs": [{"quote": fake}]}, src) == 0
    # 원문을 못 구한 경로에서는 종전대로 길이만 본다 — 여기서 막으면 요약 경로가 통째로 죽는다.
    assert rf._usable_refs({"source_refs": [{"quote": fake}]}) == 1


def test_dedupe_prefers_the_version_whose_quote_is_in_the_source():
    """지어낸 인용을 가진 앞엣것이 진짜 근거를 가진 뒤엣것을 밀어내면 안 된다."""
    from engine import config
    from engine import report_factsheet as rf

    real = "목표주가는 12만원으로 상향한다"
    fake = "목표주가는 30만원으로 상향한다" + "나" * config.EVIDENCE_QUOTE_MIN_CHARS
    src = "본문. " + real + " 끝."

    def fact(fid, quote):
        return {"fact_id": fid, "metric": "목표주가", "value": 120000.0, "unit": "원",
                "period": "2026", "scope": "company", "display": "목표주가 12만원",
                "source_refs": [{"quote": quote}]}

    kept = rf._dedupe_semantic([fact("a", fake), fact("b", real)], src)
    assert len(kept) == 1
    assert kept[0]["source_refs"][0]["quote"] == real, "지어낸 인용이 진짜 근거를 밀어냈다"


def test_cap_rescue_looks_at_real_quotes_too():
    """상한 구제도 같은 눈으로 본다 — 앞 20개의 인용이 전부 지어낸 것이면 구제가 돌아야 한다."""
    from engine import config
    from engine import report_factsheet as rf

    real = "2028년 영업이익은 13조원을 넘어설 전망이다"
    fake = "근거 없는 긴 문장" + "다" * config.EVIDENCE_QUOTE_MIN_CHARS
    src = "본문. " + real + " 끝."

    facts = [{"fact_id": f"n{i}", "metric": f"지표{i}", "value": float(i), "unit": "억원",
              "period": "2026", "display": f"지표{i} {i}억원",
              "source_refs": [{"quote": fake}]}
             for i in range(config.FACTSHEET_MAX_NUMBER_FACTS + 3)]
    # ★ 살릴 사실의 값은 그 인용이 실제로 말하는 값이어야 한다 — 12차부터 값 대조까지 한다.
    facts[-1]["value"] = 13.0
    facts[-1]["unit"] = "조원"
    facts[-1]["source_refs"] = [{"quote": real}]

    out = rf.normalize_factsheet({"number_facts": facts}, packet=_packet(src))
    quotes = [f["source_refs"][0]["quote"] for f in out["number_facts"]]
    assert real in quotes, "원문에 실제로 있는 유일한 인용이 상한에 잘려 나갔다"


def test_extract_hands_the_packet_to_normalize():
    """배선 확인: packet 이 normalize_factsheet 까지 안 가면 위 세 검사가 운영에서 무동작이다."""
    import inspect

    from engine import report_factsheet as rf

    assert "normalize_factsheet(obj, packet=packet)" in inspect.getsource(rf.extract)


def test_edge_usable_refs_checks_the_source_too():
    """★ 트윈 정합: 엣지가 인용의 실재를 안 보면 같은 리포트가 경로에 따라 다른 근거를 남긴다."""
    import pathlib

    edge = pathlib.Path(
        "supabase/functions/generate-report-draft/index.ts").read_text(encoding="utf-8")
    assert "squashedSource ? squashedSource.includes(squash(quote)) : true" in edge
    # ★ 앞머리 8자만 맞아도 통과시키는 locateChunk 로 되돌아가면 안 된다 — 지어낸 인용이 샌다.
    assert "locateChunk(quote, chunks)" not in edge.split("const usableRefs")[1][:600]
    assert "normalizeFactsheet(obj: any, chunks: any[] = [], sourceText = \"\")" in edge


# ── 리뷰 #90 11차 ────────────────────────────────────────────────────
def _retrying_stub(calls):
    """항상 타임아웃하는 gemini stub — **진짜 재시도 데코레이터를 달아** 둔다.

    ★ 평범한 함수로 갈아 끼우면 retry_with 가 없어 재시도 예산이 아예 안 걸린다. 그러면
      "폴백이 있으면 짧게 끊는다"를 재는 것이 아니라 stub 을 재는 셈이 된다.
    """
    import httpx
    from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

    from engine import config

    @retry(reraise=True, stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
           wait=wait_fixed(0),
           retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)))
    def _stub(**kwargs):
        calls.append("gemini")
        raise httpx.TimeoutException("stalled")

    return _stub



def test_ranking_rejects_a_quote_that_only_shares_the_prefix():
    """★ P2 지적: locate_chunk 는 청크 경계 인용을 구제하려고 **앞머리 8자**만 맞아도 통과시킨다.
    진짜 문장의 앞머리를 베낀 지어낸 인용이 '근거 있음'으로 세어지면, 나중에 validate_fact 가
    전체 대조로 막을 편의 진짜 근거를 미리 버리게 된다."""
    from engine import config
    from engine import report_evidence
    from engine import report_factsheet as rf

    real = "목표주가를 12만원으로 상향하며 투자의견 매수를 유지한다"
    # locate_chunk 는 **공백을 없앤** 앞머리 N자로 구제하므로, 위조도 그 기준으로 만든다.
    head = report_evidence._squash(real)[: config.EVIDENCE_QUOTE_MIN_CHARS]
    forged = head + "0만원까지 오른다고 단언했다"
    src = "리포트 본문. " + real + " 끝."

    # 청크 판정으로는 위조가 통과한다 — 그래서 그 함수를 쓰지 않는다.
    chunks = [{"chunk_id": "c0", "text": src}]
    assert report_evidence.locate_chunk(forged, chunks) != ""
    # 순위 판정은 통과시키지 않는다.
    assert rf._usable_refs({"source_refs": [{"quote": forged}]}, src) == 0
    assert rf._usable_refs({"source_refs": [{"quote": real}]}, src) == 1


def test_incomplete_response_message_separates_the_two_causes():
    """★ P2 지적: 온전한 응답에서 절이 빠진 것을 '잘렸다'고 말하면 운영자가 상한을 만진다.
    처방이 다르므로 문구를 가른다. 다만 **실패시키는 것 자체는 유지한다** — 빈 값으로 채우면
    '리포트가 리스크를 말하지 않았다'는 없는 주장을 우리가 지어내게 된다."""
    import pytest

    from engine import report_factsheet as rf
    from engine.llm import JSONParseError

    obj = {"company": "A", "what": [], "number_facts": []}
    with pytest.raises(JSONParseError, match="잘린"):
        rf._require_complete(dict(obj), salvaged=True)
    with pytest.raises(JSONParseError, match="스키마를 어겼다"):
        rf._require_complete(dict(obj), salvaged=False)


def test_gemini_retries_are_cut_short_when_a_fallback_exists():
    """★ P2 지적: 과부하가 *지연*으로 나타나면 4회 × 180초 ≈ 12분이라 15분 잡 상한 안에서
    폴백에 닿지 못한다. 갈아탈 곳이 있으면 짧게 끊는다."""
    import dataclasses

    import httpx
    import pytest

    from engine import config

    from engine import llm as llm_mod

    calls: list[str] = []

    fake_gemini = _retrying_stub(calls)

    monkey = pytest.MonkeyPatch()
    try:
        # ★ 폴백은 2026-08-29 부터 기본 꺼짐이다(운영자: 앤트로픽 연결 없음).
        #   기능 자체를 검사하는 이 테스트는 자기가 켠다 — 기본값을 되돌리면
        #   Gemini 크레딧 소진 429 에 폴백이 발동해 원인을 가리던 그날 사고가 돌아온다.
        monkey.setattr(config, "LLM_ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
        monkey.setattr(config, "ANTHROPIC_DISABLED", False)   # 차단 스위치도 함께 끈다
        monkey.setattr(llm_mod, "_gemini_create", fake_gemini)
        monkey.setattr(llm_mod, "_client", lambda: object())
        monkey.setattr(llm_mod, "_create",
                       lambda _c, *, model, **kw: '{"ok": 1}')
        monkey.setattr(config, "SECRETS",
                       dataclasses.replace(config.SECRETS, anthropic_api_key="sk-test"))
        assert llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u") == {"ok": 1}
    finally:
        monkey.undo()

    # 폴백이 있으므로 HTTP_MAX_RETRIES(4) 가 아니라 짧은 예산을 쓴다.
    assert len(calls) == config.GEMINI_ATTEMPTS_WITH_FALLBACK
    assert config.GEMINI_ATTEMPTS_WITH_FALLBACK < config.HTTP_MAX_RETRIES


def test_gemini_keeps_the_full_budget_without_a_fallback():
    """폴백이 없으면 끝까지 버틴다 — 짧게 끊으면 갈 곳도 없이 그냥 더 빨리 죽는다."""
    import dataclasses

    import httpx
    import pytest

    from engine import config
    from engine import llm as llm_mod

    calls: list[str] = []

    fake_gemini = _retrying_stub(calls)

    monkey = pytest.MonkeyPatch()
    try:
        # ★ 폴백은 2026-08-29 부터 기본 꺼짐이다(운영자: 앤트로픽 연결 없음).
        #   기능 자체를 검사하는 이 테스트는 자기가 켠다 — 기본값을 되돌리면
        #   Gemini 크레딧 소진 429 에 폴백이 발동해 원인을 가리던 그날 사고가 돌아온다.
        monkey.setattr(config, "LLM_ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
        monkey.setattr(config, "ANTHROPIC_DISABLED", False)   # 차단 스위치도 함께 끈다
        monkey.setattr(llm_mod, "_gemini_create", fake_gemini)
        monkey.setattr(config, "SECRETS",
                       dataclasses.replace(config.SECRETS, anthropic_api_key=""))
        with pytest.raises(httpx.TimeoutException):
            llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u")
    finally:
        monkey.undo()

    assert len(calls) == config.HTTP_MAX_RETRIES


# ── 리뷰 #90 12차 ────────────────────────────────────────────────────
def test_ranking_requires_the_quote_to_state_the_fact_value():
    """★ P2 지적: 원문의 진짜 문장이지만 **다른 숫자**를 말하는 인용을 '근거 있음'으로 세면,
    정작 그 값을 인용한 뒤엣것을 버리고 validate_fact 가 number_not_in_quote 로 편을 막는다."""
    from engine import report_factsheet as rf

    right = "목표주가를 12만원으로 상향한다"
    wrong = "전년 영업이익은 860억원을 기록했다"
    src = f"리포트 본문. {right} 그리고 {wrong} 끝."

    fact_right = {"value": 120000.0, "source_refs": [{"quote": right}]}
    fact_wrong = {"value": 120000.0, "source_refs": [{"quote": wrong}]}

    # 둘 다 원문에 **실재하는** 문장이다 — 실재만 보면 구별이 안 된다.
    from engine import report_evidence
    assert report_evidence.quote_found_in_source(wrong, src)
    # 값 대조까지 하면 갈린다.
    assert rf._usable_refs(fact_right, src) == 1
    assert rf._usable_refs(fact_wrong, src) == 0


def test_dedupe_prefers_the_duplicate_whose_quote_states_the_value():
    from engine import report_factsheet as rf

    right = "목표주가를 12만원으로 상향한다"
    wrong = "전년 영업이익은 860억원을 기록했다"
    src = f"리포트 본문. {right} 그리고 {wrong} 끝."

    def fact(fid, quote):
        return {"fact_id": fid, "metric": "목표주가", "value": 120000.0, "unit": "원",
                "period": "2026", "scope": "company", "display": "목표주가 12만원",
                "source_refs": [{"quote": quote}]}

    kept = rf._dedupe_semantic([fact("a", wrong), fact("b", right)], src)
    assert len(kept) == 1
    assert kept[0]["source_refs"][0]["quote"] == right


def test_value_check_is_skipped_for_nonnumeric_facts():
    """수치 없는 서술형 사실에는 값 대조를 걸지 않는다 — 대조할 값이 없다."""
    from engine import report_factsheet as rf

    quote = "LTA 장기공급계약을 체결했다고 밝혔다"
    src = "리포트 본문. " + quote + " 끝."
    assert rf._usable_refs({"value": None, "source_refs": [{"quote": quote}]}, src) == 1


# ── 리뷰 #90 13차 ────────────────────────────────────────────────────
def test_fallback_progress_only_when_the_step_is_absent():
    """★ P1 지적(실측 재현): prog 는 '단계 없음'과 '아직 시작 전'을 똑같이 0 으로 돌려준다.
    값으로 판단하면 NUMBER_BOARD 처럼 단계가 **있는** 보드에서 숫자가 먼저 떴다가 진짜
    number 단계가 시작되는 순간 되감긴다(0.293 → 0.033)."""
    from engine import board_motion as bm
    from engine import board_render as br

    number_tl = bm.build_timeline(list(bm.steps_for("NUMBER_BOARD")), 2.0)
    chart_tl = bm.build_timeline(list(bm.steps_for("CHART_BOARD")), 2.0)

    def prog_at(tl, t):
        def prog(name):
            s = tl.get(name)
            if not s or t < s.t0:
                return 0.0
            return min(1.0, (t - s.t0) / max(1e-6, s.t1 - s.t0))
        return prog

    # NUMBER_BOARD: number 단계가 **있다** → 시작 전이면 0 이어야 한다(빌려 쓰면 되감긴다).
    t = 0.37
    assert prog_at(number_tl, t)("title") > 0, "이 시각엔 title 이 이미 달리고 있어야 재현이 성립한다"
    assert br._step_prog(prog_at(number_tl, t), {"steps": number_tl}, "number") == 0.0

    # CHART_BOARD: number 단계가 **없다** → title 을 빌려 나타난다(폴백이 그려야 한다).
    assert br._step_prog(prog_at(chart_tl, t), {"steps": chart_tl}, "number") > 0


def test_gemini_4xx_does_not_fall_back():
    """★ P2 지적: 401/403(키 오류)·404(모델명 오타)를 폴백으로 덮으면 잡은 멀쩡해 보이면서
    영원히 의도치 않은 공급자로 돌고 설정 오류가 숨는다."""
    import dataclasses

    import httpx
    import pytest

    from engine import config
    from engine import llm as llm_mod

    calls: list[str] = []

    def fake_gemini(**kwargs):
        calls.append("gemini")
        raise httpx.HTTPStatusError(
            "404 Not Found", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(404))

    monkey = pytest.MonkeyPatch()
    try:
        # ★ 폴백은 2026-08-29 부터 기본 꺼짐이다(운영자: 앤트로픽 연결 없음).
        #   기능 자체를 검사하는 이 테스트는 자기가 켠다 — 기본값을 되돌리면
        #   Gemini 크레딧 소진 429 에 폴백이 발동해 원인을 가리던 그날 사고가 돌아온다.
        monkey.setattr(config, "LLM_ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
        monkey.setattr(config, "ANTHROPIC_DISABLED", False)   # 차단 스위치도 함께 끈다
        monkey.setattr(llm_mod, "_gemini_create", fake_gemini)
        monkey.setattr(llm_mod, "_client", lambda: object())
        monkey.setattr(llm_mod, "_create", lambda _c, *, model, **kw: '{"ok": 1}')
        monkey.setattr(config, "SECRETS",
                       dataclasses.replace(config.SECRETS, anthropic_api_key="sk-test"))
        with pytest.raises(httpx.HTTPStatusError):
            llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u")
    finally:
        monkey.undo()

    assert calls == ["gemini"], "설정 오류인데 anthropic 으로 넘어갔다"


def test_parse_retry_does_not_restart_gemini_after_falling_back():
    """★ P2 지적: 재시도 예산이 '요청당'이 아니라 '파싱 시도당'이 되고 있었다.

    gemini 가 타임아웃으로 죽어 anthropic 으로 갈아탔는데 그 응답의 JSON 이 깨지면,
    바깥 파싱 재시도 루프가 gemini 를 **처음부터 다시** 기다린다(2회 × 180초). 15분 잡
    안에서 두 번째 폴백에 닿지 못한다. 망가진 응답을 낸 쪽을 다시 부르는 것이 맞다.
    """
    import dataclasses

    import httpx
    import pytest

    from engine import config

    from engine import llm as llm_mod

    calls: list[str] = []
    anthropic_replies = ["깨진 JSON 이다", '{"ok": 1}']

    def fake_gemini(**kwargs):
        calls.append("gemini")
        raise httpx.TimeoutException("stalled")

    def fake_create(_client, *, model, **kw):
        calls.append(f"anthropic:{model}")
        return anthropic_replies.pop(0)

    monkey = pytest.MonkeyPatch()
    try:
        # ★ 폴백은 2026-08-29 부터 기본 꺼짐이다(운영자: 앤트로픽 연결 없음).
        #   기능 자체를 검사하는 이 테스트는 자기가 켠다 — 기본값을 되돌리면
        #   Gemini 크레딧 소진 429 에 폴백이 발동해 원인을 가리던 그날 사고가 돌아온다.
        monkey.setattr(config, "LLM_ANTHROPIC_FALLBACK_MODEL", "claude-sonnet-4-6")
        monkey.setattr(config, "ANTHROPIC_DISABLED", False)   # 차단 스위치도 함께 끈다
        fb = config.LLM_ANTHROPIC_FALLBACK_MODEL   # 켠 **뒤에** 읽는다
        monkey.setattr(llm_mod, "_gemini_create", fake_gemini)
        monkey.setattr(llm_mod, "_client", lambda: object())
        monkey.setattr(llm_mod, "_create", fake_create)
        monkey.setattr(config, "SECRETS",
                       dataclasses.replace(config.SECRETS, anthropic_api_key="sk-test"))
        assert llm_mod.call_json(model="gemini-2.5-pro", system="s", user="u") == {"ok": 1}
    finally:
        monkey.undo()

    # gemini 는 **한 번의 예산만** 쓴다. 두 번째 파싱 시도는 곧장 anthropic 으로 간다.
    assert calls == ["gemini", f"anthropic:{fb}", f"anthropic:{fb}"], calls
    assert calls.count("gemini") == 1, "폴백 뒤에도 gemini 를 처음부터 다시 기다렸다"
