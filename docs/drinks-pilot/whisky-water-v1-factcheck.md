# 위스키 대본 v4 — 근거·흐름 점검표 (2026-10-26)

운영자: "팩트체크나 내용이 흐름이 맞는지 점검안하니? JEV 확인안해?" — 이 대본은 그때까지 사람(제작자) 대조만 했고,
논문·리포트 공장이 쓰는 Jev 근거 판정을 한 번도 거치지 않았다. 아래는 원문 대조 + Jev 두 회차 결과다.

출처: Karlsson & Friedman, *Dilution of whisky – the molecular perspective*, Scientific Reports 7:6489 (2017), CC BY 4.0.
전문은 Europe PMC(PMC5561096)에서 읽었다. **컴퓨터 시뮬레이션(분자동역학) 연구 — 사람이 맛본 실험이 아니다.**

## 장면별 원문 대조

| # | 나레이션(v4) | 원문 | 판정 |
|---|---|---|---|
| 1 | 위스키에 물을 탄다고요? 사실 병 위스키는, 이미 물을 탄 거예요. | "Before bottling, the whisky is diluted to around 40 vol-% by the addition of water" | 맞음. 원액 그대로 파는 예외는 7번에서 다룬다 |
| 2 | 갓 증류하면 70도쯤이고, 통에서 숙성하면서 60도 안팎이 되는데, 이걸 물로 40도까지 낮추거든요. | "typically contain around 70% … Some alcohol evaporates during the maturation resulting in … 55–65 vol-% … diluted to around 40 vol-%" | 맞음(v3 는 숙성 단계를 빼서 4번 '60%'와 어긋났다) |
| 3 | 물을 타면 맛이 꽤 달라지는데요, 그 이유를 스모키한 향을 내는 과이아콜이라는 분자로 살펴볼게요. | "which changes the taste significantly" · "the smoky flavour is attributed to phenols, and in particular guaiacol" | 맞음(v3 '비밀은 과이아콜'은 한 분자가 전부인 것처럼 말했다 — 논문은 대표 분자로 살펴본 것) |
| 4 | 알코올이 60% 가까울 땐, 이 분자가 알코올에 둘러싸여서 술 속으로 들어가 버려요. | "At ethanol concentrations of 59 vol-% or higher, guaiacol is increasingly surrounded by ethanol molecules and is driven to the bulk" | 맞음 |
| 5 | 그런데 물을 타서 45% 아래로 내려가면, 이 분자가 술 표면으로 올라와요. | "primarily found at the liquid-air interface in mixtures that contain up to 45 vol-% of ethanol" | 맞음 |
| 6 | 우리는 술을 표면부터 마시니까, 향과 맛이 더 살아날 수 있어요. | "Because the drink is consumed at the interface first …" · "which likely influences both taste and smell" | 맞음 — '수 있어요'로 논문의 'likely'를 지켰다. Jev 는 두 회차 모두 문턱을 넘겼다(0.61·0.66) |
| 7 | 그래서 60도 안팎으로 파는 위스키라면, 30ml에 물 세 티스푼쯤 타 보세요. 40도 정도가 돼요. | 원액 55–65%(원문) + **계산**: 60% × 30ml ÷ 45ml = 40% | 맞음(계산값은 원문이 아님을 근거 목록 c6 에 표시). v3 '50도쯤'은 원액 도수가 아니었다 |
| 8 | 이건 컴퓨터 시뮬레이션으로 밝힌 결과예요. | "We carried out computer simulations of water-ethanol mixtures" | 맞음 |

## 흐름

질문(물 탄 술?) → 사실(70 → 숙성 60 → 병입 40) → 왜(과이아콜) → 진할 때(숨음) → 묽을 때(표면) → 그래서 맛·향 → 해 볼 것 → 근거의 한계.
첫 질문에 끝까지 답한다. v1~v2 의 "한두 방울" 질문은 논문이 답하지 않아 버렸다(운영자 지적).

## Jev 근거 판정(운영 문턱 0.6, 같은 질문 — `decide.unsupported_claim`)

| # | 1회차 | 2회차 |
|---|---|---|
| 1 | 0.52 | 0.64 ⚠ |
| 2 | 0.54 | 0.50 |
| 3 | 0.54 | 0.56 |
| 4 | 0.51 | 0.65 ⚠ |
| 5 | 0.63 ⚠ | 0.55 |
| 6 | 0.61 ⚠ | 0.66 ⚠ |
| 7 | 0.54 | 0.50 |
| 8 | 0.58 | 0.64 ⚠ |

**해석:** 바꾸지 않은 같은 문장이 회차마다 0.1~0.15 오르내린다. 모든 장면이 0.50~0.66 에 몰려 있어 이 대본에서는 Jev 가
문장을 가려내지 못했다(CLAUDE.md 의 "문턱 촘촘해 반복마다 흔들림" 기록과 같다). 그래서 **판정은 위 원문 대조표로 했고**,
Jev 는 "다시 볼 문장" 신호로만 썼다 — 실제로 v3 의 1·3번(과장)을 다시 보게 한 것은 Jev 다.
화면과 말의 어긋남(cross_modal_conflict)은 모든 장면 0.22 이하로 문제 없었다.
비용: Jev 호출 약 60회, 입력 단가 $0.042/백만 토큰 — 합계 1센트 미만(추정. 이번 점검은 운영 원장에 쓰지 않았다).
