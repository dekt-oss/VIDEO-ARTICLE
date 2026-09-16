"""5축 채점 + 지수 계산 (명세 3).

①②③④는 LLM 한 번으로, ⑤(buzz)는 코드로 정규화. 재미/중요/황금 지수도 코드 계산.
"""

from __future__ import annotations

import math
from typing import Any

from . import config

SCORING_SYSTEM = """너는 대중 과학 콘텐츠를 기획하는 베테랑 PD다. 주어진 논문의 "제목"과 "초록"만 보고,
일반 대중(전문지식 없음) 대상 숏폼 콘텐츠로서의 가치를 4개 축으로 채점한다.
반드시 아래 JSON 형식으로만 답하라. 설명 문장, 마크다운, 코드펜스 금지.
초록에 없는 내용을 지어내지 마라. 모르면 보수적으로 낮게 준다.

[채점 루브릭 — 각 축 0~10]

① 의외성 (surprise): 일반인이 "이런 걸 진짜 연구했다고?" 하고 놀랄 기발함·반직관성.
   0=뻔하고 예상대로 / 3=약간 흥미 / 5=눈길 감 / 8=상당히 의외 / 10=충격적·역설적.

② 이해가능성 (explainability): 전문지식 없이 60초 안에 핵심을 설명할 수 있는가.
   0=고도 전문·수식 의존 / 3=용어 많음 / 5=노력하면 설명됨 / 8=쉬움 / 10=한 문장으로 끝남.
   ※ 어려울수록 낮게. 대중 채널이므로 이 축이 특히 중요.

③ 일상연결성 (relatability): 시청자 본인 삶과 연결돼 공유를 부르는가.
   0=내 삶과 무관 / 5=간접 관련 / 8=직접 와닿음 / 10=당장 공유하고 싶음.

④ 학술중요성 (significance): 발견의 의미·파급력. 분야를 바꿀 만한 기여인가.
   초록이 주장하는 "진보의 크기"로 판단. 0=점진적 소폭 / 5=의미 있는 진전 /
   8=중요한 발견 / 10=패러다임 전환급. ※ 과장된 주장은 신뢰하지 말고 보수적으로.

[제작 준비도 루브릭 — 5축·각 0~2점(§6). 위 정렬용 점수와 별개의 "제작 가능성" 게이트]
각 축에 0~2점과 "한 문장 근거"를 함께 준다(2=충분 / 1=부분 / 0=부족).
- novelty(놀라움): 기존 상식과 다른가.
- audience_value(시청자 영향): 개인·사회·산업에 의미 있나.
- hook_fit(근거-훅 정합): 논문 결론으로 강한 훅(증거 선공개)을 만들 수 있나(낚시 아님).
- explain_60s(60초 설명력): 원인→결과를 60초에 설명 가능한가.
- visualizable(시각화 가능성): 수치·비교·움직임 등 시각으로 보일 수 있나(정지이미지 외).
- mechanism(원리 제공): **논문이 "왜 그런지"를 스스로 설명하는가.**
  2=작동 원리·인과 기전을 논문이 직접 제시(무엇이 무엇에 작용해 무엇이 된다) /
  1=저자가 해석·추정을 제시(증명은 아님, "저자들은 …때문으로 본다") /
  0=결과만 보고하고 이유를 말하지 않음(상관·효과크기·순위만).
  ※ **결과를 쉽게 설명할 수 있는 것과 원리가 있는 것은 다르다** — explain_60s 와 헷갈리지 마라.
    "A조합이 B보다 나빴다"는 60초 설명은 쉽지만 원리는 0이다.
  ※ 초록에 이유가 없으면 0 또는 1이다. 있을 것 같다고 2를 주지 마라.

[추가 산출]
- 제목번역_KO: 논문 제목을 자연스러운 한국어로 번역(전문용어는 통용 표기 우선, 고유명사·수식은 원문 유지 가능).
- 한줄요약_KO / 한줄요약_EN: 일반인용 한 문장(어려운 용어 금지).
- 채점이유: 각 점수의 근거를 2~3문장으로.
- 빨간깃발: 초록만으로 판단이 위험한 지점(과장·표본·재현성 의심)이 있으면 적기. 없으면 "".

[OUTPUT JSON SCHEMA]
{
  "surprise": <int 0-10>,
  "explainability": <int 0-10>,
  "relatability": <int 0-10>,
  "significance": <int 0-10>,
  "production": {
    "novelty": {"score": <int 0-2>, "why": "<한 문장>"},
    "audience_value": {"score": <int 0-2>, "why": "<한 문장>"},
    "hook_fit": {"score": <int 0-2>, "why": "<한 문장>"},
    "explain_60s": {"score": <int 0-2>, "why": "<한 문장>"},
    "visualizable": {"score": <int 0-2>, "why": "<한 문장>"},
    "mechanism": {"score": <int 0-2>, "why": "<한 문장>"}
  },
  "title_ko": "<string>",
  "one_liner_ko": "<string>",
  "one_liner_en": "<string>",
  "rationale": "<string>",
  "red_flag": "<string>"
}"""


def scoring_user_prompt(title: str, venue: str | None, abstract: str) -> str:
    return f"제목: {title}\n게재처: {venue or '(미상)'}\n초록: {abstract}"


def _clamp10(x: Any) -> int:
    try:
        return max(0, min(10, int(round(float(x)))))
    except (TypeError, ValueError):
        return 0


def _clamp2(x: Any) -> int:
    try:
        return max(0, min(config.PRODUCTION_AXIS_MAX, int(round(float(x)))))
    except (TypeError, ValueError):
        return 0


def parse_production(obj: Any) -> dict[str, Any]:
    """제작 준비도 축(0~2) + 근거 + 총점 + 만점 + 게이트 라벨(§6). 순수 함수."""
    src = obj if isinstance(obj, dict) else {}
    axes: dict[str, Any] = {}
    total = 0
    for key in config.PRODUCTION_AXES:
        item = src.get(key) if isinstance(src.get(key), dict) else {}
        score = _clamp2(item.get("score"))
        axes[key] = {"score": score, "why": str(item.get("why") or "")}
        total += score
    return {"axes": axes, "total": total,
            "max": config.PRODUCTION_SCORE_MAX,
            "gate": production_gate(total)}


def stored_scale(production: Any) -> int:
    """**저장된 채점 행이 어느 자로 매겨졌는가.** 옛 행을 새 자로 재지 않기 위한 것.

    ★★ 왜 필요한가(2026-09-04 실측): mechanism 축을 추가하며 만점이 10 → 12 가 됐다.
      그대로 두면 **이미 저장된 3,976 행이 새 자로 다시 재져** 등급이 조용히 바뀐다 —
      실측으로 1,284 행이 움직였고 그중 `make → redesign` 이 681 행이었다.
      그 논문들은 아무것도 나빠지지 않았다. **자만 바뀌었을 뿐이다.**

    ★ 판정은 자기보고가 아니라 데이터다: 저장된 `max` 를 쓰고, 없으면 축 이름으로 센다.
      옛 행에는 mechanism 키가 아예 없다.
    ★ 4,000건 재채점(= LLM 4,000회)을 피하는 길이기도 하다. 재채점은 운영자가
      원할 때 `python -m engine.score` 로 하면 되고, 그때 이 값이 자연히 갱신된다.
    """
    p = production if isinstance(production, dict) else {}
    try:
        stored = int(p.get("max") or 0)
    except (TypeError, ValueError):
        stored = 0
    if stored > 0:
        return stored
    axes = p.get("axes") if isinstance(p.get("axes"), dict) else {}
    n = len([k for k in axes if k in config.PRODUCTION_AXES]) or len(config.PRODUCTION_AXES)
    return config.PRODUCTION_AXIS_MAX * n


def production_gate(total: int, max_score: int | None = None) -> str:
    """총점 → 게이트 라벨. **비율로 판정한다** — 축이 늘어도 등급 뜻이 안 바뀐다.

    ★ 종전에는 절대 점수로 갈랐다(8/6/4). 축을 하나 늘리자 같은 논문이 저절로 강등됐다.
      비율로 두면 그 사고가 구조적으로 사라진다(config 의 정수 문턱이 비율의 정본이다).
    """
    scale = int(max_score or config.PRODUCTION_SCORE_MAX)
    ratio = (float(total) / scale) if scale > 0 else 0.0
    if ratio >= config.PRODUCTION_GATE_MAKE_RATIO:
        return "make"
    if ratio >= config.PRODUCTION_GATE_REDESIGN_RATIO:
        return "redesign"
    if ratio >= config.PRODUCTION_GATE_BACKLOG_RATIO:
        return "backlog"
    return "hold"


def parse_axes(obj: dict[str, Any]) -> dict[str, Any]:
    """LLM 출력 → 검증된 축 점수 + 텍스트 필드."""
    return {
        "surprise": _clamp10(obj.get("surprise")),
        "explainability": _clamp10(obj.get("explainability")),
        "relatability": _clamp10(obj.get("relatability")),
        "significance": _clamp10(obj.get("significance")),
        "production": parse_production(obj.get("production")),
        "title_ko": str(obj.get("title_ko") or ""),
        "one_liner_ko": str(obj.get("one_liner_ko") or ""),
        "one_liner_en": str(obj.get("one_liner_en") or ""),
        "rationale": str(obj.get("rationale") or ""),
        "red_flag": str(obj.get("red_flag") or ""),
    }


def zero_axes(reason: str = "JSON 파싱 불가") -> dict[str, Any]:
    """채점 실패 시 0점 처리(명세 3-3). reason 으로 실제 원인을 red_flag 에 남긴다."""
    return {
        "surprise": 0, "explainability": 0, "relatability": 0, "significance": 0,
        "production": parse_production(None),
        "title_ko": "", "one_liner_ko": "", "one_liner_en": "", "rationale": "",
        "red_flag": f"[채점 실패: {reason}]",
    }


def normalize_buzz(buzz_raw: dict[str, Any] | None) -> float:
    """⑤ buzz_raw → 0~10 (D7 로그 스케일)."""
    total = float((buzz_raw or {}).get("total", 0) or 0)
    if total <= 0:
        return 0.0
    score = config.BUZZ_LOG_COEFF * math.log1p(total)
    return round(min(config.BUZZ_SCORE_MAX, score), 3)


def significance_with_boost(significance: int, venue: str | None,
                            has_press_pickup: bool = False) -> float:
    """④ 보정 (D6 — config off 시 원점수 그대로)."""
    if not config.ENABLE_SIGNIFICANCE_BOOST:
        return float(significance)
    boosted = float(significance)
    v = (venue or "").lower()
    if any(k in v for k in config.TOP_VENUE_KEYWORDS):
        boosted += config.SIGNIFICANCE_BOOST_TOP_VENUE
    if has_press_pickup:
        boosted += config.SIGNIFICANCE_BOOST_PRESS_PICKUP
    return min(config.SIGNIFICANCE_MAX, boosted)


def fun_index(axes: dict[str, Any]) -> float:
    w = config.FUN_WEIGHTS
    return round(
        w["surprise"] * axes["surprise"]
        + w["explainability"] * axes["explainability"]
        + w["relatability"] * axes["relatability"],
        4,
    )


def importance_index(significance_eff: float, buzz_norm: float) -> float:
    w = config.IMPORTANCE_WEIGHTS
    return round(w["significance"] * significance_eff + w["buzz"] * buzz_norm, 4)


def golden_index(fun: float, importance: float) -> float:
    return round(fun * importance, 4)
