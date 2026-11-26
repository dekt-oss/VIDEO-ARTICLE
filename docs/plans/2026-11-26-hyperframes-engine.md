# 기획: 하이퍼프레임(HTML→영상) + 음악 박자 싱크를 주류 엔진에 넣기

작성 2026-11-26 · 상태 **S1~S2 운영자 승인(2026-11-26) · S1 구현 완료 · S2 러너 렌더 확인 중** · 범위 **주류 공장만**(논문·리포트 라인은 손대지 않음)

> **이번에 승인받을 범위는 S1~S2(파일 렌더까지)뿐이다.** 게시·DB 상태 전이를 바꾸는 S3 이후는 별도 승인 + deviation 문서.
> 코덱스 계획 리뷰(2026-11-26, `outputs/reviews/hyperframes-plan-codex.md`) 지적 6건 반영.

## 1. 왜

- 오늘 샘플 두 편(`experiments/hf-beat`, `experiments/hf-quarks`)이 로컬에서 0원으로 렌더됐다.
  - 박자: 음원에서 박자를 **자동 검출**(`hyperframes beats`) → 117 BPM, 23박. 비비노 코드에 손으로 적어 둔 값(117 BPM)과 같다.
    글자 등장·캐릭터 동작·배경 맥동을 그 박자에 맞췄다.
  - 입자: three.quarks(김) — 같은 시각은 항상 같은 그림(씨앗 고정 + 0초부터 다시 계산).
- 지금 주류 렌더는 Pillow 로 그림을 그리고 ffmpeg 로 이어 붙인다(`engine/drinks_render.py`·`drinks_card_reel.py`·`drinks_meme.py`·`drinks_clay.py`).
  움직임은 Ken Burns·xfade·ASS 글자 정도이고, **음악은 없거나 박자 없는 낮은 화음**이다(`drinks_meme.py:420`).
- 밈의 "박자 맞춤"은 지금 자동 게시를 못 한다 — 인스타 API 로는 앱 음원을 붙일 수 없어서 `manual_audio` 로 보낸다(0066).
  **우리 권리의 음원을 영상에 구워 넣으면** 이 제약을 비켜 갈 수 있다(단, 자동 게시로 바꾸는 것은 별도 운영자 결정 — §6).

## 2. 무엇을 만드나 (최소)

새 렌더 백엔드 하나: **"템플릿 + 데이터 + 음원 → mp4"**.

| 부품 | 위치 | 하는 일 |
|---|---|---|
| 템플릿 | `hf_templates/<이름>/`(index.html + compositions/ + assets/) | 하이퍼프레임 프로젝트. 글·색·박자는 `data-composition-variables` 로만 받는다 |
| 렌더 함수 | `engine/hf_render.py` | 템플릿을 임시 폴더로 복사 → 박자표 결정(**LEDGER 에 있으면 그것, 외부 곡만 `beats` 검출**) → `render --variables-file … --strict-variables` → mp4 경로·박자·길이 반환 |
| 음원 목록 | `assets/music/` + `assets/music/LEDGER.md` | 우리 권리 음원만. 파일마다 출처·권리·BPM 기록. 첫 곡 = 비비노 릴스 v2.2 BGM(코드 합성, 제3자 권리 없음 — 비비노 `audio-cue-and-rights-v2.1.md:6`) |
| 박자표 | 음원 LEDGER 에 곡별 **BPM·원점(초)** 기록 | 우리 합성 곡은 기록된 격자를 그대로 쓴다. 자동 검출(`beats`)은 외부 음원용 + 우리 곡 교차 확인용 |
| 설정 | `engine/config.py` | `HF_CLI_VERSION="0.9.19"`(고정), `HF_RENDER_TIMEOUT_SEC`, `DRINKS_HF_ENABLED=False`(기본 꺼짐), 음량 목표 −14 LUFS |

- CLI 는 **버전 고정**(`npx --yes hyperframes@0.9.19`). 전송(텔레메트리)은 `HYPERFRAMES_NO_TELEMETRY=1` 로 끈다.
- 글꼴은 저장소의 Pretendard(`assets/fonts/`, 라이선스 파일 있음)를 `@font-face` 로 템플릿에 넣는다. 시스템 글꼴 의존 금지.
- 렌더 뒤 음량은 기존 엔진과 같은 `loudnorm` 으로 맞춘다(샘플: −22.9 → −15.9 LUFS 실측).
- 외부 CDN(gsap·lottie-web)은 템플릿 `assets/lib/` 로 내려 두고 고정 버전만 쓴다 — 렌더가 네트워크에 기대지 않게.

## 3. 단계

| 단계 | 내용 | 돈 | 합격 기준 |
|---|---|---|---|
| S1 | `hf_render.py` + 템플릿 1개(밈 `top_text` 틀을 하이퍼프레임으로) + 순수 테스트(명령 조립·박자 JSON 파싱·변수 검증) | 0 | ① 로컬 `python -m engine.hf_render --demo out.mp4` 가 9:16·30fps·소리 있음·−14±2 LUFS ② **컷 시각 오차 ≤ 1프레임(33ms)** — 최종 음원의 박자표 기준 ③ 글자 잘림 0(하이퍼프레임 `check` 통과) ④ **실패 경로**: 박자 0건·CLI 오류·타임아웃·변수 불일치(`--strict-variables`)면 예외, 빈 mp4 를 성공으로 넘기지 않음(테스트로 고정) ⑤ 네트워크 차단 상태에서도 렌더(라이브러리 로컬화 확인) ⑥ pytest 전체 통과 |
| S2 | GitHub Actions 에서 렌더 증명(`workflow_dispatch` 전용 잡: setup-node + 크롬은 CLI 가 받음) | 0(액션 분) | 러너에서 같은 데모가 렌더되고 걸린 시간·용량을 기록. 실패면 원인 기록 후 멈춤 |
| S3 | 주류 제작 워커에 새 렌더러로 연결: `drinks_meme`(박자 맞춤 등급)부터. `DRINKS_HF_ENABLED` 켤 때만. **별도 승인** | 0 | 승인된 밈 1편이 하이퍼프레임 경로로 렌더·저장(새 묶음, sha256). 기존 경로 회귀 테스트 통과 |
| S4 | 카드 릴스·클레이 설명형에 박자 연출 이식(장면 전환을 박자에) | 0 | 운영자가 샘플을 보고 고름 |

각 단계 끝에 커밋, 큰 변경은 Codex 코드 리뷰 → 페이블 최종 검사(하네스 §3).

### S3 영향 범위(코덱스 지적 — 승인 전에 확정)

- 파이썬 검증: `engine/drinks_meme.py:125` 가 `sync_required → app_manual` 을 강제한다. 새 음원 모드(`baked_owned`)를 추가해야 한다.
- SQL: 0066 의 승인·완료 함수(`0066_drinks_meme_engine.sql:200,470`)와 표 제약 `drink_meme_sync_gate_ck` 가 같은 규칙을 가진다 → 새 마이그레이션.
- 승인 지문(`0066…sql:153`)은 spec·근거 ID 만 묶는다 → **템플릿 버전·음원 sha256·박자표**까지 묶어야 승인 뒤 바뀐 음원이 몰래 나가지 않는다.
- 워커 진입점: 밈은 `drinks-meme.yml`(`python -m engine.drinks_meme`)이 돈다. `drinks-produce.yml` 이 아니다. 노드 설치는 이 잡에 붙는다.
- 롤백 계약: 렌더러 종류를 작업 행에 기록. 스위치를 꺼도 이미 `baked_owned` 로 승인된 작업은 **재승인 필요** 상태로 돌린다(옛 경로로 몰래 바꾸지 않음). 이미 저장된 결과물은 지우지 않는다. DB 원복 시 새 상태 값은 `manual_audio` 로 되돌리는 down 마이그레이션을 같이 쓴다. 원복 때 `baked_owned` spec 의 음원 모드·안내문·승인 지문 처리는 S3 기획 때 확정(코덱스 재검토 남은 항목).
- 게시: 주류 인스타 게시는 운영자가 승인한 기존 경로(`docs/deviation-drinks-publish-loop.md`)를 그대로 탄다. 박자 맞춤 밈을 자동 게시로 푸는 것은 이 기획이 아니라 §6-2 결정 + deviation.

## 4. 건드리지 않는 것

- 논문·리포트 라인 렌더(`engine/render.py` 의 photo 등급제·화풍 잠금) — 이번 범위 밖.
- 기존 주류 렌더 경로 — 삭제하지 않는다. 새 렌더러는 옆에 붙고 스위치로만 켠다.
- 유료 그림 구매(`drinks_paid`) — 하이퍼프레임은 산 그림을 받아 움직일 뿐 새로 사지 않는다.

## 5. 위험

- **러너 렌더 시간**: 로컬 12초 영상 = 준비 15초 + 캡처 25초 정도(처음 1회는 CLI·크롬 내려받기로 4분). 러너는 GPU 가 없어 소프트웨어 렌더 → 3D(입자)는 더 느릴 수 있다. S2 에서 실측.
- **결정성**: 하이퍼프레임 규칙(시간 함수만, `Math.random` 금지)을 어기는 라이브러리(three.quarks)는 씨앗을 덮어쓰고 0초부터 다시 계산해야 한다 — 길이에 비례해 느려진다. 30초 넘는 장면이면 캐시가 필요.
- **음원 권리**: 자동 게시에 쓰는 음원은 LEDGER 에 권리가 적힌 것만. HeyGen 음원 카탈로그(로그인 필요)의 상업·인스타 사용 조건은 **확인 못 함** — 확인 전엔 쓰지 않는다.
- **인스타 저작권 판정**: 구운 음원이 우리 것이어도 인스타 자동 판정이 막을 수 있다(미검증). 게시 시험도 S3 별도 승인 범위.
- **박자 원점**: BPM 이 같아도 원점이 다르면 어긋난다. 실측: 자동 검출 22박을 비비노 격자(원점 2.8초, 20/39초 간격)와 대조 → 최대 14.2ms·평균 6.9ms(1프레임 33ms 안). 검출 23박 중 마지막 1박(11.525초)은 페이드아웃 구간의 엇박이라 제외하고 22박을 댔다. 그래도 우리 곡은 LEDGER 격자를 정본으로 쓴다.

## 6. 운영자가 정할 것

1. 이 기획대로 S1~S2 진행해도 되나(0원).
2. 박자 맞춤 밈을 "우리 음원을 구운 경우" 자동 게시 대상으로 풀 것인가 — 지금은 DB 제약(0066 `drink_meme_sync_gate_ck`)이 막는다. 풀려면 마이그레이션 + deviation 문서가 필요하다. **S3 전에 결정.**
3. 음원을 더 늘리는 방법: (a) 비비노처럼 코드 합성 (b) 권리 확인된 라이브러리 구매 (c) HeyGen 카탈로그(무료 로그인, 이용 조건 확인 필요).

## 7. S1 결과 (2026-11-26)

- `engine/hf_render.py` · `hf_templates/meme-beat/` · `assets/music/`(ledger.json + 117 BPM 곡) · `tests/test_hf_render.py`(9건) · `.github/workflows/hf-render-demo.yml`(S2).
- 박자표 대조: `--check-beats` → 자동 검출 46박 전부 박자표 1프레임 안(ratio 1.0). AAC 로 저장해도 박자가 밀리지 않음.
- 데모: 5.5초·1080×1920·30fps·AAC 48kHz·**−15.9 LUFS**(목표 −14±2 안). 글 5개가 각자 박자에 떨어짐(프레임 확인).
- 실패 경로: 렌더 도중 세션이 끊겨 **깨진 mp4 가 최종 위치에 남는 일이 실제로 있었다** → 임시 파일에 쓰고 검증 통과 뒤에만 옮기도록 고침.
- LEDGER 는 계획의 `LEDGER.md` 대신 기계가 읽는 `ledger.json` 한 파일로 했다(권리·출처·주의를 같은 파일에).
- gsap 3.15.0 은 템플릿 `assets/lib/` 에 넣었다(GreenSock 'no charge' 표준 라이선스 — 상업 사용 무료).
- 계획의 `--variables-file … --strict-variables` 대신 **엔진이 index.html 을 직접 채운다**(글 개수가 편마다 달라 칸 수가 바뀌기 때문 — 변수로는 시간 있는 요소를 만들 수 없다). 대신 템플릿에 필수 칸이 하나라도 없으면 렌더 전에 멈추고(테스트 고정), 렌더는 `--strict` 로 린트 오류에서 멈춘다.
- 코덱스 코드 리뷰(`outputs/reviews/hyperframes-s1-code-codex.md`) 3건 반영: 같은 폴더 임시 파일 + `os.replace`, 칸 누락 거부, 30fps 검사.
- **main 에 리포트용 하이퍼프레임 엔진(`engine/motion/`, `docs/plans/2026-11-24-motion-graphics-engine.md`)이 먼저 들어와 있었다.** 고정 버전은 그쪽 `MOTION_HYPERFRAMES_PKG`(0.9.72) 하나를 같이 쓴다(`HF_HYPERFRAMES_PKG`). 렌더 함수는 리포트 전용 지시서·음성 구조라 합치지 않고 따로 둔다.
- S2 워크플로는 `workflow_dispatch` 에 더해 이 경로를 고친 PR 에서도 돈다(시크릿·돈 없음, 액션 분만) — 렌더 회귀를 PR 에서 바로 보려고.
- 페이블 독립 검사 ❌1(러너 의존성 누락) 반영, ⚠️ 중 예외 감싸기·박자 개수 하한·깨진 파일 정리 테스트·브랜드 상수화 반영.
