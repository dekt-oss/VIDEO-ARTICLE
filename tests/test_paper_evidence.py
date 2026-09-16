"""논문 주장 ↔ 원문 대조 (engine/paper_evidence.py).

★ 이 파일이 고정하는 사고(2026-08-29 실측): 옥시토신 논문 영상의 컷3 이
  "이중맹검, 위약대조 방식으로 설계했다"고 말했는데 출처(초록)에는 그 말이 없었다.
  엔진의 환각이 아니라 **Fact Sheet 에 그렇게 적혀 있었고** 지시서가 충실히 화면에 실었다.
  화면 계약(photo_contract)은 "그림이 설명을 하는가"만 보지 "이 주장이 출처에 있는가"는
  보지 않는다 — 그 구멍을 여기서 막는다.
"""

from __future__ import annotations

from engine import config, paper_evidence as pe
from engine.directive import ungrounded_claim_cuts

# 실제 초록에서 따온 문장(출처: PubMed PMC13462352 / DOI 10.1073/pnas.2602655123).
SOURCE = ("Results show that OT administration significantly increased trusting behavior "
          "by roughly 15%, with consistent effects across regression models. A pooled data "
          "analysis incorporating a previous sample of low-trusting individuals further "
          "strengthens this conclusion.")


def _fs(*claims):
    return {"claims": list(claims)}


def _packet(text=SOURCE, depth="abstract_only"):
    return {"text": text, "source_depth": depth, "provider": "pmc",
            "char_count": len(text), "doc_hash": "h", "chunks": []}


def test_quote_actually_in_the_source_is_verified():
    fs = _fs({"claim_id": "C01", "evidence_grade": "B",
              "source_quote": "increased trusting behavior by roughly 15%"})
    pe.attach_evidence(fs, _packet())
    assert fs["claims"][0]["validation"]["quote_verified"] is True


def test_invented_quote_is_caught_and_the_claim_is_demoted():
    """★ 실측 사고의 회귀 테스트 — 초록에 없는 '이중맹검·위약대조'."""
    fs = _fs({"claim_id": "C02", "evidence_grade": "A",
              "source_quote": "a double-blind placebo-controlled crossover design"})
    pe.attach_evidence(fs, _packet())
    v = fs["claims"][0]["validation"]
    assert v["quote_verified"] is False
    assert v["grade_declared"] == "A"
    assert fs["claims"][0]["evidence_grade"] == config.EVIDENCE_GRADES[-1]
    assert any(r.startswith("claim_quote_not_in_source") for r in pe.block_reasons(fs))


def test_missing_source_is_unverifiable_not_failed():
    """원문이 없으면 quote_verified 는 False 가 아니라 None 이다.

    '대조했더니 없더라'와 '대조할 원문이 없었다'는 전혀 다른 사실이다. 섞으면 확보 실패한
    논문(실측 확보율 63% → 열 편 중 네 편)이 전부 거짓말쟁이로 기록된다.
    """
    fs = _fs({"claim_id": "C01", "evidence_grade": "A", "source_quote": "무엇이든"})
    pe.attach_evidence(fs, {"text": "", "source_depth": "none"})
    v = fs["claims"][0]["validation"]
    assert v["quote_verified"] is None
    assert pe.block_reasons(fs) == []                  # 판정 불가는 차단하지 않는다
    assert pe.audit(fs)["unverifiable"] == 1
    assert pe.audit(fs)["verify_rate"] is None         # 0.0 이 아니다


def test_abstract_only_cannot_carry_grade_a():
    """factsheet 프롬프트가 이미 같은 말을 했지만 지시일 뿐 검사가 없었다."""
    fs = _fs({"claim_id": "C01", "evidence_grade": "A",
              "source_quote": "increased trusting behavior by roughly 15%"})
    pe.attach_evidence(fs, _packet(depth="abstract_only"))
    assert fs["claims"][0]["evidence_grade"] == "B"


def test_full_body_may_keep_grade_a():
    fs = _fs({"claim_id": "C01", "evidence_grade": "A",
              "source_quote": "increased trusting behavior by roughly 15%"})
    pe.attach_evidence(fs, _packet(depth="full_body"))
    assert fs["claims"][0]["evidence_grade"] == "A"


def test_code_never_promotes_a_grade():
    """대조가 확인해 주는 것은 '인용문이 원문에 있다'뿐이다. 그 이상을 주장하지 않는다."""
    fs = _fs({"claim_id": "C01", "evidence_grade": "C",
              "source_quote": "increased trusting behavior by roughly 15%"})
    pe.attach_evidence(fs, _packet(depth="full_body"))
    assert fs["claims"][0]["evidence_grade"] == "C"


def test_provenance_is_recorded_on_the_fact_sheet():
    fs = _fs({"claim_id": "C01", "evidence_grade": "B", "source_quote": "x"})
    pe.attach_evidence(fs, _packet(depth="partial_body"))
    prov = fs["source_provenance"]
    assert prov["source_depth"] == "partial_body" and prov["provider"] == "pmc"


def test_directive_blocks_the_cut_that_pays_an_ungrounded_claim():
    """초안에서 무너진 주장을 컷이 집어 오면 지시서 단계에서 한 번 더 잡는다."""
    fs = _fs({"claim_id": "C01", "evidence_grade": "B",
              "source_quote": "increased trusting behavior by roughly 15%"},
             {"claim_id": "C02", "evidence_grade": "A",
              "source_quote": "a double-blind placebo-controlled crossover design"})
    pe.attach_evidence(fs, _packet())
    cuts = [{"cut_no": 3, "claim_ids": ["C02"]}, {"cut_no": 5, "claim_ids": ["C01"]}]
    got = ungrounded_claim_cuts(cuts, fs)
    assert got == ["cut_claim_not_in_source:3"]


def test_directive_does_not_block_when_the_source_was_never_available():
    fs = _fs({"claim_id": "C01", "evidence_grade": "A", "source_quote": "무엇이든"})
    pe.attach_evidence(fs, {"text": "", "source_depth": "none"})
    assert ungrounded_claim_cuts([{"cut_no": 1, "claim_ids": ["C01"]}], fs) == []


def test_reason_codes_have_web_labels():
    """사유 코드는 Python 이 정본이고 web 이 표시 문자열을 미러한다(저장소 관례)."""
    labels = open("web/lib/blockLabels.ts", encoding="utf-8").read()
    for code in (*pe.CLAIM_BLOCK_REASONS, "cut_claim_not_in_source"):
        assert f"{code}:" in labels, code


def test_unverified_draft_is_warned_not_silently_passed():
    """★ 엣지 경로 초안에는 validation 이 없다 — 그것이 '위반 0건'으로 보이면 안 된다.

    검증을 통과한 것과 검증을 안 한 것이 같은 화면으로 보이는 것이 가장 위험하다.
    다만 차단은 하지 않는다: 오늘 대시보드 [초안 생성] 버튼이 그 경로다.
    """
    from engine.directive import claim_evidence_warnings

    raw = {"claims": [{"claim_id": "C01", "evidence_grade": "A", "source_quote": "x"}]}
    assert claim_evidence_warnings(raw) == ["claim_evidence_not_run"]
    assert ungrounded_claim_cuts([{"cut_no": 1, "claim_ids": ["C01"]}], raw) == []

    pe.attach_evidence(raw, _packet())
    assert claim_evidence_warnings(raw) == []      # 대조가 돌면 경고가 사라진다


def test_no_claims_means_no_warning():
    from engine.directive import claim_evidence_warnings
    assert claim_evidence_warnings({"claims": []}) == []
    assert claim_evidence_warnings(None) == []


def test_abstract_is_used_as_the_source_when_full_text_is_missing():
    """★ 실측: 확보 실패 시 claim 5개가 전부 '판정 불가'로 나왔다 — 그런데 모델이 붙인
    인용문은 초록에 그대로 있는 문장들이었다. 우리는 초록을 갖고 있으면서 안 쓰고 있었다.

    그리고 이 구멍이 정확히 오늘의 사고를 놓친다: '이중맹검·위약대조'는 초록에 없는 말이라
    초록만으로도 잡을 수 있었다.
    """
    pk = pe.verification_packet({"text": "", "source_depth": "none"}, SOURCE)
    assert pk["text"] == SOURCE
    assert pk["source_depth"] == "abstract_only"
    assert pk["provider"] == "abstract"

    good = _fs({"claim_id": "C01", "evidence_grade": "A",
                "source_quote": "increased trusting behavior by roughly 15%"})
    pe.attach_evidence(good, pk)
    assert good["claims"][0]["validation"]["quote_verified"] is True
    assert good["claims"][0]["evidence_grade"] == "B"      # 초록은 A 를 못 단다

    bad = _fs({"claim_id": "C02", "evidence_grade": "A",
               "source_quote": "a double-blind placebo-controlled crossover design"})
    pe.attach_evidence(bad, pk)
    assert bad["claims"][0]["validation"]["quote_verified"] is False


def test_full_text_wins_over_the_abstract():
    pk = pe.verification_packet(_packet(text="본문 전문", depth="full_body"), "초록")
    assert pk["text"] == "본문 전문" and pk["source_depth"] == "full_body"


def test_no_abstract_and_no_text_stays_unverifiable():
    pk = pe.verification_packet({"text": "", "source_depth": "none"}, "")
    fs = _fs({"claim_id": "C01", "evidence_grade": "A", "source_quote": "x"})
    pe.attach_evidence(fs, pk)
    assert fs["claims"][0]["validation"]["quote_verified"] is None


# ── 인용 대조의 관용 (2026-08-29 실측) ─────────────────────────────
def test_markup_differences_do_not_fail_a_correct_quote():
    r"""★ 실측: arXiv 원문의 LaTeX·활자 따옴표를 모델이 조금 다르게 옮겨 정상 주장 5개가
    "지어낸 인용"으로 차단됐다. 인용은 정확했고 표기만 달랐다.

        모델 ``Ghost Riders''  /  원문 “Ghost Riders”
        모델 $\sim$7 min      /  원문 \sim7 min
    """
    from engine.report_evidence import quote_found_in_source as q

    src = (r'Backward propagation of its orbit independently links the object to the '
           r'“Ghost Riders in the Sky” launch, while visible spectroscopy '
           r'reveals a change of more than 8 s in its \sim7 min rotation period.')
    assert q("Backward propagation of its orbit independently links the object to the "
             "``Ghost Riders in the Sky'' launch", src)
    assert q(r"a change of more than 8 s in its $\sim$7 min rotation period", src)


def test_a_footnote_number_mismatch_does_not_fail_the_quote():
    """★ 실측: 초록의 각주 $^{1}$ 가 본문에선 9번이었다. 130자 중 129자가 일치했는데
    그 하나 때문에 정상 주장이 차단됐다. 각주 번호는 인용의 내용이 아니다."""
    from engine.report_evidence import quote_found_in_source as q

    src = "some of which will ultimately impact the Moon9 The ultimate fate of rocket stages"
    assert q("some of which will ultimately impact the Moon$^{1}$", src)


def test_a_fabricated_quote_still_fails():
    """관용은 표기 차이에만 준다 — 의역·날조는 여전히 잡혀야 한다.

    이게 깨지면 이 검증은 아무것도 보증하지 않는다.
    """
    from engine.report_evidence import quote_found_in_source as q

    src = ("Results show that OT administration significantly increased trusting "
           "behavior by roughly 15%, with consistent effects across regression models.")
    assert not q("a double-blind placebo-controlled crossover design was used", src)
    assert not q("OT administration had no effect on trusting behavior at all", src)
    # 의역(같은 뜻·다른 낱말)도 통과하면 안 된다.
    assert not q("The study found oxytocin raised trust by about fifteen percent", src)


def test_a_quote_too_short_to_mean_anything_is_rejected():
    from engine.report_evidence import quote_found_in_source as q
    assert not q("the", "the quick brown fox jumps over the lazy dog")
