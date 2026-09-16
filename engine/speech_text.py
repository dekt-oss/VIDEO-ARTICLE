"""나레이션 → **소리로 읽을 문장**. 화면(자막)은 그대로 두고 TTS 입력만 다듬는다.

무엇을 푸는가(2026-09-11 운영자 실측): 대본에 "네이처(Nature)" 처럼 영문 병기가 있으면
한국어 TTS 가 **같은 말을 두 번 읽는다** — "네이처 네이처". 화면에는 병기가 있는 편이
좋으므로 자막은 손대지 않고, 소리로 갈 때만 괄호를 뺀다.

★ 괄호를 전부 지우지 않는다. "1,260개(전체의 13%)" 처럼 **한글 내용**은 정보라서 읽어야 한다.
  지우는 것은 **라틴 문자 병기**뿐이다 — 앞말의 발음을 되풀이하는 자리다.
★ 실측 빈도: 지시서 540컷 중 4건(전부 `네이처(Nature)`). 드물지만 들으면 바로 걸린다.
  드물다는 이유로 규칙을 넓히지 않는다 — 넓히면 정보를 지운다.
"""
from __future__ import annotations

import re

from . import config

#: 앞말 뒤에 붙은 **라틴 문자 전용** 괄호 병기. 한글·숫자가 섞이면 건드리지 않는다.
#:   "네이처(Nature)" → "네이처"      (읽기 중복)
#:   "네이처 (Nature)" → "네이처"
#:   "1,260개(전체의 13%)" → 그대로   (한글 = 정보)
#:   "(그림 2)" → 그대로
_LATIN_GLOSS = re.compile(
    r"\s*[（(]\s*[A-Za-z][A-Za-z0-9 .,'&/+-]{0,40}\s*[）)]"
)


def for_speech(text: str) -> str:
    """TTS 로 보낼 문장. 자막·화면 문장과 **다를 수 있다**(의도).

    ★ 발음 교정표(config.TTS_PRONUNCIATION)도 여기서 적용한다 — 종전에는 providers/tts 가
      직접 했다. 소리로 가는 문장을 만드는 자리는 하나여야 두 곳이 갈라지지 않는다.
    """
    t = str(text or "")
    if not t.strip():
        # ★ 공백뿐이면 **빈 문자열**로 돌려준다. 호출측(providers/tts)이 `if not text` 로 유료
        #   백엔드 호출을 막는데, 공백을 그대로 돌려주면 그 가드를 그냥 통과한다
        #   (실측 2026-09-12: test_empty_narration_never_calls_a_paid_backend 가 잡았다).
        return ""
    if config.TTS_DROP_LATIN_GLOSS:
        t = _LATIN_GLOSS.sub("", t)
    for src, dst in config.TTS_PRONUNCIATION.items():
        t = t.replace(src, dst)
    # 괄호를 빼면 "네이처 에" 처럼 공백이 겹칠 수 있다.
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\s+([.,!?…])", r"\1", t)
    return t.strip()
