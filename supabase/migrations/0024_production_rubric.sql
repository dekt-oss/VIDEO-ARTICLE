-- 제작 준비도 루브릭 (수정지시서 v2 §6) — docs/deviation-hook-retention-v2.md
-- 기존 4축(0~10, 정렬용)은 그대로 두고, "제작 여부"를 가르는 5축·각 0~2점(총 10) 게이트를 추가한다.
-- 추가 컬럼은 nullable jsonb 라 기존 채점 행(1,300+편)은 null 로 남고(하위호환), 신규 채점부터 채워진다.
--
-- production 형식: {"axes": {novelty:{score,why}, audience_value, hook_fit, explain_60s, visualizable},
--                   "total": <0~10>, "gate": "make|redesign|backlog|hold"}
-- engine/scoring.py parse_production 이 생성. 대시보드 /scored 가 게이트 배지로 표시.

alter table scores add column if not exists production jsonb;
