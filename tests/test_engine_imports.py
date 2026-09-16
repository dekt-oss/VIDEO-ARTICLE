"""엔진 모듈의 이름 바인딩 정합성 검사.

왜 있나 (실제 사고):
  engine/report_db.py 가 `config.RENDER_STALE_MINUTES` 를 쓰면서 config 를 임포트하지 않았다.
  이 코드는 **렌더 잡을 처음 집어갈 때만** 실행되는 경로라, 리포트 렌더 잡이 하나도 없던
  동안에는 아무 문제가 없었다. 리포트 공장의 첫 렌더 요청이 들어온 순간
  `NameError: name 'config' is not defined` 로 워커가 죽었고, 잡은 110분간 queued 로
  방치됐다(2026-07-29). 임포트 하나 빠진 것을 잡는 데 두 시간이 걸린 셈이다.

  단위 테스트로는 이런 '드물게 실행되는 경로'를 다 덮을 수 없다. 그래서 실행 대신
  **소스를 AST 로 훑어** config 를 쓰면서 바인딩하지 않은 모듈이 있는지 정적으로 본다.
  네트워크·DB·무거운 의존성 없이 즉시 돈다.
"""

from __future__ import annotations

import ast
import pathlib

ENGINE_DIR = pathlib.Path(__file__).resolve().parent.parent / "engine"


def _uses_config_without_binding(path: pathlib.Path) -> bool:
    """`config.X` 를 쓰는데 config 라는 이름을 임포트하지 않는가.

    AST 를 쓰므로 주석·독스트링 안의 'config.' 는 세지 않는다.
    함수 안 지연 임포트(`from . import config`)도 바인딩으로 인정한다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bound: set[str] = set()
    uses_config = False

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif (isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Name)
              and node.value.id == "config"):
            uses_config = True

    return uses_config and "config" not in bound


def test_no_engine_module_uses_config_without_importing_it():
    offenders = [
        str(p.relative_to(ENGINE_DIR.parent))
        for p in sorted(ENGINE_DIR.rglob("*.py"))
        if p.name != "config.py" and _uses_config_without_binding(p)
    ]
    assert not offenders, (
        "config 를 임포트하지 않고 쓰는 모듈: " + ", ".join(offenders)
    )


def test_report_db_binds_config():
    """실제로 터졌던 모듈 — 회귀 고정."""
    from engine import report_db

    assert hasattr(report_db, "config")
    assert isinstance(report_db.config.RENDER_STALE_MINUTES, int)
