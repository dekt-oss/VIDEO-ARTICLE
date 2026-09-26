"""판단 전용 모델 Jev — **게이트가 못 가르는 것만** 묻는다 (2026-09-22).

무엇을 푸는가
------------
이 저장소의 화면 게이트는 대부분 정규식이다. 그 선택은 대체로 옳다 — 결정론적이고,
공짜이고, 왜 막혔는지 사람이 읽을 수 있다. 그런데 **정규식으로는 못 가르는 자리**가
실측으로 두 번 드러났고, 두 번 다 내가 규칙을 세우려다 실패했다:

    ① 따옴표가 "그려 달라는 라벨"인가 "겁따옴표"인가
       `a dish labeled 'Control'`      → 그림에 글자가 박힌다
       `avoids the 'bad weather' spots` → 박히지 않는다
       저장된 159건에 규칙을 대 봤더니 `bars for 'NASDAQ'`(라벨)과 `the 'cost' of`
       (겁따옴표)가 같은 형태라 **분류가 안 됐다.**

    ② 이 컷이 "연결 컷"인가 — 라우터 판정과 어긋나 기각했다.

둘 다 "이 문장이 X인가?" 라는 예·아니오 질문이다. LLM 을 한 번 부르기엔 과하고
(문장을 만들 필요가 없다), 정규식으로는 못 푼다. Jev 는 정확히 그 자리다 —
typed 판정만 내고, 출력 토큰은 과금되지 않는다.

무엇을 **하지 않는가**
--------------------
★★ **Jev 는 게이트를 풀기만 한다. 새로 막지 않는다.**
  근거는 실측이다: `represents 'Calorie Restriction'` 에 Jev 는 0.42 를 줬다(라벨 아님).
  그 문장은 2026-09-07 에 **다섯 개가 그대로 그림에 영어 글자로 박힌** 바로 그 문장이다.
  Jev 에게 최종 판정을 맡겼다면 그 사고가 돌아온다.

  그래서 호출부는 이 순서를 지킨다:
      ① 명백한 라벨 동사(labeled/titled/represents…) → **정규식이 무조건 막는다**
      ② 동사 없이 따옴표만 → 그때만 Jev 에게 묻고, 겁따옴표면 푼다
  Jev 가 틀려도 게이트가 약해지지 않는 구조다. 이 모듈이 판정을 **완화**만 할 수 있게
  설계된 이유가 그것이다.

★ 꺼져 있거나 키가 없거나 호출이 실패하면 **None** 을 돌려준다 — 호출부는 종전(정규식)
  동작을 그대로 쓴다. 판정 실패가 조용히 "통과"가 되지 않는다(error-vs-empty).

순수성
------
`config.JEV_ENABLED` 기본값은 **False** 다. 테스트와 로컬은 네트워크 호출이 0이고
게이트는 정규식 그대로 돈다. 켜는 것은 운영 판단이다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import config
from .util import log


def enabled() -> bool:
    """물어볼 조건. 스위치가 켜져 있고 키가 있어야 한다."""
    return bool(config.JEV_ENABLED and config.SECRETS.jev_api_key)


def _post(body: dict[str, Any]) -> dict[str, Any] | None:
    req = urllib.request.Request(
        config.JEV_BASE, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.SECRETS.jev_api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=config.JEV_TIMEOUT_SEC) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        # ★ 본문을 로그에 남긴다. 400 은 대개 **스키마가 틀린 것**이고(type 이름·criteria
        #   필수), 본문 없이는 무엇이 틀렸는지 알 수 없다 — 실제로 첫 시도가 그랬다.
        log.warning("Jev HTTP %s: %s", exc.code, exc.read().decode()[:200])
    except Exception as exc:  # noqa: BLE001 — 판정 실패가 파이프라인을 막지 않는다
        log.warning("Jev 호출 실패(무시): %s", exc)
    return None


def _record(usage: dict[str, Any], model: str) -> None:
    """원장에 남긴다. 출력 단가가 0 이라도 **호출이 있었다는 사실**은 남아야 한다."""
    try:
        from . import cost
        cin = int(usage.get("input_tokens") or 0)
        cout = int(usage.get("output_tokens") or 0)
        if cin or cout:
            cost.record(cost.text_attempt(
                model_id=model, purpose="judge", input_tokens=cin, output_tokens=cout))
    except Exception as exc:  # noqa: BLE001
        log.warning("Jev 비용 기록 실패(무시): %s", exc)


def noul(state: str, instructions: str, criteria: dict[str, str]) -> float | None:
    """예·아니오 판정 → '예'일 확률. 못 물었으면 **None**.

    `criteria` 는 필수다 — 빼면 API 가 400 `api_usage_error` 를 낸다(실측).
    """
    if not (enabled() and str(state or "").strip()):
        return None
    data = _post({
        "model": config.JEV_MODEL,
        "state": str(state)[:config.JEV_STATE_MAX_CHARS],
        "questions": {"q": {"type": "noul", "instructions": instructions,
                            "criteria": criteria}},
    })
    if not data:
        return None
    _record(data.get("usage") or {}, str(data.get("model") or config.JEV_MODEL))
    try:
        return float((data.get("answers") or {})["q"]["noul"])
    except (KeyError, TypeError, ValueError):
        log.warning("Jev 응답 모양이 다르다: %s", json.dumps(data, ensure_ascii=False)[:200])
        return None


#: 따옴표가 "화면에 그릴 라벨"인지 묻는 질문. 문구를 한 곳에 둔다 — 두 벌이 되면
#  실측한 문턱(0.35)이 다른 질문에 붙어 의미를 잃는다.
QUOTED_LABEL_Q = (
    "Does this image prompt ask for text to be drawn inside the picture?",
    {"true": "a quoted word names an object on screen — the model will draw those letters",
     "false": "scare quotes around an ordinary word — nothing to draw"},
)


def quoted_label_is_scare_quote(text: str) -> bool:
    """이 프롬프트의 따옴표가 **그릴 글자가 아닌가**. 못 물었으면 False(=차단 유지).

    ★ 기본값이 False 인 것이 중요하다. 판정을 못 했을 때 "라벨이 아니다"로 떨어지면
      Jev 가 죽는 날 게이트가 통째로 열린다 — 이 모듈은 **풀기만** 하는 자리이므로
      못 풀면 그냥 종전대로 막혀 있어야 한다.
    """
    p = noul(text, QUOTED_LABEL_Q[0], QUOTED_LABEL_Q[1])
    if p is None:
        return False
    return p < config.JEV_LABEL_RELEASE_BELOW


#: 도해 부품이 "한눈에 알아볼 물건"인지 묻는 질문(2026-09-24). 이것도 텍스트 안에 답이 있는
#  종류다 — "이 낱말이 구체적 사물을 가리키나". 채점 축(취향)과 다르다.
COMPONENTS_Q = (
    "Would a general viewer recognize each of these listed things at a glance as a concrete, "
    "familiar physical object (like a transmission tower, a server rack, a ship engine, a barge)?",
    {"true": "every item names a concrete object with a well-known shape",
     "false": "one or more items are abstract or generic parts (a channel, a conduit, a block, "
              "a module, a flow, a pathway) with no recognizable shape"},
)


def noul_many(state: str, questions: dict[str, tuple[str, dict[str, str]]]) -> dict[str, float] | None:
    """한 상태에 참/거짓 질문 여럿을 **한 호출로** 묻는다. 하나라도 못 읽으면 None.

    ★ 질문을 나눠 보내면 같은 입력을 질문 수만큼 다시 보낸다 — 입력 토큰이 곧 비용이다.
    """
    if not enabled():
        return None
    data = _post({"model": config.JEV_MODEL, "state": state[:config.JEV_STATE_MAX_CHARS],
                  "questions": {k: {"type": "noul", "instructions": q, "criteria": crit}
                                for k, (q, crit) in questions.items()}})
    if not data:
        return None
    _record(data.get("usage") or {}, str(data.get("model") or config.JEV_MODEL))
    try:
        ans = data.get("answers") or {}
        return {k: float(ans[k]["noul"]) for k in questions}
    except (KeyError, TypeError, ValueError):
        log.warning("Jev 응답 모양이 다르다: %s", json.dumps(data, ensure_ascii=False)[:200])
        return None


#: 실사 컷이 나레이션에 **답하는가**(2026-09-27). 화면 구성 계약(directive.STAGING_CONTRACT)의
#  "주제만 같은 사진은 되돌려 보낸다"를 실제로 하는 자리다. 질문 문구는 scripts/staging_shadow.py
#  가 565컷에 대 본 그것이다 — 문구를 바꾸면 문턱의 근거가 사라진다.
#  `showable` 은 **나레이션 쪽**을 본다: "이건 그냥 하는 말이 아니라," 같은 연결 문장은 어떤
#  장면으로도 답할 수 없어서, 그 컷을 벌하면 옳게 쓴 지시서를 벌하게 된다.
SCENE_ANSWERS_Q: dict[str, tuple[str, dict[str, str]]] = {
    "answers": (
        "Does the SCENE show the specific thing the NARRATION asserts — the action, change or "
        "comparison itself — rather than merely a place or object related to the topic?",
        {"true": "the scene stages what the narration says (a hand scoops muddy water; rocks are "
                 "dumped into a pit; a line grows longer)",
         "false": "the scene is a generic establishing shot of the topic (a wide shipyard, a port, "
                  "a factory floor) that would fit many different narrations"},
    ),
    "showable": (
        "Does the NARRATION state a concrete fact, action, change or comparison that a picture "
        "could show?",
        {"true": "it asserts something specific (prices fell while profits doubled; the engine "
                 "powers a data center; mice lived 12% longer)",
         "false": "it is a transition, a rhetorical aside or a framing phrase with nothing "
                  "specific to show (this is not just talk; let's look closer; here is why)"},
    ),
}


def scene_answers(narration: str, visual: str) -> dict[str, float] | None:
    """{answers, showable} 확률. 못 물었으면 None(호출부는 경고를 내지 않는다 — fail-open)."""
    if not str(narration or "").strip() or not str(visual or "").strip():
        return None
    return noul_many(f"NARRATION: {narration}\nSCENE: {visual}", SCENE_ANSWERS_Q)


def components_recognizable(components: list[str]) -> float | None:
    """도해 부품 목록이 알아볼 물건들인 확률. 못 물었으면 None(호출부는 경고를 내지 않는다).

    ★ 경고용이라 fail-open 이다 — 판정을 못 하면 종전 동작(경고 없음). 차단에 쓰면 안 된다.
    """
    items = [str(c).strip() for c in (components or []) if str(c).strip()]
    if not items:
        return None
    return noul("COMPONENTS: " + " | ".join(items), COMPONENTS_Q[0], COMPONENTS_Q[1])
