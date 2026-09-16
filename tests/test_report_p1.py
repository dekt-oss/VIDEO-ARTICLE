"""리포트 PF1 순수 로직 테스트 — 정규화 + 컴플라이언스 게이트. 네트워크/LLM 없음."""

from engine import config
from engine.report_attribution import build_source, build_publish_caption
from engine.report_compliance import check, scan_rules, script_text
from engine.report_factsheet import normalize_factsheet
from engine.report_scriptgen import normalize_script
from engine.report_selfcheck import normalize_selfcheck


# ── 정규화 (논문 test_p1.py 패턴 미러) ──────────────────────────────

def test_normalize_factsheet_coerces_lists():
    fs = normalize_factsheet({
        "company": "SK하이닉스",
        "what": "단일 주장",                 # 문자열 → 리스트
        "numbers": ["목표가 9만원", 42],      # 레거시 문자열 → number_facts 합성 + numbers 파생
        "opinion": "매수",
        # basis/risks 누락 → []
    })
    assert fs["company"] == "SK하이닉스"
    assert fs["what"] == ["단일 주장"]
    # ★ back-compat: numbers 는 여전히 list[str](display 파생) — 기존 소비자 계약 불변.
    assert fs["numbers"] == ["목표가 9만원", "42"]
    assert fs["basis"] == [] and fs["risks"] == []
    assert fs["opinion"] == "매수"
    # Phase 1: 레거시 문자열도 구조화 number_facts 로 합성(fact_id 부여).
    assert [nf["fact_id"] for nf in fs["number_facts"]] == ["num_0", "num_1"]
    assert fs["number_facts"][0]["display"] == "목표가 9만원"
    assert fs["number_facts"][0]["value"] is None            # 문자열은 값 없음


def test_normalize_factsheet_structured_number_facts():
    """Phase 1: 구조화 number_facts 입력 → 정규화 + numbers 파생 + fact_id 유일성."""
    fs = normalize_factsheet({
        "company": "LS ELECTRIC",
        "number_facts": [
            {"fact_id": "num_per_2026", "value": "48.6", "unit": "x", "period": "2026F",
             "metric": "PER", "basis": "broker_estimate", "attribution": "유안타증권",
             "interpretation": "valuation_risk", "source_page": 17, "display": "2026F PER 48.6배"},
            {"value": 1654, "unit": "억", "metric": "영업이익", "period": "2Q26E"},  # fact_id·display 누락
            {"fact_id": "num_per_2026", "value": 50, "metric": "PER"},              # 중복 id
        ],
    })
    nf = fs["number_facts"]
    assert nf[0]["fact_id"] == "num_per_2026" and nf[0]["value"] == 48.6 and nf[0]["unit"] == "x"
    assert nf[1]["fact_id"] == "num_1"                        # 누락 시 인덱스 기반
    assert nf[1]["display"] == "영업이익 1654억 2Q26E"          # metric+value+unit+period 합성
    assert nf[2]["fact_id"] == "num_per_2026_1"               # 중복 → 접미로 유일화
    assert fs["numbers"] == [nf[0]["display"], nf[1]["display"], nf[2]["display"]]  # numbers 파생


def test_normalize_script_defaults_and_legacy_fallback():
    sc = normalize_script({
        "upload_title_ko": "제목",
        "script_md": "본문",
        "video_flow": {"total_duration_sec": "60", "beats": ["garbage", {"order": "1", "label": "훅"}]},
        "scenes": [
            "notadict",
            {"scene": "2", "narration_ko": "나레", "duration_sec": "3",
             "visual_prompt": "레거시", "source_facts": "numbers[0]"},
        ],
    })
    assert sc["video_flow"]["total_duration_sec"] == 60      # int 강제
    assert sc["video_flow"]["beats"] == [{"order": 1, "label": "훅", "summary": "", "transition": ""}]
    assert len(sc["scenes"]) == 1                            # 비dict 드롭
    s = sc["scenes"][0]
    assert s["scene"] == 2 and s["duration_sec"] == 3
    assert s["video_prompt"] == "레거시"                     # visual_prompt → video_prompt 폴백
    assert s["source_facts"] == ["numbers[0]"]               # 문자열 → 리스트


def test_normalize_selfcheck_recomputes_all_grounded():
    # LLM 이 grounded/all_grounded=true 라 해도 unsupported 있으면 강등.
    out = normalize_selfcheck({
        "scenes": [{"scene": 1, "grounded": True, "unsupported": ["근거 없는 문장"]}],
        "all_grounded": True,
    })
    assert out["scenes"][0]["grounded"] is False
    assert out["all_grounded"] is False


# ── 컴플라이언스 게이트 (명세 §5) ──────────────────────────────────

def _clean_script(md: str):
    """면책·출처 포함 + 위반 없는 대본(통과 기준)."""
    return {"script_md": md, "scenes": []}


def test_scan_rules_flags_investment_solicitation():
    text = "이 종목 지금 사세요. 비중 확대 추천."
    flags = scan_rules(text, broker="OO증권")
    cats = {f["category"] for f in flags}
    assert "투자권유" in cats
    assert any(f["severity"] == "block" for f in flags)


def test_scan_rules_flags_unrealized_return_and_certainty():
    text = "목표가 대비 +35% 상승여력. 무조건 오릅니다."
    flags = scan_rules(text, broker="")
    cats = {f["category"] for f in flags}
    assert "미실현수익률" in cats
    assert "단정예측" in cats


def test_scan_rules_flags_missing_source_and_disclaimer():
    text = "삼성전자 실적이 좋았습니다."          # 출처(broker) 없음 + 면책 없음
    flags = scan_rules(text, broker="신한투자증권")
    cats = {f["category"] for f in flags}
    assert "출처누락" in cats                       # broker 문자열 부재
    assert "면책누락" in cats                       # 면책 어구 부재


def test_scan_rules_passes_clean_script():
    text = (
        "신한투자증권에 따르면 SK하이닉스 목표가는 9만원이다. "
        "리스크는 밸류에이션 부담이다. "
        "본 영상은 정보 제공 목적이며 투자 권유가 아닙니다. 판단과 책임은 본인에게."
    )
    flags = scan_rules(text, broker="신한투자증권")
    assert [f for f in flags if f["severity"] == "block"] == []


def test_check_never_blocks_but_keeps_flags(monkeypatch):
    # 하드 차단 제거: 규칙 위반·환각이 있어도 blocked=False, 플래그는 참고용으로 남는다.
    import engine.report_compliance as rc
    # LLM 심사관은 네트워크라 위반 판정을 반환하도록 대체(그래도 차단되지 않아야 함).
    monkeypatch.setattr(rc, "_llm_judge", lambda text: {
        "권유": "yes", "수익률광고": "yes", "단정": "yes", "출처": "missing", "면책": "missing", "근거": "테스트"})
    script = {
        "script_md": "지금 사라. 무조건 오른다.",   # 투자권유+단정(규칙 위반)
        "scenes": [{"scene": 1, "narration_ko": "지금 사라"}],
    }
    self_check = {"scenes": [{"scene": 1, "grounded": False, "unsupported": ["지금 사라"]}]}
    result = rc.check({}, script, self_check, broker="OO증권")
    assert result["blocked"] is False                      # 위반이 있어도 절대 차단하지 않음
    assert len(result["rule_flags"]) > 0                    # 규칙 플래그는 참고용으로 남음
    assert result["hallucination_flags"]                   # 근거없음 플래그도 남음


def test_script_text_concatenates_narration():
    script = {"script_md": "본문", "scenes": [{"narration_ko": "나레1"}, {"narration_ko": "나레2"}]}
    text = script_text(script)
    assert "본문" in text and "나레1" in text and "나레2" in text


# ── 출처/면책 (attribution) ────────────────────────────────────────

def test_build_source_and_disclaimer():
    src = build_source({"broker": "신한투자증권", "analyst": "김형태",
                        "company": "SK하이닉스", "opinion": "매수", "report_url": "https://x"})
    assert src["broker"] == "신한투자증권"
    assert src["disclaimer"] == config.REPORT_DISCLAIMER_TEXT   # 면책 고정


def test_publish_caption_always_includes_disclaimer():
    cap = build_publish_caption(build_source({"broker": "OO증권", "company": "삼성전자"}), teaser="티저")
    assert "OO증권" in cap
    assert "투자 권유가 아" in cap                              # 면책 항상 포함
