# 수정명세서 — 하루한편 ① editorial 앵커 교정 ② 언어 추가 렌더 ③ 클립·나레이션 길이 보정 (v1)

- 상태: draft (GitHub 커밋 후 frozen)
- 대상: video-article 기존 코드베이스 (Python 엔진 + Supabase Edge Function + Next.js)
- 선행 문서: `수정명세서_하루한편_표현방식B1도입_v3.1_리뷰반영.md` / `개발명세서_대본to영상_반자동파이프라인_PV0-PV1.md` / `수정지시서_하루한편_훅리텐션_파이프라인개정_v2.md`
- 작성 기준일: 2026.07.26

---

## 0. 결론 (두괄식)

**세 건을 하나의 PR 묶음으로 처리한다. 우선순위는 ③ > ② > ①이다.**

| # | 항목 | 판정 | 우선순위 |
|---|---|---|---|
| ③ | 클립 길이 ↔ 나레이션 길이 불일치 보정 | **즉시** — 모든 버전(comic/editorial) 공통 품질 결손. 실험 아님 | **P0** |
| ② | 언어 추가 렌더 (렌더 결과 화면에서 타 언어 생성) | 수용 — 기존 `render_assets` 캐시 재사용으로 비용 ≈ TTS만 | **P0** |
| ① | editorial 앵커 교정 + 생성 이미지 컷 제한 | 조건부 — §5 viz_template 구현 진단 통과가 선행 | **P1** |

**① 관련 판정:** editorial 노선은 폐기하지 않는다. 현 결과물(1~2편)은 `viz_template` 결손 상태의 산출물로 판단되며, 이는 노선 판정 근거가 되지 않는다(`v2 §9` 표본 규칙: 5편=오류탐지 / 10편=방향성). 단 **"잡지형 에디토리얼" 앵커는 폐기**한다 — 저널리즘 미학은 논문의 시각 언어가 아니다.

**운영 조치(코드 무관, 즉시):** editorial 신규 지시서 생성·발행 정지. `version_type` enum에서 `editorial` 제거 금지(롤백 여지 유지).

---

## 1. 런타임 탐색 (구현 전 필수 — 경로를 추정하지 말 것)

Claude Code는 코드 수정 전 아래를 확정하고 결과를 PR 본문에 기록한다.

```bash
# [A] editorial 구현 진단 (①의 선행 조건)
ls engine/viz_templates/
grep -rn "viz_template\|viz_params\|asset_source" engine/directive.py engine/render*.py engine/assemble*
grep -rn "overlay_plan" engine/ web/ supabase/functions/
grep -rn "VERSION_GUIDANCE" engine/ supabase/functions/generate-directive/

# [B] 렌더 잡 · 언어 처리 현황 (②)
grep -rn "def process_job\|lang\b" engine/render.py
grep -rn "render_assets" engine/ web/app/api/
psql> \d render_jobs        # lang / source_job_id / reuse_assets 컬럼 존재 여부
psql> \d render_assets      # (directive_id, cut_no, asset_type) 유니크 제약 여부

# [C] 에셋 생성 ↔ TTS 실행 순서 (③의 근본 원인)
grep -rn "_render_cut_clips" engine/render.py
#   → 이 함수 안에서 이미지/클립 생성과 TTS 중 무엇이 먼저 실행되는가를 라인 번호로 보고
grep -rn "estimated_sec\|duration\|tpad\|setpts\|-t " engine/assemble*.py engine/providers/video.py
```

**보고 형식:** [A] 5항목을 `구현됨 / 부분 / 미구현`으로 판정 + 근거 경로·라인. [C]는 현재 실행 순서를 의사코드 3~5줄로 요약.

---

## Part ③ — 클립 길이 ↔ 나레이션 길이 불일치 (P0)

### 3-1. 원인 진단

두 개가 겹친 문제다.

1. **고정 티어 vs 가변 실측:** 생성 영상(Veo 등)은 4s/6s/8s 같은 고정 길이 티어로만 나온다. 나레이션 길이는 TTS 실측이라 3.2s, 7.8s처럼 임의값이다. 원리적으로 딱 맞을 수 없다.
2. **실행 순서(추정, 탐색으로 확정):** 에셋을 먼저 생성하고 TTS를 나중에 돌리면, 클립 길이를 정할 시점에 정답(나레이션 길이)을 모른다. 구조적으로 어긋난다.

### 3-2. 구조적 해결 — 순서 역전 (P0)

`_render_cut_clips` 내부 순서를 **TTS 우선**으로 바꾼다.

```
[변경 전(추정)]  컷별 에셋 생성 → TTS → 조립 (에셋 길이가 먼저 굳는다)
[변경 후]        컷별 TTS → 컷 실측 길이 확정 → 에셋 생성(길이 티어 선택) → 조립
```

- video 컷의 클립 길이 티어 선택 규칙: `narration_sec` 이상인 **최소 티어**를 요청한다.
  예) 나레이션 5.3s → 6s 티어 요청 (4s 티어 + 늘리기보다 항상 우선)
- 티어 목록은 하드코딩하지 말고 `engine/providers/video.py`의 상수로 노출한다(모델 교체 대비).
- TTS는 실패해도 비용이 작고 재시도가 싸다. 유료 영상 생성을 뒤로 미루는 것이 비용 측면에서도 유리하다.

> 이 변경만으로 대부분의 케이스가 사라진다. 아래 3-3은 그럼에도 남는 갭의 보정 규칙이다.

### 3-3. 잔여 갭 보정 — 결정론적 규칙 (P0)

컷별로 `deficit = narration_sec - clip_sec`, `ratio = deficit / narration_sec` 를 계산해 **아래 표대로만** 처리한다. 자유 판단 금지.

| ratio | 전략 | 구현 | 근거 |
|---|---|---|---|
| `ratio ≤ 0` (클립이 더 김) | **트림** | 뒤에서 잘라내고 마지막 0.2s 페이드아웃 | 나레이션이 타임라인의 주인 |
| `0 < ratio ≤ 0.15` | **마지막 프레임 홀드 + 켄번스** | 정지 프레임을 늘리고 zoom 1.00→1.04 서서히 | 가장 무해. 시청자가 알아채지 못함 |
| `0.15 < ratio ≤ 0.60` | **핑퐁 루프** (정방향→역방향) | 아래 3-4 참조 | 이음새가 없어 단순 반복보다 우월 |
| `ratio > 0.60` | **보정 금지 · QA 빨간 플래그** | 승인 UI에 경고 + 컷 분할 권고 | 4s 클립에 12s 나레이션은 연출 실패다. 렌더로 가릴 문제가 아님 |

**금지 사항:**
- **속도 늘리기(`setpts`) 금지.** 0.9배 미만으로 늘리면 움직임이 뚝뚝 끊긴다. 프레임 보간(`minterpolate`)은 렌더 시간이 폭증한다.
- **단순 반복(head-to-tail loop) 금지.** 마지막 프레임과 첫 프레임이 튀어 이음새가 보인다. 핑퐁으로 대체.

### 3-4. `loop_safe` 플래그 신설 (지시서 스키마)

핑퐁 루프는 역재생이 어색한 모션에서 티가 난다(단방향 흐름, 인물 보행, 텍스트/요소 등장). 따라서 컷 단위로 허용 여부를 지시서가 선언한다.

```json
{ "loop_safe": true }
```

- 위치: `directive.cuts[]`, `motion_prompt` 옆.
- 기본값: `false` (안전측). 즉 미지정 컷은 홀드 전략으로 강제된다.
- 지시서 프롬프트 규칙(1줄 추가): *"카메라가 천천히 움직이거나 분위기만 담는 컷은 `loop_safe: true`. 인물의 걷기·물의 흐름·요소의 등장처럼 방향이 있는 모션은 `loop_safe: false`."*
- `ratio > 0.15` 이고 `loop_safe: false` → 홀드 전략으로 폴백(핑퐁 금지).

### 3-5. ffmpeg 구현 참고

> **컴공 신입생용 주석:** ffmpeg의 `-vf`(비디오 필터)는 영상을 통과시키며 변형하는 파이프라인이다. `[a][b]` 같은 대괄호는 중간 결과물에 붙이는 이름표이고, `split`으로 스트림을 복제하고 `concat`으로 이어붙인다.

```bash
# (1) 마지막 프레임 홀드 — stop_mode=clone: 마지막 프레임을 복제해 N초 연장
ffmpeg -i in.mp4 -vf "tpad=stop_mode=clone:stop_duration=1.2" out.mp4

# (2) 핑퐁 루프 — 원본과 역재생본을 이어붙여 2배 길이 확보
ffmpeg -i in.mp4 -filter_complex \
  "[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]" -map "[v]" out.mp4
#   2배로도 부족하면 위 결과에 loop 필터를 추가 적용(짝수 배수라 이음새 유지)

# (3) 트림 + 페이드아웃 (목표 길이 N)
ffmpeg -i in.mp4 -t N -vf "fade=t=out:st=$(N-0.2):d=0.2" out.mp4
```

- 켄번스는 기존 조립 경로에 이미 존재하므로 **재구현 금지**. 홀드 구간에 기존 켄번스 함수를 재사용한다(탐색 [C]에서 함수명 확정).

### 3-6. 로깅 · QA 추가

렌더 로그에 컷별로 아래를 기록한다(전략 선택이 사후 검증 가능해야 한다).

```
cut_no, clip_sec, narration_sec, ratio, loop_safe, strategy(trim|hold|pingpong|flagged)
```

`render_qa` 추가 항목:
- [ ] `ratio > 0.60` 컷 존재 → 빨간 플래그 (승인 UI 경고, 렌더 차단은 아님)
- [ ] `strategy=pingpong` 컷 비중 > 50% → 노란 경고 (지시서 컷 설계 재검토 신호)

---

## Part ② — 언어 추가 렌더 (P0)

### 2-1. 요구사항

렌더 결과 화면(⑥)에서, 완료된 영상과 **동일한 에셋으로 다른 언어 버전을 추가 생성**한다.

### 2-2. 정직한 제약 — "완전히 동일한 영상"은 불가능

컷의 화면 시간 = 나레이션 실측 길이다(기존 설계). 언어가 바뀌면 나레이션 길이가 바뀌므로 타임라인이 달라진다. 한국어 52초 영상이 영어로는 47초가 될 수 있다. 두 가지 모드가 가능하다.

| 모드 | 내용 | 판정 |
|---|---|---|
| **MODE A `asset_reuse`** | 이미지·클립은 100% 재사용, TTS·자막·타임라인은 언어별 재계산. 총 길이 다름 | **P0 채택** |
| MODE B `timeline_lock` | KO 타임라인 고정, EN TTS를 `atempo` ±10% 내 조정, 초과분은 무음 패딩 | **백로그** |

MODE B 기각 근거: 숏폼에서 두 언어의 총 길이가 일치할 실익이 없고, 발화 속도 왜곡이라는 확정적 품질 손실을 감수해야 한다. 필요해지면 그때 추가한다.

> **중요:** MODE A에서도 Part ③의 길이 보정이 언어별로 다시 계산된다. 같은 클립이 KO에서는 홀드, EN에서는 트림이 될 수 있다. 이는 정상 동작이다.

### 2-3. 구현

**DB (탐색 [B] 결과에 따라 조정):**

```sql
alter table render_jobs add column if not exists lang text;              -- 'ko' | 'en'
alter table render_jobs add column if not exists source_job_id uuid references render_jobs(id);
alter table render_jobs add column if not exists reuse_assets boolean default false;
```

**에셋 재사용 규칙:**
- `reuse_assets=true` 인 잡은 `render_assets`에서 `(directive_id, cut_no, asset_type in ('image','clip'))`를 조회해 **그대로 사용**한다.
- 캐시 미스 컷만 생성한다. 미스가 1건 이상이면 로그에 남기고 승인 UI에 알린다(원본 렌더가 캐시를 안 남긴 경우 탐지용).
- `asset_type='audio'`(TTS)는 **재사용하지 않는다** — 언어가 다르므로 당연히 재생성.

**API:**
- `POST /api/render/add-language` — body: `{ source_job_id, lang }`
- 동작: 원본 잡 검증 → 새 `render_jobs`(같은 `directive_id`, 지정 `lang`, `reuse_assets=true`, `source_job_id`) 생성 → 렌더 트리거 → job_id 반환

**가드:**
- 원본 잡 `status != 'done'` → 버튼 비활성 (에셋 캐시가 불완전할 수 있음)
- 같은 `(directive_id, lang)` 조합에 `status='done'` 잡이 이미 존재 → "이미 존재합니다. 재생성하시겠습니까?" 확인 후 진행
- **비용 검증 (DoD 항목):** `reuse_assets=true` 잡의 이미지·영상 생성 API 호출 수 = **0**. `generation_attempts` 원장으로 확인. 0이 아니면 캐시 조회가 실패하고 있다는 뜻이다.

**UI (⑥ 렌더 결과 화면):**
- 현재 언어 배지 표시 + `[영어 버전 추가 생성]` / `[한국어 버전 추가 생성]` 버튼
- 같은 `directive_id`의 언어별 잡 목록을 나란히 표시 (각각 미리보기·다운로드)
- 진행 중이면 진행률 폴링 (기존 `/api/render/status` 재사용)

---

## Part ① — editorial 앵커 교정 (P1, 진단 통과 후)

**선행 조건:** 탐색 [A]에서 `viz_templates` 5종 + `overlay_plan` 배선이 `구현됨`으로 확인될 때만 착수. `미구현`/`부분`이면 먼저 `v3.1 §5·§6`을 완성하고, 그 비용을 보고한 뒤 노선 유지 여부를 별도 결정한다.

### 1-1. `global_style` 앵커 교체

잡지형 앵커를 폐기하고 **과학 도해형**으로 바꾼다.

```
[폐기] clean editorial magazine layout, high-contrast typography zones, ...
[신규] scientific figure aesthetic, dark neutral ground, structural gridlines and axes,
       single accent color reserved for the measured value, no decorative imagery,
       no people, no on-screen text
```

근거: 잡지 미학은 저널리즘의 시각 언어다. 논문 콘텐츠의 신뢰 신호는 계측·도해이며, 화면이 "잡지 같다"는 인상 자체가 소재와 불일치한다.

### 1-2. 생성 이미지 컷 상한 — `scene_role` 기반 강제

"뜬금없는 이미지"의 재발을 프롬프트 권고가 아니라 **정규화 단계 검증**으로 막는다.

| `scene_role` | 허용 asset |
|---|---|
| `COMPARE` / `SCALE` / `EVIDENCE` | **`viz_template` 필수.** 생성 이미지 금지 |
| `HERO` | `viz_template` 우선, 생성 이미지 허용 |
| `MECHANISM` / `IMPACT` / `CAVEAT` / `PAYOFF` | 생성 이미지 허용 |

- 추가 상한: editorial 지시서에서 생성 이미지 컷 비중 **≤ 40%**.
- 위반 시 `normalize_directive`가 **거부하고 1회 재생성 요청**한다(경고 배지가 아니라 하드 게이트). 근거: `v3.1 §6`의 "editorial인데 comic_panel 비중 > 30%" 게이트와 동일 사상.

### 1-3. 판정 재개 조건

위 교정 후 editorial **3편**을 렌더해 화면 QA만 통과시킨다(성과 판정 아님). 통과하면 `v2 §9` 규칙대로 10편까지 누적해 성과를 판정한다. 3편에서도 화면이 납득 안 되면 **그때 deprecated 마킹**한다(enum 제거는 하지 않음).

---

## 4. 파일 소유권 (무간섭)

| 경로 | 소유 | 내용 |
|---|---|---|
| `engine/render.py` | Claude Code | TTS 우선 순서 역전(§3-2), `reuse_assets` 분기(§2-3) |
| `engine/assemble*.py` | Claude Code | 길이 보정 전략 배선(§3-3) — 순수 함수 호출만 |
| `engine/clip_fit.py` (신규) | **Codex** | `decide_strategy(clip_sec, narration_sec, loop_safe) -> Strategy` 순수 함수 + 단위테스트 (I/O·ffmpeg 호출 금지) |
| `engine/clip_fit_types.py` (신규) | Claude Code | `Strategy` 타입 계약 (FREEZE) |
| `engine/providers/video.py` | Claude Code | 길이 티어 상수 노출(§3-2) |
| `engine/render_qa.py` | Claude Code | §3-6 QA 항목 |
| `engine/directive.py` (+TS 사본) | Claude Code | `loop_safe` 필드, §1-1 앵커, §1-2 검증 |
| `web/app/api/render/add-language/route.ts` | Claude Code | §2-3 API |
| `web/components/RenderResultClient.tsx` | Claude Code | §2-3 UI |
| `supabase/migrations/*` | Claude Code | §2-3 컬럼 |

**Codex 작업 경계:** `clip_fit.py`는 숫자 3개(+bool)를 받아 전략 enum과 파라미터를 반환하는 순수 함수다. ffmpeg 명령 생성·파일 접근을 넣지 않는다. 경계값 테스트 필수 — `ratio = 0, 0.15, 0.60` 정확히 걸릴 때의 동작을 명시적으로 고정한다.

---

## 5. 구현 순서

1. Claude Code: §1 런타임 탐색 → 결과 보고 → 계약(`clip_fit_types.py`, `Strategy`) 확정 후 커밋(freeze)
2. 병렬: Claude Code(순서 역전 · 조립 배선 · 언어 추가 렌더) / Codex(`clip_fit.py` + 단위테스트)
3. Claude Code: 통합 → **동일 지시서로 KO 렌더 → 언어 추가 렌더(EN)** 관통 테스트
4. Part ① 은 [A] 진단 결과가 `구현됨`일 때만 착수

---

## 6. Definition of Done

**Part ③**
- [ ] `ratio` 4구간 각각을 실제로 태우는 테스트 케이스 4건 통과
- [ ] `loop_safe=false` + `ratio=0.4` 컷이 핑퐁이 아니라 홀드로 처리됨
- [ ] 렌더 로그에 컷별 `(clip_sec, narration_sec, ratio, strategy)` 전부 기록
- [ ] 나레이션이 잘리거나 영상이 먼저 끝나는 컷 = 0

**Part ②**
- [ ] ⑥ 화면에서 버튼 1회 클릭 → 타 언어 mp4 산출까지 사람 개입 0
- [ ] **`reuse_assets=true` 잡의 이미지·영상 생성 API 호출 = 0** (`generation_attempts` 원장 확인)
- [ ] 두 언어 영상의 컷 순서·에셋이 동일하고, 각 언어의 자막·나레이션 싱크가 맞음
- [ ] 총 길이 차이는 결함이 아님을 UI에 1줄 표기

**Part ①** (착수 시)
- [ ] `COMPARE`/`SCALE`/`EVIDENCE` 컷에 생성 이미지가 들어간 지시서가 정규화에서 거부됨
- [ ] editorial 3편이 화면 QA 통과

---

## 7. 열린 질문 (가정으로 진행, 확인 필요)

1. **에셋 캐시 실효성:** `render_assets`가 논문 파이프라인에서 실제로 채워지고 있는가. (리포트 파이프라인은 `directive_id=None`으로 캐시를 의도적으로 우회한다는 기록이 있음 — 논문 쪽도 같은 상태면 Part ②의 전제가 깨진다. 탐색 [B]에서 **최우선 확인**)
2. **TTS 실행 위치:** TTS가 `_render_cut_clips` 내부에 있다면 순서 역전이 지역 변경으로 끝나지만, 별도 단계라면 함수 경계 조정이 필요하다.
3. **영상 길이 티어:** 현재 사용 중인 영상 모델이 임의 길이를 지원하는가, 고정 티어인가. 임의 길이 지원 시 §3-2만으로 §3-3 대부분이 불필요해진다.
4. **`loop_safe` 판정 신뢰도:** LLM이 이 플래그를 제대로 채우는지 미검증. 기본값 `false`가 안전측이므로 최악의 경우도 "홀드로만 처리됨"에 그친다.

---

*v1 · 2026.07.26. editorial 노선 폐기 요청에 대한 판정(표본 1~2편 · 구현 미확인으로 판정 무효)과, 언어 추가 렌더·클립 길이 보정 요청을 통합. Part ①은 진단 통과를 조건으로 하는 게이트 구조.*
