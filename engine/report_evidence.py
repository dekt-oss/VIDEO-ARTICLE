"""Evidence Contract — 수치 근거의 기계 검증 (작업지시서 영상엔진품질 v3 §5).

무엇을 푸는가: 지금까지 화면의 숫자는 "모델이 그렇게 말했으니까" 나갔다. Fact Sheet 의
`number_facts` 에는 값·단위·기간이 있었지만 **그 값이 원문 어디에서 왔는지**가 없었고, 그래서
"화면의 27.48% 가 리포트에 실제로 있는 숫자인가"를 아무도 확인하지 않았다. v3.3 이 겪은
가짜 대시보드 사고(§21 K1)와 같은 계열의 위험이다.

자세(이 저장소의 기존 규율을 그대로 따른다):
- **코드가 판정한다.** 모델이 `validation.number_match: true` 라고 자기보고해도 믿지 않는다
  (engine/factsheet.py:129 의 missing_fields 재계산, engine/explainer.py 의 게이트와 같은 자세).
- **반환은 토큰 문자열 리스트.** 사람 말 라벨은 GATE_LABELS 로 분리한다(explainer.py 관례).
- **순수 모듈.** 네트워크·DB 를 모른다. 입력은 Fact Sheet 와 원문 chunk 뿐이다.

★ explainer 게이트에 얹지 않은 이유(Phase 0 §5): 입력이 다르고(Fact Sheet vs 지시서 헤더),
  단계가 다르며(초안 vs 지시서), 차단 정책이 다르다(리포트 라인 compliance 는 blocked 를
  항상 False 로 둔다). 섞으면 게이트의 의미가 흐려진다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import config

# ─────────────────────────────────────────────────────────────
# 단위 정규화 — §5-2 "단위 정규화"
#   같은 값을 두 표기로 쓰면(억원 / 억) 비교 기준 대조가 통과했다가 화면에서 어긋난다.
# ─────────────────────────────────────────────────────────────
_UNIT_ALIASES: dict[str, str] = {
    "%": "%", "퍼센트": "%", "percent": "%", "％": "%",
    "%p": "%p", "%P": "%p", "퍼센트포인트": "%p", "bp": "bp", "bps": "bp",
    "배": "x", "x": "x", "X": "x", "times": "x",
    "원": "원", "KRW": "원", "won": "원",
    "억": "억원", "억원": "억원", "조": "조원", "조원": "조원",
    "만": "만", "천": "천",
    "달러": "USD", "USD": "USD", "$": "USD", "불": "USD",
    "억달러": "억USD", "억 달러": "억USD",
    "개": "개", "명": "명", "톤": "톤", "대": "대",
}


def normalize_unit(unit: Any) -> str:
    """표기 흔들림을 하나로. 모르는 단위는 공백만 정리해 그대로 둔다(임의 매핑 금지)."""
    raw = str(unit or "").strip()
    if not raw:
        return ""
    return _UNIT_ALIASES.get(raw, raw)


# 기간 표기 — 리포트에서 실제로 쓰이는 형태만 인정한다.
#   2026F / 2026E / 2026 / 1Q26 / 2Q26F / FY4Q26 / TTM / 상반기 / 연간
_PERIOD_RE = re.compile(
    r"^(TTM|LTM|연간|상반기|하반기|"
    r"(FY)?[1-4]Q\d{2}(F|E|P)?|"
    r"(FY)?\d{4}(F|E|P)?|\d{2}(F|E|P)?)$",
    re.IGNORECASE,
)


# 같은 기간을 부르는 다른 표기를 정본 형태로 옮긴다. ★ 프로덕션 실측에서 정상 값 3건이
#   number_without_period 로 걸렸다 — "12M"(목표주가 12개월), "2026.07.30"(현재가 기준일).
#   프롬프트 예시에만 기대면 모델 출력이 흔들릴 때마다 정직한 사실이 차단된다. 코드가 판정한다.
_PERIOD_NORMALIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(\d{4})\s*년$"), r"\1"),                       # 2026년 → 2026
    (re.compile(r"^(\d{2})\s*년$"), r"\1"),                       # 26년 → 26
    (re.compile(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$"), r"\1"),   # 2026.07.30 → 2026
    (re.compile(r"^(\d{4})[.\-/](\d{1,2})$"), r"\1"),             # 2026.07 → 2026
    (re.compile(r"^FY\s*(\d{2,4})$", re.I), r"\1"),               # FY26 → 26
    (re.compile(r"^([12])H\s*(\d{2})$", re.I), r"\2"),            # 1H26 → 26 (반기는 연도로)
    (re.compile(r"^(\d{2})년\s*(상|하)반기$"), r"\1"),             # 26년 상반기 → 26
    (re.compile(r"^(\d{1,2})\s*개?월$"), "TTM"),                   # 12M / 12개월 → 기간 폭 표기
    (re.compile(r"^(\d{1,2})M$", re.I), "TTM"),
)


def normalize_period(period: Any) -> str:
    """기간 표기를 정본 형태로. 옮길 수 없으면 원문을 그대로 돌려준다."""
    raw = str(period or "").strip()
    for pattern, repl in _PERIOD_NORMALIZERS:
        if pattern.match(raw):
            return pattern.sub(repl, raw)
    return raw


def period_is_explicit(period: Any) -> bool:
    """기간이 확정 표기인가. 빈 문자열·'최근'·'향후' 같은 모호어는 미확정이다."""
    raw = normalize_period(period)
    return bool(raw) and bool(_PERIOD_RE.match(raw))


# ─────────────────────────────────────────────────────────────
# 인용 대조 — §5-2 "quote 내 숫자 ↔ value 일치", "quote 가 claim 을 지지"
# ─────────────────────────────────────────────────────────────
# ★ 하이픈을 마이너스로 읽지 않는다. `-?\d` 였을 때 "3-5% 성장"(범위 표기)의 `-5` 가 값 -5.0
#   으로 잡혀 **-5% 하락이 성장 문장으로 검증**됐다(적대적 리뷰 재현). "2025-2026년"도
#   [2025, -2026] 이 됐다. 한국 리포트에서 음수는 하이픈이 아니라 `△`·`▽` 나 "감소/하락"
#   으로 쓰므로, 마이너스는 **앞이 공백·문두·괄호일 때만** 인정한다.
_NUM_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[{=]))-\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    """문장에 적힌 숫자를 그대로 뽑는다(콤마 제거)."""
    out: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    return out


# 한국어 자릿수 표기 — 리포트 본문은 "1조 5,791억원" 처럼 한 값을 두 토막으로 쓴다.
# 숫자만 뽑으면 1 과 5791 이 되어 실제 값 15,791억을 놓친다(실측: 하나증권 LG전자 영업이익).
# ★ 복합 자릿수를 한 토큰으로 본다. '천'·'백'은 홀로 쓰이기도 하지만 리포트 본문에서는
#   대개 뒤 자릿수에 붙는 접두사다 — "3천억"은 3×10³ 이 아니라 3×10¹¹ 이다. 예전엔 '천'이
#   아예 없어 "3천억원"이 3.0 으로만 잡혔고(_UNIT_ALIASES 에는 '천'이 있어 두 표가 어긋나
#   있었다), 바로 넣었다면 3,000 이라는 **틀린 값**을 만들 뻔했다.
#   긴 토큰이 먼저 매칭되도록 정규식 순서를 유지한다.
_KOREAN_SCALES: dict[str, float] = {
    "조": 1e12,
    "천억": 1e11, "백억": 1e10, "억": 1e8,
    "천만": 1e7, "백만": 1e6, "만": 1e4,
    "천": 1e3,
}
_KO_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(조|천억|백억|억|천만|백만|만|천)")


# 두 자릿수 토막을 한 값으로 묶으려면 사이가 **공백뿐**이어야 한다.
#
# ★ 두 번 고쳤다. 처음엔 구분자를 안 봐서 "영업이익 1조, 순이익 8,000억" 이 1.8조가 됐고,
#   그 다음엔 구두점 + 낱글자 조사 목록(은/는/이/가…)으로 막았는데 그 목록에 없는 어절이
#   끼면 그대로 뚫렸다(적대적 리뷰 재현):
#     "매출 3조 순익 500억"     → 3.05조   ← '순익'에 조사가 없다
#     "3조 규모 500억 투자"      → 3.05조
#     "목표 1조 달성 3,000억 투자" → 1.3조
#   검증기가 원문에 없는 후보 숫자를 스스로 만들어 내면, 그 후보가 대조를 통과시켜
#   **거짓 검증 통과**가 된다. 목록을 늘리는 대신 규칙을 뒤집는다 — 합치는 쪽이 증명한다.
#   진짜 복합 표기("1조 5,791억원", "23조 8,265억원")는 사이에 공백밖에 없다.
_KO_JOIN_OK_RE = re.compile(r"^\s*$")


def korean_scaled_spans(text: str) -> list[tuple[float, int, int]]:
    """'1조 5,791억' → (원 단위 합산값, 시작, 끝). 밀도 계산이 스팬을 필요로 한다.

    묶는 조건 둘: ① 자릿수가 **내림차순**일 것('2조 3조'는 다른 두 값이다)
                  ② 두 토막 **사이에 구분자가 없을** 것. 쉼표·괄호·조사가 끼면 다른 값이다.
    """
    tokens: list[tuple[float, float, int, int]] = []   # (숫자, 배수, 시작, 끝)
    for m in _KO_NUM_RE.finditer(text or ""):
        try:
            tokens.append((float(m.group(1).replace(",", "")),
                           _KOREAN_SCALES[m.group(2)], m.start(), m.end()))
        except ValueError:
            continue

    out: list[tuple[float, int, int]] = []
    i = 0
    while i < len(tokens):
        total = tokens[i][0] * tokens[i][1]
        start, last_scale, last_end = tokens[i][2], tokens[i][1], tokens[i][3]
        j = i + 1
        while j < len(tokens) and tokens[j][1] < last_scale:
            between = (text or "")[last_end:tokens[j][2]]
            if not _KO_JOIN_OK_RE.match(between):
                break
            total += tokens[j][0] * tokens[j][1]
            last_scale, last_end = tokens[j][1], tokens[j][3]
            j += 1
        out.append((total, start, last_end))
        i = j
    return out


def korean_scaled_numbers(text: str) -> list[float]:
    """'1조 5,791억' → 원 단위 합산값 목록."""
    return [v for v, _s, _e in korean_scaled_spans(text)]


# 대조에서 무시할 것 — 글자·숫자가 아닌 모든 것.
#   ★ 왜 이렇게까지 지우는가(2026-08-29 논문 라인 실측): arXiv 원문에는 LaTeX 잔재와
#     활자 따옴표가 섞여 있고, 모델은 그것을 조금씩 다르게 옮긴다. 실측된 두 경우 —
#         모델 ``Ghost Riders''      원문 “Ghost Riders”
#         모델 $\sim$7 min           원문 \sim7 min
#     둘 다 **인용은 정확한데 표기만 다르다.** 그런데 대조가 실패해 정상 주장 5개가
#     "지어낸 인용"으로 차단됐다. 옳게 한 것을 벌하는 게이트는 반드시 무시당한다.
#   ★ 그래도 위조는 못 지나간다: 구두점을 지워도 **낱말의 순서와 철자는 그대로** 요구된다.
#     지어낸 문장이 우연히 같은 문자열이 될 수는 없다.
_NON_ALNUM = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㆎ一-鿿]+")
def _squash(text: str) -> str:
    """대조용 정규화 — 공백·유니코드 폭·구두점·마크업 차이를 없앤다.

    ★ 원문은 PDF·HTML 추출물이라 줄바꿈과 이중 공백이 아무 데나 있고, LaTeX 조각과
      활자 따옴표가 섞인다. 인용문을 그대로 `in` 으로 찾으면 **옳게 옮겨 적은 인용도
      실패한다** — 위 _NON_ALNUM 주석의 실측 두 건이 그것이다.
    """
    norm = unicodedata.normalize("NFKC", text or "")
    return _NON_ALNUM.sub("", norm)


def _longest_edge_match(q: str, src: str) -> int:
    """q 의 **앞에서부터** 또는 **뒤에서부터** 원문에 통째로 들어 있는 최대 길이."""
    def grow(get_slice) -> int:
        lo, hi = 0, len(q)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if get_slice(mid) in src:
                lo = mid
            else:
                hi = mid - 1
        return lo

    return max(grow(lambda n: q[:n]), grow(lambda n: q[len(q) - n:]))


def quote_found_in_source(quote: str, source_text: str) -> bool:
    """인용문이 원문에 실제로 있는가.

    ★ 완전 일치를 요구하지 않는다(2026-08-29 실측). 표기 차이를 규칙으로 쫓는 방식은
      **서로 충돌한다**: 각주 표기 `$^{1}$` 는 빼야 대조가 되는데(본문에선 9번이다),
      단위 지수 `km s$^{-1}$` 는 빼면 대조가 깨진다(본문에 -1 이 남아 있다).
      규칙을 늘릴수록 새 문서 형식마다 또 깨진다.

    ★ 그래서 **연속 일치 비율**로 본다. 인용의 앞이나 뒤에서부터 원문에 통째로 들어 있는
      길이가 전체의 EVIDENCE_QUOTE_MATCH_RATIO 이상이면 근거가 있는 것으로 본다.
      실측 두 건 모두 129/130·다수 일치였고, 어긋난 것은 문서 장치(각주 번호)뿐이었다.

    ★ 위조는 여전히 못 지나간다: 90% 를 **연속으로** 일치시키려면 사실상 원문을 그대로
      옮겨야 한다. 지어낸 문장이 우연히 그렇게 될 수는 없다.
    """
    q = _squash(quote)
    if len(q) < config.EVIDENCE_QUOTE_MIN_CHARS:
        return False
    src = _squash(source_text)
    if q in src:
        return True
    return _longest_edge_match(q, src) / len(q) >= config.EVIDENCE_QUOTE_MATCH_RATIO


def match_candidates(text: str) -> list[float]:
    """대조 후보 숫자. 한국어 자릿수 표기는 **합산값 하나**로만 세고 토막은 빼낸다.

    ★ 토막을 남기면 "1조 5,791억" 의 `1` 이 후보가 되고, 만(1e4) 환산과 겹쳐 9,999 가
      통과한다(실측). 자릿수 표기의 구성 요소는 독립된 수치가 아니다.
    """
    spans = korean_scaled_spans(text)
    out: list[float] = [v for v, _s, _e in spans]
    covered = [(s, e) for _v, s, e in spans]
    for m in _NUM_RE.finditer(text or ""):
        if any(s <= m.start() < e for s, e in covered):
            continue
        try:
            out.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    return out


# 문장이 "줄었다"를 말하는 표지. 한국 리포트의 음수 표기는 부호가 아니라 서술어와
# 삼각기호(△·▲·▽)다 — "영업이익 △15%", "전년 대비 15% 감소".
_NEGATIVE_DIRECTION_RE = re.compile(
    r"[△▽▼]|감소|하락|축소|둔화|역성장|적자|손실|마이너스|하회|급락|下落"
)


def _close(a: float, b: float, tol: float) -> bool:
    """상대 오차 비교. 0 은 정확히 일치할 때만 통과한다."""
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    return denom > 0 and abs(a - b) / denom <= tol


def value_supported_by_quote(value: Any, quote: str, *, tolerance: float | None = None) -> bool:
    """인용문 안의 숫자 중 하나가 value 와 일치하는가.

    ★ 두 번 고쳤다. 처음엔 임의의 자릿수 배수를 곱해 비교했는데 오차 허용과 겹쳐 "1" 이
      9,999 와 일치로 판정됐다. 그래서 가수(mantissa) 비교로 바꿨더니 이번엔 **부호를 버리고**
      (+15% 성장이 "-15% 감소" 원문으로 검증됐다) **10배 오류를 통과**시키고(15,791 vs 1,579억)
      허용 오차가 가수 크기에 따라 1%~10% 로 흔들렸다(적대적 리뷰 재현).

    지금 방식: **부호를 보존**하고, 자릿수 환산은 한국어 단위계(만·억·조)에 해당하는
    **명시적 배수**로만 제한하며, 그 안에서 **상대 오차**로 비교한다. 단위 환산은 통과시키되
    자릿수 오류와 근사값은 막는다.
    """
    if value is None:
        return False
    tol = config.EVIDENCE_NUMBER_TOLERANCE if tolerance is None else tolerance
    target = float(value)
    # ★ 한국 리포트는 감소를 `-15%` 로 쓰지 않고 "15% 감소"·"△15%"·"15% 하락" 으로 쓴다.
    #   부호 보존만 넣었을 때 -15 가 "영업이익이 15% 감소했다" 로 검증되지 않아 정직한
    #   사실에 number_not_in_quote 하드블록이 붙었다(부호 오탐 하나를 막고 다른 오탐을 만든 것).
    #   문장이 감소를 말하면 양수 후보도 음수로 읽는다. 반대 방향은 하지 않는다 —
    #   "-15% 감소" 를 +15 로 읽어주면 부호 보존이 무의미해진다.
    negated = bool(_NEGATIVE_DIRECTION_RE.search(quote or ""))
    for a in match_candidates(quote):
        signs = (a, -a) if (negated and a > 0) else (a,)
        for signed in signs:
            for scale in config.EVIDENCE_SCALE_FACTORS:
                if _close(signed * scale, target, tol):
                    return True
    return False


# ─────────────────────────────────────────────────────────────
# evidence unit 정규화 — number_facts 항목을 승격한다(기존 필드는 그대로 둔다)
# ─────────────────────────────────────────────────────────────
def _known_chunk_ids(chunks: Any) -> set[str]:
    return {str(c.get("chunk_id")) for c in (chunks or []) if isinstance(c, dict) and c.get("chunk_id")}


def locate_chunk(quote: str, chunks: Any) -> str:
    """인용문이 실제로 들어 있는 청크의 id. 못 찾으면 빈 문자열.

    ★ 모델이 붙인 chunk_id 라벨을 믿지 않는다 — 이 저장소의 "코드가 판정한다" 자세 그대로다.
      프로덕션 실측에서 **19개 ref 전부 chunk_id 가 빈 문자열**이었다. 인용문 19개는 모두
      원문에 그대로 있었는데(대조 확인) 모델이 붙인 라벨만 청크 목록과 안 맞아서 버려진
      것이다. 라벨을 버리고 위치로 찾으면 그대로 해소된다.
    """
    q = _squash(quote)
    if len(q) < config.EVIDENCE_QUOTE_MIN_CHARS:
        return ""
    for c in (chunks or []):
        if not isinstance(c, dict) or not c.get("chunk_id"):
            continue
        if q in _squash(str(c.get("text") or "")):
            return str(c["chunk_id"])
    # 청크 경계에 걸친 인용은 어느 한 청크에도 통째로 들어 있지 않다 — 앞머리로 찾는다.
    head = q[: config.EVIDENCE_QUOTE_MIN_CHARS]
    for c in (chunks or []):
        if not isinstance(c, dict) or not c.get("chunk_id"):
            continue
        if head in _squash(str(c.get("text") or "")):
            return str(c["chunk_id"])
    return ""


def normalize_source_refs(value: Any, chunks: Any) -> list[dict[str, Any]]:
    """source_refs 정규화. chunk_id 는 **인용문의 실제 위치로 다시 매긴다.**

    모델이 준 id 는 그것이 맞을 때만 남기고, 틀렸거나 비었으면 위치로 찾는다. 어느 청크에도
    없으면 빈 문자열 — dangling 참조를 만들지 않는다는 원래 규칙은 그대로다.

    page 는 여기서 만들지 않는다. 우리가 PDF 를 파싱하지 않으므로 페이지는 Fact Sheet 의
    source_page 로 해소되는 것만 살아남는다(engine/explainer.filter_page_refs 와 같은 자세).
    """
    known = _known_chunk_ids(chunks)
    by_id = {str(c.get("chunk_id")): c for c in (chunks or [])
             if isinstance(c, dict) and c.get("chunk_id")}
    out: list[dict[str, Any]] = []
    for item in (value or []):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        if not quote:
            continue
        claimed = str(item.get("chunk_id") or "").strip()
        chunk_id = ""
        if claimed in known:
            body = _squash(str(by_id[claimed].get("text") or ""))
            if _squash(quote) in body:
                chunk_id = claimed          # 라벨이 맞다
        if not chunk_id:
            chunk_id = locate_chunk(quote, chunks)
        out.append({
            "chunk_id": chunk_id,
            "quote": quote[: config.EVIDENCE_QUOTE_MAX_CHARS],
        })
    return out[: config.EVIDENCE_MAX_SOURCE_REFS]


def validate_fact(fact: dict[str, Any], source_text: str) -> dict[str, Any]:
    """수치 사실 1개를 원문과 대조한다. **코드 판정** — 모델 자기보고를 덮어쓴다.

    반환은 4종 판정 dict. 판정 불가(원문 없음·인용 없음)는 False 가 아니라 None 이다 —
    "검증했더니 틀렸다"와 "검증할 수 없었다"를 섞으면 게이트가 거짓말을 한다.
    """
    refs = fact.get("source_refs") or []
    quotes = [str(r.get("quote") or "") for r in refs]
    joined = " ".join(quotes)

    number_match: bool | None = None
    quote_supports: bool | None = None
    if quotes:
        quote_supports = any(quote_found_in_source(q, source_text) for q in quotes) \
            if source_text else None
        if fact.get("value") is not None:
            number_match = value_supported_by_quote(fact.get("value"), joined)

    unit_match = bool(normalize_unit(fact.get("unit"))) if fact.get("value") is not None else None
    return {
        "number_match": number_match,
        "unit_match": unit_match,
        "period_match": period_is_explicit(fact.get("period")),
        "quote_supports_claim": quote_supports,
    }


def attach_evidence(fact_sheet: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    """Fact Sheet 의 number_facts 를 evidence unit 으로 승격한다(제자리 갱신 후 반환).

    추가하는 것: `unit_norm` · `source_refs`(정규화) · `validation`(코드 판정).
    기존 필드는 하나도 건드리지 않는다 — 하위호환(대시보드·지시서가 이미 읽는다).
    """
    packet = packet or {}
    chunks = packet.get("chunks") or []
    source_text = str(packet.get("text") or "")
    for fact in (fact_sheet.get("number_facts") or []):
        fact["unit_norm"] = normalize_unit(fact.get("unit"))
        fact["source_refs"] = normalize_source_refs(fact.get("source_refs"), chunks)
        fact["validation"] = validate_fact(fact, source_text)
    return fact_sheet


# ─────────────────────────────────────────────────────────────
# §5-3 게이트 — 하드 차단 4종 + content_profile 최소 기준
# ─────────────────────────────────────────────────────────────
def hard_blocks(fact_sheet: dict[str, Any]) -> list[str]:
    """§5-3 하드 차단 4종. 개수와 무관하게 하나라도 걸리면 차단 후보다.

    ★ "검증할 수 없었다"(None)는 차단하지 않는다. 원문이 없는 리포트(텔레그램 계열)까지
      전부 막으면 재고가 통째로 멈춘다 — 그건 §9 의 source_depth 정책이 다룰 문제다.
    """
    out: list[str] = []
    facts = fact_sheet.get("number_facts") or []
    if not facts:
        return out

    # ★ 예전에는 facts[0] 을 "핵심 수치"로 가정했는데 그 가정이 성립하지 않는다 — number_facts
    #   순서는 LLM 출력 순서 그대로이고 프롬프트에 "핵심을 첫 번째로"라는 지시가 없다
    #   (적대적 리뷰). 지금은 "인용이 붙은 수치가 **하나도** 없는가"를 본다.
    if not any(f.get("source_refs") for f in facts):
        out.append("no_fact_has_source_ref")

    for fact in facts:
        fid = fact.get("fact_id") or "?"
        v = fact.get("validation") or {}
        if fact.get("value") is not None:
            if not fact.get("unit_norm"):
                out.append(f"number_without_unit:{fid}")
            if not v.get("period_match"):
                out.append(f"number_without_period:{fid}")
        if v.get("quote_supports_claim") is False:
            out.append(f"quote_not_in_source:{fid}")
        if v.get("number_match") is False:
            out.append(f"number_not_in_quote:{fid}")

    out.extend(f"conflicting_numbers:{k}" for k in conflict_groups(facts))
    return sorted(set(out))


def conflict_groups(facts: list[dict[str, Any]]) -> list[str]:
    """같은 것을 가리키는데 값이 다르면 충돌이다(§5-2).

    자동으로 하나를 고르지 않는다 — 어느 쪽이 맞는지는 원문을 본 사람이 정한다.

    ★ 키에 `comparator.basis` 와 `scope` 를 넣는다. 넣지 않으면 **컨센서스 14,000억 vs 실적
      15,791억** 처럼 정당하게 나란히 적은 두 값이 충돌로 잡힌다(적대적 리뷰 재현).
    """
    buckets: dict[str, set[float]] = {}
    for f in facts:
        if f.get("value") is None or not f.get("metric"):
            continue
        basis = (f.get("comparator") or {}).get("basis") or f.get("basis") or ""
        key = "|".join([
            str(f.get("metric")), str(f.get("period") or ""),
            str(f.get("unit_norm") or f.get("unit") or ""),
            str(f.get("scope") or ""), str(basis),
        ])
        buckets.setdefault(key, set()).add(round(float(f["value"]), 6))
    return sorted(k for k, vals in buckets.items() if len(vals) > 1)


def profile_gate(fact_sheet: dict[str, Any], profile: str) -> list[str]:
    """§5-3 content_profile 최소 기준 — **경고**(주 차단은 hard_blocks).

    v1 의 "≥8 근거 / ≥3 비교" 일괄 기준은 시황·이벤트 리포트에 과도하다는 지적(§0-1 #3)을
    받아 프로파일별로 나뉘었다. 임계값은 전부 config 에 있다.
    """
    spec = config.EVIDENCE_PROFILE_MINIMUMS.get(
        profile, config.EVIDENCE_PROFILE_MINIMUMS[config.EVIDENCE_PROFILE_DEFAULT])
    facts = fact_sheet.get("number_facts") or []
    out: list[str] = []

    if len(facts) < spec["min_evidence"]:
        out.append(f"evidence_below_min:{len(facts)}/{spec['min_evidence']}")

    comparators = sum(1 for f in facts if (f.get("comparator") or {}).get("basis"))
    if comparators < spec["min_comparator"]:
        out.append(f"comparator_below_min:{comparators}/{spec['min_comparator']}")

    # ★ 리스크는 키워드로 찾지 않는다. factsheet 가 "리포트가 말한 것만, 없으면 빈 배열"로
    #   바뀌었는데(§5) 게이트가 본문에서 '리스크|우려|부담' 을 찾고 있어, 정상 Fact Sheet 에도
    #   category_missing:리스크 가 상시 떴다(적대적 리뷰 재현). 두 변경이 서로를 밟았다.
    #   risks 배열이 있으면 충족, 없으면 그대로 경고 — 배열 자체가 판정 대상이다.
    if spec.get("requires_risks") and not (fact_sheet.get("risks") or []):
        out.append("risks_missing")

    haystack = " ".join([
        *(str(x) for x in (fact_sheet.get("what") or [])),
        *(str(x) for x in (fact_sheet.get("basis") or [])),
        *(str(x) for x in (fact_sheet.get("risks") or [])),
        *(str(f.get("metric") or "") for f in facts),
        *(str(f.get("display") or "") for f in facts),
    ])
    for category, keywords in spec["required_categories"].items():
        if not any(k in haystack for k in keywords):
            out.append(f"category_missing:{category}")
    return sorted(out)


def build_block(fact_sheet: dict[str, Any], profile: str = "") -> dict[str, Any]:
    """게이트 진입점. 대시보드가 이미 읽는 키 관례(block_reasons/warnings)에 맞춘다."""
    prof = profile or str(fact_sheet.get("content_profile") or config.EVIDENCE_PROFILE_DEFAULT)
    reasons = hard_blocks(fact_sheet)
    warnings = profile_gate(fact_sheet, prof)
    return {
        "content_profile": prof,
        "source_depth": str(fact_sheet.get("source_depth") or "summary_only"),
        "block_reasons": reasons,
        "warnings": warnings,
        "blocked": bool(reasons) and config.EVIDENCE_HARD_BLOCK_ENABLED,
    }


# ─────────────────────────────────────────────────────────────
# §6 Story Plan 검증 — 근거가 많아도 산만하면 설명이 안 된다(§16 해석표)
# ─────────────────────────────────────────────────────────────
def validate_story_plan(plan: dict[str, Any], fact_sheet: dict[str, Any]) -> list[str]:
    """논증 설계를 검사한다. 순수 함수 — 경고 토큰 리스트를 돌려준다."""
    out: list[str] = []
    plan = plan or {}
    if not str(plan.get("thesis") or "").strip():
        out.append("thesis_missing")

    chain = plan.get("claim_chain") or []
    if len(chain) < config.STORY_CLAIM_MIN:
        out.append(f"claims_below_min:{len(chain)}/{config.STORY_CLAIM_MIN}")
    if len(chain) > config.STORY_CLAIM_MAX:
        out.append(f"claims_above_max:{len(chain)}/{config.STORY_CLAIM_MAX}")

    known = {str(f.get("fact_id")) for f in (fact_sheet.get("number_facts") or [])}
    for c in chain:
        role, order = c.get("role"), c.get("order")
        # 훅은 근거 없이 궁금하게만 해도 된다. 나머지는 무엇으로 지불하는지 밝혀야 한다.
        if role != "hook" and not (c.get("evidence_refs") or []):
            out.append(f"claim_without_evidence:{order}")
        for ref in (c.get("evidence_refs") or []):
            if known and ref not in known:
                out.append(f"evidence_ref_unknown:{ref}")

    # 결론이 증거보다 먼저 오면 시청자는 근거를 들을 이유가 없다.
    roles = [c.get("role") for c in chain]
    if "closing" in roles and "proof" in roles and roles.index("closing") < roles.index("proof"):
        out.append("closing_before_proof")

    # 같은 수치를 여러 주장이 반복하면 근거가 늘어난 게 아니라 같은 말을 되풀이한 것이다.
    seen: dict[str, int] = {}
    for c in chain:
        for ref in (c.get("evidence_refs") or []):
            seen[ref] = seen.get(ref, 0) + 1
    out.extend(f"evidence_reused:{ref}" for ref, n in seen.items() if n > 1)
    return sorted(set(out))


# 나레이션에서 **시점**을 가리키는 표기. 시청자에게 수치로 들리지 않으므로 밀도 계산에서 뺀다.
# 뒤에 자릿수 단위가 붙은 것(2,000억)은 값이므로 연도로 보지 않는다.
_PERIOD_MARKER_RE = re.compile(
    r"(?:19|20)\d{2}\s*년"                       # 2026년
    r"|(?:19|20)\d{2}\s*[FEP]\b"                 # 2026F
    r"|\bFY\s*\d{2,4}"                           # FY26
    # 2Q26 · 1H26 · 3Q26F(전망). 끝의 [FEP] 를 허용하지 않으면 "3Q26F" 가 통째로 안 걸린다
    # — \b 가 뒤따르는 F 때문에 실패하기 때문이다(실측: 차트 축 라벨이 기간으로 안 읽혔다).
    r"|[1-4]\s*[QH]\s*(?:19|20)?\d{2}\s*[FEP]?\b"
    r"|\d{1,2}\s*분기"                            # 3분기
    r"|\b\d{2}\s*년(?![\d])"                      # 26년
    r"|(?:19|20)\d{2}(?![\d,.]|\s*[조억만천원%배])"  # 문장 속 홑 연도(2026 대비)
)


def spoken_numbers(text: str) -> list[float]:
    """시청자가 **소리 내 듣는 수치**의 개수를 센다. 밀도 판정의 입력.

    ★ 그냥 숫자를 세면 안 된다(적대적 리뷰 재현): "2026년 영업이익은 1조 5,791억원" 은
      숫자 3개로 세어져 밀도 경고가 뜬다. 실제로 들리는 수치는 **하나**다.
      - 연도(19xx·20xx)는 시점이지 수치가 아니다
      - 한국어 자릿수 표기('1조 5,791억')는 두 토막이지만 한 값이다
    """
    # ★ 값으로 거르지 않고 **기간 표기 자체를 가린 뒤** 센다. 값으로 거르던 시절
    #   "2Q26 매출 7.6조원" 의 분기 숫자 2 와 "3분기 …" 의 3 이 수치로 남았고, 리터럴 '년'을
    #   요구해서 "2026F"·"26년"도 놓쳤다. 놓치면 두 군데가 동시에 틀어진다:
    #   ① 밀도 경고 오탐, ② **면제 취소가 잘못 발동해서** "2026F, 지금이 시작일까요?" 같은
    #   훅이 다시 빨간 깃발을 받는다(§5-4 이전으로 회귀).
    return match_candidates(_PERIOD_MARKER_RE.sub(" ", text or ""))


def validate_text_density(scenes: list[dict[str, Any]]) -> list[str]:
    """§6 텍스트 밀도 — 한 씬이 소화할 수 있는 양인가.

    ★ 나레이션을 씬의 duration_sec 와 비교하지 않는다. 렌더는 그 값을 쓰지 않고 **나레이션
      실측 길이**로 컷을 만든다(assemble.py "duration 은 나레이션 실측"). 예전에는 그 비교
      때문에 최근 초안 12편 전부에서 씬 대부분이 "다 읽을 수 없다" 경고를 받았고, 정작 완성
      영상은 멀쩡했다 — 항상 켜진 경고는 진짜 경고(근거 부족)까지 같이 묻는다.
      대신 편마다 한 줄로 "계획 길이 ↔ 발화 기준 예상 길이" 어긋남만 알린다.
      근거: docs/deviation-density-warning.md
    """
    out: list[str] = []
    planned = 0.0
    spoken = 0.0
    for s in (scenes or []):
        no = s.get("scene")
        narration = str(s.get("narration_ko") or "")
        planned += float(s.get("duration_sec") or 0)
        if narration and config.STORY_SPEAK_CHARS_PER_SEC > 0:
            spoken += len(narration) / config.STORY_SPEAK_CHARS_PER_SEC
        if len(spoken_numbers(narration)) > config.STORY_MAX_NUMBERS_PER_SCENE:
            out.append(f"too_many_numbers_in_scene:{no}")
    # 계획이 없거나(0초) 나레이션이 없으면 비교할 것이 없다.
    if planned > 0 and spoken > 0:
        off = abs(spoken - planned) / planned
        if off > config.STORY_DURATION_TOLERANCE:
            out.append(f"duration_estimate_off:계획 {planned:.0f}초 → 예상 {spoken:.0f}초")
    return out


GATE_LABELS: dict[str, str] = {
    "number_without_unit": "단위가 없는 수치가 있습니다.",
    "number_without_period": "어느 시점의 수치인지가 확정되지 않았습니다(예: 2026F, 2Q26).",
    "quote_not_in_source": "인용문이 원문에서 발견되지 않습니다(지어낸 인용 가능성).",
    "number_not_in_quote": "인용문 안에 그 숫자가 없습니다.",
    "conflicting_numbers": "같은 지표·기간에 서로 다른 값이 있습니다(어느 쪽이 맞는지 확인 필요).",
    "evidence_below_min": "이 유형의 리포트에 필요한 근거 수치 개수가 모자랍니다.",
    "comparator_below_min": "비교 기준이 붙은 수치가 모자랍니다(숫자만 크게 내보내지 않기 위함).",
    "category_missing": "이 유형에 필요한 근거 범주가 빠졌습니다.",
    "risks_missing": "리포트가 언급한 리스크가 Fact Sheet 에 없습니다.",
    "no_fact_has_source_ref": "원문 인용이 붙은 수치가 하나도 없습니다.",
    "thesis_missing": "이 영상이 증명하려는 한 문장이 없습니다.",
    "claims_below_min": "핵심 주장이 너무 적습니다.",
    "claims_above_max": "핵심 주장이 너무 많습니다(하나에 집중되지 않습니다).",
    "claim_without_evidence": "근거 없이 주장만 있는 대목이 있습니다.",
    "evidence_ref_unknown": "Fact Sheet 에 없는 근거를 가리킵니다.",
    "closing_before_proof": "결론이 증거보다 먼저 나옵니다.",
    "evidence_reused": "같은 수치를 여러 주장이 반복해서 씁니다.",
    "duration_estimate_off": "계획한 길이와 나레이션 길이가 다릅니다 — 영상은 나레이션 길이로 나갑니다.",
    # 옛 검사(2026-08-19 이전 초안에 저장된 토큰) — 지금은 만들지 않지만 저장된 행이 있다.
    # 라벨을 지우면 화면에 원시 토큰이 그대로 찍힌다.
    "narration_too_long_for_cut": "(옛 검사) 컷 길이보다 나레이션이 깁니다 — 지금은 편당 1건으로 요약합니다.",
    "too_many_numbers_in_scene": "한 씬에 소리 내 읽는 숫자가 너무 많습니다.",
}


def gate_label(reason: str) -> str:
    """'number_without_unit:num_3' → 사람 말. 접미(:id)는 떼고 찾는다."""
    return GATE_LABELS.get(reason.split(":")[0], reason)
