# 편차 기록 — 설명판형(explainer)·웹툰(webtoon) 폐기 (2026-08-28)

## 지시

> "설명판형은 없습니다. 그런건 안쓸거에요. 없애세요. 웹툰도 없습니다. 없애세요."
> — 운영자, 2026-08-28

## 무엇을 없앴나

**새로 발주할 수 없게 했다.** 두 버전은 이제 어느 화면에서도 고를 수 없고, 엔진·엣지 어느
경로로도 만들어지지 않는다.

| 표면 | 변경 |
|---|---|
| `engine/config.VIDEO_VERSIONS` | `("comic", "image_sequence", "photo")` — 둘 제거 |
| `engine/directive.VERSION_GUIDANCE` | webtoon·explainer 가이던스 블록 제거(각 35줄·26줄) |
| `engine/report_directive.py` | `EXPLAINER_CONTRACT`·`attach_explainer`·`gate_feedback_prompt` 제거 |
| `engine/explainer.py` | **파일 삭제** |
| `engine/fin_charts/` | **디렉터리 삭제**(이미 아무도 import 하지 않던 죽은 코드) |
| `supabase/functions/generate-directive/index.ts` | 버전 enum·가이던스에서 둘 제거 |
| `web/lib/versions.ts` | 두 공장 발주 목록에서 제거 → 양쪽 모두 `["comic", "photo"]` |
| 테스트 | `test_explainer.py`·`test_fin_pipeline.py` 삭제, 등록 검사 → **폐기 검사로 반전** |

## 무엇을 남겼나 (의도적)

**이미 만든 영상·지시서는 계속 열린다.** editorial(2026-07-28) 때와 같은 자세다.

- `config.VERSION_VISUAL_TYPE` 의 두 키 — 옛 행이 렌더될 때 쓰인다.
- `web/lib/types.ts` 의 `VersionType` union·`ExplainerBlock` 타입, `ExplainerPanel.tsx` —
  저장된 explainer 지시서를 열면 예전처럼 검수 패널이 보인다.
- `engine/board_render.py`·`board_layout`·`board_motion` — 보드 렌더 경로. 새 지시서는
  `board` 필드를 만들지 않으므로 `code_render_board()` 가 항상 False 다. 옛 행에서만 산다.
- `EXPLAINER_*` config 상수 — 위 보드 렌더러가 읽는다.

즉 **생성은 막고 재생은 살렸다.** 이 구분이 없으면 지금까지 만든 리포트 영상의 지시서 화면이
통째로 깨진다.

## 잃은 것 하나 — 되살려야 한다

설명판형에는 이 저장소에서 **유일하게 작동하던 계약 게이트**가 붙어 있었다:

1. 계약 위반(근거 보드 없음·주장 귀속 없음·숫자에 비교 기준 없음)을 **코드가 판정**하고
2. 위반 사유를 프롬프트에 **되먹여 1회 자동 재생성**하고
3. 그래도 안 되면 **승인을 잠갔다**.

폐기하면서 이 장치도 함께 사라졌다. **아이디어는 옳았고, 지금 계약이 새는 곳은 실사형이다** —
같은 날 실측에서 실사형 지시서가 계약을 여러 곳에서 어겼는데 게이트가 하나도 잡지 못했다
(`docs/리뷰요청_지시서렌더엔진_v1.md` §3). 실사형 게이트를 만들 때 같은 모양으로 되살린다.
되살릴 코드는 커밋 이력에 있다(`attach_explainer` / `gate_feedback_prompt`).

`engine/report_directive.generate()` 의 docstring 에 그 메모를 남겨 뒀다.

## 되돌리는 법

`git revert` 로 이 커밋을 되돌리면 두 버전이 그대로 돌아온다. 부분 복구가 필요하면
`VIDEO_VERSIONS`(엔진·엣지)와 `web/lib/versions.ts` 의 목록에 키를 다시 넣는 것만으로도
발주가 살아난다 — 가이던스·계약은 그 뒤에 붙인다.

## 검증

- 파이썬 1116 passed(폐기 검사 2개 신설: 양쪽 발주 목록에서 사라졌는가 / 옛 행은 여전히
  렌더 매핑을 갖는가).
- 웹 28 passed + `tsc --noEmit` 통과.
- ⚠️ **엣지 함수는 배포해야 반영된다.** `supabase/functions/generate-directive` 를 배포하고
  바이트 대조까지 해야 대시보드 발주 경로에서 두 버전이 실제로 사라진다.

## 관련
- `docs/deviation-webtoon-b1-removal.md` — editorial 폐기(2026-07-28). 같은 패턴의 선례.
- `docs/개선명세서_설명판형_v3_3.md`·`docs/deviation-explainer-v3_3.md` — 폐기된 설명판형의 명세·구현 기록.
- `docs/수정명세서_웹툰버전_v1.md` — 폐기된 웹툰 버전의 명세.
- `docs/리뷰요청_지시서렌더엔진_v1.md` — 이 폐기와 같은 날 작성한 지시서·렌더 엔진 리뷰 요청.
