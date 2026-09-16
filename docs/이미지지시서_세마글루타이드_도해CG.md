# 이미지 지시서 — 세마글루타이드 (도해 CG 화풍)

**시작 그림 6장.** 영상은 이 그림들이 정해진 뒤에 만든다 —
영상 프롬프트는 `Keep the SAME design and materials ... do not restyle any object` 라
**화풍을 첨부 이미지가 100% 결정하기 때문**이다(2026-09-07 실측: 영상으로는 화풍이 안 갈렸다).

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로 — 반드시 설정 항목으로. 프롬프트의 `vertical 9:16` 글자는 모델이 무시한다** · 출력 이미지만

## 지난 시험에서 바뀐 것

S1(주사 펜)은 실사로, S2(사육장)는 도해로 나왔다. 같은 접미사인데 갈린 이유는
**장면 묘사 안의 광학 어휘**였다 — `shallow depth of field` 가 부정어 `no lens blur` 를 이겼다.
그래서 이번에는 두 곳을 같이 고쳤다.

| | 지난번 | 이번 |
|---|---|---|
| 화풍 접미사 | `physically based materials, fine surface detail` (사실성을 **올리는** 어휘) | `simplified geometric forms, minimal micro-texture` |
| 장면 묘사 | 그대로 (`shallow depth of field`, `macro detail`, `blurred`) | **광학 어휘 제거**(배치 정보는 유지) |

> MECHANISM 컷(세포·분자)은 **손대지 않았다** — 이미 3D 도해이고 광학 어휘도 없다.

---

## 그림 1/6 — `S1_HOOK_MICE`  (REALITY)

담는 컷: **컷1, 컷2**

- 컷1 — 노화를 늦추는 약이 나왔습니다. 그런데 새로 만든 약이 아니라고요?
- 컷2 — 이미 병원에서 널리 쓰이는 비만 치료제였습니다. 늙은 생쥐의 수명을 92일 늘렸죠.

<details><summary>이 컷에서 걷어낸 광학 어휘</summary>

```diff
- Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, shallow depth of field, cool clinical light catching its plastic barrel. Behind it, far out of focus, two small shapes are barely readable as animals. Photoreal macro detail. Nothing
+ Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, cool clinical light catching its plastic barrel. Behind it, further back, two small shapes are barely readable as animals. Nothing written anywhere in the frame, no markings on the p
```
</details>

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, cool clinical light catching its plastic barrel. Behind it, further back, two small shapes are barely readable as animals. Nothing written anywhere in the frame, no markings on the pen., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

---

## 그림 2/6 — `S2_COMPARISON_MICE`  (REALITY)

담는 컷: **컷3, 컷4**

- 컷3 — 캘리포니아 버클리 연구팀이 네이처에 발표한 결과입니다.
- 컷4 — 대조군 생쥐의 중앙 수명 742일과 비교하면, 세마글루타이드 투여 생쥐는 834일을 살았죠.

<details><summary>이 컷에서 걷어낸 광학 어휘</summary>

```diff
- Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background i
+ Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background i
```
</details>

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background is A plain modern laboratory. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

---

## 그림 3/6 — `S3_ADMINISTRATION`  (REALITY)

담는 컷: **컷5, 컷6, 컷7**

- 컷5 — 이 연구는 20개월령 암컷 C57BL/6 생쥐에게 3개월간 세마글루타이드를 투여하여
- 컷6 — 생리적 기능 향상과 노화 특징 완화를 관찰했습니다.
- 컷7 — 수명 연구는 생쥐의 수명 기간 동안 진행되었고요.

<details><summary>이 컷에서 걷어낸 광학 어휘</summary>

```diff
- A gloved hand of a researcher carefully holding a small, aged female C57BL/6 mouse. The mouse is calm and appears healthy. In the background, a sterile laboratory setting with blurred equipment. No on-screen text.
+ A gloved hand of a researcher carefully holding a small, aged female C57BL/6 mouse. The mouse is calm and appears healthy. In the background, a sterile laboratory setting with Further back, equipment. No on-screen text.
```
</details>

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A gloved hand of a researcher carefully holding a small, aged female C57BL/6 mouse. The mouse is calm and appears healthy. In the background, a sterile laboratory setting with Further back, equipment. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

---

## 그림 4/6 — `S4_CALORIE_RESTRICTION_ANALOGY`  (MECHANISM)

담는 컷: **컷8, 컷9**

- 컷8 — 세마글루타이드는 칼로리 제한과 유사하게 노화 관련 기능 저하를 완화할 뿐만 아니라, 탐색 행동, 공간 기억, 혈당 조절에서는 칼로리 제한보다 더 유리한 궤적을 보였습니다.
- 컷9 — 즉, 단순히 체중 감소 효과를 넘어선다는 거죠.

> MECHANISM — 기존 3D 도해 화풍 그대로다.

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A split screen showing two parallel processes. On the left, a stylized aged cell with a 'calorie restriction' symbol (e.g., an empty plate icon) hovering over it, showing subtle improvement. On the right, the same stylized aged cell with a 'semaglutide' molecule (green, elongated) approaching and binding to it, initiating a more pronounced transformation into a healthier, more active cell. Simultaneously, small, glowing representations of neural pathways (for spatial memory/exploratory behavior) and pancreatic cells (for glucose control) appear and become more vibrant on the semaglutide side, indicating superior effects. No on-screen text., vertical 9:16 portrait aspect ratio, high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, single amber accent color on the part being explained, neutral desaturated background, engineering-diagram clarity, high geometric detail, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic texture, no lens flare, no bokeh, no cluttered background, no people in focus
```

---

## 그림 5/6 — `S5_SEMAGLUTIDE_MECHANISM`  (MECHANISM)

담는 컷: **컷10, 컷11, 컷12**

- 컷10 — 세마글루타이드는 노화 관련 염증을 줄이고
- 컷11 — NAD+ 수준을 높이며
- 컷12 — 노화 조절 유전자의 발현을 유도하는 등 다양한 메커니즘으로 노화를 늦추는 것으로 나타났습니다.

> MECHANISM — 기존 3D 도해 화풍 그대로다.

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A stylized animal cell with many small, red, spiky inflammatory cytokine molecules surrounding it. A green, elongated semaglutide molecule appears and moves towards the cytokines, causing them to visibly shrink and disappear. No on-screen text., vertical 9:16 portrait aspect ratio, high-fidelity 3D technical render, precise isometric cutaway with crisp layer separation, physically based materials with fine surface detail, sharp beveled edges, clean topology, volumetric studio lighting with soft ambient occlusion, subtle depth cue, single amber accent color on the part being explained, neutral desaturated background, engineering-diagram clarity, high geometric detail, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic texture, no lens flare, no bokeh, no cluttered background, no people in focus
```

---

## 그림 6/6 — `S6_LIMITATION_MICE`  (REALITY)

담는 컷: **컷13, 컷14**

- 컷13 — 하지만 이 연구는 암컷 생쥐만을 대상으로 했고
- 컷14 — 인간에게도 동일한 효과가 나타날지는 장기적인 임상 연구가 더 필요합니다.

<details><summary>이 컷에서 걷어낸 광학 어휘</summary>

```diff
- A sterile laboratory setting. In the foreground, a cage of female C57BL/6 mice is clearly visible. In the background, slightly out of focus, is another cage containing male C57BL/6 mice, symbolizing the unstudied population. The lighting is slightly dimmer, conveying a sense of caution. No on-screen
+ A sterile laboratory setting. In the foreground, a cage of female C57BL/6 mice is clearly visible. In the background, further back, is another cage containing male C57BL/6 mice, symbolizing the unstudied population. The lighting is slightly dimmer, conveying a sense of caution. No on-screen text.
```
</details>

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A sterile laboratory setting. In the foreground, a cage of female C57BL/6 mice is clearly visible. In the background, further back, is another cage containing male C57BL/6 mice, symbolizing the unstudied population. The lighting is slightly dimmer, conveying a sense of caution. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

---

## 볼 것

1. **6장이 한 화면 언어로 보이는가** — 특히 그림 1·2(실험실)와 그림 4·5(세포)가
   같은 작품처럼 보여야 한다. 지금까지는 여기서 화면이 튀었다
2. **쥐가 보기 견딜 만한가** — 그림 2가 정면 승부다
3. **그림 1이 이번엔 도해로 나오는가** — 지난번 실사로 갔던 컷이다
4. 세로 9:16 · 글자 없음

## 통과하면

`engine/config.py` 두 곳을 바꾼다 —
`VISUAL_ROLE_STYLE["REALITY"]` / `VISUAL_ROLE_NEGATIVE["REALITY"]`,
그리고 **지시서 생성 프롬프트**에서 광학 어휘를 금지한다(둘 다 해야 한다).
