# 런타임 경로 탐색 결과 (지시서 §1)

경로를 추측하지 않고 실제 grep 으로 확인한 결과다. 일회성 검증용 기록이며 프로덕션 코드는 읽기만 했다.

---

## ★ 핵심 확인: 레퍼런스 이미지 입력 지원 여부 → **아니오**

현재 이미지 생성 호출은 **텍스트 프롬프트 전용**이다.

`engine/providers/image.py:36-41`
```python
def _image_request_body(cut, header) -> dict:
    return {
        "contents": [{"parts": [{"text": _build_image_prompt(cut, header)}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
```

`parts` 에 `text` 하나만 넣는다. 레퍼런스를 넘기려면 같은 `parts` 배열에 `inline_data`(base64 이미지)
파트를 추가해야 하는데 그 경로가 없다. 실시간 호출(`_gemini_image`, `image.py:60`)과 Batch 호출
(`build_batch_requests`, `image.py:137`)이 **둘 다 이 함수 하나를 공유**하므로 양쪽 모두 미지원이다.

`inline_data` 라는 문자열이 `image.py:48` 에도 있지만 그건 **응답 파싱**(생성된 이미지를 꺼내는 쪽)이다.
입력이 아니다.

→ 지시서 §6 에 따라 **프롬프트 접두사 고정 방식**으로 전환해야 한다.

---

## 파일별 위치

| 대상 | 위치 | 비고 |
|---|---|---|
| 이미지 생성 진입점 | `engine/providers/image.py:108` `generate_image(cut, header, out_path) -> (path, cost)` | provider 분기: placeholder / gemini / higgsfield(미구현) |
| 실제 Gemini 호출 | `engine/providers/image.py:60` `_gemini_image` | `{GEMINI_BASE}/{IMAGE_MODEL}:generateContent`, 재시도·레이트리밋 포함 |
| 프롬프트 조립 | `engine/providers/image.py:25` `_build_image_prompt` | `header.global_style` + `cut.visual_prompt` + 9:16 + burn-in negative |
| 이미지 요청 바디 | `engine/providers/image.py:36` `_image_request_body` | **레퍼런스 입력 없음(위 참조)** |
| 이미지 Batch | `engine/providers/image.py:137` `build_batch_requests` / `155` `submit_batch` / `171` `poll_batch` | 같은 요청 바디 공유 |
| 영상 클립(Veo) | `engine/providers/video.py:70` `_veo_i2v` | I2V, **start_image 필수** — 컷 스틸을 첫 프레임으로 넣는 구조가 이미 있음 |
| 클립 길이 티어 | `engine/providers/video.py:35` `pick_clip_tier` | `VEO_CLIP_MAX_TIER_SEC` 상한 |
| TTS | `engine/providers/tts.py:86` `synthesize(cut, out_path, lang)` | provider 분기 동일 패턴 |
| 렌더 조립 | `engine/assemble.py:422` `assemble` / `435` `assemble_full` | **ffmpeg 외부 바이너리 의존** |
| 로컬 렌더 진입점 | `engine/render.py:398` `render_directive_local(directive, out_path, ...)` | DB 없이 지시서 dict 로 렌더 — 이번 샘플에 가장 적합 |
| 지시서 정규화 | `engine/directive.py:694` `normalize_directive` | |
| 컷 길이 상수 | `engine/config.py:243-244` `CUT_MIN_SEC=3`, `CUT_MAX_SEC=8` | |
| 씬 종류 | `engine/config.py:688` `SCENE_KINDS` | |
| 에셋 경로 규칙 | `engine/render.py:164` `{directive_id}/assets/cut_{n}.png`, `:231` `.mp4` | Supabase Storage 기준 |

---

## 실행 환경 점검 (지시서에 없지만 착수 전 필수)

| 항목 | 상태 | 영향 |
|---|---|---|
| `GEMINI_API_KEY` | **없음** | 레퍼런스 2장·컷 8장·Veo 클립 생성 전부 불가 |
| `SUPABASE_SERVICE_KEY` / `ANON_KEY` | **없음** (`SUPABASE_URL` 만 있음) | §2 의 기존 화성 지시서·mp4·컷 이미지를 `before/` 로 가져올 수 없음 |
| `ANTHROPIC_API_KEY` | 없음 | 이번 작업엔 불필요(대본 재생성 안 함) |
| `ffmpeg` / `ffprobe` | **없음** (`which` 종료코드 1) | §3-5 최종 mp4 조립 불가 |
| `IMAGE_PROVIDER` | `placeholder` | 단색 PNG + ASCII 라벨만 생성됨 |
| `VIDEO_PROVIDER` | `placeholder` | |
| `TTS_PROVIDER` | `placeholder` | |
| 로컬 렌더 산출물 | 없음 (`*.mp4`/`*.png` 0건) | `before/` 를 로컬에서 채울 방법 없음 |

이 세 가지(생성 키·Storage 접근·ffmpeg)가 모두 없어서 **이 환경에서는 샘플 영상을 만들 수 없다.**
지시서 §0-5("막히면 우회하지 말고 멈추고 보고한다")에 따라 여기서 멈추고 보고한다.

placeholder 로 8컷을 뽑는 것은 기술적으로 가능하지만 단색 배경에 ASCII 라벨이라
§7 판정("컷이 넘어갈 때 끊긴다는 느낌이 줄었는가")에 아무 답도 주지 못한다. 우회로 판단해 하지 않았다.
