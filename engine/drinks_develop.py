"""주류 소재 자동 개발 워커 — 근거 초안(원문 그대로 인용) → 대본·화면 계획 초안. 2026-10-30. docs/deviation-drinks-develop.md

    python -m engine.drinks_develop      # 대기 중인 개발 요청을 처리(대시보드 [근거 초안 만들기]·[제작안 초안 만들기])

두 단계 요청(승인은 사람이 기존 화면에서 따로 한다 — 이 워커는 초안까지만 쓰고 제출·승인 함수를 부르지 않는다):
  evidence  소재 → 출처 찾기(무료) → 출처마다 주장 추출(모델) → **원문 인용을 코드가 글자 단위로 대조** → 근거 초안(drinks_develop_save_evidence)
  plan      운영자가 승인한 근거 버전의 핵심 주장만으로 30~40초 대본·화면 계획(모델) → 코드 검사(+Jev 근거 판정, 켜졌을 때) →
            막히면 딱 한 번 다시 쓴다 → 그래도 막히면 **저장하지 않고** 멈춘다(blocked)

규칙:
  · 모델을 부르는 모든 곳은 [가잡기 → 호출 → 확정/해제] 를 거친다(Ledger). 결재(budget_id)가 없으면 호출 전에 budget_missing 으로 멈춘다.
    상한(결재 금액·요청 1건 $0.5·호출 20번)은 DB 가 센다 — 이 코드는 예상 금액을 정직하게 말할 뿐이다.
  · 모델 호출은 전부 주입 함수(Deps)다. 테스트는 가짜를 넣는다(실제 모델·네트워크 호출 0).
  · 원문에 없는 인용은 버린다. 인용 대조는 DB 의 quote_check(drinks_norm_text)와 같은 기준으로 하되, 더 보수적이다(아래 verify_quote).
  · 주장 문장(text)이 인용을 벗어났는지는 코드가 숫자만 본다 — 뜻의 비약은 Jev(켜졌을 때)와 운영자 검토가 본다. support_review 는 not_reviewed 로 둔다.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import config
from . import drinks_script_check as script_check
from .drinks_collect import DbError, supabase_rpc
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
CLAIM_TYPES = ("product_fact", "process", "comparison", "opinion")


class DevelopError(Exception):
    """작업을 멈춘다. outcome: blocked(사람이 손봐야 함) | failed(실행 문제)."""

    def __init__(self, code: str, message: str, outcome: str = "blocked", result: Optional[dict[str, Any]] = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.outcome = outcome
        self.result = result or {}


# ─────────────────────────────────────────────────────────────
# 원문 인용 대조 — 이 파일에서 가장 중요한 코드
# ─────────────────────────────────────────────────────────────

_ASCII_WS = re.compile(r"[ \t\n\r\f\v]+")
_UNI_WS = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"…|\.{3,}")


def clean_source_text(raw: str) -> str:
    """가져온 글을 보관용으로: NFC, 모든 유니코드 공백 → 보통 공백 한 칸. 보관하는 본문과 대조하는 본문이 같아지게 한다."""
    return _UNI_WS.sub(" ", unicodedata.normalize("NFC", raw or "")).strip()


def _db_like(s: str) -> str:
    """DB drinks_norm_text 와 같은 정규화: 앞뒤 공백 제거 · (ASCII) 공백 연속 한 칸 · 소문자. NFC·유니코드 공백 변환은 하지 않는다."""
    return _ASCII_WS.sub(" ", (s or "").strip()).lower()


def verify_quote(quote: str, source_text: str) -> bool:
    """quote 가 source_text 에 **글자 그대로** 들어 있나(공백·대소문자 차이만 무시).

    ★ 모델이 낸 인용에는 NFC·유니코드 공백 정리를 해 준다(모델은 NBSP 를 못 낸다). 그러나 원문 쪽은 손대지 않는다 —
      DB 가 같은 원문에 같은 기준으로 다시 재므로, 여기서 더 너그러우면 'Python 은 통과, DB 는 불일치'가 생긴다.
    ★ 줄임표(…, ...)가 든 인용은 이어 붙인 발췌라서 글자 그대로가 아니다 — 거절한다. 너무 짧은 인용도 거절한다."""
    q = clean_source_text(quote)
    if not (config.DRINKS_DEVELOP_QUOTE_MIN_CHARS <= len(q) <= config.DRINKS_DEVELOP_QUOTE_MAX_CHARS):
        return False
    if _ELLIPSIS.search(q):
        return False
    return _db_like(q) in _db_like(source_text)


def _numbers(s: str) -> set[str]:
    return script_check._nums(s)


def verify_claims(raw: list[Any], source_text: str, *, snippet_numbers: bool = True) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """모델이 뽑은 주장 → (원문 대조를 통과한 것, 버린 이유별 개수). 통과 못 한 주장은 조용히 버리지 않고 센다."""
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    seen: set[str] = set()

    def drop(why: str) -> None:
        dropped[why] = dropped.get(why, 0) + 1

    for c in raw or []:
        if not isinstance(c, dict):
            drop("not_object")
            continue
        text = str(c.get("text") or "").strip()
        quote = str(c.get("original_quote") or "").strip()
        ctype = str(c.get("claim_type") or "").strip()
        if not text or not quote:
            drop("empty")
            continue
        if ctype not in CLAIM_TYPES:
            drop("bad_type")
            continue
        if not verify_quote(quote, source_text):
            drop("quote_not_in_source")
            continue
        key = _db_like(clean_source_text(quote))
        if key in seen:
            drop("duplicate_quote")
            continue
        # 주장 문장의 숫자는 인용에 있어야 한다(환산·계산한 숫자는 원문 숫자가 아니다 — 2026-10-26 사고와 같은 종류)
        if snippet_numbers and (_numbers(text) - _numbers(quote)):
            drop("number_not_in_quote")
            continue
        seen.add(key)
        kept.append({"text": text, "original_quote": clean_source_text(quote), "claim_type": ctype})
    return kept, dropped


# ─────────────────────────────────────────────────────────────
# 비용 — 가잡기 · 호출 · 확정/해제
# ─────────────────────────────────────────────────────────────

def _price(model: str) -> dict[str, float]:
    p = config.TEXT_PRICING.get(model)
    if not p:
        raise DevelopError("price_unknown", f"단가표에 없는 모델입니다: {model} — 비용을 말할 수 없으면 부르지 않습니다", "failed")
    return p


def estimate_usd(model: str, in_chars: int, max_out_tokens: int) -> float:
    """호출 1회의 **상한** 예상(입력 추정 + 출력 상한). 결제 실패 대체 모델이 더 비싸면 그 단가로 센다. 올림해서 0 이 되지 않는다."""
    models = [model]
    fb = getattr(config, "LLM_PAYMENT_FALLBACK_MODEL", None)
    if fb and model.lower().startswith("gemini") and fb in config.TEXT_PRICING:
        models.append(fb)
    in_tokens = in_chars / max(config.DRINKS_DEVELOP_CHARS_PER_TOKEN, 0.5)
    best = 0.0
    for m in models:
        p = _price(m)
        best = max(best, in_tokens * p["text_input_per_token"] + max_out_tokens * p["text_output_per_token"])
    return max(round(best + 0.00005, 4), 0.0001)


def usage_usd(model: str, usage: dict[str, Any]) -> float:
    p = config.TEXT_PRICING.get(model) or {}
    cin = int(usage.get("promptTokenCount") or usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    cout = int(usage.get("candidatesTokenCount") or usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    cout += int(usage.get("thoughtsTokenCount") or 0)
    return cin * float(p.get("text_input_per_token", 0.0)) + cout * float(p.get("text_output_per_token", 0.0))


@dataclass
class UsageBox:
    usd: float = 0.0
    calls: int = 0

    def add(self, model: str, usage: dict[str, Any]) -> None:
        self.usd += usage_usd(model, usage)
        self.calls += 1


@contextmanager
def capture_usage():
    """engine/llm.py 의 텍스트 사용량 기록(_record_text_usage)을 엿본다 — 원래 기록(비용 원장)은 그대로 하고 실제 금액만 모은다."""
    from . import llm

    box = UsageBox()
    orig = llm._record_text_usage

    def wrapper(model: str, usage: dict[str, Any]) -> None:
        box.add(model, usage or {})
        return orig(model, usage)

    llm._record_text_usage = wrapper
    try:
        yield box
    finally:
        llm._record_text_usage = orig


class Ledger:
    """모델 호출 1회 = 가잡기 → 호출 → 확정(실제 금액; 모르면 예상 금액) 또는 해제(실패). 결재가 없으면 호출 전에 멈춘다."""

    def __init__(self, rpc: Rpc, lease: dict[str, Any], budget_id: Optional[str]):
        self.rpc = rpc
        self.lease = lease
        self.budget_id = budget_id
        self.calls: list[dict[str, Any]] = []
        self.spent = 0.0

    def run(self, model: str, est_usd: float, fn: Callable[[], Any], note: str) -> Any:
        if not self.budget_id:
            raise DevelopError("budget_missing", "결재(예산)가 없는 요청은 모델을 부를 수 없습니다 — 대시보드에서 개발 결재를 열고 다시 요청하세요")
        try:
            hold = self.rpc("drinks_develop_hold", {**self.lease, "est_usd": est_usd, "model": model, "note": note})
        except DbError as exc:
            if exc.code in ("budget_exceeded", "request_cap_exceeded", "approval_closed", "approval_expired", "hold_limit", "budget_missing"):
                raise DevelopError(exc.code, exc.message) from exc
            if exc.code == "canceled":
                raise DevelopError("canceled", exc.message, "failed") from exc
            raise
        with capture_usage() as box:
            try:
                value = fn()
            except BaseException as exc:  # noqa: BLE001 — 실패한 호출은 해제(청구 확인 전이라도 쓴 분은 아래에서 확정)
                if box.calls and box.usd > 0:
                    self.rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "settled", "actual_usd": round(box.usd, 4),
                                                       "note": f"{note} — 실패했지만 사용량이 기록됨({type(exc).__name__})"})
                    self.spent += box.usd
                else:
                    self.rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "released", "note": f"{note} — 실패({type(exc).__name__})"})
                raise
        actual = box.usd if box.calls else est_usd   # 사용량을 모르면 예상 금액으로 확정(지출을 작게 적지 않는다)
        self.rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "settled", "actual_usd": round(actual, 4),
                                           "note": note + ("" if box.calls else " — 사용량 미확인, 예상 금액으로 확정")})
        self.spent += actual
        self.calls.append({"model": model, "est_usd": est_usd, "actual_usd": round(actual, 4), "note": note})
        return value


# ─────────────────────────────────────────────────────────────
# 실제 모델 호출(주입 기본값) — 0단계 테스트는 쓰지 않는다
# ─────────────────────────────────────────────────────────────

EXTRACT_SYSTEM = (
    "너는 술(위스키·사케·전통주) 이야기를 만드는 팩트체커다. 주어진 '원문'에서, 질문에 답하는 데 쓸 수 있는 사실 주장만 뽑는다.\n"
    "규칙:\n"
    "1. original_quote 는 원문에서 **글자 그대로 복사한 연속된 한 구절**이다(20~500자). 번역·요약·줄임표(…)·이어 붙이기 금지. 원문 언어 그대로.\n"
    "2. text 는 그 구절이 말하는 것을 한국어 한 문장으로 쓴다. 구절에 없는 숫자·양·권고·결론을 더하지 않는다. 숫자는 구절에 있는 그대로만 쓴다(환산·계산 금지).\n"
    "3. 원문이 말하지 않은 것(처방, '~하면 좋다', 추론)은 뽑지 않는다. 확실하지 않으면 빼는 것이 맞다.\n"
    "4. claim_type: product_fact(제품·기준·정의), process(만드는/작용하는 과정), comparison(비교), opinion(누군가의 의견·평가).\n"
    "5. 최대 8개. 답은 JSON 만: {\"claims\": [{\"text\": \"…\", \"original_quote\": \"…\", \"claim_type\": \"process\"}]}"
)

PLAN_SYSTEM = (
    "너는 술 숏폼(30~40초 릴스) 대본과 화면 계획을 쓴다. 입력으로 받은 '승인된 근거'(주장과 원문 인용)만 쓴다. JSON 만 낸다.\n"
    "엄격한 규칙:\n"
    "- 근거에 없는 숫자·양(방울·티스푼·ml·잔)·처방('~해 보세요')·결론·인과를 만들지 않는다. 인용에 있는 숫자만 쓴다. 근거의 claim_id 만 쓴다.\n"
    "- 대본은 대중이 한 번에 알아듣는 쉬운 구어체(말하듯 ~해요/~예요). 문어체(-습니다) 금지. 한 장면 나레이션은 한두 문장, 짧게.\n"
    "- 장면은 5~7개, 장면 timing_sec 합계 30~40초. 1번 장면은 소재의 질문을 던진다(물음표). 마지막은 근거가 말하는 선에서 마무리.\n"
    "- 사실을 말하는 장면(content_kind=fact)은 claim_ids 에 근거를 단다. 도입·전환(transition)은 비워도 된다.\n"
    "- 각 장면: narration, visual_role(reality|mechanism|text_card), content_kind, claim_ids, timing_sec, answers_ko(이 장면이 답하는 질문), "
    "staging_ko(화면에서 무슨 일이 일어나나), explanation, visual_prompt(영어), "
    "continuity(앞 장면 이어 그리기면 'ref:N'), motion_prompt(영어, 선택).\n"
    # ★ 2026-10-30 1단계 실측: "무엇이 보이고 무엇이 바뀌나"라고만 적었더니 모델이 {visible, changes} 두 칸만 만들어
    #   엔진 게이트(photo_contract.mechanism_spec_complete)에 두 편 모두 막혔다 — 지시문을 검사 규칙과 같은 말로 맞춘다.
    "- visual_role=mechanism 은 **눈에 보이는 과정(채우기·밀봉·섞기·떠오르기처럼 무언가가 바뀌는 장면)**에만 쓴다. 표시 규칙·분류처럼 과정이 아닌 사실은 "
    "reality(실제 사물·행동 장면) 또는 text_card 로 한다. mechanism 장면에는 반드시 이 다섯 칸을 모두 채운 mechanism 객체를 단다(영어): "
    "{\"subject\": \"장면의 주인공 사물\", \"components\": [\"알아볼 수 있는 실제 물건 2개 이상\"], \"relationship\": \"부품끼리의 관계\", "
    "\"initial_state\": \"처음 상태\", \"transformation\": \"무엇이 어떻게 바뀌나\", \"final_state\": \"끝 상태\", \"highlighted_element\": \"설명 대상\", "
    "\"claim_ids\": [근거 id]}.\n"
    # ★ 같은 실측: 라벨이 소재라 "label·letters·inscription·no text" 를 쓴 지시문이 전부 '화면에 글자 요구'로 막혔다
    #   (부정어로는 못 막는다 — 엔진 교훈). 낱말 자체를 쓰지 않게 하고, 무엇을 보여 줄지를 긍정으로 쓰게 한다.
    "- visual_prompt 에는 label, text, letters, words, numbers, inscription, sign, caption, chart, diagram, arrow, legend 같은 낱말을 "
    "**쓰지 않는다**('no text' 같은 부정도 쓰지 않는다). 라벨·날짜·표시 규칙이 주제여도 그림은 병을 옆이나 뒤에서 보거나, 담기·밀봉·고르기 같은 "
    "손의 행동으로 보여 준다. 글자가 꼭 필요한 정보(날짜 종류·규칙 이름)는 text_card 장면의 explanation 으로만 쓴다.\n"
    "- viewer_conclusion: {\"text\": \"시청자가 이어 들으면 내리는 결론 한 줄\", \"claim_ids\": [근거 id…]} — 결론도 인용 안에서만.\n"
    "- 출력 형식: {\"scenes\": [...], \"viewer_conclusion\": {...}}"
)


def _gold_example() -> str:
    """손으로 만든 통과 사례(whisky-water-v1)의 모양을 예시로 보인다. 파일이 없으면 빈 문자열."""
    try:
        path = Path(__file__).resolve().parents[1] / "docs" / "drinks-pilot" / "whisky-water-v1.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        ex = {"claims": [{k: c[k] for k in ("claim_id", "text", "original_quote") if k in c} for c in d["claims"][:3]],
              # ★ 2026-10-30: 앞 3개만 보여 줬더니 도해(mechanism) 장면 예시가 하나도 없었다 — 완전한 구조를 가진 첫 도해 장면을 함께 보인다.
              "scenes": d["scenes"][:3] + [s for s in d["scenes"] if isinstance(s.get("mechanism"), dict)][:1],
              "viewer_conclusion": d.get("viewer_conclusion")}
        return json.dumps(ex, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return ""


def llm_extract_claims(question: str, source_text: str) -> list[dict[str, Any]]:
    from . import llm

    llm.set_text_purpose("drinks_develop_evidence")
    out = llm.call_json(model=config.DRINKS_DEVELOP_EXTRACT_MODEL, system=EXTRACT_SYSTEM,
                        user=f"질문: {question}\n\n원문:\n{source_text}", max_tokens=config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS)
    return [c for c in (out.get("claims") or []) if isinstance(c, dict)]


def plan_user_prompt(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]]) -> str:
    rows = [{"claim_id": c.get("claim_id"), "text": c.get("text"), "claim_type": c.get("claim_type"),
             "quotes": [r.get("original_quote") for r in (c.get("source_refs") or []) if isinstance(r, dict)]} for c in claims]
    parts = [f"소재 질문: {question}", f"핵심 메시지(운영자): {brief.get('core_takeaway') or '(없음)'}",
             "승인된 근거:\n" + json.dumps(rows, ensure_ascii=False)]
    ex = _gold_example()
    if ex:
        parts.append("통과한 사례의 모양(내용을 베끼지 말고 형식만 참고):\n" + ex)
    if feedback:
        parts.append("직전 초안이 아래 검사에 막혔다. 같은 문제를 고쳐서 처음부터 다시 쓴다:\n" + "\n".join(f"- {m}" for m in feedback))
    return "\n\n".join(parts)


def llm_write_plan(question: str, claims: list[dict[str, Any]], brief: dict[str, Any], feedback: Optional[list[str]] = None) -> dict[str, Any]:
    from . import llm

    llm.set_text_purpose("drinks_develop_plan")
    return llm.call_json(model=config.DRINKS_DEVELOP_PLAN_MODEL, system=PLAN_SYSTEM,
                         user=plan_user_prompt(question, claims, brief, feedback), max_tokens=config.DRINKS_DEVELOP_PLAN_MAX_TOKENS)


def jev_unsupported_p(narration: str, source: str) -> Optional[float]:
    """Jev 근거 판정(켜졌을 때만). 못 물으면 None(fail-open) — 신호이지 차단이 아니다."""
    if not config.DRINKS_DEVELOP_JEV_ENABLED:
        return None
    try:
        from . import decide

        return decide.unsupported_claim_p(narration, source) if decide.enabled() else None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Deps:
    extract_claims: Callable[[str, str], list[dict[str, Any]]] = llm_extract_claims
    write_plan: Callable[..., dict[str, Any]] = llm_write_plan
    jev_check: Callable[[str, str], Optional[float]] = jev_unsupported_p
    fetcher_factory: Optional[Callable[[list[str]], Any]] = None   # hosts → SafeFetcher 같은 것(get 메서드)

    def fetcher(self, hosts: list[str]) -> Any:
        if self.fetcher_factory:
            return self.fetcher_factory(hosts)
        from .drinks_fetch import SafeFetcher

        return SafeFetcher(hosts, interval_sec=config.DRINKS_MIN_INTERVAL_SEC, max_requests=12)


# ─────────────────────────────────────────────────────────────
# 출처 찾기 (evidence)
# ─────────────────────────────────────────────────────────────

@dataclass
class Source:
    origin: str                      # linked(운영자 등록) | collected(승인 수집원) | official | europepmc
    title: str
    text: Optional[str]              # None = 본문 없음(주소만 등록됨)
    snapshot_id: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    source_kind: str = "other"
    rights_status: str = "unknown"
    usage_terms: Optional[str] = None
    role: Optional[str] = None
    new_source: dict[str, Any] = field(default_factory=dict)   # snapshot_id 가 없을 때 drinks_develop_add_source 에 보낼 출처


_STOP = {"the", "and", "for", "why", "how", "what", "does", "with", "that", "this", "왜", "어떻게", "무엇", "하는", "있는", "에서", "으로", "이유"}


def topic_terms(topic: dict[str, Any]) -> list[str]:
    raw = " ".join(str(topic.get(k) or "") for k in ("title", "question", "target_subject", "angle"))
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9가-힣一-龥ぁ-んァ-ヶ]{2,}", raw)]
    out: list[str] = []
    for t in toks:
        if t not in _STOP and t not in out:
            out.append(t)
    return out[:8]


def ascii_query_terms(topic: dict[str, Any]) -> list[str]:
    return [t for t in topic_terms(topic) if re.fullmatch(r"[a-z0-9]+", t)]


def jats_to_text(xml: str) -> str:
    """Europe PMC fullTextXML(JATS) → 본문. <body> 가 없으면 <abstract>. 참고문헌은 버린다."""
    s = xml or ""
    s = re.sub(r"<ref-list\b.*?</ref-list>", " ", s, flags=re.S)
    m = re.search(r"<body\b[^>]*>(?P<b>.*?)</body>", s, re.S) or re.search(r"<abstract\b[^>]*>(?P<b>.*?)</abstract>", s, re.S)
    if not m:
        return ""
    t = re.sub(r"</(p|sec|title|list-item|caption)>", "\n", m.group("b"))
    t = re.sub(r"<[^>]+>", " ", t)
    return clean_source_text(html_mod.unescape(t))


def _decode(res: Any) -> str:
    body = getattr(res, "body", b"")
    if isinstance(body, str):
        return body
    return body.decode(getattr(res, "charset", None) or "utf-8", "replace")


def find_europepmc(topic: dict[str, Any], fetcher: Any) -> tuple[list[Source], list[str]]:
    """오픈액세스(CC 라이선스) 논문. 기본 꺼짐(config.DRINKS_DEVELOP_EUROPEPMC_ENABLED). 영어 낱말이 없으면 건너뛴다."""
    from .drinks_fetch import FEED_TYPES, JSON_TYPES, FetchError

    notes: list[str] = []
    terms = ascii_query_terms(topic)
    if not terms:
        return [], ["europepmc: 소재에 영어 검색어가 없어 건너뜀"]
    query = "(" + " AND ".join(f'"{t}"' for t in terms[:4]) + ") AND OPEN_ACCESS:Y"
    out: list[Source] = []
    try:
        res = fetcher.get(f"{config.EUROPEPMC_REST_BASE}/search", accept=JSON_TYPES,
                          params={"query": query, "format": "json", "resultType": "core", "pageSize": config.DRINKS_DEVELOP_EUROPEPMC_PAGE_SIZE})
        hits = (json.loads(_decode(res)).get("resultList") or {}).get("result") or []
    except (FetchError, ValueError) as exc:
        return [], [f"europepmc: 검색 실패({getattr(exc, 'code', type(exc).__name__)})"]
    for h in hits:
        lic = str(h.get("license") or "").lower().strip()
        pmcid = h.get("pmcid")
        if not pmcid or not lic.startswith("cc"):
            continue
        try:
            xml = _decode(fetcher.get(f"{config.EUROPEPMC_REST_BASE}/{pmcid}/fullTextXML", accept=FEED_TYPES))
        except FetchError as exc:
            notes.append(f"europepmc: {pmcid} 본문 실패({exc.code})")
            continue
        text = jats_to_text(xml)
        if not text:
            continue
        doi = h.get("doi")
        url = f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/PMC/{str(pmcid).removeprefix('PMC')}"
        rights = "quote_ok" if lic in ("cc0", "cc by", "cc by-sa", "cc-by", "cc-by-sa") else "summary_only"
        title = str(h.get("title") or pmcid)
        publisher = f"{h.get('journalTitle') or 'Europe PMC'} ({h.get('pubYear') or '연도 미상'})"
        out.append(Source("europepmc", title, text, url=url, publisher=publisher, source_kind="expert", rights_status=rights,
                          usage_terms=f"{lic.upper()} — 저자·출처 표기", new_source={
                              "canonical_url": url, "title": title, "publisher": publisher, "source_kind": "expert", "depth": "full_text",
                              "body_text": text[: config.DRINKS_MAX_BODY_CHARS], "rights_status": rights,
                              "usage_terms": f"{lic.upper()} — 저자·출처 표기 (Europe PMC {pmcid})", "original_language": "en"}))
    return out, notes


def find_official(topic: dict[str, Any], deps: Deps) -> tuple[list[Source], list[str]]:
    """운영자가 약관을 확인한 공식·전문 출처 목록(config.DRINKS_DEVELOP_OFFICIAL_SOURCES). terms_verified 아닌 항목은 쓰지 않는다."""
    from urllib.parse import urlsplit

    from .drinks_fetch import FetchError, HTML_TYPES, Robots
    from .drinks_parse import decode, parse_page

    notes: list[str] = []
    terms = topic_terms(topic)
    out: list[Source] = []
    for ent in config.DRINKS_DEVELOP_OFFICIAL_SOURCES:
        if ent.get("terms_verified") is not True:
            continue
        kws = [str(k).lower() for k in ent.get("keywords") or []]
        if kws and not any(k in terms or any(k in t for t in terms) for k in kws):
            continue
        url = str(ent.get("url") or "")
        host = (urlsplit(url).hostname or "").lower()
        fetcher = deps.fetcher([host])
        try:
            if not Robots(fetcher).allowed(url):
                notes.append(f"official: {ent.get('name')} robots 금지")
                continue
            res = fetcher.get(url, accept=HTML_TYPES)
            page = parse_page(decode(res.body, res.charset), res.url)
        except FetchError as exc:
            notes.append(f"official: {ent.get('name')} 실패({exc.code})")
            continue
        text = clean_source_text(page.text)
        if not text:
            continue
        out.append(Source("official", page.title or str(ent.get("name")), text, url=url, publisher=ent.get("publisher"),
                          source_kind=str(ent.get("source_kind") or "official"), rights_status=str(ent.get("rights_status") or "unknown"),
                          usage_terms=ent.get("usage_terms"), new_source={
                              "canonical_url": url, "title": page.title or ent.get("name"), "publisher": ent.get("publisher"),
                              "source_kind": ent.get("source_kind") or "official", "depth": "full_text",
                              "body_text": text[: config.DRINKS_MAX_BODY_CHARS], "rights_status": ent.get("rights_status") or "unknown",
                              "usage_terms": ent.get("usage_terms")}))
    return out, notes


def gather_sources(job: dict[str, Any], rpc: Rpc, lease: dict[str, Any], deps: Deps) -> tuple[list[Source], list[dict[str, Any]]]:
    """출처 후보를 모은다. 반환: (쓸 수 있는 출처 — 순서 = 우선순위, 쓰지 못한 출처와 이유 목록)."""
    topic = job["topic"]
    skipped: list[dict[str, Any]] = []
    usable: list[Source] = []
    rows = rpc("drinks_develop_sources", {**lease, "terms": topic_terms(topic)}) or []
    for r in rows:
        kind = r.get("source_kind") or "other"
        label = r.get("title") or r.get("canonical_url") or r.get("snapshot_id")
        if r.get("linked") and r.get("role") == "discovery":
            skipped.append({"title": label, "why": "질문·인기 신호로 붙은 출처라 사실 근거로 쓰지 않음(근거 역할로 바꾸면 쓴다)"})
            continue
        if kind in config.DRINKS_DEVELOP_SOURCE_KINDS_NEVER:
            skipped.append({"title": label, "why": f"출처 종류가 {kind} 라 사실 근거로 쓰지 않음"})
            continue
        if not r.get("linked") and kind not in config.DRINKS_DEVELOP_SOURCE_KINDS_AUTO:
            skipped.append({"title": label, "why": f"출처 종류가 {kind} 라 자동으로 쓰지 않음(공식·전문·제조사만)"})
            continue
        if not r.get("body_text"):
            skipped.append({"title": label, "why": "본문이 없고 주소만 등록돼 있음 — 원문을 붙여넣어야 읽을 수 있음"})
            continue
        usable.append(Source("linked" if r.get("linked") else "collected", str(label or ""), r["body_text"], snapshot_id=r["snapshot_id"],
                             url=r.get("canonical_url"), publisher=r.get("publisher"), source_kind=kind,
                             rights_status=r.get("rights_status") or "unknown", usage_terms=r.get("usage_terms"), role=r.get("role")))
    notes: list[str] = []
    off, n = find_official(topic, deps)
    usable += off
    notes += n
    if config.DRINKS_DEVELOP_EUROPEPMC_ENABLED:
        fetcher = deps.fetcher(list(config.DRINKS_DEVELOP_EUROPEPMC_HOSTS))
        epmc, n = find_europepmc(topic, fetcher)
        usable += epmc
        notes += n
    for n in notes:
        skipped.append({"title": "(찾기)", "why": n})
    return usable[: config.DRINKS_DEVELOP_MAX_SOURCES], skipped


def insufficient_message(kept: int, report: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    lines = [f"원문 인용 대조를 통과한 근거가 {kept}건입니다(최소 {config.DRINKS_DEVELOP_MIN_CLAIMS}건)."]
    if report:
        lines.append("읽은 출처: " + "; ".join(f"{r['title']}({r['claims_kept']}건 통과/{r['claims_dropped']}건 버림)" for r in report))
    else:
        lines.append("읽을 수 있는 출처가 하나도 없었습니다.")
    for s in skipped[:6]:
        lines.append(f"- 건너뜀: {s['title']} — {s['why']}")
    lines.append("해야 할 일: 소재 화면의 [출처 추가]로 공식·전문 출처(제조사·공공기관·논문)의 원문 글을 붙여넣어 근거 역할로 등록한 뒤 다시 요청하세요. "
                 "출처는 서로 다른 곳 2곳 이상이 좋고, 사용 조건(인용 가능 여부)을 함께 적어 주세요.")
    return "\n".join(lines)[:3900]


# ─────────────────────────────────────────────────────────────
# 근거 초안
# ─────────────────────────────────────────────────────────────

def run_evidence(job: dict[str, Any], rpc: Rpc, lease: dict[str, Any], ledger: Ledger, deps: Deps, beat: Callable[[str], None]) -> dict[str, Any]:
    topic = job["topic"]
    question = topic["question"]
    beat("sources")
    sources, skipped = gather_sources(job, rpc, lease, deps)
    kept_all: list[dict[str, Any]] = []   # {text, original_quote, claim_type, src: Source}
    report: list[dict[str, Any]] = []
    for src in sources:
        if len(kept_all) >= config.DRINKS_DEVELOP_MAX_CLAIMS:
            break
        if not src.text or len(src.text) < config.DRINKS_MIN_BODY_CHARS:
            skipped.append({"title": src.title, "why": "본문이 너무 짧음"})
            continue
        beat(f"extract:{src.title[:60]}")
        text = src.text[: config.DRINKS_DEVELOP_SOURCE_MAX_CHARS]
        est = estimate_usd(config.DRINKS_DEVELOP_EXTRACT_MODEL, len(EXTRACT_SYSTEM) + len(question) + len(text), config.DRINKS_DEVELOP_EXTRACT_MAX_TOKENS)
        raw = ledger.run(config.DRINKS_DEVELOP_EXTRACT_MODEL, est, lambda t=text: deps.extract_claims(question, t), f"근거 추출: {src.title[:80]}")
        # 모델에 보낸 글(앞부분)에 대해서만 대조한다 — 잘린 뒤쪽을 인용했다면 그것은 모델이 본 적 없는 글이다.
        kept, dropped = verify_claims(raw, text)
        report.append({"title": src.title, "origin": src.origin, "url": src.url, "chars": len(text), "claims_raw": len(raw or []),
                       "claims_kept": len(kept), "claims_dropped": sum(dropped.values()), "dropped_by": dropped})
        for k in kept:
            k["src"] = src
        kept_all += kept
    kept_all = kept_all[: config.DRINKS_DEVELOP_MAX_CLAIMS]
    if len(kept_all) < config.DRINKS_DEVELOP_MIN_CLAIMS:
        raise DevelopError("evidence_insufficient", insufficient_message(len(kept_all), report, skipped), "blocked",
                           {"sources": report, "skipped": skipped, "claims_kept": len(kept_all)})
    # 통과한 주장이 있는 출처만 소재에 붙인다(읽었지만 쓸모없던 출처로 소재를 어지럽히지 않는다)
    beat("link")
    ids: dict[int, str] = {}
    for k in kept_all:
        s: Source = k["src"]
        if id(s) in ids:
            continue
        if s.snapshot_id and s.role != "evidence":
            rpc("drinks_develop_link_snapshot", {**lease, "snapshot_id": s.snapshot_id, "relation_note": "자동 개발: 근거 추출에 사용"})
            ids[id(s)] = s.snapshot_id
        elif s.snapshot_id:
            ids[id(s)] = s.snapshot_id
        else:
            added = rpc("drinks_develop_add_source", {**lease, "source": s.new_source})
            ids[id(s)] = added["snapshot_id"]
    claims = []
    for i, k in enumerate(kept_all, 1):
        s = k["src"]
        c = {"claim_id": f"c{i}", "text": k["text"], "claim_type": k["claim_type"], "support_review": "not_reviewed",
             "source_refs": [{"snapshot_id": ids[id(s)], "original_quote": k["original_quote"]}]}
        if k["claim_type"] == "opinion":
            c["attribution"] = s.publisher or s.title
        claims.append(c)
    flags = _claim_flags(claims, deps)
    cids = [c["claim_id"] for c in claims]
    brief = {"audience_question": question, "selected_claim_ids": cids, "proposed_formats": ["video"],
             "required_claims": {"video": cids[: config.DRINKS_DEVELOP_REQUIRED_CLAIMS]}}
    beat("save")
    saved = rpc("drinks_develop_save_evidence", {**lease, "evidence_pack": {"claims": claims}, "brief": brief})
    qc = saved.get("quote_check") or {}
    return {"review_id": saved.get("review_id"), "claims_kept": len(claims), "sources": report, "skipped": skipped,
            "quote_check": qc, "jev_claim_flags": flags,
            "dropped_total": sum(sum(r["dropped_by"].values()) for r in report),
            "needs_operator": ["핵심 메시지(core_takeaway) 한 줄", "주장별 지지 검토(support_review)", "출처 사용 조건 확인"]
            + (["DB 인용 대조가 일치하지 않은 인용이 있음 — 화면에서 확인"] if qc.get("unmatched") else [])}


def _claim_flags(claims: list[dict[str, Any]], deps: Deps) -> list[dict[str, Any]]:
    out = []
    for c in claims:
        quote = " ".join(r["original_quote"] for r in c["source_refs"])
        p = deps.jev_check(c["text"], quote)
        if p is not None and p >= config.DRINKS_DEVELOP_JEV_UNSUPPORTED_MIN:
            out.append({"claim_id": c["claim_id"], "p": round(p, 3)})
    return out


# ─────────────────────────────────────────────────────────────
# 제작안 초안
# ─────────────────────────────────────────────────────────────

def develop_checks(plan: dict[str, Any], allowed_ids: set[str]) -> list[script_check.Finding]:
    """개발 단계에서 더 요구하는 모양 검사(차단). 쇼츠 길이·훅·결론·허용된 근거만."""
    out: list[script_check.Finding] = []
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return [script_check.Finding("no_scenes", None, "장면(scenes)이 없습니다")]
    lo, hi = config.DRINKS_DEVELOP_SCENES
    if not (lo <= len(scenes) <= hi):
        out.append(script_check.Finding("scene_count", None, f"장면이 {len(scenes)}개입니다({lo}~{hi}개여야 합니다)"))
    total = 0.0
    for sc in scenes:
        try:
            total += float(sc.get("timing_sec") or 4)
        except (TypeError, ValueError):
            total += 4
    slo, shi = config.DRINKS_DEVELOP_SECONDS
    if not (slo <= total <= shi):
        out.append(script_check.Finding("duration_out_of_range", None, f"장면 길이 합계가 {total:g}초입니다({slo:g}~{shi:g}초여야 합니다)"))
    if "?" not in str(scenes[0].get("narration") or ""):
        out.append(script_check.Finding("first_scene_not_question", 1, "1번 장면이 질문을 던지지 않습니다(물음표 없음)"))
    for i, sc in enumerate(scenes, 1):
        bad = [c for c in (sc.get("claim_ids") or []) if str(c) not in allowed_ids]
        if bad:
            out.append(script_check.Finding("claim_not_allowed", i, f"승인된 핵심 주장이 아닌 근거: {', '.join(map(str, bad))}"))
    concl = plan.get("viewer_conclusion")
    if not isinstance(concl, dict) or not str(concl.get("text") or "").strip():
        out.append(script_check.Finding("conclusion_missing_dev", None, "'시청자가 내릴 결론' 한 줄이 없습니다"))
    elif any(str(c) not in allowed_ids for c in concl.get("claim_ids") or []):
        out.append(script_check.Finding("claim_not_allowed", None, "결론의 근거가 승인된 핵심 주장이 아닙니다"))
    return out


def check_plan(plan: dict[str, Any], review: dict[str, Any], topic: dict[str, Any]) -> script_check.Report:
    claims = review.get("claims") or []
    allowed = {str(c.get("claim_id")) for c in claims}
    brief = dict(review.get("brief") or {})
    brief.setdefault("audience_question", topic.get("question"))
    spec = script_check.plan_spec(plan, claims, sources=review.get("sources"), brief=brief)
    # plan_spec 의 sources 는 check() 가 'source' 칸이 없으면 읽지 않는다(실측) — 출처 표기(논문 연도 등)의 숫자를 허용 범위에 넣으려면 'source' 로 준다.
    spec["source"] = {str(i): " ".join(str(v) for v in (s or {}).values()) for i, s in enumerate(review.get("sources") or [])}
    rep = script_check.check(spec)
    rep.blocks.extend(develop_checks(plan, allowed))
    return rep


def jev_flags(plan: dict[str, Any], claims: list[dict[str, Any]], deps: Deps) -> list[dict[str, Any]]:
    by_id = {str(c.get("claim_id")): c for c in claims}
    out = []
    for i, sc in enumerate(plan.get("scenes") or [], 1):
        cids = [str(x) for x in sc.get("claim_ids") or [] if str(x) in by_id]
        if not cids or (sc.get("content_kind") or "fact") != "fact":
            continue
        src = "\n".join(r.get("original_quote") or "" for c in cids for r in by_id[c].get("source_refs") or [] if isinstance(r, dict))
        p = deps.jev_check(str(sc.get("narration") or ""), src)
        if p is not None and p >= config.DRINKS_DEVELOP_JEV_UNSUPPORTED_MIN:
            out.append({"scene": i, "p": round(p, 3)})
    return out


def source_table(plan: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    """장면 → 근거 → 원문 인용 대조표. 운영자가 승인 전에 눈으로 대조한다."""
    by_id = {str(c.get("claim_id")): c for c in review.get("claims") or []}
    meta = {str(s.get("snapshot_id")): s for s in review.get("sources") or []}
    rows = []
    for i, sc in enumerate(plan.get("scenes") or [], 1):
        cl = []
        for cid in [str(x) for x in sc.get("claim_ids") or []]:
            c = by_id.get(cid)
            if not c:
                continue
            quotes = [{"quote": r.get("original_quote"), "source_title": (meta.get(str(r.get("snapshot_id"))) or {}).get("title"),
                       "source_url": (meta.get(str(r.get("snapshot_id"))) or {}).get("url"), "snapshot_id": r.get("snapshot_id")}
                      for r in c.get("source_refs") or [] if isinstance(r, dict)]
            cl.append({"claim_id": cid, "text": c.get("text"), "quotes": quotes})
        rows.append({"scene": i, "narration": sc.get("narration"), "content_kind": sc.get("content_kind") or "fact", "claims": cl})
    return rows


def clean_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """저장용: DB 가 보존하는 칸만(viewer_conclusion 은 notes 한 줄로 옮긴다 — 0050·0054·0057 검증기는 scenes·notes 만 남긴다)."""
    concl = plan.get("viewer_conclusion") if isinstance(plan.get("viewer_conclusion"), dict) else {}
    ids = "·".join(str(c) for c in concl.get("claim_ids") or [])
    notes = f"시청자 결론({ids}): {concl.get('text')}" if concl.get("text") else None
    return {"scenes": plan.get("scenes") or [], "notes": notes}


def run_plan(job: dict[str, Any], rpc: Rpc, lease: dict[str, Any], ledger: Ledger, deps: Deps, beat: Callable[[str], None]) -> dict[str, Any]:
    topic, review = job["topic"], job["review"]
    claims = review.get("claims") or []
    if not claims:
        raise DevelopError("no_core_claims", "승인된 근거 버전에 핵심 주장이 없습니다")
    brief = review.get("brief") or {}
    question = topic["question"]
    feedback: Optional[list[str]] = None
    plan: dict[str, Any] = {}
    rep = script_check.Report()
    flags: list[dict[str, Any]] = []
    rewrites = 0
    for attempt in range(config.DRINKS_DEVELOP_MAX_REWRITES + 1):
        beat(f"write:{attempt}")
        in_chars = len(PLAN_SYSTEM) + len(plan_user_prompt(question, claims, brief, feedback))
        est = estimate_usd(config.DRINKS_DEVELOP_PLAN_MODEL, in_chars, config.DRINKS_DEVELOP_PLAN_MAX_TOKENS)
        plan = ledger.run(config.DRINKS_DEVELOP_PLAN_MODEL, est, lambda fb=feedback: deps.write_plan(question, claims, brief, fb),
                          "대본·화면 계획 초안" if attempt == 0 else "대본·화면 계획 다시 쓰기")
        if not isinstance(plan, dict):
            plan = {}
        beat(f"check:{attempt}")
        rep = check_plan(plan, review, topic)
        flags = jev_flags(plan, claims, deps)
        if rep.ok and not flags:
            break
        if attempt < config.DRINKS_DEVELOP_MAX_REWRITES:
            feedback = [f"{f.scene or '전체'}번 {f.code}: {f.message}" for f in rep.blocks] + \
                       [f"{f['scene']}번 장면: 인용한 원문을 넘는 주장일 수 있음(Jev {f['p']})" for f in flags] + \
                       [f"(알림) {f.scene or '전체'}번 {f.code}: {f.message}" for f in rep.warns[:6]]
            rewrites += 1
    if not rep.ok:
        raise DevelopError("script_check_failed", "대본 검사에서 막혔습니다(다시 쓴 뒤에도).\n" + script_check.summary_ko(rep), "blocked",
                           {"checks": rep.as_dict(), "rewrites": rewrites, "jev_flags": flags, "rejected_plan": plan})
    beat("save")
    saved = rpc("drinks_develop_save_plan", {**lease, "plan_json": clean_plan(plan)})
    return {"revision_id": saved.get("revision_id"), "checks": rep.as_dict(), "rewrites": rewrites, "jev_flags": flags,
            "source_table": source_table(plan, review), "viewer_conclusion": plan.get("viewer_conclusion"),
            "coverage": saved.get("coverage")}


# ─────────────────────────────────────────────────────────────
# 워커 루프
# ─────────────────────────────────────────────────────────────

def process_job(job: dict[str, Any], rpc: Rpc, deps: Deps) -> dict[str, Any]:
    lease = {"request_id": job["request_id"], "lease_token": job["lease_token"]}
    ledger = Ledger(rpc, lease, job.get("budget_id"))

    def beat(step: str) -> None:
        hb = rpc("drinks_heartbeat_develop", {**lease, "step": step}) or {}
        if hb.get("cancel_requested"):
            raise DevelopError("canceled", "운영자가 취소했습니다", "failed")

    def finish(outcome: str, **kw: Any) -> dict[str, Any]:
        return rpc("drinks_finish_develop", {**lease, "outcome": outcome, **kw})

    try:
        if not job.get("budget_id"):
            raise DevelopError("budget_missing", "결재(예산)가 없는 요청입니다 — 대시보드에서 개발 결재를 열고 다시 요청하세요")
        beat("start")
        run = run_evidence if job["kind"] == "evidence" else run_plan
        result = run(job, rpc, lease, ledger, deps, beat)
        result["cost"] = {"spent_usd": round(ledger.spent, 4), "calls": ledger.calls}
        return finish("succeeded", result=result)
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 개발 요청 %s 임대를 잃어 결과를 저장하지 않습니다", job["request_id"])
            return {"status": "lease_lost"}
        try:
            return finish("failed", error_code=exc.code, error_message=exc.message, result={"cost": {"spent_usd": round(ledger.spent, 4), "calls": ledger.calls}})
        except DbError:
            return {"status": "lease_lost"}
    except DevelopError as exc:
        res = dict(exc.result)
        res["cost"] = {"spent_usd": round(ledger.spent, 4), "calls": ledger.calls}
        try:
            return finish(exc.outcome, error_code=exc.code, error_message=exc.message, result=res)
        except DbError:
            return {"status": "lease_lost"}
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 요청을 running 에 남기지 않는다
        log.exception("drinks: 개발 요청 %s 예외", job["request_id"])
        try:
            return finish("failed", error_code="worker_error", error_message=f"워커 예외: {type(exc).__name__}",
                          result={"cost": {"spent_usd": round(ledger.spent, 4), "calls": ledger.calls}})
        except DbError:
            return {"status": "lease_lost"}


def run_queue(rpc: Rpc, deps: Deps, *, worker_id: str, max_jobs: int = 5) -> list[dict[str, Any]]:
    out = []
    for _ in range(max_jobs):
        got = rpc("drinks_start_develop", {"worker_id": worker_id}) or {}
        job = got.get("job")
        if not job:
            break
        log.info("drinks: 개발 %s 시작 (%s, %s)", job["request_id"], job["kind"], job["topic"].get("title"))
        res = process_job(job, rpc, deps)
        log.info("drinks: 개발 %s → %s", job["request_id"], (res or {}).get("status"))
        out.append({"request_id": job["request_id"], **(res or {})})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 소재 자동 개발 워커")
    ap.add_argument("--max-jobs", type=int, default=5)
    args = ap.parse_args(argv)
    res = run_queue(supabase_rpc(), Deps(), worker_id=config.WORKER_ID, max_jobs=args.max_jobs)
    return 1 if any(r.get("status") in ("failed", "lease_lost") for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
