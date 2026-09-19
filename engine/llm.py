"""Anthropic LLM 호출 래퍼.

CLAUDE.md 규약:
- 출력은 JSON only 로 받고, 파싱 실패 시 1회 재시도 → 그래도 실패면 호출자가 0점 처리.
- API 5xx/타임아웃은 지수 백오프.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from anthropic import Anthropic, APIStatusError, APITimeoutError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import config, cost
from .util import RateLimiter, gemini_auth, http_get, log  # noqa: F401 (http_get reserved)

_gemini_limiter = RateLimiter(config.GEMINI_MIN_INTERVAL_SEC)


# 살려서 만든 객체에 남기는 표식. 호출자가 "이건 잘린 응답에서 건진 것"임을 알아야
# 더 엄격한 검사를 걸 수 있다(engine/report_factsheet._require_complete).
SALVAGED_MARK = "__salvaged__"


class JSONParseError(ValueError):
    """LLM 응답을 JSON 으로 파싱하지 못함."""


class OutputTruncatedError(ValueError):
    """출력이 상한에서 잘렸다.

    ★ JSONParseError 와 **일부러 구분**한다. 파싱 실패는 재시도가 의미 있지만(모델이 다르게
      쓸 수 있다), 상한 절단은 같은 자리에서 똑같이 잘리므로 재시도가 순수한 낭비다.
    ★ `partial` 에 잘린 원문을 담는다 — 호출자가 건져 쓸 수 있게. 이게 없으면 하류의
      "너무 길면 잘라 쓴다" 방어가 **영원히 도달하지 못한다**(파싱 전에 예외가 나므로).
    """

    def __init__(self, message: str, partial: str = ""):
        super().__init__(message)
        self.partial = partial


def salvage_json(text: str) -> dict[str, Any]:
    """잘린 JSON 을 **마지막 완성된 요소까지만** 살려 파싱한다.

    ★ 왜 필요한가: 상한 절단은 하류의 개수 상한보다 **먼저** 일어난다. Fact Sheet 처럼
      "앞에서부터 N개만 쓰면 충분한" 출력은, 뒷부분이 잘렸어도 앞부분이 온전하면 쓸 수 있다.
      리포트에 숫자가 1,194개 들어 있어 모델이 100개를 뽑다 잘리더라도, 우리가 필요한 건
      20개뿐이다 — 그 20개는 이미 온전히 들어와 있다.

    ★ 아무 데나 쓰면 안 된다. 대본처럼 **뒤쪽 씬이 빠지면 안 되는** 출력에는 쓰지 않는다
      (call_json 의 salvage 인자를 명시적으로 켠 호출만 이 경로를 탄다).

    방식: 문자열 밖에서 괄호 깊이를 세며 훑고, 열린 괄호를 닫아 파싱을 시도한다. 실패하면
    마지막 쉼표까지 물러나 다시 시도한다(끝에 걸친 반쪽 요소를 버린다).
    """
    s = (text or "").strip()
    start = s.find("{")
    if start == -1:
        raise JSONParseError("살릴 JSON 객체가 없다")
    s = s[start:]

    # 문자열 안/밖을 구분하며 괄호 스택을 만든다(이스케이프 처리 포함).
    stack: list[str] = []
    in_str = False
    esc = False
    # (자른 위치, 그 지점의 중첩 깊이). 깊이가 **얕을수록** 더 바깥의 완성된 요소다.
    close_cuts: list[tuple[int, int]] = []
    comma_cuts: list[tuple[int, int]] = []
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            close_cuts.append((i + 1, len(stack)))
        elif ch == ",":
            comma_cuts.append((i, len(stack)))   # 쉼표 **앞**까지가 온전하다

    # ★ 가장 긴 것부터 시도하되, **반쯤 쓰인 객체를 남기는 지점은 거부**한다(아래 참조).
    #   쉼표는 마지막 수단이다 — 요소 경계가 아니라서 반쪽이 남기 쉽다.
    def _idx(cuts: list[tuple[int, int]]) -> list[int]:
        return [i for i, _d in sorted(cuts, key=lambda c: -c[0])]

    candidates = [len(s)] + _idx(close_cuts) + _idx(comma_cuts)
    for cut in candidates:
        head = s[:cut]
        # 그 지점의 괄호 깊이를 다시 계산해 닫는다.
        st: list[str] = []
        ins = False
        es = False
        for ch in head:
            if ins:
                if es:
                    es = False
                elif ch == "\\":
                    es = True
                elif ch == '"':
                    ins = False
                continue
            if ch == '"':
                ins = True
            elif ch in "{[":
                st.append("}" if ch == "{" else "]")
            elif ch in "}]" and st:
                st.pop()
        if ins:
            continue                   # 문자열 한가운데 — 더 물러난다
        # ★★ 여기가 급소다. 닫아야 할 것 중에 **루트가 아닌 객체**가 남아 있으면, 그 객체는
        #    쓰다 만 것이다. 그대로 닫으면 반쪽 요소가 살아남는다 — 실측 결함:
        #      {"fact_id":"b","metric":"PER","value":19,"comparator":{…}}
        #    comparator 는 닫혔지만 source_refs 가 없다. **인용 없는 금융 수치**가 화면에
        #    나가는 것이 이 저장소가 가장 막으려는 사고다(§5 Evidence Contract).
        #    배열은 닫아도 된다 — 원소가 줄 뿐 각 원소는 온전하다. 루트 객체도 마찬가지다.
        if any(c == "}" for c in st[1:]):
            continue
        try:
            return json.loads(head + "".join(reversed(st)))
        except json.JSONDecodeError:
            continue
    raise JSONParseError("잘린 JSON 을 살리지 못했다")


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type((APITimeoutError, APIStatusError)),
)
def _create(client: Anthropic, *, model: str, system: str, user: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # ★ 응답이 잘렸으면 **여기서** 말한다. 그러지 않으면 잘린 JSON 이 파서로 내려가
    #   `Expecting ',' delimiter: line 693 column 8` 같은 암호가 되고, 운영자는 모델이
    #   이상한 JSON 을 냈다고 오해한다(실측: 리포트 초안 3건 연속 실패의 실제 원인이 이것이었다).
    #   재시도해도 같은 자리에서 잘리므로 재시도는 낭비다.
    # ★★ 잘리는 이유가 **두 가지**이고 처방이 정반대다. 한 문구로 뭉뚱그리면 운영자가 틀린
    #    쪽을 손본다 — 입력이 넘쳐서 죽었는데 출력 상한만 계속 올리는 식이다.
    _u = getattr(resp, "usage", None)
    _record_text_usage(model, {"input_tokens": getattr(_u, "input_tokens", 0),
                               "output_tokens": getattr(_u, "output_tokens", 0)})
    stop = getattr(resp, "stop_reason", None)
    if stop == "max_tokens":
        raise OutputTruncatedError(
            f"출력이 max_tokens({max_tokens})에서 잘렸다 — **출력 상한을 올려야** 한다 "
            f"(LLM_SCRIPT_MAX_TOKENS, model={model})",
            partial="".join(b.text for b in resp.content
                            if getattr(b, "type", None) == "text"))
    if stop == "model_context_window_exceeded":
        # 입력+출력이 컨텍스트 창을 넘었다. 여기서 max_tokens 를 올리면 오히려 더 빨리 넘는다.
        raise OutputTruncatedError(
            f"입력이 커서 컨텍스트 창을 넘었다 — **입력을 줄여야** 한다 "
            f"(예: DRAFT_INCLUDE_FULLTEXT=false 또는 SOURCE_FULLTEXT_MAX_CHARS 축소). "
            f"출력 상한을 올리는 것은 역효과다 (model={model})")
    return "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")


class AnthropicDisabledError(RuntimeError):
    """Anthropic 경로가 코드로 막혀 있다(config.ANTHROPIC_DISABLED)."""


def _client() -> Anthropic:
    """Anthropic 클라이언트. **차단 스위치가 켜져 있으면 만들지 않는다.**

    ★ 왜 여기인가(2026-08-29 운영자 지시: "앤트로픽 경로 전부 코드에서 막아"):
      기본 모델을 Gemini 로 바꾸는 것만으로는 부족하다는 것이 그날 증명됐다. 세션 초반에
      "제미나이로 해야지"라는 지시를 받고 나는 **그 실행만** 바꿨고, 기본값과 폴백은
      Anthropic 그대로 뒀다. 그래서 지시서 생성이 Anthropic 으로 나갔고 Gemini 가 429 를
      낼 때마다 자동으로 그쪽으로 넘어갔다. 잔액이 0이라 400 으로 거절돼 과금은 안 됐지만
      **그건 운이 좋았던 것이지 내가 막은 것이 아니다.**

      그래서 판정을 **클라이언트를 만드는 단 하나의 지점**으로 옮긴다. 모델 ID 가 claude 로
      시작하든, 폴백이 켜져 있든, 환경변수에 키가 있든 — 여기를 지나야 나갈 수 있고,
      여기서 막힌다. 설정 한 곳을 빠뜨려서 새는 일이 구조적으로 불가능해진다.
    """
    if config.ANTHROPIC_DISABLED:
        raise AnthropicDisabledError(
            "Anthropic 경로가 막혀 있다(ANTHROPIC_DISABLED=true). "
            "Gemini 모델을 쓰거나, 정말 필요하면 ANTHROPIC_DISABLED=false 로 명시로 켜라.")
    config.SECRETS.require("anthropic_api_key")
    return Anthropic(api_key=config.SECRETS.anthropic_api_key, timeout=config.LLM_HTTP_TIMEOUT_SEC)


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
)
def _gemini_create(*, model: str, system: str, user: str, max_tokens: int) -> str:
    """Gemini REST 호출. responseMimeType=application/json 으로 JSON 강제."""
    config.SECRETS.require("gemini_api_key")
    _gemini_limiter.wait()  # 무료 등급 RPM 제한 대비
    url = f"{config.GEMINI_BASE}/{model}:generateContent"
    gen_config: dict[str, Any] = {
        "responseMimeType": "application/json",
        "maxOutputTokens": max_tokens,
        "temperature": 0.4,
    }
    # gemini-2.5 추론 모델은 사고 토큰이 출력 예산을 잠식해 JSON 이 잘린다.
    #  - flash: 사고 끔(thinkingBudget=0 허용).
    #  - pro 등: 사고 필수(budget 0 은 "only works in thinking mode" 400) → 끄지 말고 출력 예산을 키운다.
    # (2.0 등 비추론 모델은 thinkingConfig 미지원이라 2.5 에만.)
    ml = model.lower()
    if "2.5" in ml and "flash" in ml:
        gen_config["thinkingConfig"] = {"thinkingBudget": config.GEMINI_THINKING_BUDGET}
    elif "2.5" in ml:
        gen_config["maxOutputTokens"] = max(max_tokens, config.GEMINI_PRO_MAX_OUTPUT_TOKENS)
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen_config,
    }
    # 생성 호출은 조회보다 훨씬 오래 걸린다 — 일반 HTTP 타임아웃(30초)이 아니라 LLM 전용 값을 쓴다.
    with httpx.Client(timeout=config.LLM_HTTP_TIMEOUT_SEC) as client:
        resp = client.post(url, headers=gemini_auth(), json=body)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise httpx.TransportError(f"{resp.status_code} from gemini")
        resp.raise_for_status()
        data = resp.json()
    # ★ Anthropic 경로와 같은 이유로 절단을 먼저 본다(엣지 폴백이 이 경로를 쓴다).
    # ★★ **실제로 요청한 값**을 적는다. 2.5-pro 는 위에서 max(max_tokens, GEMINI_PRO_...) 로
    #    덮어쓰므로, 인자를 그대로 적으면 운영자가 LLM_SCRIPT_MAX_TOKENS 를 그 아래로 올려도
    #    아무 변화가 없다 — 실효 상한이 여전히 더 크기 때문이다. 처방이 헛돌지 않게 한다.
    # ★ 원장 기록은 절단 검사보다 **먼저**다(2026-09-02 실측). 잘린 호출도 돈은 나갔는데
    #   raise 뒤에 있어서 원장에 0원으로 남았다 — 실제 비용이 가장 큰 호출(출력이 상한까지
    #   찬 것)일수록 기록에서 빠지는 구조였다.
    _record_text_usage(model, data.get("usageMetadata") or {})
    if (data.get("candidates") or [{}])[0].get("finishReason") == "MAX_TOKENS":
        raise OutputTruncatedError(
            f"출력이 maxOutputTokens({gen_config['maxOutputTokens']})에서 잘렸다 — "
            f"상한을 올려야 한다 (model={model})",
            partial="".join(p.get("text", "") for p in
                            (data["candidates"][0].get("content") or {}).get("parts", [])))
    try:
        return "".join(
            part.get("text", "")
            for part in data["candidates"][0]["content"]["parts"]
        )
    except (KeyError, IndexError) as exc:
        raise JSONParseError(f"Gemini 응답 형식 예상 밖: {exc}") from exc


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
)
def _deepseek_create(*, model: str, system: str, user: str, max_tokens: int) -> str:
    """DeepSeek 호출(OpenAI 호환 /chat/completions).

    ★ 왜 어댑터가 필요한가: 모델 ID 만 바꿔서는 안 된다. 이 파일의 두 경로는 응답 **형태**에
      맞춰 짜여 있다 — 절단 판정(stop_reason / finishReason), 사용량 키(input_tokens /
      promptTokenCount), 텍스트 추출 방식이 전부 공급자마다 다르다. 그 셋을 여기서 번역하지
      않으면 잘린 응답이 조용히 통과하고 원장에 0원으로 남는다(2026-08-29 사고의 그 구조).

    ★ 폴백을 달지 않는다. Gemini 경로의 Anthropic 폴백은 2.5-pro 의 503 때문에 생긴 것이고,
      그 비용이 정당화된 근거가 있었다. DeepSeek 에는 그런 실측이 아직 없다 — 근거 없이
      폴백을 달면 조용히 비싼 쪽으로 새는 길만 하나 더 생긴다.
    """
    config.SECRETS.require("deepseek_api_key")
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": 0.4,          # Gemini 경로와 같은 값 — 비교가 온도 차이로 오염되지 않게
        "stream": False,
    }
    # ★ JSON 강제는 **프롬프트에 'json' 이라는 말이 있을 때만** 건다. DeepSeek 은 이 조건이
    #   깨지면 빈 문자열이나 공백만 돌려주는 것으로 문서화돼 있다 — 켜는 것이 오히려 실패를
    #   만든다. 조건을 못 맞추면 그냥 끄고 _extract_json 의 관용 파서에 맡긴다.
    if "json" in (system + user).lower():
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.SECRETS.deepseek_api_key}",
               "Content-Type": "application/json"}
    with httpx.Client(timeout=config.LLM_HTTP_TIMEOUT_SEC) as client:
        resp = client.post(f"{config.DEEPSEEK_BASE}/chat/completions", headers=headers, json=body)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise httpx.TransportError(f"{resp.status_code} from deepseek")
        resp.raise_for_status()
        data = resp.json()
    # ★ 기록이 절단 검사보다 **먼저**다 — Gemini 경로와 같은 이유(잘린 호출도 돈은 나간다).
    _record_text_usage(model, data.get("usage") or {})
    choice = (data.get("choices") or [{}])[0]
    text = str((choice.get("message") or {}).get("content") or "")
    if choice.get("finish_reason") == "length":
        raise OutputTruncatedError(
            f"출력이 max_tokens({max_tokens})에서 잘렸다 — 상한을 올려야 한다 (model={model})",
            partial=text)
    if not text.strip():
        raise JSONParseError(f"DeepSeek 응답이 비어 있다 (finish_reason={choice.get('finish_reason')})")
    return text


def _gemini_text(*, model: str, system: str, user: str, max_tokens: int,
                 state: dict[str, Any] | None = None) -> str:
    """Gemini 호출 + 지속 실패 시 Anthropic 폴백.

    ★ 왜 폴백이 필요한가: gemini-2.5-pro 는 과부하 시 503 을 낸다. 위의 재시도는 4회·
      최대 ~45초라 몇 분씩 가는 과부하는 못 넘긴다. 그러면 요청 행이 "503 from gemini" 로
      죽고 운영자에게는 **설명판형이 아예 안 만들어지는** 것으로 보인다(실측 2026-08-04).
      엣지 함수(generate-report-draft `llmText`)는 이미 같은 폴백을 갖고 있었다 — 트윈을 맞춘다.

    ★ 절단(OutputTruncatedError)은 폴백하지 않는다. 모델을 바꿔도 같은 프롬프트라 또 잘리고,
      운영자가 "출력 상한을 올려라"라는 정확한 처방 대신 비싼 재시도를 보게 된다.
    """
    fallback = config.LLM_ANTHROPIC_FALLBACK_MODEL
    # ★ 차단 스위치가 켜져 있으면 폴백은 존재하지 않는 것으로 본다 — 그래야 Gemini 재시도가
    #   짧게 끊기지 않는다(GEMINI_ATTEMPTS_WITH_FALLBACK). 오늘 429 에 폴백이 발동해
    #   Gemini 를 2번만 시도하고 죽은 Anthropic 으로 30분을 버린 것이 그 사고다.
    has_fallback = bool(fallback and config.SECRETS.anthropic_api_key
                        and not config.ANTHROPIC_DISABLED)
    # ★ 폴백이 있으면 gemini 재시도를 **짧게 끊는다.** 503 은 빨리 돌아오지만 과부하가
    #   *지연*으로 나타나면 매 시도가 LLM_HTTP_TIMEOUT_SEC(180초)를 다 쓴다. 기본 4회면
    #   백오프까지 약 12분인데 report-draft.yml 의 잡 상한이 15분이다 — 폴백에 도달하기 전에
    #   잡이 죽고, 그 뒤로 대본·자기검증·컴플라이언스 호출이 더 남아 있다(리뷰 지적).
    #   갈아탈 곳이 있으면 오래 기다릴 이유가 없다. 없으면 종전대로 끝까지 버틴다.
    #   ※ retry_with 는 tenacity 가 붙여 주는 것이다. 테스트가 이 함수를 평범한 stub 으로
    #     갈아 끼우는 경우가 있어 getattr 로 본다 — 없으면 그냥 한 번 부른다.
    retry_with = getattr(_gemini_create, "retry_with", None)
    call = (retry_with(stop=stop_after_attempt(config.GEMINI_ATTEMPTS_WITH_FALLBACK))
            if (has_fallback and retry_with) else _gemini_create)
    try:
        return call(model=model, system=system, user=user, max_tokens=max_tokens)
    except OutputTruncatedError:
        raise
    # ★ HTTPStatusError 는 **일부러 뺐다.** 그건 raise_for_status() 가 4xx 에 내는 것이라
    #   401/403(키 오류)·404(모델명 오타)처럼 **설정이 틀린** 경우다. 그걸 폴백으로 덮으면
    #   잡은 멀쩡해 보이면서 영원히 의도치 않은 공급자로 돌고, 비용은 비용대로 나간다
    #   (리뷰 지적). 429·5xx 는 위에서 TransportError 로 바꿔 던지므로 여기 걸린다.
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        if not has_fallback:
            # 폴백이 꺼져 있거나 키가 없다 — 원인을 가리지 말고 그대로 올린다.
            raise
        log.warning("gemini 실패(%s) → anthropic 폴백: %s", exc, fallback)
        # ★ 한 번 갈아탔으면 **이 요청 동안은 계속 그쪽으로 간다.** 호출자의 JSON 파싱
        #   재시도 루프가 여기를 다시 부르면, 안 그럴 경우 죽은 gemini 를 처음부터 또
        #   기다린다 — 2회 × 180초를 파싱 재시도마다 되풀이한다는 뜻이라, 짧게 끊어 둔
        #   예산이 "요청당"이 아니라 "파싱 시도당"이 된다(리뷰 지적). 15분 잡 안에서
        #   두 번째 폴백에 닿지 못한다. 망가진 응답을 낸 쪽을 다시 부르는 것이 맞다.
        if state is not None:
            state["provider"] = fallback
        return _create(_client(), model=fallback, system=system, user=user,
                       max_tokens=max_tokens)


def _backend_for(model: str) -> str:
    """모델 ID → 공급자. 판정을 **한 곳에만** 둔다.

    ★ 종전에는 `startswith("gemini")` 한 줄이 call_json 안에 박혀 있었고, "gemini 가 아니면
      Anthropic" 이라는 뜻이 되어 있었다. 공급자가 셋이 되는 순간 그 이분법은 틀린 기본값을
      낸다 — 새 공급자를 Anthropic 으로 보내 버린다.
    """
    m = model.lower()
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("deepseek"):
        return "deepseek"
    return "anthropic"


def _extract_json(text: str) -> dict[str, Any]:
    """코드펜스/잡텍스트를 관용적으로 벗겨 JSON 객체 파싱."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise JSONParseError("JSON 객체를 찾지 못함")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as exc:
        raise JSONParseError(str(exc)) from exc


def call_json(
    *, model: str, system: str, user: str, max_tokens: Optional[int] = None,
    salvage_truncated: bool = False,
) -> dict[str, Any]:
    """JSON 응답 호출. 파싱 실패 시 config.LLM_JSON_RETRY 회 재시도.

    최종 실패 시 JSONParseError 를 던진다(호출자가 0점 처리 + 로그).

    salvage_truncated: 출력이 상한에서 잘렸을 때 **앞부분만이라도 살려** 돌려준다.
      ★ 기본 off 인 이유: 대본처럼 뒤쪽이 빠지면 안 되는 출력에 이걸 켜면, 씬이 잘린
        불완전한 대본이 통과해 버린다. "앞에서부터 N개면 충분한" 출력에만 켠다.
      ★ 이 인자가 없으면 하류의 개수 상한이 **영원히 도달하지 못한다** — 절단은 파싱보다
        먼저 일어나므로 normalize 단계의 방어는 이미 온전한 응답만 다듬는다(리뷰 지적).
    """
    mt = max_tokens or config.LLM_MAX_TOKENS
    backend = _backend_for(model)
    # ★ Anthropic 클라이언트는 **그 경로일 때만** 만든다. 종전 `None if use_gemini else _client()`
    #   는 gemini 가 아니면 무조건 Anthropic 을 깨웠다 — deepseek 모델을 주면 차단 스위치에
    #   걸려 엉뚱한 곳에서 죽는다.
    client = _client() if backend == "anthropic" else None
    last_exc: Exception | None = None
    # ★ 이 요청이 폴백으로 갈아탄 공급자를 기억한다 — 아래 재시도 루프가 gemini 를 처음부터
    #   다시 기다리지 않게. 재시도의 목적은 **파싱 실패 복구**이므로, 망가진 응답을 낸 쪽을
    #   다시 부르는 것이 맞다.
    state: dict[str, Any] = {}
    for attempt in range(config.LLM_JSON_RETRY + 1):
        try:
            if state.get("provider"):
                raw = _create(_client(), model=state["provider"], system=system,
                              user=user, max_tokens=mt)
            elif backend == "gemini":
                raw = _gemini_text(model=model, system=system, user=user, max_tokens=mt,
                                   state=state)
            elif backend == "deepseek":
                raw = _deepseek_create(model=model, system=system, user=user, max_tokens=mt)
            else:
                raw = _create(client, model=model, system=system, user=user, max_tokens=mt)
        except OutputTruncatedError as exc:
            if not (salvage_truncated and getattr(exc, "partial", "")):
                raise
            obj = salvage_json(exc.partial)      # 못 살리면 JSONParseError 로 올라간다
            obj[SALVAGED_MARK] = True
            log.warning("출력이 잘렸으나 앞부분을 살려 진행한다(%d자): %s",
                        len(exc.partial), exc)
            return obj
        try:
            return _extract_json(raw)
        except JSONParseError as exc:
            last_exc = exc
            log.warning("JSON 파싱 실패(attempt %d/%d): %s",
                        attempt + 1, config.LLM_JSON_RETRY + 1, exc)
    assert last_exc is not None
    raise last_exc

# ─────────────────────────────────────────────────────────────
# 텍스트 비용 기록 — "어제 얼마 썼나"에 코드가 답하게 한다
# ─────────────────────────────────────────────────────────────
# ★ 왜 여기인가(2026-08-29 사고): 원장에 텍스트 호출이 **한 줄도 없었다.** 이미지·영상만
#   기록돼서, 운영자가 지출을 물었을 때 원장은 $2.79 만 보여줬고 진짜 지출(대본 48벌 생성 +
#   두 번의 채점)은 어디에도 없었다. 나는 추정으로 답할 수밖에 없었다.
# ★ 호출 지점이 아니라 **공급자 경계**에 둔다. 호출부(factsheet·scriptgen·directive·판정
#   스크립트)마다 붙이면 언젠가 하나를 빠뜨리고, 빠뜨린 그 하나가 제일 비싼 것일 수 있다.
# ★ 기록 실패가 호출을 막지 않는다 — 관측을 켜다가 사고를 내면 안 된다(cost.record 와 같은 자세).
_TEXT_PURPOSE: dict[str, str] = {}      # 호출자가 set_text_purpose 로 라벨을 남긴다


def set_text_purpose(purpose: str) -> None:
    """이 프로세스의 텍스트 호출 용도 라벨(factsheet|script|selfcheck|directive|judge).

    라벨이 없으면 'unlabeled' 로 남는다 — 기록을 건너뛰지 않는다. "호출이 없었다"와
    "라벨을 안 붙였다"는 전혀 다른 사실이고, 섞으면 이번 사고가 반복된다.
    """
    _TEXT_PURPOSE["value"] = str(purpose or "").strip() or "unlabeled"


def _record_text_usage(model: str, usage: dict[str, Any]) -> None:
    try:
        # 공급자마다 키 이름이 다르다. 하나라도 빠뜨리면 그 공급자의 호출이 원장에서
        # **통째로 사라진다**(0 이면 아래에서 return 한다) — 이번 사고의 재발 경로다.
        cin = int(usage.get("promptTokenCount") or usage.get("input_tokens")
                  or usage.get("prompt_tokens") or 0)
        cout = int(usage.get("candidatesTokenCount") or usage.get("output_tokens")
                   or usage.get("completion_tokens") or 0)
        # 사고(thinking) 토큰도 출력으로 과금된다 — 빼먹으면 pro 비용이 실제보다 작게 보인다.
        cout += int(usage.get("thoughtsTokenCount") or 0)
        if not (cin or cout):
            return
        cost.record(cost.text_attempt(
            model_id=model, purpose=_TEXT_PURPOSE.get("value", "unlabeled"),
            input_tokens=cin, output_tokens=cout))
    except Exception as exc:  # noqa: BLE001 — 기록 실패가 호출을 막지 않는다
        log.warning("텍스트 비용 기록 실패(무시): %s", exc)
