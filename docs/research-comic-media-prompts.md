# 연구 노트 — 만화식(comic)에 최적화된 장면 미디어 프롬프트

> 상태: **적용됨(옵션 A).** 초안 단계 image_prompt 의 art style 규칙을 만화식(웹툰) 화풍으로 통일하도록
> `engine/scriptgen.py` `SCRIPT_SYSTEM` 과 `supabase/functions/generate-draft/index.ts` 에 반영했다(이중 관리 동기화).
> 아래는 결정 근거·대안·검증 방법 기록. video_prompt 는 "만화 그림을 그대로 애니메이션(화풍 유지)" 제약을 추가했다.

## 1. 문제 (운영자 관찰)

숏츠는 전부 **만화식(comic)** 으로 렌더한다. 그런데 초안검수 화면의 **장면별 이미지 프롬프트가 "이미지 나열식"에 최적화**된 형태로 나온다 — 사실적/3D 모션그래픽 톤이라 만화 화풍과 어긋난다. 만화식에 맞는 미디어 프롬프트가 필요하다.

## 2. 진단 (코드 근거)

파이프라인은 **두 단계**에서 시각 프롬프트를 만든다.

### (a) 초안 단계 — 스타일 무관하게 생성
- 위치: `engine/scriptgen.py:54-66`(image_prompt 규칙), `:67-78`(video_prompt 규칙). 클라우드 미러: `supabase/functions/generate-draft/index.ts:87-98`, `:100-111`.
- 규칙 7) art style/medium 이 콘텐츠에 따라 갈린다: **데이터·개념 장면 → "sleek 3D motion graphics / data visualization", 일상·현실 장면 → "photorealistic cinematic still".**
- 즉 초안 단계는 **만화/이미지나열 어느 버전도 모른다.** 화풍은 콘텐츠 성격으로만 결정된다. → 만화식과 근본적으로 어긋나는 지점.
- 저장: `drafts.video_prompts`(scenes 배열). 초안검수 화면(`web/components/ReviewClient.tsx`)이 이 프롬프트를 그대로 노출·복사 제공한다.

### (b) 지시서 단계 — 여기서만 만화 화풍 적용
- 위치: `engine/directive.py:112-121` `VERSION_GUIDANCE["comic"]`.
- comic 은 **global_style 앵커**(예: `flat modern webtoon style, bold clean ink outlines, soft cel shading, muted pastel palette, consistent character design`)를 고정하고, **모든 컷 visual_prompt 가 그 앵커로 시작**하도록 강제한다.
- 정규화(`normalize_directive`, `engine/directive.py:265-319`)가 `visual_type=comic_panel` 강제.
- 저장: `directives.cuts`. 실제 렌더는 이 컷의 `visual_prompt` 를 쓴다.

### 핵심
- **렌더 입력은 (b) 지시서의 컷 프롬프트다.** 초안 (a)의 image_prompt 는 지시서 생성 시 "기존 장면 초안(scenes)"으로 참고만 되고(`directive.py:131-144` `directive_user_prompt`), 만화 화풍은 (b)에서 덧입혀진다.
- 따라서 **운영자가 초안검수에서 보는 장면 프롬프트가 비-만화톤인 것은 "표시상"의 불일치**가 크다. 최종 렌더 화풍은 지시서 comic 가이드가 잡는다. 다만: ① 운영자가 초안 프롬프트를 복사해 외부 툴로 직접 이미지를 뽑는 워크플로에선 톤이 어긋나고, ② 지시서가 초안 프롬프트의 "사실적 스타일" 서술을 일부 계승하면 화풍이 흔들릴 수 있다.

## 3. 개선안 (택1 또는 조합)

### 옵션 A — 초안 장면 프롬프트를 만화 화풍으로 재작성
- `SCRIPT_SYSTEM` image_prompt 규칙 7)을 만화 앵커 기반으로 교체(webtoon/comic panel, ink outline, cel shading, consistent character design).
- 장점: 초안검수 화면·복사 프롬프트가 처음부터 만화톤 → 운영자 체감 일치. 지시서 계승도 일관.
- 단점: 이미지 나열식(엔진 하위호환)과 공유되는 초안이 만화 전용이 됨. 데이터 시각화 장면의 표현력 저하 가능. 이중 관리 프롬프트 2곳(`scriptgen.py`·edge) 동시 수정.

### 옵션 B — 초안은 화풍 무관 유지, 지시서 comic 가이드 강화
- (a)는 그대로 두고, `VERSION_GUIDANCE["comic"]` 를 더 구체화(인물 시트/표정/컷 구성/말풍선 배제 등) + 초안 프롬프트의 사실톤 서술을 **명시적으로 덮어쓰라**는 지시 추가.
- 장점: 최소 변경, 하위호환 유지, 렌더 화풍 개선에 집중.
- 단점: 초안검수 화면의 표시 프롬프트는 여전히 비-만화톤(운영자 체감 불일치는 남음).

### 옵션 C — 초안에 comic 전용 프롬프트 필드 분리
- scenes 에 `image_prompt_comic`(또는 버전별 맵) 필드 추가, 초안검수에서 만화톤 프롬프트를 별도 노출.
- 장점: 버전별 최적 프롬프트 병존, 표시·렌더 모두 정합.
- 단점: 스키마·정규화·UI·이중관리 모두 확장 → 비용 큼. 현재 comic 단일 운영이라 과설계 위험.

**잠정 추천:** comic 단일 운영이 확정된 현재 상황에선 **옵션 A**(초안 프롬프트 자체를 만화톤으로) 가 운영자 체감·렌더 일관성 모두를 잡아 가장 단순하다. 데이터 장면 표현력은 만화 내 "인포그래픽 패널" 서술로 흡수 가능한지 검증 필요.

## 4. 검증 방법 (PR 전 필수)

1. **프롬프트 A/B**: 동일 Fact Sheet 1편으로 before(현재)/after(옵션 A) 초안을 생성, 장면 image_prompt 를 이미지 생성기(Imagen/Flux 등)에 넣어 **화풍 일관성·인물 디자인 유지·컷 간 톤 통일**을 나란히 비교.
2. **엔드투엔드 렌더 샘플**: 같은 논문으로 comic 지시서 → 렌더 mp4 를 before/after 로 뽑아 실제 최종 결과 화풍을 대조(초안 프롬프트 변경이 지시서 계승을 통해 최종에 어떻게 반영되는지).
3. **환각 불변식 회귀**: image/video 프롬프트는 자기검증 대상이 아니지만, 프롬프트가 Fact Sheet 밖 구체 수치/객체를 지어내지 않는지 수동 점검(`no on-screen text` 등 기존 제약 유지).
4. **이중 관리 동기화**: `engine/scriptgen.py` ↔ `supabase/functions/generate-draft/index.ts` 프롬프트 문자열 diff 0 확인.

## 5. 적용 내역 (옵션 A)
- `SCRIPT_SYSTEM` image_prompt 규칙 7)을 사진/3D 분기에서 **웹툰 화풍 앵커 통일**로 교체
  (`modern Korean webtoon/comic style, bold clean ink outlines, soft cel shading, flat muted pastel palette,
  consistent character design`). 데이터 장면은 "만화 인포그래픽 패널"로.
- video_prompt 공통 제약에 "만화 그림을 그대로 애니메이션(실사·3D화 금지, 화풍 유지)" 추가.
- 두 곳(engine·edge) 동기화. 스키마 변경 없음.
- 남은 검증(운영): §4의 A/B·엔드투엔드 렌더 샘플로 화풍 일관성 실측 필요. image_sequence(UI 미사용, 엔진 잔존)는
  초안 프롬프트가 웹툰톤이 되지만 지시서 단계 가이드가 사실톤으로 덮으므로 실사용 경로(comic)에는 영향 없음.
