"""공개 저장소 전환 가드(2026-09-15) — 규약을 주석이 아니라 테스트로 못박는다.

공개되면 공격자는 라우트·큐·워크플로를 전부 읽는다고 가정한다. 아래가 하나라도 깨지면
"브라우저/anon 자격만으로 비용·발행·운영 변경" 경로가 다시 열린다.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "web" / "app" / "api"
WRITE = re.compile(r"\.(insert|update|upsert|delete)\(")
HANDLER = re.compile(r"^export async function (POST|PUT|PATCH|DELETE)\([^)]*\)[^{]*\{", re.M)


def _write_routes():
    return [f for f in sorted(API.glob("*/route.ts")) if WRITE.search(f.read_text(encoding="utf-8"))]


def test_every_write_route_is_operator_gated_first():
    missing = []
    for f in _write_routes():
        src = f.read_text(encoding="utf-8")
        for m in HANDLER.finditer(src):
            body = [l.strip() for l in src[m.end():m.end() + 600].splitlines()
                    if l.strip() and not l.strip().startswith("//")]
            if not body or "requireOperator()" not in body[0]:
                missing.append(f"{f.parent.name}:{m.group(1)}")
    assert not missing, f"쓰기 라우트 맨 앞에 requireOperator() 가 없다: {missing}"


def test_every_write_route_writes_with_the_service_client():
    bad = [f.parent.name for f in _write_routes()
           if "const supabase = createClient();" in f.read_text(encoding="utf-8")]
    assert not bad, f"anon 클라이언트로 쓰는 라우트(0049 뒤엔 RLS 로 거부된다): {bad}"


def test_operator_guard_fails_closed_outside_development():
    src = (ROOT / "web" / "lib" / "apiGuard.ts").read_text(encoding="utf-8")
    assert "return null;\n  }\n  if (isOperator())" not in src
    assert 'if (!key) return process.env.NODE_ENV === "development";' in src


def test_middleware_matcher_has_no_extension_bypass():
    src = (ROOT / "web" / "middleware.ts").read_text(encoding="utf-8")
    matcher = re.search(r"matcher:\s*\[(.*?)\]", src, re.S).group(1)
    assert "png" not in matcher and "jpg" not in matcher, "확장자 제외는 동적 페이지 게이트 우회였다"


def test_every_edge_function_requires_the_invoke_secret():
    for f in sorted((ROOT / "supabase" / "functions").glob("*/index.ts")):
        src = f.read_text(encoding="utf-8")
        assert "function callerCheck" in src, f.parent.name
        serve = src.index("Deno.serve(")
        assert "callerCheck(req)" in src[serve:serve + 400], f"{f.parent.name}: 핸들러 앞단 검사 없음"
        # 거절 사유는 돌려주되 값은 절대 싣지 않는다
        assert "EDGE_INVOKE_SECRET" in src and "expected" in src
        assert "reason: expected" not in src


def test_edge_callers_send_the_invoke_secret():
    for f in API.glob("*/route.ts"):
        src = f.read_text(encoding="utf-8")
        if "functions/v1/" in src:
            assert '"x-edge-secret": edgeSecret' in src, f.parent.name
            assert "NEXT_PUBLIC_EDGE" not in src


def test_workflows_have_least_privilege_and_pinned_actions():
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        src = f.read_text(encoding="utf-8")
        assert re.search(r"^permissions:\s*\n\s+contents: read", src, re.M), f"{f.name}: 최상위 permissions 없음"
        for use in re.findall(r"uses:\s*(\S+)", src):
            assert re.search(r"@[0-9a-f]{40}$", use), f"{f.name}: SHA 고정 안 됨 → {use}"
        assert "pull_request_target" not in src, f.name
        assert "self-hosted" not in src, f.name
        # 입력값을 run: 스크립트에 직접 끼우지 않는다(셸 주입)
        for run in re.findall(r"run: \|\n((?:\s{10,}.*\n)+)", src):
            assert "${{ inputs." not in run and "${{ github.event.inputs." not in run \
                and "${{ github.head_ref" not in run, f"{f.name}: run 스크립트에 입력값 직접 삽입"


def test_lockdown_migration_closes_all_anon_writes():
    sql = (ROOT / "supabase" / "migrations" / "0049_public_repo_lockdown.sql").read_text(encoding="utf-8")
    assert "revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated" in sql
    assert "storage_objects_backup_20260821 enable row level security" in sql
