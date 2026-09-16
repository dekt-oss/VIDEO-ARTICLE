# 배포 표면(Deploy Surfaces) & 반영 체크리스트

> 왜 이 문서가 있나: "코드는 머지됐는데 실제 동작은 옛날"인 사고가 실제로 났다(지시서 생성이
> scene_kind·hook/cta 없이 나옴). 원인은 이 저장소가 **배포 표면이 여러 개**인데 그중 하나(엣지
> 함수)는 머지로 자동 반영되지 않기 때문. "머지 = 반영"이 성립하지 않는 지점을 여기 못박는다.

## 배포 표면 4가지 — 무엇이 언제 반영되나
| 표면 | 코드 위치 | 반영 방법 | 머지만 하면 됨? |
|---|---|---|---|
| **엔진(렌더 워커)** | `engine/**` | GitHub Actions `render.yml` 이 main 을 checkout | ✅ 자동 |
| **엣지 함수** | `supabase/functions/**` | `supabase functions deploy <fn>` | ❌ **배포 필요** → `deploy-edge.yml` 자동화 |
| **DB 스키마** | `supabase/migrations/**` | `supabase db push` 또는 SQL 적용 | ❌ **적용 필요** |
| **대시보드(웹)** | `web/**` | Vercel 이 push/merge 로 자동 빌드·배포 | ✅ 자동 |

## 핵심 함정
- **엣지 함수(지시서·초안 생성)**: `engine/directive.py` 를 고쳐도, 대시보드가 실제로 호출하는 것은
  `supabase/functions/generate-directive` 다(이중 관리 지점). Python 을 고치면 TS 도 고치고 **배포**까지
  해야 새 지시서에 반영된다. `deploy-edge.yml`(main 머지 시 자동배포)로 이 단계를 자동화했다.
  - 자동배포 선행조건: GitHub Secrets `SUPABASE_ACCESS_TOKEN` + `SUPABASE_PROJECT_REF`.
- **마이그레이션**: 새 컬럼/테이블은 운영 DB에 적용해야 워커·웹이 그 컬럼을 읽는다.
- **소급 안 됨**: 엔진/엣지/스키마를 반영해도 **이미 생성된 지시서·렌더에는 소급되지 않는다.**
  변화를 보려면 **새 지시서 생성 → 새 렌더**가 필요하다.

## "반영했다"고 말하기 전 체크리스트
- [ ] `engine/**` 변경 → main 머지됨(다음 렌더부터 적용). 필요하면 `render.yml` 데모로 확인.
- [ ] `supabase/functions/**` 변경 → **배포됨**(`deploy-edge.yml` 성공 or 수동 `supabase functions deploy`).
- [ ] `supabase/migrations/**` 변경 → **운영 DB 적용됨**(컬럼/테이블 존재 확인).
- [ ] `web/**` 변경 → Vercel 배포 Ready.
- [ ] 동작 검증은 **새 지시서/새 렌더**로(옛 산출물은 안 바뀜).
