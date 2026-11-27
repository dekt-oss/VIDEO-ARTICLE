# deviation: 밈 '우리 음원 박자 구움'(owned_track) — 박자 맞춤 밈의 자동 게시 길

2026-11-27 · 운영자 지시 "3단계 진행해"(2026-11-27) · 기획 `docs/plans/2026-11-26-hyperframes-engine.md` S3 · 마이그레이션 `0091_drinks_meme_owned_track.sql`

## 무엇과 다른가

`docs/deviation-drinks-meme-engine.md` 는 "박자 맞춤 밈은 자동 게시하지 않는다(앱에서 음원을 붙인다)"였다. 인스타 API 로는 음원 시작 위치를 못 정하기 때문이다.
이번에 **음원을 우리가 박자에 맞춰 영상에 구워 넣는 길**을 하나 더 냈다. 앱에서 맞춰 붙일 것이 없으므로 그 밈은 박자 무관(`sync_free`)이고, 기존 게시 대기 → 발행안 → 운영자 승인·예약 → 게시 워커 경로를 그대로 탄다.

## 규칙

- 음원 방식 `owned_track` + `track`(= `assets/music/ledger.json` 키). 권리가 `owned*` 인 곡만, 파일 sha256 이 목록과 같아야 렌더한다.
- ① 위쪽 글 틀(`top_text`) + 글 배경(`text_bg`)만 — 하이퍼프레임 템플릿이 그 틀 하나다(`hf_templates/meme-beat`).
- 박자 맞춤 카드도 `owned_track` 이면 박자 무관으로 승인된다. `app_manual`·`sync_required`·표 제약은 그대로다.
- LLM 글 초안: 박자 맞춤 카드 + ① 틀 + 스위치 켜짐이면 `owned_track` 으로 만든다(꺼져 있거나 ② 틀이면 옛 앱 부착 그대로).
- 같은 규칙이 세 곳에 있다: `engine/drinks_meme.py validate_spec/check_safety` · DB `drinks_meme_blockers`(0091) · `web/lib/drinks/meme.ts`. 테스트가 셋을 대조한다.
- 렌더는 `engine/hf_render.py`(하이퍼프레임 `config.HF_HYPERFRAMES_PKG`), 워커 `drinks-meme.yml` 에 Node 를 붙였다. 무음 결과는 자동 검사(`ambient_silent`)가 막는다.

## 되돌리기

- 즉시: 워커 환경변수 `DRINKS_HF_ENABLED=0` → `owned_track` 밈은 `hf_disabled` 로 **멈춘다**(옛 무음·분위기 경로로 몰래 바꾸지 않는다). LLM 초안도 옛 앱 부착으로 돌아간다.
- DB: 0066 의 `drinks_meme_blockers` 를 다시 적용(0091 머리말 참고). 만든 파일·게시 기록은 지우지 않는다.

## 미검증 / 남은 것

- **길이 검사 어긋남(알려진 한계):** DB(0091)는 박자표를 몰라 비트 합(6~15초)만 잰다. 박자에 맞추면 길이가 늘어(첫 박 0.36초·박자 반올림·마지막 글 2초) 15초 근처 글은 DB 승인 뒤 워커 검사(`meme_duration`)에서 이유와 함께 멈춘다. 곡이 늘면 DB 에 박자표를 둔다.

- 구운 음원을 인스타 자동 판정이 어떻게 보는지(저작권 표시 등) — 첫 게시 때 운영자가 확인.
- 음원은 1곡뿐이고 원래 영상의 효과음이 섞여 있다(ledger `caveat`). 곡을 늘리는 방법은 기획서 §6-3.
- 박자 싱크의 실제 듣는 느낌은 사람 귀로 판정해야 한다(Claude 는 숫자로만 쟀다).
