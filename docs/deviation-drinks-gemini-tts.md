# deviation — 주류 공장 TTS 를 제미나이 TTS 로 (2026-11-28)

## 결정
소유자 지시 2026-11-28: "엔진에도 제미나이 TTS 사용하는 걸로 반영". 주류 공장(영상 렌더 `drinks_render`·사진클레이 `drinks_clay`·설명형 `drinks_explainer_queue`)의
기본 TTS 를 Edge(현수) → **제미나이 TTS `gemini-2.5-flash-preview-tts`, 목소리 Alnilam**(소유자 지정)으로 바꾼다. 되돌리기: `DRINKS_TTS=edge`.

## 무엇이 바뀌었나
- `engine/providers/gemini_tts.py` — AI Studio 키(`AQ.` 형식)로 호출. 문장마다 같은 말투 지시(`config.GEMINI_TTS_STYLE`), `engine/voice_qc.py` 숫자 검사로
  피치가 튄 문장은 최대 3번 다시 받아 가장 나은 것을 쓴다. 토큰 × 단가를 `SPENT` 에 쌓아 렌더 costs 에 기록.
- `providers/tts.py` 에 `TTS_PROVIDER=gemini` 분기. `drinks_render._guard_free` 가 gemini 만 추가로 연다(다른 유료 TTS 는 여전히 막힘).
- `drinks-produce.yml` 은 **TTS 전용 이름 `GEMINI_TTS_API_KEY`** 로만 키를 받는다 — 그림·영상 구매 경로가 읽는 `GEMINI_API_KEY` 는 여전히 없다
  (`tests/test_drinks_explainer_queue.py::test_ci_worker_has_no_switch_and_no_key` 의 원래 의도 유지).

## 왜 구글 클라우드 TTS(Chirp 3 HD) 가 아닌가
같은 목소리 이름이지만 `texttospeech.googleapis.com` 은 AI Studio 키를 받지 않는다 — 401 "API keys are not supported by this API"(서비스를 켠 뒤에도 같음, 2026-11-28 실측).
소유자가 키를 따로 관리하기 싫다고 해 같은 키로 되는 제미나이 TTS 를 쓴다.

## 잃는 것
- **단어 타임스탬프 없음** — Edge WordBoundary 로 맞추던 자막 줄 시작이 글자 비례(`drinks_clay.line_starts` 폴백)로 바뀐다.
- **무료가 아니다** — 단가(ai.google.dev 가격표 요약, 2026-11-28): 입력 $0.50 · 음성 출력 $10 / 100만 토큰. 사케 1편(10문장) 실측 약 $0.012.
- 문장마다 따로 합성돼 톤이 들쭉날쭉할 수 있다 — 말투 지시 + 숫자 검사로 줄였지만 귀 확인을 대신하지 못한다.
- 2026-11-10 운영자 비교 청취로 확정한 현수(`DRINKS_CLAY_TTS_VOICE`)는 `DRINKS_TTS=edge` 일 때만 쓰인다.
