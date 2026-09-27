"""지시서 ↔ 기초 자료 대조 — **최종 나레이션이 근거를 벗어나지 않았는가**.

무엇을 푸는가(운영자 질문 2026-09-05): "우리의 기초 자료와 전체 완성된 지시서의 설명내용이
일치하는지 한번 점검하는 작업도 있어??" — **없었다.**

실측으로 확인한 구멍:
  · `selfcheck.check`(대본↔Fact Sheet 대조)는 **초안 단계에서만** 돈다(engine/draft.py).
  · 그런데 지시서 LLM 은 나레이션을 **다시 쓴다**(실측: 14개 중 3개가 새 문장이었고
    그 3개가 전부 훅·도입부였다 — 과장 위험이 가장 큰 자리다).
  · 운영자가 ⑤ 화면에서 손으로 고친 문장은 **어떤 검증도 거치지 않는다.**
  · 지시서 경로 어디에도 나레이션 검증 호출이 없다(grep 0건).

★ 이 모듈은 **LLM 을 쓰지 않는다.** 돈이 들지 않으므로 지시서를 만질 때마다 돌릴 수 있고,
  기계가 확신할 수 있는 것만 본다:
    ① 숫자 — 화면·나레이션의 수치가 Fact Sheet 에 있는가(지어낸 숫자가 가장 위험하다)
    ② 주장 — 컷이 가리키는 claim_id 가 원장에 실재하는가
    ③ 단서 — 원장이 "쥐/일부/평균"이라 한 것을 지시서가 지웠는가
    ④ 인과 — 원장이 association_only 인데 지시서가 "때문에·막는다"로 말했는가
  의미 수준의 과장(범위 확대·논리 비약)은 LLM 판정이 필요하다 — 그건 selfcheck 가 한다.
  여기서 잡는 것과 거기서 잡는 것은 **다른 층위**이고, 둘 다 필요하다.
"""

from __future__ import annotations

import re
from typing import Any

from . import config

# 숫자 + 단위. 연도·순번은 단위가 없어 대부분 걸러진다.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|퍼센트|배|일|년|개월|주|시간|분|초|"
                  r"명|마리|건|개|억|조|만|천|원|달러|mg|kg|g|km|m|cm)?")
# 사람 대상으로 넘겼는지 — 동물 연구에서 가장 흔한 과장.
_HUMAN = re.compile(r"(우리|사람|인간|당신|환자)(?:도|은|는|이|가|에게|의)")
_ANIMAL = re.compile(r"(쥐|생쥐|마우스|동물|mice|mouse)", re.I)
# 인과를 단정하는 말.
_CAUSAL = re.compile(r"(때문에|덕분에|막는다|막아|없앤다|치료한다|낫게|유발한다|만든다)")
# 유보·한계를 나타내는 말. 이런 문장은 사람을 주어로 써도 옳다.
_HEDGE = re.compile(r"(아직|여부|필요|모른|불분명|가능성|기대|추가 연구|임상 연구|장기적)")


def _bare(n: str) -> float | None:
    """'92일' → 92.0. 단위를 떼고 수만 남긴다."""
    m = re.match(r"[\d.]+", re.sub(r",", "", n))
    try:
        return float(m.group(0)) if m else None
    except ValueError:
        return None


def _derivable(n: str, pool: set[float]) -> bool:
    """원장 수치 두 개의 차 또는 합으로 만들어지는 값인가.

    ★ 왜 필요한가: 논문은 중앙 수명 742일·834일을 보고하는데 우리 훅은 '92일 더'라고 말한다.
      그건 우리가 뺀 값이다 — 지어낸 것과는 다르게 다뤄야 한다.
    """
    v = _bare(n)
    if v is None:
        return False
    xs = sorted(pool)
    for i, a in enumerate(xs):
        for b in xs[i:]:
            if abs(abs(b - a) - v) < 1e-6 or abs((a + b) - v) < 1e-6:
                return True
    return False


def _norm_num(t: str) -> str:
    """비교용 정규화 — 쉼표·공백을 지우고 숫자만 남긴다."""
    return re.sub(r"[,\s]", "", t)


def _numbers(text: str) -> set[str]:
    return {_norm_num(m.group(0)) for m in _NUM.finditer(str(text or ""))
            if any(ch.isdigit() for ch in m.group(0))}


def source_numbers(fact_sheet: dict[str, Any] | None) -> set[str]:
    """Fact Sheet 전체가 지불하는 숫자 집합(문자열 값과 숫자 값을 전부 훑는다).

    ★ 숫자 값도 센다(2026-09-25). 리포트 Fact Sheet 는 수치를 `number_facts[].value` 에
      **float** 로 둔다(목표주가 9000.0). 문자열만 훑으면 영문 나레이션의 "9,000" 이
      "Fact Sheet 에 없다"(빨강)가 됐다 — 원장에 있는 숫자다.
    """
    out: set[str] = set()

    def walk(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            out.add(str(int(v)) if float(v).is_integer() else f"{v:g}")
        elif isinstance(v, str):
            out.update(_numbers(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(fact_sheet or {})
    return out


def audit(header: dict[str, Any], cuts: list[dict[str, Any]],
          fact_sheet: dict[str, Any] | None) -> dict[str, Any]:
    """지시서 → {findings[], stats}. 순수 함수, 네트워크·LLM 없음.

    finding = {level: "red"|"yellow", code, cut_no, detail}
      red    = 기계가 확신한다(지어낸 숫자·없는 주장 참조).
      yellow = 사람이 봐야 한다(단서 소실·인과 단정·대상 확대).
    """
    fs = fact_sheet if isinstance(fact_sheet, dict) else {}
    claims = {str(c.get("claim_id")): c for c in (fs.get("claims") or [])
              if isinstance(c, dict) and c.get("claim_id")}
    known_nums = source_numbers(fs)
    raw_nums = {x for x in (_bare(n) for n in known_nums) if x is not None}
    findings: list[dict[str, Any]] = []

    # 이 논문이 다루는 대상이 동물인가 — 원장 어디든 동물이 나오면 그렇게 본다.
    animal_study = bool(_ANIMAL.search(" ".join(
        str(v) for v in (fs.get("what_found") or []) + (fs.get("how") or []))))
    assoc_only = {cid for cid, c in claims.items()
                  if str(c.get("causal_strength") or "") == "association_only"}

    for cut in cuts:
        no = cut.get("cut_no")
        text = " ".join(str(cut.get(k) or "") for k in ("narration_ko", "narration_en"))
        overlay = " ".join(str(o.get("text") or "") for o in (cut.get("overlay_plan") or [])
                           if isinstance(o, dict))

        # ① 지어낸 숫자 — 나레이션·화면 카드의 수치가 원장에 없다.
        #   ★ **계산한 값과 지어낸 값을 가른다**(2026-09-05 실측). 우리 지시서의 '92일'은
        #     원장의 742일·834일 차이였다 — 지어낸 것이 아니라 우리가 뺀 것이다.
        #     둘을 같은 빨강으로 부르면 진짜 환각이 묻힌다. 계산은 노랑으로 내리되
        #     **가리지는 않는다**(빼기가 틀릴 수도 있고, 원문이 안 쓴 수치를 헤드라인으로
        #     내세우는 것 자체가 판단이 필요한 일이다).
        for scope, blob in (("나레이션", text), ("화면 카드", overlay)):
            for n in _numbers(blob) - known_nums:
                if _derivable(n, raw_nums):
                    findings.append({"level": "yellow", "code": "number_derived_from_source",
                                     "cut_no": no,
                                     "detail": f"{scope}의 '{n}' 은 원장 수치의 차/합이다"
                                               " — 우리가 계산한 값이니 맞는지 보라"})
                else:
                    findings.append({"level": "red", "code": "number_not_in_source",
                                     "cut_no": no, "number": n,
                                     "detail": f"{scope}의 '{n}' 이 Fact Sheet 에 없다"})

        # ② 없는 주장 참조.
        for cid in (cut.get("claim_ids") or []):
            if str(cid) not in claims:
                findings.append({"level": "red", "code": "claim_id_unknown",
                                 "cut_no": no, "detail": f"원장에 없는 주장 {cid}"})

        # ③ 동물 연구인데 사람 얘기로 말한다(단서 소실).
        #   ★ 한계·유보 문장은 제외한다(2026-09-05 오탐). "인간에게도 같은 효과가 나타날지는
        #     아직 모른다"는 **옳게 쓴 문장**이고, 그걸 벌하면 운영자가 이 검사를 무시하게 된다.
        if (animal_study and _HUMAN.search(text) and not _ANIMAL.search(text)
                and not _HEDGE.search(text)
                and str(cut.get("evidence_role") or "") not in ("caveat", "limitation")):
            findings.append({"level": "yellow", "code": "animal_result_stated_for_humans",
                             "cut_no": no,
                             "detail": "동물 연구인데 이 컷은 사람을 주어로 말한다"})

        # ④ 상관인데 인과로 단정한다.
        if _CAUSAL.search(text) and (set(map(str, cut.get("claim_ids") or [])) & assoc_only):
            findings.append({"level": "yellow", "code": "causal_overreach",
                             "cut_no": no,
                             "detail": "상관 주장을 인과로 말한다"})

    # ⑤ 훅은 따로 본다 — 가장 많이 다시 쓰이고 가장 과장되기 쉬운 자리다.
    hook = str(header.get("hook_ko") or "")
    for n in _numbers(hook) - known_nums:
        findings.append({"level": "red", "code": "hook_number_not_in_source",
                         "cut_no": 0, "number": n, "detail": f"훅의 '{n}' 이 Fact Sheet 에 없다"})
    if animal_study and _HUMAN.search(hook) and not _ANIMAL.search(hook)             and not _HEDGE.search(hook):
        findings.append({"level": "yellow", "code": "hook_states_human_result",
                         "cut_no": 0, "detail": "동물 연구인데 훅이 사람을 주어로 말한다"})

    return {
        "findings": findings,
        "stats": {
            "cuts": len(cuts),
            "red": sum(1 for f in findings if f["level"] == "red"),
            "yellow": sum(1 for f in findings if f["level"] == "yellow"),
            "animal_study": animal_study,
            "source_numbers": len(known_nums),
        },
    }
