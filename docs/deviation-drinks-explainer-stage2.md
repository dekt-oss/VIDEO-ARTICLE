# 설명형 릴스 2단계 준비 — S0.5 → S2 → S3 를 돈 쓰기 직전까지 (2026-11-02)

**한 줄:** 위스키 "왜 안 상하나" 설명형 한 편을 사기 전에 필요한 것 — 대본 지시문 보강, 공급자 요청 모양의 문서 대조, 단계별 스크립트(결재 문장·상한·지시서 표), 품질 판정 6항목 — 을 **0원으로 끝까지** 돌려 놓았다. **실제 모델·영상 호출은 한 번도 하지 않았고, 운영 DB 에 쓴 것도 없다.** 세 스크립트는 `--yes` 와 결재 문장 없이는 아무것도 보내지 않는다.

근거 문서: `docs/기획_릴스3형식_트렌드보드_v2_2026-10-31.md` §3·§9·§10, `docs/총괄계획_릴스3형식_수집부터게시까지_2026-11-02.md` §4-1·§6. 앞 단계: `docs/deviation-drinks-explainer-stage1.md`, `docs/deviation-drinks-explainer-queue.md`.

## 지금 있는 것

| 무엇 | 어디 | 상태 |
|---|---|---|
| 대본 지시문: 시각 주장표 4칸 + `motion_prompt` **필수** + 2번 이후 장면마다 `continuity`(`ref:N`·`match`·`cut`) + "첫 도해가 훅" | `engine/drinks_develop.py plan_system()`·`_visual_claim_rules()` | 가짜 응답으로 통과. 실제 모델이 이 모양을 내는지는 S0.5 에서 본다 |
| 경계 종류 검사(차단) | `drinks_develop.explainer_boundary_checks`·`continuity_kind` | 개발 단계(check_plan)만. 지시서 단계는 없어도 `cut` 으로 읽는다 |
| 큐가 `match`·`cut` 선언을 읽는다 | `drinks_explainer_queue.scene_boundary` | `match` = `ref:(n-1)` |
| Omni 요청·응답 모양(문서 대조) + 무료 사전 검증 + 조회 정정 | `engine/providers/video.py` | **호출 0회.** 아래 표 |
| 구매 전 사전 검증 게이트 | `drinks_paid.LiveAdapter.check_ready` → `provider_preflight_failed` | 스위치·결재 뒤, 가잡기 전 |
| S0.5 스크립트(가짜 응답 끝까지, 상한 $0.30) | `scripts/explainer_s05.py` | dry-run 통과. 산출 `docs/preview-2026-11-02/explainer-s05/` |
| S2 스크립트(1번 + 훅 슬롯, 상한 $2.60) | `scripts/explainer_s2.py` | dry-run 통과. 산출 `docs/preview-2026-11-02/explainer-s2/` |
| S3·S4 스크립트(편 전체, 상한 $8.90 − S2) + 캡션 초안 | `scripts/explainer_s3.py` | dry-run 통과. 산출 `docs/preview-2026-11-02/explainer-s3/` |
| 공용: 결재 문장·지시서 표·범위 계산·게이트 | `scripts/explainer_stages.py` | |
| 품질 판정 6항목 | SQL 0067 `drinks_explainer_review` required · web `QUALITY_CHECKS`/`ReviewForm` · `config.DRINKS_EXPLAINER_QUALITY_ITEMS` | **이미 있었다.** 셋이 같은지 시험이 대조한다 |
| 시험 | `tests/test_drinks_explainer_stage2.py`(19) + `test_drinks_explainer_queue.py` 갱신 | 네트워크 0 |

마이그레이션은 **없다**(0069 를 쓰지 않았다). 새 칸이 필요한 자리가 없었다 — `continuity` 는 이미 제작안 JSON 안에 있고, 검수 항목은 0067 에 있다.

## 공급자 문서 대조 결과 (2026-11-02, ai.google.dev — 호출 없이 문서만)

| 항목 | 결과 | 어떻게 반영했나 |
|---|---|---|
| 주소·인증 | **검증됨** `POST v1beta/interactions`, `x-goog-api-key` 헤더 | 그대로 |
| `input` 블록 모양 | **검증됨** `{"type":"image","data":…,"mime_type":…}` · `{"type":"text","text":…}` | 그대로(옛 가정이 맞았다) |
| 시작 그림이 첫 프레임인가 | **검증됨(문서)** `generation_config.video_config.task="image_to_video"`: "첫 그림이 시작 프레임, 둘째 그림(선택)이 끝 프레임" | 요청에 `generation_config` 를 넣었다. §3-5 이어 그리기의 전제가 문서로 확인됐다 — 실제 픽셀이 고정되는지는 S2 가 본다 |
| `response_format` | **검증됨** `type:"video"`, `aspect_ratio`(`9:16`/`16:9`), `resolution`(360p/720p/1080p/4k), `delivery`(`inline`/`uri`), `duration`(문자열) | `delivery:"inline"` 명시. 옛 코드는 `delivery` 없이 보냈다 |
| 길이 지정 | **칸은 있음, 형식은 미검증** — `duration` 이 문자열이라는 것만 문서에 있다 | `"8s"`(protobuf Duration 표기)로 보낸다. 틀리면 400 → `ExplainerNotSent`(청구 없음). 문장에도 "About 8 seconds" 를 같이 쓴다. `DRINKS_EXPLAINER_OMNI_SEND_DURATION=False` 로 칸을 뺄 수 있다 |
| 응답에서 영상 위치 | **검증됨(설명)** `steps[].{type:"model_output"}.content[].{type:"video", data|uri, mime_type}` — 다만 문서의 예시 응답은 글 모델 것뿐이다 | 파서를 `steps` 로 바꿨다. **옛 가정 `outputs[]` 는 더 읽지 않는다**(시험이 못 박음). 모양이 다르면 `ExplainerOutcomeUnknown` |
| 청구 단위 | **검증됨** 토큰. `usage.total_output_tokens`·`output_tokens_by_modality[{modality:"video"}]`. $17.50/100만 토큰, 720p 초당 5,792토큰 | 영상 모달리티 토큰이 있으면 그것, 없으면 total |
| 동기/폴링 | **검증됨** 기본 동기(한 응답에 `status:"completed"`). `background:true` 면 `GET interactions/{id}` 로 상태를 본다 | `background·store·stream=false` 로 보낸다(문서 권장). `status` 가 `in_progress` 면 결과 불명으로 멈춘다 |
| 결과 불명 정정 | **검증됨** `GET v1beta/interactions/{id}` 가 영상을 inline 으로 다시 준다 | `fetch_omni_interaction` — 코드만. 운영자가 닫는 흐름(대시보드)은 그대로이고 이 함수를 부르는 화면은 아직 없다 |
| 부정 프롬프트·seed | **검증됨: 칸 없음**(문서: "parameter 로 지원 안 함, 문장에 쓴다") | 보내지 않는다. 금지할 오해는 문장에 그대로(종전과 같다) |
| 무료 사전 검증 | **검증됨** `GET v1beta/models/{model}` → `{name, displayName, version, supportedGenerationMethods[]}` | `omni_preflight`: 404·이름 불일치면 **보내기 전에** 거절. 메서드 이름은 기록만(어떤 값이 오는지 미검증) |
| 모델 수명 | **검증됨** `gemini-omni-1.1-flash` Stable, 종료일 없음. `veo-*` 는 Gemini API 모델 목록에 없다 | 그대로 |
| Vertex Veo 3.1 Fast | 바꾸지 않았다(전송 미연결, "1 count=1초" 미검증) | 그대로 |

**단가와 금액은 문서와 맞는다.** dry-run 지시서(가짜 대본 9장면·최종 43.4초): 한 편 예상 $7.65·제안 상한 $8.60(문서 §3-7: $7.95·$8.90), S2 예상 $2.21·상한 $2.60(문서 §3-10: 약 $2.2·$2.6). 차이는 가짜 대본의 클립 초 수(60초 vs 64초)다.

## 세 스크립트의 안전 장치

- 기본 실행은 **0원 dry-run** 이다. `--yes` 가 없으면 운영 DB 에 쓰지 않고 모델·공급자를 부르지 않는다. `--yes` 가 있어도 `--approve "…"`(운영자가 승인한 말 그대로, DB `approver_words`)가 없으면 멈춘다.
- 상한은 `config.DRINKS_EXPLAINER_STAGE_CAPS_USD`(s05 0.30 / s2 2.60 / s3 8.90)에서만 읽고, 지시서로 계산한 예상이 상한을 넘으면 `--yes` 가 있어도 멈춘다. S3 상한은 원장(이 편 결재들의 확정액 + 가잡기)에서 S2 사용액을 빼서 정한다.
- 영상 구매(S2·S3 `buy`)는 그 위에 `DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1`(운영자 PC 한 회)과 `GEMINI_API_KEY` 가 있어야 하고, 무료 사전 검증을 지나야 한다. **코드가 스위치를 켜는 자리는 없다**(시험이 grep 으로 본다).
- 운영 DB 에 `drinks_explainer_status`(0067)가 없으면 쓰기 전에 멈춘다. **2026-11-02 읽기 조회: 운영 DB 는 0062·0064 는 있고 0067 은 없다.** S2 `plan` 전에 0067 적용(별도 결재)이 필요하다.
- 비밀값은 찍지도 저장하지도 않는다(`env_summary` 는 켜짐 여부만). 키는 헤더로만 간다.
- dry-run 의 네트워크: `explainer_s2 buy/status/plan` 과 `explainer_s3 buy/assemble/caption` 은 지시서를 운영 DB 에서 **읽어야** 표를 찍을 수 있어 `--plan-id` 를 주면 읽기 호출을 한다(쓰기 없음). 환경 변수가 없으면 읽기도 하지 않는다.

## 여기서 정한 것 (문서에 없던 것)

- **`match` 를 `continuity` 값으로 받는다.** 기획 §3-5 의 `match` 는 경계 종류이고 대본 칸은 `ref:N` 만 있었다. 모델이 "바로 앞이 이어진다"를 가장 자주 말하므로 `match` = `ref:(n-1)` 로 읽는다. `cut` 은 큐 문서에서 더한 종류다. 역할이 바뀌는 자리는 대본이 `cut` 으로 적고 코드가 `cut_to_mechanism` 으로 바꾼다 — 모델에게 전환의 뜻까지 고르게 하지 않는다.
- **경계 선언 누락은 개발 단계에서만 막는다.** 지시서 단계(`build_directive`)에서 막으면 리허설·옛 제작안이 전부 멈춘다. 지시서는 선언이 없으면 `cut` 으로 읽고, 그 결과는 지시서 표의 `boundary_in` 에 나간다 — 운영자가 결재 전에 본다.
- **S2 상한 안의 재시도 예비는 "덮는지"만 보인다.** 문서는 예상 $2.2·상한 $2.6 을 정했고, 그 폭($0.39)은 8초 클립 재시도($0.81)를 못 덮는다. 그래서 S2 에서 한 번 실패하면 **새 결재**다 — 스크립트가 그렇게 말한다. S3 는 폭($1.24)이 덮는다.
- **S0.5 운영 흐름은 두 요청이다.** 소재(549a5721…)가 이미 `selected` 라 [이걸로](`drinks_pick_topic`)는 "이미 승인된 소재"로 거부된다. 그래서 `evidence`(근거 다시 모으기, B3·B7 보강) → 대시보드에서 새 근거 버전 승인(사람) → `plan`(48초 대본) 순서로 가고, 둘이 한 개발 결재($0.30)를 나눠 쓴다(`--budget-id`). 근거 보강이 B3·B7 을 못 찾으면 그 비트는 지운다(§3-6-2) — 40초에 못 미치면 보류다.
- **S0.5 dry-run 의 길이 추정은 음절 ÷ 5.9/초(글자·숫자만).** 문장부호까지 세면 7초 장면이 10초 클립으로 올라가 S2 가 상한을 넘는다(실측). 실제 길이는 edge TTS 가 재고(`--tts edge`), 운영 지시서는 늘 실측이다.
- **사전 검증은 두 자리에서 돈다.** `LiveAdapter.check_ready`(작업 시작, 가잡기 전)와 `generate_explainer_clip`(클립마다, 스위치·결재 있을 때). 둘 다 무료 GET 이고, 구매 작업 하나에 1 + 클립 수만큼 조회가 간다. 둘 중 하나만 두면 직접 호출 경로나 작업 경로 중 하나가 빈다.
- **`fetch_omni_interaction` 은 코드만 있다.** 결과 불명(`unknown_billed`)을 조회로 정정하는 길이 문서로 열렸지만, 시도 표의 `provider_request_id` 를 읽어 닫아 주는 화면·명령은 아직 없다. 운영자가 billed/void 로 닫는 흐름이 그대로 정본이다.
- **캡션 "AI 생성 영상" 줄은 S3 스크립트의 초안에만 있다.** 게시 워커(`drinks_publish.py`)는 다른 작업이 동시에 고치고 있어 건드리지 않았다. 화면 안내(ExplainerProduction)는 종전대로 "코드가 넣지 않는다"고 말한다.

## 운영자가 실행할 명령 (돈이 드는 순서대로 — 각 단계는 따로 결재)

전제: 운영자 PC, `.env` 에 `SUPABASE_URL`·`SUPABASE_SERVICE_KEY`·`GEMINI_API_KEY`. S2 부터는 운영 DB 에 **0067 적용**이 먼저다.

1. **S0.5 (상한 $0.30, 모델 호출만)**
   ```bash
   python -m scripts.explainer_s05                                             # 0원: 지시문·가짜 대본·지시서 표 확인
   python -m scripts.explainer_s05 evidence --yes --approve "<승인 문장>"       # 근거 보강 요청 + 워커 1회
   #   → 대시보드에서 새 근거 버전(B3·B7 포함)을 보고 승인(사람)
   python -m scripts.explainer_s05 plan --yes --approve "<승인 문장>" --budget-id <위에서 열린 budget_id>
   #   → 대시보드에서 48초 대본·시각 주장표·원문 대조표를 보고 승인(사람)
   ```
2. **S2 (상한 $2.60, 1번 + 훅 슬롯 후보 2)** — 0067 적용 뒤
   ```bash
   python -m scripts.explainer_s2 preflight                                    # 무료 GET 1회: 모델 존재·메서드 이름 기록
   python -m scripts.explainer_s2 plan --plan-id <승인된 제작안 id> --yes --approve "<승인 문장>"   # 0원: TTS 실측 → 지시서·금액
   DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1 python -m scripts.explainer_s2 buy --plan-id <id> --yes --approve "<승인 문장>"
   #   → 대시보드 제작 화면에서 후보 판정·선택(사람). 첫 프레임 고정·실측 길이·청구 토큰을 여기서 확정한다
   ```
3. **S3 (상한 $8.90 − S2 사용액)**
   ```bash
   DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1 python -m scripts.explainer_s3 buy --plan-id <id> --yes --approve "<승인 문장>"   # 사람 선택 자리에서 멈추면 같은 명령을 다시
   python -m scripts.explainer_s3 assemble --plan-id <id> --yes                # 0원: 조립 → 자동 검사
   #   → 대시보드에서 과정 검수 3항목 → 품질 검수 6항목 → 파일 승인 = 게시 대기. 캡션은 `explainer_s3 caption` 초안 + "AI 생성 영상" 줄
   ```
   S4(사케)는 같은 S3 명령을 다른 `--plan-id` 로.

## 아직 안 된 것 · 미검증

- **실제 응답 모양·`duration` 형식·그림 품질·첫 프레임 고정(픽셀)**: 전부 S2 에서 처음 본다. 모양이 다르면 "모름"으로 멈추고 돈은 나갔을 수 있다 — 그래서 S2 가 작다.
- **모델이 새 지시문(continuity·motion_prompt 필수)을 실제로 따르는가**: S0.5 에서 본다. 못 따르면 재작성 1회 뒤 저장하지 않는다(종전 규칙).
- **B3·B7 근거**: 소재 개발 엔진이 승인 수집원·공식 목록에서 찾는다. 못 찾으면 운영자가 출처를 붙여야 한다 — 그 뒤에야 48초가 된다.
- **운영 DB 0067 미적용**: S2 전 결재 대상.
- **`fetch_omni_interaction` 을 부르는 화면·명령 없음**(위).
- **게시 캡션에 "AI 생성 영상" 자동 삽입 없음**(게시 워커는 다른 작업 중).
- `supportedGenerationMethods` 에 무엇이 오는지 모른다 — `preflight` 가 기록한다.

## 되돌리기

- 지시문·경계 검사: `drinks_develop.py` 의 `_visual_claim_rules` 끝 세 줄과 `explainer_boundary_checks`·`check_plan` 의 한 줄. `continuity_kind` 는 큐가 쓰므로 함께 되돌린다(`scene_boundary` 를 옛 `REF.match` 로).
- 공급자: `providers/video.py` 의 `build_omni_request`·`parse_omni_response` 를 옛 모양으로 — 하지만 옛 모양은 **문서와 다르다**는 것이 이번에 확인됐으니 되돌릴 이유가 없다. 사전 검증만 끄려면 `DRINKS_EXPLAINER_OMNI_PREFLIGHT_ENABLED=false`.
- 스크립트: `scripts/explainer_stages.py`·`explainer_s05.py`·`explainer_s2.py`·`explainer_s3.py` 와 `docs/drinks-pilot/whisky-spoil-explainer-dryrun.json` 을 지운다. 다른 코드가 부르지 않는다.
- config: 파일 끝 "설명형 2단계" 절.

## 재현(0원)

```bash
python -m scripts.explainer_s05                               # docs/preview-<날짜>/explainer-s05/{directive.json,source_table.md,prompt_*.txt,report.json}
python -m scripts.explainer_s2                                # .../explainer-s2/{report.json,directive_table.txt}
python -m scripts.explainer_s3 --s2-spent 2.21 --selected 1,2 # .../explainer-s3/{report.json,directive_table.txt}
python -m pytest tests/test_drinks_explainer_stage2.py tests/test_drinks_explainer_queue.py -q
```
