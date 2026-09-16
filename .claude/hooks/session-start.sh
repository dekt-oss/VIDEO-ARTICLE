#!/bin/bash
# SessionStart hook — video-article
# 프로젝트 골격이 생기면 의존성을 자동 설치한다. 아직 없으면(현재 상태) 안내만 하고 정상 종료한다.
# 멱등(여러 번 실행 안전)·비대화식.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$ROOT"

did_something=0

# --- Python 엔진 (engine/) ---
if [ -f "engine/requirements.txt" ]; then
  echo "[session-start] engine/requirements.txt 발견 → pip 설치"
  python3 -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  python3 -m pip install --quiet -r engine/requirements.txt
  # 엔진을 모듈로 import 할 수 있게 루트를 PYTHONPATH에 추가(세션 동안 유지)
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export PYTHONPATH="."' >> "$CLAUDE_ENV_FILE"
  fi
  did_something=1
elif [ -f "engine/pyproject.toml" ]; then
  echo "[session-start] engine/pyproject.toml 발견 → pip 설치(editable)"
  python3 -m pip install --quiet -e ./engine
  did_something=1
fi

# --- Next.js 대시보드 (web/) ---
# 컨테이너 상태가 캐시되므로 ci 대신 install 선호.
if [ -f "web/package.json" ]; then
  echo "[session-start] web/package.json 발견 → npm 설치"
  ( cd web && npm install --no-audit --no-fund )
  did_something=1
fi

if [ "$did_something" -eq 0 ]; then
  echo "[session-start] 아직 설치할 프로젝트 골격이 없습니다(engine/·web/ 미생성)."
  echo "[session-start] docs/작업계획서.md의 M0부터 진행하세요. (no-op 종료)"
fi

exit 0
