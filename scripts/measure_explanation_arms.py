"""Phase 0-B/0-C — 같은 논문 3안 비교 (작업명세서_설명엔진_v2 §2).

세 갈래를 **같은 논문**에 돌려 "원문 효과"와 "설명 모델 효과"를 분리한다.
서로 다른 논문 20편 vs 20편 비교는 금지다(v2 리뷰의 정정) — 논문 난이도 차가 효과를 덮는다.

  A = 현행: 초록 → Fact Sheet → 대본
  B = 전문 주입: 초록+원문 전문 → Fact Sheet(원문 인용 포함) → **현행 대본 프롬프트 그대로**
  C = 설명 모델: B 의 Fact Sheet → Scientific Explanation Model → 그 설명 단위를 소비하는 대본

0-B 는 A vs B, 0-C 는 A vs B vs C 다 — 같은 산출물을 두 번 만들지 않는다.

평가: 루브릭 10항목 × 0~2점(20점). 심사관은 세 시안을 **섞인 익명 라벨**로 본다.
GO: C−A ≥ +4점 그리고 목차/장식형 컷 비율 절반 이하. C−B < +2 면 설명 모델 계층을 접는다.

★ 모델: 세 갈래 모두 같은 모델을 쓴다. 비교하는 것은 **구조**이지 모델 티어가 아니다.
  백엔드는 **Gemini** 로 잡는다 — 논문 초안을 실제로 만드는 것은 엣지 함수 generate-draft 이고
  거기가 gemini-2.5-flash(추출)·gemini-2.5-pro(대본)로 돈다. 운영과 다른 백엔드로 재 놓고
  운영 품질을 논할 수 없다. (engine/config.py 의 MODEL_* 기본값은 Anthropic 이라 환경변수로 건다.)

★★ Anthropic 폴백을 **끄고** 돌린다(LLM_ANTHROPIC_FALLBACK_MODEL=""). 켜 두면 Gemini 과부하 시
   일부 갈래만 조용히 Anthropic 이 만들고, 그러면 A/B/C 가 "구조 차이"가 아니라 "모델 차이"를
   재게 된다. 무엇으로 만들었는지는 행마다 models 에 남는다.

사용:
    MODEL_FACTSHEET=gemini-2.5-flash MODEL_SCRIPT=gemini-2.5-pro \
    MODEL_JUDGE=gemini-2.5-flash LLM_ANTHROPIC_FALLBACK_MODEL= \
    python -m scripts.measure_explanation_arms \
        --sources <phase0a.jsonl> --limit 20 --workers 2 --out <arms.jsonl> --summary <arms.json>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import config, factsheet, paper_source, scriptgen  # noqa: E402
from engine.llm import call_json  # noqa: E402
from engine.util import log  # noqa: E402

# 실측용 전문 상한. 운영값(60,000)보다 낮게 잡는다 — 세 갈래 × 20편이면 입력 토큰이 비용의
# 절반을 먹는다. 상한을 낮춘 사실은 산출물에 남긴다(fulltext_chars).
ARM_FULLTEXT_CHARS = int(os.getenv("ARM_FULLTEXT_CHARS", "30000"))
# 심사관 모델. 실측 전용이라 config 상수로 올리지 않는다 — 운영 파이프라인에 심사관은 없다.
MODEL_JUDGE = os.getenv("MODEL_JUDGE", config.MODEL_FACTSHEET)
# LLM 출력 상한. ★ 운영값은 8192(engine/scriptgen.generate · config.LLM_MAX_TOKENS)지만
# 실측에서는 올린다 — sonnet 이 8192 에서 잘리면 예외가 나고 **그 편이 통째로 날아간다**
# (실측 1차 실행에서 실제로 1건 발생). 세 갈래 중 하나만 날아가면 paired 비교가 성립하지 않는다.
# 세 갈래에 같은 값을 준다. 전문을 받는 B·C 는 원장이 길어 A 보다 잘릴 위험이 크다 —
# 그래서 이 조정은 B·C 에 유리한 쪽이 아니라 **비교 자체를 가능하게 하는** 쪽이다.
ARM_MAX_TOKENS = int(os.getenv("ARM_MAX_TOKENS", "32768"))
# ★ 16384 도 모자랐다(2026-08-28 Gemini 실행, arm_b 원장 추출이 gemini-2.5-flash 에서 잘림).
#   원문 30,000자를 주면 원장이 초록 때보다 훨씬 길어진다 — **이것 자체가 Phase 2 의 발견이다**:
#   운영에 올릴 때는 상한을 올리는 것이 아니라 claim 개수에 상한을 둬야 한다.

# ─────────────────────────────────────────────────────────────
# B — Fact Sheet 에 원문을 함께 넣는다
# ─────────────────────────────────────────────────────────────
FULLTEXT_RULES = f"""
[원문 전문이 함께 주어진다]
- 초록에 없고 본문에만 있는 사실도 추출하라. 특히 **왜·어떻게**(메커니즘·절차·조건)를 놓치지 마라.
- 본문에서 확인한 주장은 source_section 을 body/table/figure 로 적고, source_quote 에
  **원문 구절을 글자 그대로** 옮겨라(요약·번역·재작성 금지. 영어 원문이면 영어 그대로).
- source_page 는 적지 마라. 우리는 페이지 번호를 갖고 있지 않다 — 지어내면 화면에 거짓이 나간다.
- 원문이 있다고 해서 자동으로 A 등급이 되지 않는다. 효과 크기·표·그림을 실제로 확인한 주장만 A 다.
- 상관을 인과로 승격하지 마라. 연구 설계가 인과를 지지하지 않으면 causal_strength 는
  association_only 이하다.
전문 구간은 {config.PAPER_SOURCE_MARKER} … {config.PAPER_SOURCE_END_MARKER} 사이에 있다.
"""

FACTSHEET_FULLTEXT_SYSTEM = factsheet.FACTSHEET_SYSTEM + FULLTEXT_RULES

# ─────────────────────────────────────────────────────────────
# C — Scientific Explanation Model (명세 §5 스키마)
# ─────────────────────────────────────────────────────────────
EXPLANATION_SYSTEM = f"""너는 과학 설명 설계자다. 논문의 **원리**를 설명 단위로 분해한다.
대본을 쓰는 것이 아니다. "무엇을 발견했다"가 아니라 **왜 그렇게 되는가·어떤 순서로 일어나는가**를
단계로 쪼개는 것이 네 일이다.

입력: Claim Ledger(JSON) + 논문 원문 전문({config.PAPER_SOURCE_MARKER} … {config.PAPER_SOURCE_END_MARKER}).
출력: JSON only. 설명 문장·마크다운·코드펜스 금지.

{{
  "explanation_units": [
    {{ "unit_id": "<비우면 코드가 U01, U02 … 로 부여>",
       "unit_type": "MECHANISM|STRUCTURE|COMPARISON|SCALE",
       "subtype": "CAUSAL_CHAIN|PROCESS|FLOW|FEEDBACK|null",
       "title": "<이 설명 단위가 설명하는 것 한 줄(한국어)>",
       "explains_claim_ids": ["<이 설명이 지불하는 원장 claim_id — 원장에 있는 것만>"],
       "carries_primary": <true/false — 핵심 주장을 설명하는 단위인가>,
       "steps": [
         {{ "step": <정수 1..N>,
            "text": "<이 단계에서 실제로 일어나는 일(한국어 한 문장)>",
            "claim_ids": ["<근거 claim_id. 없으면 빈 배열>"],
            "source_refs": [{{ "quote": "<원문 구절 그대로. 8자 이상, 300자 이하>" }}] }}
       ] }}
  ]
}}

규칙(★ 이걸 어기면 설명이 아니라 목차가 된다):
- **단계는 상태 변화를 담아야 한다.** "A를 분석했다 → 결과를 얻었다" 는 절차 나열이지 설명이 아니다.
  "X가 늘면 Y의 결합이 막히고, 그래서 Z가 축적된다" 처럼 **무엇이 무엇을 어떻게 바꾸는지**를 써라.
- MECHANISM 은 최소 2단계, 각 단계가 앞 단계의 결과를 받아야 한다.
- 각 factual step 은 claim_ids 또는 source_refs 중 **최소 하나**를 반드시 갖는다. 둘 다 없는
  단계는 만들지 마라 — 근거 없는 원리는 환각이다.
- source_refs.quote 는 **원문에 그대로 있는 문자열**이다. 코드가 원문과 대조한다. 번역·요약 금지.
- 논문이 인과를 지지하지 않으면 CAUSAL_CHAIN 을 쓰지 마라(상관이면 COMPARISON 이나 STRUCTURE).
- 논문 밖 일반상식으로 빈칸을 메우지 마라. 원문이 말하지 않는 원리는 **없는 것으로 둔다**.
- 단위는 3~6개. 핵심 주장을 설명하는 단위(carries_primary=true)가 최소 1개 있어야 한다.
"""

EXPLANATION_SCRIPT_RULES = """

[★ 설명 단위(explanation_units)가 함께 주어진다 — 대본은 이것을 **소비**한다]
- 각 설명 단위는 이미 "왜·어떻게"를 단계로 갖고 있다. 대본이 원리를 새로 지어내지 마라.
- 최소 1개의 씬은 carries_primary=true 인 설명 단위의 단계를 화면으로 옮긴다.
- 설명 단위를 쓴 씬은 explanation_id 에 그 unit_id 를 남긴다.
- image_prompt/video_prompt 는 그 단계에서 **무엇이 무엇을 바꾸는지**가 보이게 그려라.
  제목 카드·목차·아이콘 나열은 설명이 아니다.
- 설명 단위에 없는 구조·인과를 이미지 프롬프트에 추가하지 마라.
"""

SCRIPT_SYSTEM_C = scriptgen.SCRIPT_SYSTEM + EXPLANATION_SCRIPT_RULES

# ─────────────────────────────────────────────────────────────
# 심사 루브릭
# ─────────────────────────────────────────────────────────────
# ★ v2 리뷰 §17 원문은 저장소에 없다(운영자 Downloads 보관). 명세 §9 의 성공·실패 조건에서
#   10항목을 재구성했다 — 재구성 사실을 실측 문서에 명시한다.
RUBRIC = [
    ("discovery_clarity", "무엇을 발견했는지가 한 번에 잡히는가"),
    ("mechanism_depth", "왜·어떻게가 단계로 설명되는가(언급만 하면 0점)"),
    ("causal_accuracy", "상관을 인과로 넘기지 않는가"),
    ("scope_disclosure", "연구가 실제로 말한 범위(대상·기간·조건)가 드러나는가"),
    ("evidence_attribution", "각 주장이 논문의 어느 사실에서 왔는지 추적 가능한가"),
    ("no_hallucination", "논문에 없는 사실·수치가 없는가"),
    ("reference_separation", "비유·배경 설명이 연구 결론과 구분되는가"),
    ("visual_substance", "컷이 내용을 보여주는가(제목카드·목차·장식이면 0점)"),
    ("narrative_cohesion", "순서대로 읽으면 하나의 이야기이고 훅에 답하는가"),
    ("information_density", "길이 대비 정보밀도(반복·CTA 로 채우지 않는가)"),
]

JUDGE_SYSTEM = """너는 숏폼 과학영상 심사관이다. 같은 논문으로 만든 시안 여러 개를 채점한다.
어느 시안이 어떤 방식으로 만들어졌는지는 모른다. 알려고 하지 말고 결과물만 본다.

각 시안을 아래 10항목에 0/1/2 로 채점한다.
  0 = 못한다 / 1 = 부분적으로 한다 / 2 = 확실히 한다
항목:
""" + "\n".join(f"  - {k}: {d}" for k, d in RUBRIC) + """

추가로 각 시안에서 **장식형 컷 비율**을 센다:
  장식형 = 제목 카드, 목차, 아이콘 나열, 내용과 무관한 분위기 컷, 무엇이 일어나는지 안 보이는 컷.
  decorative_cuts / total_cuts 를 그대로 적는다.

★ 후한 점수를 주지 마라. **주어진 검증 기준 원문**에 없는 사실이 보이면 no_hallucination 은 0이다.
  ★★ 원문 본문에 있는 사실은 초록에 없더라도 **환각이 아니다.** 초록에 없다는 이유로 깎지 마라.
★ mechanism_depth 는 "원리를 언급"이 아니라 "단계가 이어지는 설명"일 때만 2다.
JSON only:
{
  "scores": [
    { "label": "<시안 라벨>",
      "items": { "<항목키>": <0|1|2>, ... },
      "total": <0..20>,
      "total_cuts": <int>, "decorative_cuts": <int>,
      "note": "<한 줄 근거>" }
  ],
  "ranking": ["<최고 라벨>", "...", "<최저 라벨>"]
}"""

LABELS = ("시안-가", "시안-나", "시안-다")


# ─────────────────────────────────────────────────────────────
# 갈래 실행
# ─────────────────────────────────────────────────────────────
def _packet_for(rec: dict[str, Any]) -> dict[str, Any]:
    """0-A 산출물 한 줄 → 상한 낮춘 packet(비용 통제)."""
    text = (rec.get("text") or "")[:ARM_FULLTEXT_CHARS]
    return {**rec, "text": text, "char_count": len(text),
            "truncated": bool(rec.get("truncated")) or len(rec.get("text") or "") > len(text)}


def _script(fs: dict[str, Any], *, system: str = scriptgen.SCRIPT_SYSTEM,
            extra_user: str = "") -> dict[str, Any]:
    """대본 1회. ★ scriptgen.generate 를 쓰지 않는 이유는 max_tokens 하나뿐이다 —
    프롬프트·정규화는 운영과 같은 것을 그대로 쓴다(세 갈래의 유일한 차이는 system·입력)."""
    obj = call_json(model=config.MODEL_SCRIPT, system=system,
                    user=scriptgen.script_user_prompt(fs) + extra_user,
                    max_tokens=ARM_MAX_TOKENS)
    return scriptgen.normalize_script(obj, fs)


def arm_a(rec: dict[str, Any]) -> dict[str, Any]:
    fs = factsheet.extract(rec.get("title") or "", rec.get("venue"), rec.get("abstract") or "")
    return {"fact_sheet": fs, "script": _script(fs)}


def arm_b(rec: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    user = (factsheet.factsheet_user_prompt(rec.get("title") or "", rec.get("venue"),
                                            rec.get("abstract") or "")
            + "\n\n" + paper_source.fulltext_block(packet))
    obj = call_json(model=config.MODEL_FACTSHEET, system=FACTSHEET_FULLTEXT_SYSTEM,
                    user=user, max_tokens=ARM_MAX_TOKENS)
    fs = factsheet.normalize_factsheet(obj)
    return {"fact_sheet": fs, "script": _script(fs)}


def normalize_units(obj: dict[str, Any], known_claims: tuple[str, ...]) -> list[dict[str, Any]]:
    """설명 단위 정규화. unit_id 는 코드가 부여하고, 원장에 없는 claim 참조는 드롭한다."""
    raw = obj.get("explanation_units")
    out: list[dict[str, Any]] = []
    for i, u in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(u, dict):
            continue
        steps = []
        for j, s in enumerate(u.get("steps") or []):
            if not isinstance(s, dict):
                continue
            cids = [str(x) for x in (s.get("claim_ids") or []) if str(x) in known_claims]
            refs = [{"quote": str(r.get("quote") or "").strip()}
                    for r in (s.get("source_refs") or []) if isinstance(r, dict)
                    and str(r.get("quote") or "").strip()]
            steps.append({"step": int(s.get("step") or (j + 1)),
                          "text": str(s.get("text") or "").strip(),
                          "claim_ids": cids, "source_refs": refs})
        out.append({
            "unit_id": str(u.get("unit_id") or "").strip() or f"U{i + 1:02d}",
            "unit_type": str(u.get("unit_type") or "MECHANISM").upper(),
            "subtype": (str(u.get("subtype")).upper() if u.get("subtype") else None),
            "title": str(u.get("title") or "").strip(),
            "explains_claim_ids": [str(x) for x in (u.get("explains_claim_ids") or [])
                                   if str(x) in known_claims],
            "carries_primary": bool(u.get("carries_primary")),
            "steps": steps,
        })
    return out


_WS = re.compile(r"\s+")


def verify_quotes(units: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
    """인용 대조 — quote 가 원문에 실제로 있는가. 코드가 문자열로 확인한다(모델 신뢰 금지)."""
    hay = _WS.sub(" ", source_text or "").lower()
    total = matched = 0
    for u in units:
        for s in u["steps"]:
            for r in s["source_refs"]:
                total += 1
                q = _WS.sub(" ", r["quote"]).lower()
                ok = len(q) >= config.EVIDENCE_QUOTE_MIN_CHARS and q in hay
                r["verified"] = ok
                matched += int(ok)
    steps = [s for u in units for s in u["steps"]]
    grounded = sum(1 for s in steps if s["claim_ids"] or s["source_refs"])
    return {"quotes": total, "quotes_verified": matched,
            "quote_verify_rate": round(matched / total, 3) if total else 0.0,
            "steps": len(steps), "steps_grounded": grounded,
            "step_ground_rate": round(grounded / len(steps), 3) if steps else 0.0}


def arm_c(rec: dict[str, Any], packet: dict[str, Any], fs_b: dict[str, Any]) -> dict[str, Any]:
    user = ("Claim Ledger:\n" + json.dumps(fs_b, ensure_ascii=False, indent=2)
            + "\n\n" + paper_source.fulltext_block(packet))
    obj = call_json(model=config.MODEL_FACTSHEET, system=EXPLANATION_SYSTEM,
                    user=user, max_tokens=ARM_MAX_TOKENS)
    units = normalize_units(obj, factsheet.claim_ids(fs_b))
    audit = verify_quotes(units, packet.get("text") or "")
    script = _script(fs_b, system=SCRIPT_SYSTEM_C,
                     extra_user="\n\n설명 단위(explanation_units):\n"
                                + json.dumps(units, ensure_ascii=False, indent=2))
    return {"fact_sheet": fs_b, "explanation_units": units, "explanation_audit": audit,
            "script": script}


# ─────────────────────────────────────────────────────────────
# 심사
# ─────────────────────────────────────────────────────────────
def render_arm(arm: dict[str, Any]) -> str:
    """심사관이 볼 시안 본문. 만든 방식이 드러나는 필드(설명 단위·원장)는 넣지 않는다."""
    sc = arm["script"]
    lines = [f"제목(업로드용): {sc.get('upload_title_ko')}", "", "대본:", sc.get("script_md") or ""]
    lines.append("\n컷 목록:")
    for s in sc.get("scenes") or []:
        lines.append(f"- 컷{s['scene']} ({s.get('duration_sec')}초) [{s.get('evidence_role')}] "
                     f"{s.get('title')}\n  나레이션: {s.get('narration_ko')}"
                     f"\n  화면: {s.get('image_prompt_ko') or s.get('image_prompt')}"
                     f"\n  움직임: {s.get('video_prompt_ko') or s.get('video_prompt')}")
    return "\n".join(lines)


def judge(rec: dict[str, Any], arms: dict[str, dict[str, Any]], order: list[str]) -> dict[str, Any]:
    """섞인 익명 라벨로 세 시안을 한 번에 채점 — 같은 심사관이 같은 자리에서 비교한다.

    ★ 심사관에게 **초록이 아니라 원문**을 준다. 1차 실행에서 초록만 줬더니, 본문에서 정당하게
      가져온 수치를 심사관이 전부 환각으로 깎았다("초록에 없는 구체 수치가 다수 등장해
      no_hallucination 0"). 그러면 B·C 는 원문을 읽었다는 이유로 감점당한다 — 측정하려던
      것과 정반대다. 세 갈래 모두 같은 원문을 기준으로 검증한다(A 의 사실도 원문의 부분집합이다).
    """
    packet = _packet_for(rec)
    ref = paper_source.fulltext_block(packet) or f"초록: {rec.get('abstract')}"
    body = [f"논문 제목: {rec.get('title')}",
            "[검증 기준 원문 — 여기에 있는 사실은 정당하다. 여기에 없는 사실만 환각이다]",
            ref, ""]
    for label, arm_key in zip(LABELS, order):
        body += [f"===== {label} =====", render_arm(arms[arm_key]), ""]
    obj = call_json(model=MODEL_JUDGE, system=JUDGE_SYSTEM,
                    user="\n".join(body), max_tokens=4096)
    got: dict[str, Any] = {}
    for row in (obj.get("scores") or []):
        label = str(row.get("label") or "").strip()
        if label not in LABELS:
            continue
        arm_key = order[LABELS.index(label)]
        items = {k: int(row.get("items", {}).get(k, 0) or 0) for k, _ in RUBRIC}
        got[arm_key] = {
            "items": items,
            "total": sum(items.values()),           # 모델의 total 을 믿지 않고 코드가 합산
            "total_cuts": int(row.get("total_cuts") or 0),
            "decorative_cuts": int(row.get("decorative_cuts") or 0),
            "note": str(row.get("note") or ""),
        }
    return got


# ─────────────────────────────────────────────────────────────
def run_paper(rec: dict[str, Any], index: int) -> dict[str, Any]:
    packet = _packet_for(rec)
    a = arm_a(rec)
    b = arm_b(rec, packet)
    c = arm_c(rec, packet, b["fact_sheet"])
    arms = {"A": a, "B": b, "C": c}
    # 라벨 배치를 편마다 돌린다 — 심사관이 "첫 시안이 늘 현행" 같은 규칙을 잡지 못하게.
    order = [["A", "B", "C"], ["B", "C", "A"], ["C", "A", "B"]][index % 3]
    scores = judge(rec, arms, order)
    return {
        "external_id": rec.get("external_id"), "title": rec.get("title"),
        "source_depth": rec.get("source_depth"), "provider": rec.get("provider"),
        "fulltext_chars": packet["char_count"],
        "label_order": order,
        # ★ 모델을 **행마다** 남긴다. 집계에서 config 를 읽으면 --summarize-only 로 나중에
        #   집계할 때 그때의 환경변수가 찍혀, 실제로 무엇으로 만든 결과인지 거짓이 된다
        #   (실측 중 실제로 model_script 가 opus 로 잘못 찍혔다).
        "models": {"script": config.MODEL_SCRIPT, "factsheet": config.MODEL_FACTSHEET,
                   "judge": MODEL_JUDGE, "max_tokens": ARM_MAX_TOKENS,
                   "fulltext_chars_cap": ARM_FULLTEXT_CHARS,
                   # ★ 폴백 모델도 남긴다. 켜져 있으면 Gemini 실패 시 조용히 Anthropic 이
                   #   같은 실측 안에서 일부 갈래만 만들 수 있다 — 그러면 비교가 무너진다.
                   "anthropic_fallback": config.LLM_ANTHROPIC_FALLBACK_MODEL or "(꺼짐)"},
        "scores": scores,
        "explanation_audit": c["explanation_audit"],
        "arms": {k: {"script": v["script"], "fact_sheet": v["fact_sheet"],
                     **({"explanation_units": v["explanation_units"]} if "explanation_units" in v else {})}
                 for k, v in arms.items()},
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def totals(arm: str) -> list[int]:
        return [r["scores"][arm]["total"] for r in rows if arm in r.get("scores", {})]

    def deco(arm: str) -> list[float]:
        out = []
        for r in rows:
            s = r.get("scores", {}).get(arm)
            if s and s.get("total_cuts"):
                out.append(s["decorative_cuts"] / s["total_cuts"])
        return out

    ta, tb, tc = totals("A"), totals("B"), totals("C")
    paired = [(r["scores"]["A"]["total"], r["scores"]["B"]["total"], r["scores"]["C"]["total"])
              for r in rows if all(k in r.get("scores", {}) for k in ("A", "B", "C"))]
    mean = lambda xs: round(statistics.mean(xs), 2) if xs else 0.0  # noqa: E731
    c_minus_a = mean([c - a for a, _, c in paired])
    c_minus_b = mean([c - b for _, b, c in paired])
    per_item = {k: {arm: mean([r["scores"][arm]["items"][k] for r in rows
                               if arm in r.get("scores", {})])
                    for arm in ("A", "B", "C")} for k, _ in RUBRIC}
    return {
        "n": len(rows), "n_paired": len(paired),
        "mean_total": {"A": mean(ta), "B": mean(tb), "C": mean(tc)},
        "B_minus_A": mean([b - a for a, b, _ in paired]),
        "C_minus_A": c_minus_a,
        "C_minus_B": c_minus_b,
        "decorative_ratio": {arm: mean(deco(arm)) for arm in ("A", "B", "C")},
        "per_item_mean": per_item,
        "quote_verify_rate": mean([r["explanation_audit"]["quote_verify_rate"] for r in rows
                                   if r.get("explanation_audit")]),
        "step_ground_rate": mean([r["explanation_audit"]["step_ground_rate"] for r in rows
                                  if r.get("explanation_audit")]),
        "go_c_minus_a": c_minus_a >= 4.0,
        "keep_explanation_layer": c_minus_b >= 2.0,
        # 행에 남은 값을 읽는다 — 집계 시점의 환경변수가 아니라 **만들 때 쓴 것**이 진실이다.
        "models": sorted({json.dumps(r.get("models") or {}, ensure_ascii=False, sort_keys=True)
                          for r in rows}),
    }


def preflight() -> str:
    """쓸 모델을 **시작 전에** 한 번씩 찔러 본다. 실패하면 이유를 한 줄로 돌려준다.

    ★ 왜 필요한가: 1차 실행에서 크레딧이 바닥난 것을 20편이 트레이스백을 쏟은 뒤에야 알았다.
      돈·시간을 쓰기 전에 알 수 있는 실패는 앞에서 잡는다. 호출 1~2회, 출력 32토큰이다.
    """
    for label, model in (("factsheet", config.MODEL_FACTSHEET), ("script", config.MODEL_SCRIPT),
                         ("judge", MODEL_JUDGE)):
        try:
            call_json(model=model, system='JSON only. {"ok": true}', user="ping", max_tokens=32)
        except Exception as exc:  # noqa: BLE001 — 원인 문자열이 그대로 운영자에게 간다
            return f"{label} 모델({model}) 사전 점검 실패: {str(exc)[:300]}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, help="measure_paper_source 의 JSONL")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--summarize-only", action="store_true",
                    help="--out 에 이미 쌓인 결과만으로 집계한다(중단된 실행 구제)")
    ap.add_argument("--rejudge", action="store_true",
                    help="이미 만든 시안을 **다시 채점만** 한다(대본 재생성 없음). "
                         "심사 프롬프트를 고쳤을 때 옛 결과를 새 기준으로 맞추는 용도")
    args = ap.parse_args()

    if not args.summarize_only:   # 집계만 할 때는 LLM 을 부르지 않는다
        problem = preflight()
        if problem:
            log.error("사전 점검에서 멈춘다 — 한 편도 만들지 않았다.\n  %s", problem)
            return 3

    if args.summarize_only:
        rows = [json.loads(line) for line in open(args.out, encoding="utf-8")]
        summary = summarize(rows)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    recs = [json.loads(line) for line in open(args.sources, encoding="utf-8")]

    if args.rejudge:
        # ★ 시안은 그대로 두고 채점만 다시 한다. 대본 6회를 다시 만들면 비교 대상이 바뀌어
        #   "심사 기준을 바꾼 효과"와 "생성이 달라진 효과"가 섞인다.
        by_id = {r.get("external_id"): r for r in recs}
        rows = [json.loads(line) for line in open(args.out, encoding="utf-8")]

        def again(row: dict[str, Any]) -> dict[str, Any]:
            src = by_id.get(row["external_id"]) or {}
            row["scores"] = judge(src or row, row["arms"], row["label_order"])
            row["rejudged"] = True
            log.info("재채점 %s: %s", row["external_id"],
                     {k: v["total"] for k, v in row["scores"].items()})
            return row

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            rows = list(ex.map(again, rows))
        with open(args.out, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary = summarize(rows)
        with open(args.summary, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    usable = [r for r in recs if r.get("source_depth") in ("full_body", "partial_body")
              and (r.get("abstract") or "").strip()][:args.limit]
    log.info("3안 비교 대상 %d편 (모델: script=%s factsheet=%s judge=%s)",
             len(usable), config.MODEL_SCRIPT, config.MODEL_FACTSHEET, MODEL_JUDGE)

    def one(pair: tuple[int, dict[str, Any]]) -> dict[str, Any] | None:
        i, rec = pair
        log.info("[%d/%d] 시작 %s", i + 1, len(usable), rec.get("external_id"))
        try:
            row = run_paper(rec, i)
        except Exception as exc:  # noqa: BLE001 — 한 편의 실패가 실측을 멈추지 않는다
            log.warning("실패 %s: %s", rec.get("external_id"), exc)
            traceback.print_exc()
            return None
        log.info("[%d/%d] 완료 %s", i + 1, len(usable), rec.get("external_id"))
        return row

    # 편 단위 병렬. 한 편이 LLM 6회(그중 대본 2회는 출력 8k)라 순차로는 편당 10분이 넘는다.
    rows: list[dict[str, Any]] = []
    with open(args.out, "w", encoding="utf-8") as f, \
            ThreadPoolExecutor(max_workers=args.workers) as ex:
        for row in ex.map(one, list(enumerate(usable))):
            if row is None:
                continue
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()

    summary = summarize(rows)
    with open(args.summary, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
