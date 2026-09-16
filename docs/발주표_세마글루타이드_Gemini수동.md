# 발주표 — 세마글루타이드 (Gemini 수동 샘플용)

지시서 `e7793db0` · 컷 14개 → **장면(stage) 6개 · 이미지 6장 · 영상 14개**

> 아래 프롬프트는 파이프라인이 실제로 Gemini 에 보내는 문장 그대로다(`providers.image._build_image_prompt` · `providers.video.build_motion_prompt` 를 직접 호출).
> ffmpeg·Actions 없이 **손으로 샘플을 만들어 보기 위한 표**다.

## 만드는 순서

장면마다 이렇게 한다. 장면끼리는 독립이라 아무 장면이나 먼저 해도 된다.

```
1) [이미지] 그 장면의 '시작 그림' 1장을 만든다 (9:16 세로)
2) [영상 1] 그 그림을 시작 프레임으로 넣고 → 클립 1 생성
3) [영상 2] 클립 1의 **마지막 프레임**을 캡처해 시작 프레임으로 넣고 → 클립 2 생성
4) 클립이 더 있으면 3) 을 반복 (표의 '시작 프레임' 열을 따른다)
5) 만든 클립들을 순서대로 이어 붙이면 그 장면의 연속 영상이 된다
```

★ 3) 이 핵심이다. 앞 클립의 마지막 프레임에서 이어받아야 **같은 장면이 계속되는** 느낌이 난다.
   Veo 가 한 번에 8초까지만 만들기 때문에 긴 장면은 이렇게 이어 만드는 수밖에 없다.

## 매번 넣어야 하는 설정

아래 각 블록에도 다시 적어 뒀지만, 한 번에 보면 이렇다.

### 이미지 (그림 만들 때)

| 항목 | 값 |
|---|---|
| 모델 | `gemini-2.5-flash-image` |
| **종횡비** | **9:16 (세로)** |
| 출력 | 이미지만 |

> ⚠️ **종횡비는 반드시 설정 항목으로 넣어야 한다.** 프롬프트 끝의 `vertical 9:16` 이라는
> 글자는 모델이 **무시한다** — 1차 샘플에서 8장이 전부 1024×1024 정사각형으로 나온 직접
> 원인이 이것이다. 만든 뒤 세로가 맞는지 눈으로 확인할 것.

### 영상 (움직이게 할 때)

| 항목 | 값 |
|---|---|
| 모델 | `veo-3.1-lite-generate-preview` |
| **종횡비** | **9:16 (세로)** |
| 길이 | 블록마다 다름 (8초 / 6초 / 4초) |
| 시작 이미지 | **필수** — 블록에 적힌 것을 첨부 |
| 소리 | **없음(무음)** |
| 해상도 | 720p — 단, 파이프라인은 이 값을 **보내지 않는다** |

> 파이프라인이 해상도를 안 보내는 이유: 이 프리뷰 모델의 `predictLongRunning` 이
> `resolution` 을 거부한 적이 있어 껐다(`VEO_SEND_RESOLUTION=false`).
> 소리도 같은 이유로 안 보낸다(`generateAudio` 400). **나레이션은 따로 붙인다.**

---

## 장면 1/6 — `S1_HOOK_MICE`

- 담는 컷: **컷1, 컷2**
- 필요한 길이: **14.3초** (나레이션 실측 합) → 만들 영상 **16초** (8+8)

**이 장면에서 읽는 나레이션**

- 컷1 (6.09초) — 노화를 늦추는 약이 나왔습니다. 그런데 새로 만든 약이 아니라고요?
- 컷2 (7.48초) — 이미 병원에서 널리 쓰이는 비만 치료제였습니다. 늙은 생쥐의 수명을 92일 늘렸죠.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, shallow depth of field, cool clinical light catching its plastic barrel. Behind it, far out of focus, two small shapes are barely readable as animals. Photoreal macro detail. Nothing written anywhere in the frame, no markings on the pen., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷1 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-3.0s the camera moves laterally alongside as the mouse group semaglutide stands out from the rest. The camera drifts slowly sideways along the pen, keeping it sharp while the two blurred shapes behind it begin to resolve., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 8초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷2 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-2.0s the camera pulls back to reveal the whole structure as the mouse group control comes into view; then 2.0-5.0s the camera pushes in rapidly as the mouse group semaglutide stands out from the rest. A rapid push-in past the pen onto the upright glossy mouse, its bright eye filling the frame as the hunched mouse slides out of view., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷1 | 0.00초 | 6.44초 |
| 컷2 | 6.44초 | 7.83초 |

> 남는 1.74초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 장면 2/6 — `S2_COMPARISON_MICE`

- 담는 컷: **컷3, 컷4**
- 필요한 길이: **13.9초** (나레이션 실측 합) → 만들 영상 **14초** (8+6)

**이 장면에서 읽는 나레이션**

- 컷3 (4.84초) — 캘리포니아 버클리 연구팀이 네이처에 발표한 결과입니다.
- 컷4 (8.32초) — 대조군 생쥐의 중앙 수명 742일과 비교하면, 세마글루타이드 투여 생쥐는 834일을 살았죠.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background is a blurred, modern laboratory. No on-screen text., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷3 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: The camera slowly pans from the less active control group on the left to the more active semaglutide-treated group on the right, highlighting the difference in vitality., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 6초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 6초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷4 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: Subtle zoom in on the two cages, holding steady to allow the comparison to be absorbed, with a slight focus shift between the two groups., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷3 | 0.00초 | 5.19초 |
| 컷4 | 5.19초 | 8.67초 |

> 남는 0.14초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 장면 3/6 — `S3_ADMINISTRATION`

- 담는 컷: **컷5, 컷6, 컷7**
- 필요한 길이: **17.7초** (나레이션 실측 합) → 만들 영상 **20초** (8+8+4)

**이 장면에서 읽는 나레이션**

- 컷5 (7.17초) — 이 연구는 20개월령 암컷 C57BL/6 생쥐에게 3개월간 세마글루타이드를 투여하여
- 컷6 (4.81초) — 생리적 기능 향상과 노화 특징 완화를 관찰했습니다.
- 컷7 (4.65초) — 수명 연구는 생쥐의 수명 기간 동안 진행되었고요.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., A gloved hand of a researcher carefully holding a small, aged female C57BL/6 mouse. The mouse is calm and appears healthy. In the background, a sterile laboratory setting with blurred equipment. No on-screen text., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷5 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-8.0s the camera pushes in rapidly as the researcher hand travels across. The researcher's hand gently rotates the mouse to show its side, then slowly brings a small syringe into view, poised for injection., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 8초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷6 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-5.0s the camera pushes in rapidly as the syringe strikes the surface. A close-up shot of the syringe tip gently touching the mouse's skin, simulating the injection process, with a subtle focus on the point of contact., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 3 — 4초 · 시작 프레임: 앞 클립(영상 2)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 4초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷7 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-5.0s the camera pulls back to reveal the whole structure as the mouse group semaglutide travels across. The camera pulls back from the injection site to show the mouse re-entering its cage and moving freely, symbolizing the long-term nature of the study., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷5 | 0.00초 | 7.52초 |
| 컷6 | 7.52초 | 5.16초 |
| 컷7 | 12.68초 | 5.00초 |

> 남는 2.32초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 장면 4/6 — `S4_CALORIE_RESTRICTION_ANALOGY`

- 담는 컷: **컷8, 컷9**
- 필요한 길이: **18.1초** (나레이션 실측 합) → 만들 영상 **20초** (8+8+4)

**이 장면에서 읽는 나레이션**

- 컷8 (12.66초) — 세마글루타이드는 칼로리 제한과 유사하게 노화 관련 기능 저하를 완화할 뿐만 아니라, 탐색 행동, 공간 기억, 혈당 조절에서는 칼로리 제한보다 더 유리한 궤적을 보였습니다.
- 컷9 (4.69초) — 즉, 단순히 체중 감소 효과를 넘어선다는 거죠.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., A split screen showing two parallel processes. On the left, a stylized aged cell with a 'calorie restriction' symbol (e.g., an empty plate icon) hovering over it, showing subtle improvement. On the right, the same stylized aged cell with a 'semaglutide' molecule (green, elongated) approaching and binding to it, initiating a more pronounced transformation into a healthier, more active cell. Simultaneously, small, glowing representations of neural pathways (for spatial memory/exploratory behavior) and pancreatic cells (for glucose control) appear and become more vibrant on the semaglutide side, indicating superior effects. No on-screen text., vertical 9:16 portrait aspect ratio, high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, single amber accent color on the part being explained, neutral desaturated background, engineering-diagram clarity, high geometric detail, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic texture, no lens flare, no bokeh, no cluttered background, no people in focus
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷8 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-5.0s the camera pushes in rapidly as the semaglutide molecule travels across. The semaglutide molecule actively binds to the cell, triggering a cascade of internal changes. On the right side, the neural and pancreatic cell representations visibly brighten and show increased activity, while the calorie restriction side shows only a subtle, less dynamic improvement., high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, neutral desaturated background, engineering-diagram clarity, high geometric detail, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 8초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷8 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-5.0s the camera pushes in rapidly as the semaglutide molecule travels across. The semaglutide molecule actively binds to the cell, triggering a cascade of internal changes. On the right side, the neural and pancreatic cell representations visibly brighten and show increased activity, while the calorie restriction side shows only a subtle, less dynamic improvement., high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, neutral desaturated background, engineering-diagram clarity, high geometric detail, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 3 — 4초 · 시작 프레임: 앞 클립(영상 2)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 4초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷9 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-5.0s the camera pushes in rapidly as the token set grows larger. The camera pulls steadily back from the cell while the three green molecules travel outward along their separate routes, each one reaching a different structure and making it glow softly., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷8 | 0.00초 | 13.01초 |
| 컷9 | 13.01초 | 5.04초 |

> 남는 1.94초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 장면 5/6 — `S5_SEMAGLUTIDE_MECHANISM`

- 담는 컷: **컷10, 컷11, 컷12**
- 필요한 길이: **15.6초** (나레이션 실측 합) → 만들 영상 **16초** (8+8)

**이 장면에서 읽는 나레이션**

- 컷10 (4.14초) — 세마글루타이드는 노화 관련 염증을 줄이고
- 컷11 (3.11초) — NAD+ 수준을 높이며
- 컷12 (7.31초) — 노화 조절 유전자의 발현을 유도하는 등 다양한 메커니즘으로 노화를 늦추는 것으로 나타났습니다.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., A stylized animal cell with many small, red, spiky inflammatory cytokine molecules surrounding it. A green, elongated semaglutide molecule appears and moves towards the cytokines, causing them to visibly shrink and disappear. No on-screen text., vertical 9:16 portrait aspect ratio, high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, single amber accent color on the part being explained, neutral desaturated background, engineering-diagram clarity, high geometric detail, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic texture, no lens flare, no bokeh, no cluttered background, no people in focus
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷10 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-4.0s the camera moves laterally alongside as the semaglutide molecule travels across. The semaglutide molecule actively moves through the scene, causing the red inflammatory cytokines to rapidly diminish and fade away, emphasizing the reduction of inflammation., high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, neutral desaturated background, engineering-diagram clarity, high geometric detail, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 8초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷12 · 등급 `invest`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-3.0s the camera pushes in rapidly as the semaglutide molecule travels across; then 3.0-6.0s the camera moves laterally alongside as the gene expression complex stands out from the rest. The semaglutide molecule navigates into the nucleus and interacts with the gene expression complex, which then visibly activates and causes the DNA strand to slowly unwind, illustrating gene expression., high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, neutral desaturated background, engineering-diagram clarity, high geometric detail, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷10 | 0.00초 | 4.49초 |
| 컷11 | 4.49초 | 3.46초 |
| 컷12 | 7.95초 | 7.66초 |

> 남는 0.39초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 장면 6/6 — `S6_LIMITATION_MICE`

- 담는 컷: **컷13, 컷14**
- 필요한 길이: **11.3초** (나레이션 실측 합) → 만들 영상 **12초** (8+4)

**이 장면에서 읽는 나레이션**

- 컷13 (4.41초) — 하지만 이 연구는 암컷 생쥐만을 대상으로 했고
- 컷14 (6.16초) — 인간에게도 동일한 효과가 나타날지는 장기적인 임상 연구가 더 필요합니다.

### ① 시작 그림 (이미지 1장)

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(파라미터로 지정, 프롬프트 글자는 무시됨)** · 출력 이미지만

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., A sterile laboratory setting. In the foreground, a cage of female C57BL/6 mice is clearly visible. In the background, slightly out of focus, is another cage containing male C57BL/6 mice, symbolizing the unstudied population. The lighting is slightly dimmer, conveying a sense of caution. No on-screen text., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### ② 영상 1 — 8초 · 시작 프레임: ① 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 8초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷13 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: The camera slowly pans from the clearly visible female mouse cage to the subtly blurred male mouse cage in the background, emphasizing the scope limitation., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ② 영상 2 — 4초 · 시작 프레임: 앞 클립(영상 1)의 **마지막 프레임**

`설정` 모델 `veo-3.1-lite-generate-preview` · **종횡비 9:16 세로** · **길이 4초** · 시작 이미지 첨부 · **무음**

- 프롬프트 출처: 컷14 · 등급 `standard`

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-7.0s the camera pushes in rapidly as the researcher team stands out from the rest. The camera dollies slowly forward past the researcher and down the empty corridor, the rows of empty chairs sliding by on the left, ending on the bright window at the far end., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### ③ 완성된 장면 영상에서 컷이 가져갈 구간

| 컷 | 시작 | 길이 |
|---|---:|---:|
| 컷13 | 0.00초 | 4.76초 |
| 컷14 | 4.76초 | 6.51초 |

> 남는 0.74초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.

---

## 합계

- 이미지 **6장** (옛 방식은 컷마다 1장이라 14장이었다)
- 영상 **14개**, 총 98초
- 예상 영상비 $4.90 (Veo 0.05/초 기준)

## 확인할 것 (샘플의 목적)

1. **장면 안에서 화면이 이어지는가** — 영상 1 끝과 영상 2 시작이 같은 장면으로 보이는가
2. **컷 경계에서 안 끊기는가** — 위 ③ 표의 구간들이 한 영상에서 잘려 나오므로,
   컷이 바뀔 때 인물·배경·조명이 유지되어야 한다
3. **정지가 없는가** — 특히 `S4` 는 옛 방식에서 컷8이 4.66초 얼어붙던 자리다
4. **이어받기 깊이** — 3번째 클립(깊이 2)에서 인물·재질이 흐려지지 않는지
   (지금 상한 `MAX_CHAIN_DEPTH=2` 는 아직 실측된 적이 없다)
