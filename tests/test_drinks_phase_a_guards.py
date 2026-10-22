"""주류 공장 A단계 경계 가드(2026-10-22) — 명세 docs/주류공장_구조명세_v1_2026-10-21.md §13-A.

A단계는 "수동 입력 → 근거 → 선정 → 공통 기획 → 형식별 제작안"까지다. 아래가 깨지면 주류 화면이
유료 생성·외부 발행 경로로 이어지거나, 주류 데이터가 anon 에게 열리거나, 논문·리포트 화면에 섞인다.
DB 동작 자체(전이·소유 관계·불변)는 supabase/tests/drinks_phase_a.test.mjs 가 실제 Postgres 로 검사한다.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MIG = ROOT / "supabase" / "migrations" / "0050_drinks_factory_phase_a.sql"


def _drinks_web_files():
    roots = [WEB / "app" / "drinks", WEB / "app" / "api" / "drinks", WEB / "components" / "drinks", WEB / "lib" / "drinks"]
    return [f for r in roots for f in r.rglob("*.ts*") if not f.name.endswith(".test.ts")]


def test_drinks_route_is_operator_gated_first_and_uses_service_client():
    src = (WEB / "app" / "api" / "drinks" / "route.ts").read_text(encoding="utf-8")
    m = re.search(r"export async function POST\([^)]*\)[^{]*\{", src)
    first = [l.strip() for l in src[m.end():].splitlines() if l.strip() and not l.strip().startswith("//")][0]
    assert first == "const denied = await requireOperator();"
    assert "createAdminClient()" in src
    assert "queueWriter" not in src, "anon 폴백 금지 — 주류 표는 anon 권한이 없다"
    assert not re.search(r"^export async function (GET|PUT|PATCH|DELETE)", src, re.M)


def test_drinks_code_never_reaches_render_or_publish_paths():
    banned = ["trigger-render", "trigger-publish", "render_jobs", "upload_requests", "report_render_jobs",
              "report_upload_requests", "functions/v1/", "workflow_dispatch", "GITHUB_DISPATCH_TOKEN",
              "draft_requests", "directive_requests", "image_batch_jobs"]
    def code(f):  # 주석 줄은 뺀다 — "이 경로를 쓰지 않는다"는 설명까지 걸리면 안 된다
        return "\n".join(l for l in f.read_text(encoding="utf-8").splitlines()
                         if not l.strip().startswith(("//", "*", "/*")))
    hits = [f"{f.relative_to(WEB)}: {b}" for f in _drinks_web_files() for b in banned if b in code(f)]
    assert not hits, "주류 A단계 코드가 유료 생성·발행 경로를 참조한다:\n" + "\n".join(hits)


def test_drinks_queries_are_server_only():
    for f in _drinks_web_files():
        src = f.read_text(encoding="utf-8")
        if '"use client"' in src:
            assert "lib/drinks/queries" not in src and "supabase/admin" not in src, f"{f.name}: 클라이언트가 service key 경로를 import"


def test_migration_grants_nothing_to_anon_and_adds_no_job_or_publish_tables():
    sql = MIG.read_text(encoding="utf-8").lower()
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", sql), "anon/authenticated/public 에 grant 금지"
    assert "create policy" not in sql, "주류 표는 정책 없이 RLS 로 전면 차단한다"
    tables = re.findall(r"create table if not exists (\w+)", sql)
    assert sorted(tables) == sorted([
        "drink_source_snapshots", "drink_snapshot_attestations", "drink_topics", "drink_topic_sources",
        "drink_topic_reviews", "drink_deliverables", "drink_plan_revisions", "drink_workflow_events"])
    for t in tables:
        assert f"alter table {t} enable row level security" in sql, t
    # 기존 paper/report 표를 건드리지 않는다
    altered = set(re.findall(r"alter table (\w+)", sql))
    assert altered <= set(tables), f"주류 외 표 변경: {altered - set(tables)}"


def test_factory_branch_is_explicit_for_drinks():
    shell = (WEB / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    assert 'pathname === "/drinks" || pathname.startsWith("/drinks/")' in shell
    nav = (WEB / "lib" / "nav.ts").read_text(encoding="utf-8")
    assert 'case "drinks":' in nav and "GROUPS_DRINKS" in nav


def test_ci_runs_drinks_unit_and_db_tests():
    """DB 무결성 검사(PGlite)가 CI 의 필수 검사로 돈다 — 임시 폴더·수동 설치 없이."""
    import json
    wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "lib/drinks/*.test.ts" in wf
    assert (WEB / "lib" / "drinks" / "drinks.db.test.ts").exists()
    pkg = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", pkg["devDependencies"]["@electric-sql/pglite"]), "정확한 버전으로 고정"
    lock = (WEB / "package-lock.json").read_text(encoding="utf-8")
    assert '"node_modules/@electric-sql/pglite"' in lock


def test_db_test_does_not_grant_privileges_itself():
    """하네스가 GRANT 를 따로 주면 마이그레이션의 권한 누락을 가린다."""
    src = (WEB / "lib" / "drinks" / "drinks.db.test.ts").read_text(encoding="utf-8").lower()
    assert "grant select" not in src and "grant all" not in src and "grant insert" not in src
