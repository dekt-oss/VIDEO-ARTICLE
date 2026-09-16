"""리포트 팩토리 — 4축 경량 채점 + 정렬 지수 (명세 §3).

논문 5축(engine/scoring.py)의 축소판. 대상이 하루 수~수십 건뿐이라 무겁게 갈 필요가 없다.
①②③④ 는 LLM 한 번으로, 관심/스토리/안전 지수는 코드로 계산(순수 로직 — tests 대상).
"""

from __future__ import annotations

from typing import Any

from . import config

REPORT_SCORING_SYSTEM = """너는 금융 리포트를 대중용 숏폼 콘텐츠로 기획하는 베테랑 PD다.
주어진 증권사 리포트의 "제목·테마·핵심요약·목표가/의견"만 보고, 일반 대중(전문지식 없음)
대상 숏폼으로서의 가치를 4개 축으로 채점한다. 반드시 아래 JSON 형식으로만 답하라.
설명 문장, 마크다운, 코드펜스 금지. 요약에 없는 내용을 지어내지 마라. 모르면 보수적으로 낮게.

[채점 루브릭 — 각 축 0~10]

① 시의성/관심도 (timeliness): 지금 대중이 궁금해할 종목·테마인가(오늘 화제성).
   0=지난 얘기·관심 없음 / 5=어느 정도 관심 / 8=지금 뜨거움 / 10=오늘의 핵심 화제.

② 이해 가능성 (explainability): 배경지식 없이 60~70초에 설명되는가.
   0=고도 전문·수식 의존 / 5=노력하면 설명됨 / 8=쉬움 / 10=한 문장으로 끝남.
   ※ 어려울수록 낮게. 대중 채널이므로 이 축이 특히 중요.

③ 스토리성/의외성 (story): "오 이런 일이?" 훅이 서는가(실적 서프라이즈·판 바뀜·반전).
   0=뻔함 / 5=눈길 감 / 8=상당히 의외 / 10=충격적 반전.

④ 컴플라이언스 안전도 (safety): 소재의 안전도. ★ 높을수록 안전, 낮을수록 위험.
   초저유동성 잡주·과열 테마·극단적 목표가·펌핑 소지일수록 낮게 준다.
   0=매우 위험(잡주·과열·극단 목표가) / 5=보통 / 8=대형주·안정적 / 10=지수·매크로 등 매우 안전.

[추가 산출]
- 제목번역_KO: 대중이 클릭할 자연스러운 한국어 제목(자극적이되 사실 왜곡 금지).
- 한줄요약_KO / 한줄요약_EN: 일반인용 한 문장(어려운 용어 금지).
- 앵글: 이 리포트를 대중용으로 풀 핵심 앵글 한 줄.
- 리스크노트: 컴플라이언스/편향 관점 주의점(과열·펌핑 소지·목표가 극단 등). 없으면 "".

[OUTPUT JSON SCHEMA]
{
  "timeliness": <int 0-10>,
  "explainability": <int 0-10>,
  "story": <int 0-10>,
  "safety": <int 0-10>,
  "title_ko": "<string>",
  "one_liner_ko": "<string>",
  "one_liner_en": "<string>",
  "angle": "<string>",
  "risk_note": "<string>"
}"""


def scoring_user_prompt(report: dict[str, Any]) -> str:
    """reports 행 → 채점 입력 프롬프트. 원문 전문이 아니라 요약·정형 팩트만 준다."""
    lines = [
        f"제목: {report.get('title') or '(미상)'}",
        f"테마: {report.get('theme') or '(미상)'}",
        f"출처: {report.get('broker') or '(미상)'}",
    ]
    if report.get("company"):
        lines.append(f"종목: {report.get('company')}")
    if report.get("target_price"):
        lines.append(f"목표가: {report.get('target_price')}")
    if report.get("opinion"):
        lines.append(f"투자의견: {report.get('opinion')}")
    if report.get("is_risk"):
        lines.append("(ARIA 위험 신호로 분류됨)")
    lines.append(f"핵심요약: {report.get('summary') or ''}")
    return "\n".join(lines)


def _clamp10(x: Any) -> int:
    try:
        return max(0, min(10, int(round(float(x)))))
    except (TypeError, ValueError):
        return 0


def parse_axes(obj: dict[str, Any]) -> dict[str, Any]:
    """LLM 출력 → 검증된 4축 점수 + 텍스트 필드."""
    return {
        "timeliness": _clamp10(obj.get("timeliness")),
        "explainability": _clamp10(obj.get("explainability")),
        "story": _clamp10(obj.get("story")),
        "safety": _clamp10(obj.get("safety")),
        "title_ko": str(obj.get("title_ko") or ""),
        "one_liner_ko": str(obj.get("one_liner_ko") or ""),
        "one_liner_en": str(obj.get("one_liner_en") or ""),
        "angle": str(obj.get("angle") or ""),
        "risk_note": str(obj.get("risk_note") or ""),
    }


def zero_axes(reason: str = "JSON 파싱 불가") -> dict[str, Any]:
    """채점 실패 시 0점 처리(명세 3-3). reason 을 risk_note 에 남긴다."""
    return {
        "timeliness": 0, "explainability": 0, "story": 0, "safety": 0,
        "title_ko": "", "one_liner_ko": "", "one_liner_en": "", "angle": "",
        "risk_note": f"[채점 실패: {reason}]",
    }


def interest_index(axes: dict[str, Any]) -> float:
    """관심 지수 = 시의성·이해·스토리 가중합."""
    w = config.REPORT_INTEREST_WEIGHTS
    return round(
        w["timeliness"] * axes["timeliness"]
        + w["explainability"] * axes["explainability"]
        + w["story"] * axes["story"],
        4,
    )


def story_index(axes: dict[str, Any]) -> float:
    """스토리 지수 = 스토리 중심(시의성 보조)."""
    w = config.REPORT_STORY_WEIGHTS
    return round(w["story"] * axes["story"] + w["timeliness"] * axes["timeliness"], 4)


def safety_index(axes: dict[str, Any]) -> float:
    """안전 지수 = 안전도 원점수(높을수록 안전)."""
    return round(float(axes["safety"]), 4)
