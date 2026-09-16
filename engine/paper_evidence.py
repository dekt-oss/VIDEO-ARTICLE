"""논문 주장 ↔ 원문 대조 (설명엔진 v2 §5 · 2026-08-29).

무엇을 푸는가: 논문 라인의 Fact Sheet 는 claim 마다 `source_quote`·`source_section`·
`evidence_grade` 를 **가지고 있었는데 아무도 대조하지 않았다.** 모델이 "본문에서 확인했고
등급은 A"라고 쓰면 그대로 화면까지 갔다.

2026-08-29 실측이 이 구멍을 정확히 보여줬다. 옥시토신 논문 지시서의 컷3 이
"이중맹검, 위약대조 방식으로 설계했다"고 말하는데 **출처(초록)에는 그 말이 없다.**
추적하니 Fact Sheet 의 claim 에 그렇게 적혀 있었고 지시서는 충실히 화면에 실었다.
즉 화면 계약(engine/photo_contract.py)을 아무리 조여도 **Fact Sheet 가 틀리면 전부
통과한다.** 화면 계약은 "그림이 설명을 하는가"를 보지 "이 주장이 출처에 있는가"는 보지 않는다.

여기서 그것을 코드가 판정한다. 리포트 라인이 이미 같은 전환을 했고
(engine/report_evidence.py), 그 대조 기계를 **재사용한다** — 인용 대조·청크 위치 찾기는
논문이든 리포트든 같은 문제다. 두 벌로 만들면 한쪽만 고쳐지는 날이 온다.

자세(저장소 규율 그대로):
- **코드가 판정한다.** 모델의 evidence_grade 자기보고를 믿지 않고 재계산한다.
- **판정 불가와 실패를 섞지 않는다.** 원문이 없으면 `verified` 는 False 가 아니라 None 이다.
  "대조했더니 없더라"와 "대조할 원문이 없었다"는 전혀 다른 사실이고, 섞으면 확보 실패한
  논문이 전부 거짓말쟁이로 기록된다.
- **순수 모듈.** 네트워크·DB 를 모른다. 입력은 Fact Sheet 와 source packet 뿐이다.

★ 왜 등급을 낮추기만 하고 올리지는 않는가: 모델이 C 라고 쓴 것을 코드가 A 로 올리려면
  "이 인용이 정말 그 주장을 지지하는가"를 판단해야 하는데 그것은 문자열 대조로 안 된다.
  대조가 확인해 주는 것은 **인용문이 원문에 있다**는 사실뿐이다. 그 이상을 주장하지 않는다.
"""

from __future__ import annotations

from typing import Any

from . import config, report_evidence

# 원문 확보 수준별로 **허용되는 최고 등급**. abstract_only 인데 A 를 달 수는 없다.
#   ★ factsheet.py 가 이미 프롬프트로 같은 말을 하고 있었지만(§"초록만 주어졌으면 A 를 쓰지
#     마라") 지시일 뿐 검사가 없었다. 여기서 코드가 강제한다.
DEPTH_GRADE_CEILING: dict[str, str] = {
    "full_body": "A",
    "partial_body": "A",
    "abstract_only": "B",
    "parse_failed": "C",
    "none": "C",
}

# 사유 코드(정본). 화면 계약과 같은 방식으로 web 이 표시 문자열을 미러한다.
CLAIM_BLOCK_REASONS: tuple[str, ...] = (
    "claim_quote_not_in_source",   # 인용문이 원문에 없다 — 지어낸 인용
    "claim_without_quote",         # 원문이 있는데 인용을 안 붙였다
)

# 근거 상태 — **셋을 구분한다**(코덱스 리뷰 §5). 둘로 뭉치면 확보 실패가 거짓말로 둔갑한다.
EVIDENCE_STATES: tuple[str, ...] = (
    "SUPPORTED",                      # 대조했고 원문에 있다
    "UNSUPPORTED",                    # 대조했더니 원문에 없다 — 지어낸 인용
    "UNVERIFIABLE_AT_CURRENT_DEPTH",  # 대조할 원문이 그만큼 없다 — 주장의 잘못이 아니다
)


def verification_packet(packet: dict[str, Any] | None,
                        abstract: str | None) -> dict[str, Any]:
    """대조에 쓸 원문. 전문이 없으면 **초록을 원문으로 삼는다**.

    ★ 왜 필요한가(2026-08-29 실측): 확보 체인이 실패하면 packet.text 가 비고, 그러면 코드가
      "대조할 원문이 없다"고 판정해 **모든 주장이 판정 불가**가 된다. 실제로 옥시토신 논문에서
      claim 5개 전부 `??` 로 나왔는데, 모델이 붙인 인용문은 **초록에 그대로 있는 문장들**이었다.
      우리는 초록을 갖고 있으면서 안 쓰고 있었던 것이다.

      그리고 이 구멍이 정확히 오늘의 사고를 놓친다: "이중맹검·위약대조"는 **초록에 없는 말**이라
      초록만으로도 잡을 수 있었다. 전문이 없다고 대조를 포기하면 잡을 수 있는 것도 못 잡는다.

    ★ 확보 수준은 그대로 abstract_only 다 — 초록을 원문으로 쓴다고 근거가 두꺼워지지 않는다.
      provider 에 'abstract' 를 남겨 무엇을 대조했는지가 행에 보이게 한다.
    """
    packet = dict(packet or {})
    if packet.get("text"):
        return packet
    text = (abstract or "").strip()
    if not text:
        return packet                      # 초록조차 없다 — 진짜로 판정 불가
    return {
        **packet,
        "text": text,
        "chunks": [],
        "provider": packet.get("provider") or "abstract",
        "source_depth": "abstract_only",
        "char_count": len(text),
    }


def _ceiling_for(depth: str) -> str:
    return DEPTH_GRADE_CEILING.get(str(depth or "none"), "C")


def _cap_grade(grade: Any, ceiling: str) -> str:
    """등급을 상한 아래로 끌어내린다. 올리지는 않는다."""
    g = str(grade or "").strip().upper()
    if g not in config.EVIDENCE_GRADES:
        g = "D"
    grades = list(config.EVIDENCE_GRADES)          # ("A","B","C","D") — 앞이 높다
    if grades.index(g) < grades.index(ceiling):
        return ceiling
    return g


def verify_claim(claim: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    """claim 하나 → validation dict. claim 을 건드리지 않는 순수 판정.

    반환:
      quote_present   인용문을 붙였는가
      quote_verified  True/False/None — None 은 **대조할 원문이 없었다**는 뜻
      chunk_id        인용문이 실제로 들어 있는 청크(모델 라벨이 아니라 위치로 찾은 것)
      grade_declared  모델이 쓴 등급
      grade_effective 코드가 확보 수준·대조 결과로 조정한 등급
    """
    packet = packet or {}
    source_text = str(packet.get("text") or "")
    depth = str(packet.get("source_depth") or "none")
    quote = str(claim.get("source_quote") or "").strip()

    quote_present = bool(quote)
    if not source_text:
        quote_verified: bool | None = None          # 판정 불가 — 실패가 아니다
        chunk_id = ""
    elif not quote_present:
        quote_verified = False
        chunk_id = ""
    else:
        quote_verified = report_evidence.quote_found_in_source(quote, source_text)
        chunk_id = report_evidence.locate_chunk(quote, packet.get("chunks"))

    ceiling = _ceiling_for(depth)
    effective = _cap_grade(claim.get("evidence_grade"), ceiling)
    # 인용이 원문에 **없다고 확인된** 주장은 근거가 없는 것과 같다 — 최하 등급으로 내린다.
    #   판정 불가(None)는 내리지 않는다. 확보 실패를 주장의 잘못으로 기록하면 안 된다.
    if quote_verified is False:
        effective = config.EVIDENCE_GRADES[-1]
    return {
        "quote_present": quote_present,
        "quote_verified": quote_verified,
        "chunk_id": chunk_id,
        "grade_declared": str(claim.get("evidence_grade") or ""),
        "grade_effective": effective,
        "source_depth": depth,
        # ★ 셋을 구분한다(코덱스 리뷰 §5). `quote_verified` 의 True/False/None 과 같은 정보를
        #   **이름 붙여** 남긴다 — 소비자가 None 을 False 로 읽는 사고를 막는다.
        "evidence_state": ("SUPPORTED" if quote_verified is True else
                           "UNSUPPORTED" if quote_verified is False else
                           "UNVERIFIABLE_AT_CURRENT_DEPTH"),
        # ★★ 계약 버전. **저장된 판정은 검증 코드보다 오래 산다**(코덱스 리뷰 §4, 2026-08-30).
        #
        #   실측: 골든B 의 fact_sheet 에 `quote_verified:false` 4건이 박혀 있어 지시서 단계가
        #   정상 컷 4개를 차단했다. 그런데 **지금 코드로 재대조하면 10/10 통과한다**(최저 0.992).
        #   그 false 는 커밋 c681613(연속 일치 비율 도입) **이전** 코드가 쓴 값이었다.
        #   대조 알고리즘이 아니라 원장의 신선도가 문제였던 것이다.
        #
        #   그래서 판정에 버전을 찍는다. 버전이 다른 판정은 소비자가 **거짓이 아니라 판정
        #   불가**로 다뤄야 한다 — "판정 불가와 실패를 섞지 않는다"를 시간 축으로 넓힌 것이다.
        "contract_version": config.EVIDENCE_CONTRACT_VERSION,
    }


def is_current(validation: Any) -> bool:
    """이 판정이 **지금 계약으로** 내려진 것인가. 아니면 판정 불가로 다뤄야 한다."""
    return (isinstance(validation, dict)
            and validation.get("contract_version") == config.EVIDENCE_CONTRACT_VERSION)


def attach_evidence(fact_sheet: dict[str, Any],
                    packet: dict[str, Any] | None) -> dict[str, Any]:
    """Fact Sheet 의 claims 에 코드 판정을 붙인다(제자리 갱신 후 반환).

    기존 필드는 건드리지 않는다 — 대시보드·지시서가 이미 읽고 있다. `validation` 을 더하고
    `evidence_grade` 만 **효력 등급으로 바꾼다**(선언 등급은 validation 안에 남는다).
    """
    packet = packet or {}
    claims = fact_sheet.get("claims")
    if not isinstance(claims, list):
        return fact_sheet
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        v = verify_claim(claim, packet)
        claim["validation"] = v
        claim["evidence_grade"] = v["grade_effective"]
    fact_sheet["source_provenance"] = {
        "source_depth": str(packet.get("source_depth") or "none"),
        "provider": str(packet.get("provider") or "none"),
        "char_count": int(packet.get("char_count") or 0),
        "doc_hash": str(packet.get("doc_hash") or ""),
        "parse_error": str(packet.get("parse_error") or ""),
    }
    return fact_sheet


def audit(fact_sheet: dict[str, Any]) -> dict[str, Any]:
    """대조 결과 요약. 승인 화면과 로그가 같은 숫자를 보게 한다.

    ★ verify_rate 는 **대조 가능했던 것 중** 비율이다. 원문이 없어 판정 불가한 주장은
      분모에서 빠지고 `unverifiable` 로 따로 센다 — 섞으면 "확보 실패"가 "검증 실패"로
      둔갑한다(report_reasoning.quote_verify_rate 가 None 을 쓰는 것과 같은 이유).
    """
    claims = [c for c in (fact_sheet.get("claims") or []) if isinstance(c, dict)]
    checked = [c for c in claims
               if (c.get("validation") or {}).get("quote_verified") is not None]
    verified = [c for c in checked
                if (c.get("validation") or {}).get("quote_verified") is True]
    return {
        "claims": len(claims),
        "checked": len(checked),
        "verified": len(verified),
        "unverifiable": len(claims) - len(checked),
        "verify_rate": (round(len(verified) / len(checked), 3) if checked else None),
        "source_depth": (fact_sheet.get("source_provenance") or {}).get("source_depth", "none"),
    }


def block_reasons(fact_sheet: dict[str, Any]) -> list[str]:
    """화면에 나가면 안 되는 주장들. 사유 코드 리스트(사람 말 라벨은 web 이 붙인다).

    ★ **판정 불가는 차단하지 않는다.** 원문 확보율이 63% 라(docs/실측_0ABC_설명엔진.md)
      전부 막으면 열 편 중 네 편이 통째로 멈춘다. 확보 실패는 등급 상한(B 이하)으로 다루고,
      운영자는 audit 의 source_depth 로 그 사실을 본다.
    ★ 차단하는 것은 **대조했더니 없더라**는 경우뿐이다 — 그건 지어낸 인용이다.
    ★ 그리고 **낡은 계약으로 내려진 판정도 차단하지 않는다**(코덱스 리뷰 §4). 골든B 가
      그것으로 정상 컷 4개를 잃었다 — 지금 코드로는 통과하는 주장들이었다. 판정을 저장하면
      검증 코드보다 오래 사므로, 버전이 다른 판정은 판정 불가로 되돌린다.
    """
    out: list[str] = []
    bad_quote: list[str] = []
    no_quote: list[str] = []
    for c in (fact_sheet.get("claims") or []):
        if not isinstance(c, dict):
            continue
        v = c.get("validation") or {}
        cid = str(c.get("claim_id") or "?")
        if not is_current(v):
            continue
        if v.get("quote_verified") is False:
            (bad_quote if v.get("quote_present") else no_quote).append(cid)
    if bad_quote:
        out.append("claim_quote_not_in_source:" + ",".join(sorted(bad_quote)[:6]))
    if no_quote:
        out.append("claim_without_quote:" + ",".join(sorted(no_quote)[:6]))
    return out
