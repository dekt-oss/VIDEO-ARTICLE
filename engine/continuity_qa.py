"""연속성 멀티모달 QA — **세계가 이어졌는지 코드가 보게 한다** (계획서 Phase 3 D2).

무엇이 비어 있었나
------------------
v3 는 참조 조건 생성으로 "앞 stage 의 세계를 이어간다"를 만든다. 그런데 **이어졌는지
판정하는 눈이 없었다.** `sequence_render.degraded_summary` 는 `degraded` 코드를 세는
그릇인데, 그 코드를 넣는 쪽에는 참조가 없거나 배선이 끊긴 경우만 있었다 —
"그림은 나왔는데 다른 세계다"를 말하는 곳은 어디에도 없었다.

실측이 그게 실재하는 실패임을 보여 준다(2026-08-31 G2·G4): 네 클립 **전부** 달 표면
실사로 시작해 "받침대 위 분화구 다이어그램"으로 끝났다. `world_drift` 가 클립 안에서
그것을 보지만, **stage 와 stage 사이**는 아무도 안 봤다.

어떻게 판정하나
---------------
앞 그림과 새로 만든 그림을 flash 에게 나란히 보여 주고 묻는다 — 같은 장소·같은 대상인가.
계획서 D2 그대로: 실패하면 **재생성 1회**, 그래도 실패면 기록하고 **진행한다.**
렌더를 죽이지 않는다 — 화면이 비는 것이 가장 나쁜 결말이다.

★ 왜 모델에게 묻나: 여기서는 자기보고가 아니다. 모델은 자기가 만든 그림을 변호하는
  것이 아니라 **두 장을 대조**한다. 코드가 픽셀로 "같은 세계"를 판정할 방법이 없고
  (밝기 분포는 구도만 바뀌어도 흔들린다), 사람 눈이 하던 일을 옮기는 것이 목적이다.

★ 판정 불가와 실패를 섞지 않는다. 키가 없거나 호출이 실패하면 `measured=False` 이고
  아무것도 벌하지 않는다 — 이 저장소의 다른 신호(clip_candidates·crop)와 같은 계약이다.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from . import config
from .util import log

#: 이 판정이 남기는 저하 코드. `sequence_render.degraded_summary` 가 세는 그릇에 들어간다.
DEGRADED_WORLD_CHANGED = "continuity_world_changed"

_SYSTEM = (
    "너는 영상 연속성 검수자다. 두 장의 정지 이미지가 **같은 장면의 연속**인지 판정한다. "
    "첫 번째가 앞 장면, 두 번째가 이어지는 장면이다."
)

_USER = (
    "두 이미지가 같은 세계인가? 아래를 본다.\n"
    "- 같은 장소인가(배경·재질·조명이 이어지는가)\n"
    "- 같은 대상·인물인가(생김새가 유지되는가)\n"
    "★ 상태가 달라지는 것은 **정상**이다. 물건이 움직이거나 쌓이거나 카메라가 이동한 것은\n"
    "  같은 세계다. 장소가 통째로 바뀌거나, 실사에서 도표·다이어그램으로 넘어갔거나,\n"
    "  인물이 다른 사람이 된 경우만 다른 세계다.\n"
    'JSON 만 출력한다: {"same_world": true|false, "reason": "한 문장"}'
)


def enabled() -> bool:
    """판정을 돌릴 조건. 무료 경로(placeholder)와 키 없음에서는 돌지 않는다.

    ★ 유료 이미지 제공자일 때만 본다 — placeholder 렌더는 그림이 회색 사각형이라
      판정할 것이 없고, 그런데도 호출하면 데모 렌더마다 돈이 나간다.
      `_gen_still` 의 `record_ledger = paid` 와 같은 기준이다.
    """
    paid = config.image_is_paid()
    return bool(config.CONTINUITY_QA_ENABLED and paid and config.SECRETS.gemini_api_key)


def failed(verdict: dict[str, Any] | None) -> bool:
    """세계가 바뀌었다고 **판정된** 경우만 True. 순수 함수.

    판정 불가(measured=False)는 False 다 — 못 쟀다고 벌하지 않는다.
    """
    v = verdict or {}
    return bool(v.get("measured")) and v.get("same_world") is False


def _part(path: str) -> dict[str, Any]:
    with open(path, "rb") as f:
        return {"inlineData": {"mimeType": "image/png",
                               "data": base64.b64encode(f.read()).decode()}}


def ask(system: str, user: str, image_paths: list[str]) -> dict[str, Any] | None:
    """이미지 몇 장 + 질문 → JSON 응답(dict). 못 하면 None.

    ★ 이 저장소에서 **그림을 보고 판정하는 유일한 통로**다. 후보 선택(clip_candidates)도
      여기를 쓴다 — 두 곳이 각자 호출을 만들면 모델·타임아웃·파싱이 갈라지고, 한쪽만
      고쳐지는 그 실패가 또 나온다.
    ★ 예외를 밖으로 내지 않는다. 판정은 부수 작업이고, 못 하면 못 한 대로 진행한다.
    """
    try:
        import httpx

        # ★ gemini-2.5 은 사고 토큰이 출력 예산을 먹는다(llm._gemini_create 와 같은 규칙).
        #   실측(2026-09-11 성격 유전 전반부 렌더): 상한 200 을 사고가 다 써서 본문이 비었고,
        #   `json.loads("")` 로 판정 5회가 전부 "판정 불가"로 건너뛰어졌다.
        #   flash 는 사고를 끄고, pro 는 끌 수 없으니 출력 예산을 키운다.
        gen: dict = {"maxOutputTokens": config.CONTINUITY_QA_MAX_TOKENS}
        ml = config.CONTINUITY_QA_MODEL.lower()
        if "2.5" in ml and "flash" in ml:
            gen["thinkingConfig"] = {"thinkingBudget": config.GEMINI_THINKING_BUDGET}
        elif "2.5" in ml:
            gen["maxOutputTokens"] = max(gen["maxOutputTokens"], config.GEMINI_PRO_MAX_OUTPUT_TOKENS)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [
                *[_part(p) for p in image_paths], {"text": user}]}],
            "generationConfig": gen,
        }
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{config.CONTINUITY_QA_MODEL}:generateContent")
        r = httpx.post(url, json=body, timeout=config.LLM_HTTP_TIMEOUT_SEC,
                       headers={"x-goog-api-key": config.SECRETS.gemini_api_key})
        r.raise_for_status()
        parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        text = "".join(str(p.get("text") or "") for p in parts)
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as exc:                  # noqa: BLE001 — 판정 실패가 렌더를 죽이지 않는다
        log.warning("멀티모달 판정 건너뜀(판정 불가): %s", exc)
        return None


def judge(before_path: str, after_path: str) -> dict[str, Any]:
    """앞 그림 vs 새 그림 → {measured, same_world, reason}. 실패는 예외를 내지 않는다."""
    out: dict[str, Any] = {"measured": False, "same_world": None, "reason": ""}
    data = ask(_SYSTEM, _USER, [before_path, after_path])
    if data is None:
        return out
    same = data.get("same_world")
    if not isinstance(same, bool):
        log.warning("연속성 판정 응답에 same_world 없음 — 판정 불가로 둔다")
        return out
    out.update(measured=True, same_world=same, reason=str(data.get("reason") or ""))
    return out
