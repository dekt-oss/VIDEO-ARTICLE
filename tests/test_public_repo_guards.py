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
            # ★ Next 15(2026-09-16): cookies() 가 async 라 게이트도 async 다.
            #   `await` 를 빠뜨리면 반환값이 Promise(항상 truthy)라 라우트가 통째로 막히고,
            #   더 나쁜 쪽으로는 isOperator() 를 await 없이 쓰면 **항상 통과**한다.
            if not body or "await requireOperator()" not in body[0]:
                missing.append(f"{f.parent.name}:{m.group(1)}")
    assert not missing, f"쓰기 라우트 맨 앞에 `await requireOperator()` 가 없다: {missing}"


def test_operator_checks_are_always_awaited():
    """`isOperator()` / `requireOperator()` 를 await 없이 부르는 곳이 없어야 한다.

    await 를 빠뜨린 `isOperator()` 는 Promise 라 언제나 truthy 다 — 게이트가 조용히
    **전부 통과**로 뒤집힌다. 타입검사는 잡아주지 못하는 형태(조건식에 Promise 를 쓰는 것은
    TS 가 허용한다)라 소스 형태로 못박는다.
    """
    web = ROOT / "web"
    bad = []
    for f in sorted(list(web.rglob("*.ts")) + list(web.rglob("*.tsx"))):
        if "node_modules" in f.parts or f.name == "apiGuard.ts":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for call in ("isOperator()", "requireOperator()"):
                if call in line and f"await {call}" not in line:
                    bad.append(f"{f.relative_to(web)}:{i}: {line.strip()}")
    assert not bad, "await 없는 운영자 검사(게이트가 항상 통과로 뒤집힌다):\n" + "\n".join(bad)


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


def test_middleware_matcher_does_not_exempt_the_image_optimizer():
    """`_next/image` 실행 표면을 **두 겹**으로 없앤다 (2026-09-16).

    GHSA-2xp9-vwfh-vxw4 는 Image Optimization API 의 미인증 RCE 다(next < 15.5.24).
    이 앱은 next/image 를 쓰지 않으므로 그 경로를 통째로 없앤다.

    ★ 왜 두 겹인가 — 프로덕션 실측으로 배운 것:
      middleware 의 matcher 예외만 빼면 **로컬 `next start` 에서는** 307 로 막힌다.
      그런데 **Vercel 에서는 안 막힌다** — `/_next/image?url=…` 가 400 을 내고 헤더에
      `X-Vercel-Error: INVALID_IMAGE_OPTIMIZE_REQUEST` 가 찍힌다. 그 경로는 Vercel
      플랫폼의 최적화기가 **Next 미들웨어보다 앞에서** 처리하기 때문이다.
      그래서 `next.config.mjs` 의 `images.unoptimized` 로 빌드 산출물 단계에서 끈다.
      matcher 쪽도 그대로 둔다(로컬·자체호스팅에서 유효).
    """
    src = (ROOT / "web" / "middleware.ts").read_text(encoding="utf-8")
    matcher = re.search(r"matcher:\s*\[(.*?)\]", src, re.S).group(1)
    assert "_next/image" not in matcher, "이미지 최적화 엔드포인트가 게이트 밖에 있다"

    cfg = (ROOT / "web" / "next.config.mjs").read_text(encoding="utf-8")
    assert re.search(r"images:\s*\{[^}]*unoptimized:\s*true", cfg), (
        "next.config 에 images.unoptimized 가 없다 — Vercel 에서는 미들웨어가 "
        "`/_next/image` 를 막지 못한다(플랫폼이 앞단에서 처리한다)"
    )

    # `next/image` 를 **import 하는** 곳만 센다. next-env.d.ts 의
    # `types="next/image-types/global"` 은 Next 가 만드는 줄이라 사용처가 아니다.
    web = ROOT / "web"
    imports = re.compile(r"""["']next/image["']""")
    users = sorted(
        str(f.relative_to(web)).replace("\\", "/")
        for f in list(web.rglob("*.tsx")) + list(web.rglob("*.ts"))
        if "node_modules" not in f.parts
        and f.name != "middleware.ts"
        and imports.search(f.read_text(encoding="utf-8"))
    )
    assert not users, f"next/image 사용처가 생겼다 — 게이트 예외 여부를 다시 판단할 것: {users}"


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
