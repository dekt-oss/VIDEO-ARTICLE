#!/usr/bin/env bash
# 완료 확인 — CI(.github/workflows/tests.yml)가 돌리는 검사를 이 PC 에서 그대로 돌린다(돈 드는 호출·외부 쓰기 없음).
cd "$(git rev-parse --show-toplevel)" || { echo "SMOKE FAIL 0/0 (git 저장소 밖)"; exit 1; }
source .claude/shared/smoke-run.sh

# 의존성은 SessionStart 훅(.claude/hooks/session-start.sh)이 깐다: engine/requirements.txt + web/npm install.
# CI 와 같이 ffmpeg 가 있어야 설명형 강제 멈춤 시험이 건너뛰지 않는다.

# 임시 파일은 finish 직전에 지운다 — EXIT trap 을 걸면 공용 실행기의 안전장치(finish 누락 시 FAIL)를 덮어쓴다.
PYTEST_OUT="$(mktemp)"

# 파이썬 잡: 순수 로직 테스트 전체(-rs 로 건너뛴 이유를 남긴다)
run_pytest() {
  python3 -m pytest -q -rs | tee "$PYTEST_OUT"
  return "${PIPESTATUS[0]}"
}

# CI 의 "조용히 건너뛴 테스트" 가드 — 기준 14건(tests.yml 과 같은 값, 바꾸면 같이 바꾼다)
guard_skipped() {
  local skipped
  skipped=$(grep -oE '[0-9]+ skipped' "$PYTEST_OUT" | grep -oE '^[0-9]+' | tail -1)
  echo "   건너뛴 테스트: ${skipped:-0}건"
  [ "${skipped:-0}" -le 14 ]
}

step "pytest" run_pytest
step "건너뛴 테스트 가드(≤14)" guard_skipped

# 웹 잡: 순수 모듈 테스트 → 주류 순환 e2e(PGlite) → 타입 검사 → lint
step "web node --test" bash -c 'cd web && node --test lib/*.test.ts lib/work/*.test.ts lib/drinks/*.test.ts lib/drinks/work/*.test.ts components/drinks/topics/*.test.ts components/drinks/work/*.test.ts'
step "주류 순환 e2e" python3 -m pytest -q tests/test_drinks_loop_e2e.py tests/test_drinks_stage5_publish_loop.py tests/test_drinks_review_fixes.py
step "web tsc --noEmit" bash -c 'cd web && npx tsc --noEmit'
step "web lint" bash -c 'cd web && npm run lint'

rm -f "$PYTEST_OUT"
finish
