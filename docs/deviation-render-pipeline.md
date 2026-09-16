# 범위 이탈 기록: 논문→영상화 반자동 파이프라인 (P-V0~P-V1)

> CLAUDE.md 작업 규칙 6 — "명세/리뷰와 충돌하는 구현 결정이 생기면 임의로 진행하지 말고
> `docs/`를 갱신하며 근거를 남긴다." 에 따른 기록.
> 원본 명세: `docs/개발명세서_하루한편_대본to영상화_PV0PV1.md`(업로드본).

## 무엇이 추가되나
기존 `④ 초안(drafts)`에서 출발해 **대본 → 버전별 컷 지시서(자동) → 사람 승인(게이트) → mp4 렌더(자동)**까지
잇는 반자동 영상화 층을 추가한다. 두 페이즈로 분리 측정한다.

- **P-V0 (지시서):** 대본 → 버전 선택(만화/이미지나열/애니) → 컷별 제작 지시서 생성 → 대시보드 검수·승인.
- **P-V1 (렌더):** 승인된 지시서 → 에셋·TTS·조립 → mp4.

## CLAUDE.md 범위와의 충돌
CLAUDE.md 범위는 "영상 자동 렌더링, TTS, cron 무인 실행/클라우드 엔진 배포"를 **P2 이후로 명시적 제외**한다.
본 파이프라인은 이 경계를 넘는다(렌더·TTS). 기존 이탈(`deviation-cloud-draft.md`, `deviation-scheduled-collect.md`)과
동일하게 사용자 승인 하에 진행하며 근거를 여기 남긴다.

## 확정 결정 (DV1~DV6)
- **DV1 렌더 실행 위치 = GitHub Actions 러너.** 클라우드 층(Supabase Edge=Deno·ffmpeg 없음, Vercel 서버리스=실행시간/번들
  제한)에서는 mp4 렌더가 불가능하다. 장시간 실행 워커가 필요하므로 `.github/workflows/render.yml`(`workflow_dispatch`)에서
  `python -m engine.render`가 `render_jobs` 큐를 소비한다. 로컬 `python -m engine.render` 병행 가능.
- **DV2 지시서 생성 위치 = 클라우드 엣지 함수 + 파이썬 소스오브트루스.** 지시서 생성은 순수 LLM/JSON(ffmpeg 불필요)이라
  `generate-draft`와 동일하게 엣지 함수로 즉시 피드백. 정규화 로직은 테스트 가능한 `engine/directive.py`가 원본이고
  `supabase/functions/generate-directive/index.ts`가 이를 포팅한다(→ 이중관리 지점, 아래 참조).
- **DV3 첫 에셋·음성 제공자 = 무료 우선.** 이미지=Gemini(nano banana), TTS=Edge TTS. 제공자를 인터페이스 뒤에 두고
  (엔진의 `llm.py` 모델 라우팅과 동일 발상) 교체 가능하게 한다. 이번 라운드(P-V0)는 `placeholder` 기본.
- **DV4 EN 나레이션 = 자막/텍스트로만.** P-V1 음성 트랙은 KO만. EN 나레이션은 지시서에 보존하되 별도 렌더하지 않는다(렌더 2배 비용 회피).
  - **★ DV4 는 DV11(규격 v2)로 대체됨** — 사용자 요구(한/영 두 버전 동시 운영)에 따라 EN 을 자막만이 아니라 **별도 음성·자막·조립으로 완전 이중언어 렌더**한다. 아래 "규격 v2 개정" 참조.
- **DV5 애니(v3) 엔진 = 파라미터화된 씬 템플릿.** LLM이 자유 형식 Manim 코드를 생성하면 컴파일 실패·레이아웃 붕괴가 잦다.
  미리 짜둔 씬 템플릿(타이틀카드/화살표-흐름/단계 등장/수치 비교)에 값만 채운다. P-V1(M-V6).
- **DV6 총길이 예산 = config.** `TARGET_TOTAL_SEC`(기본 50, 40~60 범위), 컷당 3~8초. 컷 수는 총길이에서 유도.

## 라운드 범위
- **P-V0(완료):** DB 확장 + 버전별 지시서 생성(엣지+엔진) + 대시보드 ⑤/⑥ + 렌더 워커 스켈레톤(플레이스홀더로 버전2가 실제 mp4까지 관통).
- **M-V5 무료 경로(완료):** 자막 싱크(ASS, 단어 타임스탬프/컷 단위) + 한글 자막 번인(libass, 세이프에어리어) + BGM 더킹(sidechaincompress+loudnorm) + **Edge TTS**(무료, 단어 타임스탬프). 실증: 한글 자막이 하단 세이프에어리어에 렌더된 실제 mp4.
- **M-V6 버전3 애니(완료):** 자유 Manim 코드 금지 → **파라미터 씬 템플릿 4종**(타이틀/화살표흐름/단계등장/수치비교, `engine/manim_templates.py`). 무료·결정론적·LaTeX 불요(Text/pango). `select_template` 이 컷의 visual_prompt 키워드로 템플릿을 고르고, Manim 이 무음 클립을 렌더 → 나레이션·자막·BGM 후단 조립. 실증: "입력→처리→출력" 도해 + 한글 자막이 렌더된 실제 mp4.
- **잔여(P-V1, 키/라이선스 필요):** Gemini(nano banana) 이미지 배선, ElevenLabs, 상업 라이선스 BGM 라이브러리(현재는 사인 톤 플레이스홀더), 버전1 만화 화풍 일관성(레퍼런스+seed), 예산캡·해시 캐시 멱등 마무리.

### M-V6 기술 메모(Manim)
LLM 자유 코드 대신 **파라미터 템플릿**만 렌더한다(컴파일 안정·결정론). `Tex/MathTex/DecimalNumber` 는 LaTeX
의존이라 금지하고 숫자도 `Text(str(n))` 로 쓴다(러너에 LaTeX 없음). manim 빌드에 `libcairo2-dev·libpango1.0-dev`,
한글 렌더에 `fonts-nanum` 필요(러너 apt). `manim_templates` 상단(select_template)은 순수 로직이라 manim 미설치
환경에서도 import·테스트되고, 실제 렌더만 지연 import 한다. 애니 렌더 실패 시 컷은 placeholder 스틸로 폴백(전체 중단 금지).

### M-V5 기술 메모(자막)
자막은 **ASS 파일에 `PlayResX/Y`를 렌더 해상도로 명시**해 번인한다. SRT+`force_style` 은 libass 가
기본 PlayResY=288 좌표계로 스케일해 폰트 크기·MarginV 가 어긋나(자막이 화면 밖으로 밀림) 못 쓴다.
한글 렌더는 `fonts-nanum`(러너 apt) 필요. Edge TTS 는 Microsoft 공개 wss 엔드포인트에 붙으므로 TLS
가로채기 프록시 환경에선 막힐 수 있으나 GitHub Actions/일반 네트워크에선 정상이다.

## 규격 v2 개정 (DV7~DV11) — 정식 규격서 `docs/규격서_숏폼_v2.md`
> 사용자 요구: "숏폼 영상을 더 세밀히 규격화·업그레이드 + 한/영 두 버전 동시 운영." 업로드 규격서(v2)를
> 반영한다. 값(CPS·더킹 dB·플랫폼 오프셋)은 실측 A/B 보정 대상 → 전부 `engine/config.py` 상수.

- **DV7 자막 최소노출 = 청킹 단계 레이트 강제(2초 고정 폐기).** 오디오 싱크는 불가침(오디오를 지연시키지
  않는다). 가독 요구시간 `R=글자수/target_CPS`, 자연 표시창 `W`. Fallback 트리: W>=R 그대로 → 간극 있으면
  tail_hold(≤0.5s) 연장 → 그래도 부족하면 청크 어절 수 축소 → 하드 플로어 0.7s 미만이면 인접 청크 병합.
  `subtitles.chunk_by_rate()`. target_CPS 시작값 KO 11 / EN 20(`CAPTION_TARGET_CPS`).
- **DV8 플랫폼별 자막 오프셋 = 분리 레이어.** 비주얼·오디오 마스터 1개, 자막 레이어만 플랫폼별 앵커%로
  y-오프셋(MarginV) 재합성. 마스터는 가장 빡빡한 TikTok. `subtitles.build_ass(platform=)`,
  `PLATFORM_CAPTION_ANCHOR_PCT`. 산출물 = (언어 × 플랫폼). platform 미전달 시 기존 동작 유지(하위호환).
- **DV9 시각 다양성 래더 = scene_kind enum + 강제 제약.** 컷마다 `scene_kind`(comic_panel/motion_graphic/
  kinetic_typography/data_viz/broll_stock). 같은 kind 3연속 금지(정규화가 제자리 교정), 고효율 씬(코드 기반)
  10초당 1회 권장. **렌더 매핑: 고효율 kind → 기존 Manim 템플릿 클립, 그 외 → 스틸**(신규 렌더러 없이 다양성
  확보). `directive.enforce_scene_variety()`, `render.render_kind_for_scene()`. `visual_type`(버전 강제)은
  레거시 호환으로 병행 유지.
- **DV10 더킹 = 사전계산 엔벨로프(펌핑 방지).** 실시간 sidechaincompress 대신 VO 스팬을 간극<800ms 병합해
  결정론적 볼륨 엔벨로프(-20dB, attack 8/release 300ms)를 BGM 에 적용. `assemble.duck_spans_from_words()`,
  `build_bgm_envelope_duck_command()`. `DUCK_METHOD` 로 사이드체인 폴백 선택 가능.
- **DV11 완전 이중언어(DV4 대체).** 언어 무관 에셋 로직 공유, **(b)TTS·(c)자막·(d)조립은 언어별 2회**(탄력
  섹션 — 언어별 독립 재타이밍). 언어별 Edge TTS 보이스(`EDGE_TTS_VOICE_BY_LANG`)·자막 폰트(`CAPTION_FONT`)·
  훅/CTA 트랜스크리에이션(`hook_ko/en`,`cta_ko/en`). `render.render_directive_local(lang=)`,
  `render_all_languages()`, `tts.synthesize(lang=)`.
  - **주의(코드 기반 클립 텍스트):** kinetic_typography/data_viz 등 Manim 클립은 화면에 텍스트를 굽는다.
    "에셋 공유"라도 이 클립은 **언어별로 재렌더**한다(narration_{lang} 텍스트를 얹으므로). 값비싼 이미지
    생성(comic/broll)만 진짜 언어 무관 공유 대상. Manim 은 무료·결정론적이라 재렌더 비용이 무시할 만하다.
  - **큐 확장(완료):** `render_jobs.lang`(0012 마이그레이션, 기본 'ko') 추가. 지시서 승인 시 대시보드에서
    언어(한국어/영어/둘 다)를 골라 언어별 렌더 잡을 발주한다(`directive-approve` 가 언어별로 큐 적재,
    `(directive, lang)` 단위 중복 방지). 워커(`claim_render_jobs`→`process_job(lang)`)가 잡의 lang 으로
    렌더하고 Storage 경로에 `_{lang}` 접미사. ⑥ 렌더 결과 목록은 잡별 언어 뱃지(KO/EN) 표시.

- **DV12 화면 레이아웃 = 중앙 밴드 레터박스(기본).** 2026 숏폼 트렌드(콘텐츠를 중앙 밴드에 넣고 상하
  검정 바)를 반영해 `LAYOUT_MODE=center_band` 기본. 콘텐츠 밴드 1080×1200(상단 오프셋 220, 하단 바 500),
  `assemble.effect_filter`/`build_clip_cut_command` 가 밴드 렌더 후 pad. `full_bleed` 로 되돌릴 수 있음.
  자막은 콘텐츠 하단(플랫폼 앵커)에 유지.
- **① 자막 청킹 실렌더 수정(후속).** 한국어 edge-tts WordBoundary 가 성기게(구/문장 단위) 오거나 비어
  컷 통짜 자막이 되던 문제 → `subtitles._split_word_events`(성긴 이벤트를 어절로 재분할·시간 비례 배분) +
  `chunk_text_by_rate`(워드 없을 때 나레이션 문자열을 어절 청킹)로 교정. 렌더러의 컷 폴백도 통짜 대신 청킹.
- **재발방지(배포 표면).** 원인 = "머지=반영"이 성립 안 하는 표면(엣지 함수)을 사람이 잊음. `deploy-edge.yml`
  (main 머지 시 엣지 함수 자동배포) + `docs/deploy-surfaces.md`(4개 표면·체크리스트) 추가.

- **출처 구체화 + 발행 캡션(후속).** "한 연구" 추상 표현 문제 → OpenAlex authorships 에서 소속기관
  캡처(`sources/openalex._authors`) + Fact Sheet에 검증가능 `source` 블록 부착(`engine/attribution.build_source`,
  generate-draft `buildSource`) + 대본/지시서 프롬프트에 "source의 기관/게재처/저자로 구체화, 없는 건
  지어내지 말 것" 규칙. 대본은 여전히 "Fact Sheet만" 입력이라 환각 방지 불변식 유지(source가 Fact Sheet 안).
  숏츠 발행 캡션(설명란)은 `attribution.build_publish_caption`/`web/lib/publishCaption.ts`(결정론)로 구성,
  검수 화면에 KO/EN 복사 버튼. 이중관리 지점(engine ↔ generate-draft ↔ web).

## 트레이드오프 / 유지보수 주의
- **이중 관리(신규):** 지시서 생성 프롬프트·정규화·모델 ID 가 Python(`engine/directive.py`)과 TS(Edge Function)에
  양쪽 존재한다. `generate-draft`와 같은 성격의 동기화 지점이며 Edge Function 상단 주석에 명시한다.
- **제공자 추상화:** 이미지/영상/TTS 는 `engine/providers/`에서 `placeholder`|실제 구현으로 라우팅. 키 없이도 조립·싱크·자막·BGM
  로직을 완성·테스트한다. 첫 실배선은 무료(Gemini 이미지 + Edge TTS, P-V1).
- **환각 방지 불변식 보존:** 지시서 입력은 대본+Fact Sheet 만, 각 컷 `source_facts` 근거, 근거 없는 컷은 승인 화면에 빨간 표시.
  effects/transition/bgm_cue 는 config enum 만(자유 텍스트 금지, 미지원 토큰은 드롭+로그).
- **최초의 Storage 사용:** 렌더 mp4·에셋은 용량이 커서 Supabase Storage `renders` 버킷에 두고 DB엔 URL만 저장한다.
  저장소가 지금까지 메타데이터만 저장했으므로(“PDF 미저장, 링크만”) 버킷 생성은 이번이 최초다.
- **범위 유지:** 수집·채점·초안은 그대로. 자동 발행(YouTube/IG)은 여전히 P-V2 이후로 제외.

## 합격기준 (명세 §10, 분리 측정)
- **P-V0:** 3버전 각각에서 대본 1편→지시서가 JSON 스키마 오류 0 으로 생성 · source_facts 빠진 컷이 승인 화면에 실제 빨간 표시 ·
  사람 ≤15분 검수로 승인 가능(컷 편집 포함).
- **P-V1:** 승인 지시서→사람 개입 없이 mp4 산출 · 나레이션-자막-컷 길이 싱크 어긋남 없음 · 편당 실비용 ≤ 예산 캡 ·
  실패 컷은 전체 중단 없이 플레이스홀더 · 3버전 각 1편 "컨셉이 보이는" 수준.

## 운영 선행조건 (P-V1 실렌더 시)
1. Storage 버킷 `renders` 생성(마이그레이션 0009 에 포함).
2. `supabase functions deploy generate-directive` + (Anthropic 쓰면) `supabase secrets set ANTHROPIC_API_KEY=…`.
3. GitHub Actions Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, (P-V1) `GEMINI_API_KEY`.
