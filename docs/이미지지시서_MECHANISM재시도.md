# 이미지 지시서 — MECHANISM 2장 재시도 (그림 4·5)

그림 4는 **파스텔 광택 발광**, 그림 5는 **아웃라인 선화**로 나와 그림 2·3(실험실)과
안 어울렸다. 원인을 찾았다.

## 원인 — MECHANISM 부정어가 비어 있었다

| 금지 항목 | REALITY | MECHANISM (기존) |
|---|---|---|
| 아웃라인·선화 | ✅ | **없음** ← 그림 5 원인 |
| 발광·네온·블룸 | (없었음) | **없음** ← 그림 4 원인 |
| 만화·애니 | ✅ | **없음** |
| 플랫 벡터 | ✅ | **없음** |

기존 MECHANISM 부정어는 이게 전부였다 —
`not a photograph, no photorealistic texture, no lens flare, no bokeh,`
`no cluttered background, no people in focus`

REALITY 쪽에는 이번에 다 넣었는데 MECHANISM 은 "이미 3D 도해니까" 하고 손대지 않았다.
그게 실수였다. 그리고 STYLE 의 `engineering-diagram clarity` 가 **도해 = 선으로 그린 그림**
쪽으로 밀었다.

## 처방 — 그림 2·3 과 같은 토대를 쓴다

```diff
- high-fidelity 3D technical render, precise isometric cutaway ...,
-   physically based materials with fine surface detail, sharp beveled edges,
-   ... engineering-diagram clarity, high geometric detail
+ stylized 3D render, simplified geometric forms with clean silhouettes,
+   matte surfaces with minimal micro-texture,
+   isometric cutaway with crisp layer separation,     ← 도해 시점만 남긴다
+   even studio lighting, limited desaturated palette with a single amber accent,
+   neutral background
```

**REALITY 와 다른 것은 `isometric cutaway` 한 줄뿐이다.** 재질·조명·색은 같다 —
그래야 한 영상 안에서 실험실 장면과 세포 도해가 같은 작품으로 보인다.

`설정` 모델 `gemini-2.5-flash-image` · **종횡비 9:16 세로(설정 항목으로)** · 출력 이미지만

---

## 그림 4 — 컷8

- 세마글루타이드는 칼로리 제한과 유사하게 노화 관련 기능 저하를 완화할 뿐만 아니라, 탐색 행동, 공간 기억, 혈당 조절에서는 칼로리 제한보다 더 유리한 궤적을 보였습니다.

장면 묘사에서 걷어낸 발광·채도 어휘:

```diff
- ...ed aged cell with a 'semaglutide' molecule (green, elongated) approaching and binding to it, initiating a more pronounced transformation into a healthier, more active cell. Simultaneously, small, glow...
+ ...ed aged cell with a 'semaglutide' molecule (green, elongated) approaching and binding to it, initiating a more pronounced transformation into a healthier, more active cell. Simultaneously, small repre...
```

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A split screen showing two parallel processes. On the left, a stylized aged cell with a 'calorie restriction' symbol (e.g., an empty plate icon) hovering over it, showing subtle improvement. On the right, the same stylized aged cell with a 'semaglutide' molecule (green, elongated) approaching and binding to it, initiating a more pronounced transformation into a healthier, more active cell. Simultaneously, small representations of neural pathways (for spatial memory/exploratory behavior) and pancreatic cells (for glucose control) appear and are highlighted in amber on the semaglutide side, indicating superior effects. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, isometric cutaway with crisp layer separation, even studio lighting, limited desaturated palette with a single amber accent, neutral background, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no cartoon outlines, no line art, no ink contours, no cel shading, no flat vector art, no anime, no glowing effects, no neon, no bloom, no light emission, no lens blur, no bokeh, no film grain
```

---

## 그림 5 — 컷10

- 세마글루타이드는 노화 관련 염증을 줄이고

```text
Scientific 3D visualization, clean and precise, with a focus on biological processes and laboratory settings., A stylized animal cell with many small, red, spiky inflammatory cytokine molecules surrounding it. A green, elongated semaglutide molecule appears and moves towards the cytokines, causing them to visibly shrink and disappear. No on-screen text., vertical 9:16 portrait aspect ratio, stylized 3D render, simplified geometric forms with clean silhouettes, matte surfaces with minimal micro-texture, isometric cutaway with crisp layer separation, even studio lighting, limited desaturated palette with a single amber accent, neutral background, no text, no captions, no subtitles, no labels, no letters, no numbers, no speech bubbles, no watermarks, not a photograph, no photorealistic detail, no cartoon outlines, no line art, no ink contours, no cel shading, no flat vector art, no anime, no glowing effects, no neon, no bloom, no light emission, no lens blur, no bokeh, no film grain
```

---

## 볼 것

**그림 2·3 옆에 놓고 본다.** 4장이 같은 작품처럼 보이면 통과다.

- 아웃라인(윤곽선)이 사라졌는가 ← 그림 5 문제
- 파스텔·발광이 사라지고 회색조 + 앰버 하나로 정리됐는가 ← 그림 4 문제
- 단면(cutaway)은 여전히 보이는가 ← 이걸 잃으면 도해의 값어치가 없다
