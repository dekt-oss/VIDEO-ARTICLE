# -*- coding: utf-8 -*-
"""만들어 놓고 아무도 안 부르는 것 전수 조사.

    python -m scripts.sweep_unwired

★ 왜: 2026-08-30 하루에 같은 종류 결함이 **다섯 번** 나왔다 —
  change_prose · entity_prose · effective_visual_role · Veo 프롬프트 · 영상 컷 분기.
  전부 "만들었는데 한쪽만 연결" 이었고 전부 **그림이 이상해서 우연히** 찾았다. 그건 운이다.

★ 이름마다 전체를 훑으면 느리다. **파일을 한 번만 토큰화**해 세고 이름을 조회한다.
"""
import ast
import collections
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(".")
_B = chr(92) + chr(98)   # 워드 경계. 셸을 거치면 제어문자로 둔갑해 조용히 죽는다
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# ── 1. engine/ 의 공개 이름 수집 ────────────────────────────
decls: dict[str, list[tuple[str, int, str]]] = collections.defaultdict(list)
for path in sorted(ROOT.glob("engine/**/*.py")):
    if path.name == "__init__.py":
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                decls[node.name].append((path.as_posix(), node.lineno, "함수"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            n = node.target.id
            if n.isupper() and not n.startswith("_"):
                decls[n].append((path.as_posix(), node.lineno, "상수"))

# ── 2. 파일별 토큰을 **한 번만** 센다 ────────────────────────
prod_use: dict[str, set[str]] = collections.defaultdict(set)   # 이름 → 쓰는 제품 파일
test_use: dict[str, int] = collections.Counter()

def scan(paths, is_test):
    for p in paths:
        if not p.is_file() or p.suffix not in (".py", ".ts", ".tsx", ".sql", ".yml", ".yaml"):
            continue
        rel = p.as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for tok in set(WORD.findall(text)):
            if tok not in decls:
                continue
            if is_test:
                test_use[tok] += 1
            else:
                prod_use[tok].add(rel)

scan(ROOT.glob("tests/**/*"), True)
for area in ("engine", "scripts", "web", "supabase", "tools"):
    scan(ROOT.glob(f"{area}/**/*"), False)

# ── 3. 판정 ─────────────────────────────────────────────────
only_tests, nobody = [], []
# ★ 자기 모듈 **안에서** 쓰이면 배선된 것이다(내부 헬퍼). 선언 줄만 있는 경우를 가른다.
own_internal: dict[str, bool] = {}
for name, sites in decls.items():
    used_inside = False
    for rel, ln, _kind in sites:
        text = pathlib.Path(rel).read_text(encoding="utf-8", errors="ignore")
        # 선언 줄을 뺀 나머지에서 이름이 다시 나오는가
        lines = text.splitlines()
        rest = chr(10).join(l for i, l in enumerate(lines, 1) if i != ln)
        if re.search(_B + re.escape(name) + _B, rest):
            used_inside = True
            break
    own_internal[name] = used_inside

for name, sites in decls.items():
    own = {s[0] for s in sites}
    others = prod_use.get(name, set()) - own
    if others or own_internal.get(name):
        continue
    row = (sites[0][0], sites[0][1], sites[0][2], name, test_use.get(name, 0))
    (only_tests if test_use.get(name, 0) else nobody).append(row)

only_tests.sort(key=lambda r: r[0])
nobody.sort(key=lambda r: r[0])

print("=" * 78)
print(f"★ 테스트만 부르고 **제품 코드는 아무도 안 부르는 것**: {len(only_tests)}건")
print("   ('테스트는 통과하는데 화면은 그대로' 의 정확한 모양)")
print("=" * 78)
for rel, ln, kind, name, th in only_tests:
    print(f"  {rel}:{ln}  {kind} {name}  (테스트 {th}파일)")

print()
print("=" * 78)
print(f"아무도 안 부르는 것(테스트조차): {len(nobody)}건")
print("=" * 78)
for rel, ln, kind, name, _ in nobody:
    print(f"  {rel}:{ln}  {kind} {name}")
