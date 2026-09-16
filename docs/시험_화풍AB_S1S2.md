# 화풍 A/B 시험 — 장면 S1·S2

쥐가 실사로 나오는 것이 보기 힘들다는 지적(2026-09-07)에 대한 비교 시험이다.
**A = 지금 코드가 내보내는 프롬프트. B = REALITY 역할의 화풍/부정어만 바꾼 것.**
나머지(장면 묘사·카메라·구도·길이)는 한 글자도 건드리지 않았다 — 화풍 말고 다른 변수가
섞이면 무엇 때문에 좋아졌는지 알 수 없다.

## 무엇이 다른가

| | A (현재) | B (제안) |
|---|---|---|
| 화풍 | `photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain` | `cinematic 3D render, physically based materials, volumetric studio lighting, muted desaturated palette` |
| 부정어 | `not an illustration, ..., **no 3D render**, no painting` | `**not a photograph**, no photorealistic skin or fur texture, no cartoon, no anime` |
| 전체 톤 | `Scientific realism` | `Scientific 3D visualization` |


### ⚠️ 시험하면서 찾은 구조 문제

**화풍이 두 곳에서 정해지고 있다.**

1. 지시서 LLM 이 `visual_prompt` **안에** 화풍 단어를 쓴다 —
   REALITY 컷 1·2·9·14 에 `Photoreal`, MECHANISM 컷 8·10·11·12 에 `stylized`/`3D rendering`
2. 코드가 `VISUAL_ROLE_STYLE` 접미사를 뒤에 붙인다

B 안은 2번만 바꾼다. 1번을 그대로 두면 한 프롬프트 안에서 `not a photograph` 와
`Photoreal macro detail` 이 **서로 반대를 말한다.** 그래서 이 표의 B 에서는 화풍
형용사만 걷어냈다(장면 내용은 그대로). **실제로 코드를 바꿀 때는 지시서 생성**
**프롬프트도 함께 고쳐야 한다** — 안 그러면 매번 이 충돌이 난다.

> `MECHANISM`(세포·분자 도해) 역할은 **그대로 둔다** — 이미 3D 렌더다.
> B 가 통과하면 두 역할이 같은 재질·조명 언어를 쓰게 되어, 지금처럼
> 컷7(실사 쥐) → 컷8(3D 세포) 에서 화면이 튀는 문제도 같이 사라진다.

## 순서

**이미지 4장부터 만든다**(S1-A, S1-B, S2-A, S2-B). 화풍 판단은 그림만으로 충분하고
영상보다 훨씬 싸다. 마음에 드는 쪽이 정해지면 그 쪽 영상만 만들면 된다.

`이미지 설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(반드시 파라미터로 — 프롬프트 글자는 무시된다)** · 출력 이미지만

---

# 장면 1 — `S1_HOOK_MICE`  (컷 1, 2)

- 컷1 — 노화를 늦추는 약이 나왔습니다. 그런데 새로 만든 약이 아니라고요?
- 컷2 — 이미 병원에서 널리 쓰이는 비만 치료제였습니다. 늙은 생쥐의 수명을 92일 늘렸죠.

## 시작 그림

### A — 현재 (실사)

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, shallow depth of field, cool clinical light catching its plastic barrel. Behind it, far out of focus, two small shapes are barely readable as animals. Photoreal macro detail. Nothing written anywhere in the frame, no markings on the pen., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### B — 제안 (사실적 CG)

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., Extreme close-up of a single ordinary injection pen lying on a clean surface, the kind already stocked in pharmacies, shallow depth of field, cool clinical light catching its plastic barrel. Behind it, far out of focus, two small shapes are barely readable as animals. macro detail. Nothing written anywhere in the frame, no markings on the pen., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

## 영상 (그림이 정해진 뒤에)

### 영상 1 — 8초 · 시작 프레임: 위 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · 종횡비 9:16 세로 · 길이 8초 · 시작 이미지 첨부 · 무음

**A — 현재**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-3.0s the camera moves laterally alongside as the mouse group semaglutide stands out from the rest. The camera drifts slowly sideways along the pen, keeping it sharp while the two blurred shapes behind it begin to resolve., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

**B — 제안**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-3.0s the camera moves laterally alongside as the mouse group semaglutide stands out from the rest. The camera drifts slowly sideways along the pen, keeping it sharp while the two blurred shapes behind it begin to resolve., stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### 영상 2 — 8초 · 시작 프레임: 앞 클립(영상 1)의 마지막 프레임

`설정` 모델 `veo-3.1-lite-generate-preview` · 종횡비 9:16 세로 · 길이 8초 · 시작 이미지 첨부 · 무음

**A — 현재**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-2.0s the camera pulls back to reveal the whole structure as the mouse group control comes into view; then 2.0-5.0s the camera pushes in rapidly as the mouse group semaglutide stands out from the rest. A rapid push-in past the pen onto the upright glossy mouse, its bright eye filling the frame as the hunched mouse slides out of view., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

**B — 제안**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: shot sequence within the clip: 0.0-2.0s the camera pulls back to reveal the whole structure as the mouse group control comes into view; then 2.0-5.0s the camera pushes in rapidly as the mouse group semaglutide stands out from the rest. A rapid push-in past the pen onto the upright glossy mouse, its bright eye filling the frame as the hunched mouse slides out of view., stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

---

# 장면 2 — `S2_COMPARISON_MICE`  (컷 3, 4)

- 컷3 — 캘리포니아 버클리 연구팀이 네이처에 발표한 결과입니다.
- 컷4 — 대조군 생쥐의 중앙 수명 742일과 비교하면, 세마글루타이드 투여 생쥐는 834일을 살았죠.

## 시작 그림

### A — 현재 (실사)

```text
Scientific realism, clean and precise, with a focus on biological processes and laboratory settings., Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background is a blurred, modern laboratory. No on-screen text., vertical 9:16 portrait aspect ratio, photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not an illustration, no cartoon, no anime, no webtoon, no drawing, no 3D render, no painting, no flat vector art
```

### B — 제안 (사실적 CG)

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., Two identical laboratory cages side-by-side on a sterile lab bench. The left cage contains a group of aged female C57BL/6 mice that are less active. The right cage contains a group of aged female C57BL/6 mice that are significantly more active and alert, exploring their environment. The background is a blurred, modern laboratory. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no fur or skin micro-texture, no pores, no lens blur, no bokeh, no film grain, no cartoon outlines, no anime, no flat vector art
```

## 영상 (그림이 정해진 뒤에)

### 영상 1 — 8초 · 시작 프레임: 위 시작 그림

`설정` 모델 `veo-3.1-lite-generate-preview` · 종횡비 9:16 세로 · 길이 8초 · 시작 이미지 첨부 · 무음

**A — 현재**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: The camera slowly pans from the less active control group on the left to the more active semaglutide-treated group on the right, highlighting the difference in vitality., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

**B — 제안**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: The camera slowly pans from the less active control group on the left to the more active semaglutide-treated group on the right, highlighting the difference in vitality., stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

### 영상 2 — 6초 · 시작 프레임: 앞 클립(영상 1)의 마지막 프레임

`설정` 모델 `veo-3.1-lite-generate-preview` · 종횡비 9:16 세로 · 길이 6초 · 시작 이미지 첨부 · 무음

**A — 현재**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: Subtle zoom in on the two cages, holding steady to allow the comparison to be absorbed, with a slight focus shift between the two groups., photorealistic cinematic still, natural daylight, muted documentary color grade, subtle film grain, aerial or macro perspective, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

**B — 제안**

```text
Animate the attached still image. It is the exact first frame. Keep the SAME subjects, the SAME design and materials, the SAME setting, the SAME lighting and the SAME framing. Do not redraw or re-imagine the scene, do not replace or restyle any object. Only the following motion happens: Subtle zoom in on the two cages, holding steady to allow the comparison to be absorbed, with a slight focus shift between the two groups., stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, even studio lighting, limited desaturated palette with a single amber accent, neutral background, technical illustration clarity, vertical 9:16, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks
```

---

## 볼 것

1. **쥐가 보기 견딜 만한가** — 이게 이 시험의 출발점이다
2. **"진짜 있는 일"이라는 느낌이 남아 있는가** — B 가 너무 일러스트로 가면 REALITY 역할의
   목적(실재감 앵커)이 사라진다. 만화가 아니라 **사실적 CG** 여야 한다
3. **글자가 안 나오는가** — 두 안 모두 부정어에 넣었지만 실제로 지켜지는지
4. **세로 9:16 로 나왔는가** — 종횡비를 파라미터로 안 넣으면 정사각형이 나온다

## 이 결과로 정해지는 것

B 가 나으면 `engine/config.py` 의 `VISUAL_ROLE_STYLE["REALITY"]` 와
`VISUAL_ROLE_NEGATIVE["REALITY"]` 두 줄을 바꾼다. 그러면 **모든 실사형 영상이 함께 바뀐다.**
지시서 생성 쪽 `global_style` 문구도 같이 손봐야 한다(지금은 LLM 이 "Scientific realism" 을 쓴다).
