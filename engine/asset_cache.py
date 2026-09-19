"""에셋 캐시를 **어느 공장의 표에 둘지** 정하는 한 자리 (2026-09-19).

무엇을 푸는가: 두 공장이 같은 렌더 경로를 쓰는데 캐시 표는 서로 다르다.
`render_assets.directive_id` 는 `directives(id)` 를, `report_render_assets.directive_id` 는
`report_directives(id)` 를 가리킨다 — 리포트 지시서 id 를 논문 표에 넣으면 FK 위반이다.
그래서 리포트 렌더는 지금까지 `directive_id=None` 으로 불러 **캐시를 통째로 포기**했다
(0020 마이그레이션이 표는 만들어 뒀지만 "PF2 v1 미배선"이라고 적힌 그 자리다).

대가는 돈이다: 리포트는 **다시 렌더할 때마다 그림을 다시 산다.** 언어를 늘려도 공유가
안 된다. 첫 시퀀스만 먼저 사 보고 나중에 편 전체를 조립하는 일도 불가능했다.

여기서 하는 일은 **표를 고르는 것 하나뿐**이다. 키(content_hash)·정책·순서는 render.py 가
그대로 갖는다 — 캐시 판정을 두 벌로 만들면 한쪽만 고쳐지는 날이 온다.

★ 원장(generation_attempts)은 **여기로 오지 않는다.** 그 표의 FK 는 논문 directives 뿐이라
  리포트 id 를 넣을 수 없다. `ledger_directive_id()` 가 그 경계다.
"""

from __future__ import annotations

from typing import Any

REPORT = "report"


def _store(kind: str):
    """이 공장의 캐시 표를 다루는 모듈."""
    if str(kind) == REPORT:
        from . import report_db
        return report_db
    from . import db
    return db


def storage_prefix(kind: str, directive_id: str) -> str:
    """Storage 안 경로 접두. 리포트 mp4 가 이미 `report/` 아래 있으므로 에셋도 같이 둔다."""
    return f"report/{directive_id}" if str(kind) == REPORT else str(directive_id)


def get(kind: str, directive_id: str, cut_no: int, asset_type: str) -> dict[str, Any] | None:
    return _store(kind).get_render_asset(directive_id, cut_no, asset_type)


def put(kind: str, row: dict[str, Any]) -> None:
    _store(kind).upsert_render_asset(row)


def upload(kind: str, local_path: str, dest_path: str, content_type: str) -> str:
    return _store(kind).upload_render(local_path, dest_path, content_type)


def ledger_directive_id(kind: str, directive_id: str | None) -> str | None:
    """비용 원장에 실을 directive_id.

    ★ 리포트는 **항상 None** 이다. `generation_attempts.directive_id` 가 논문 `directives` 를
      참조하므로 리포트 지시서 id 를 넣으면 insert 가 통째로 실패한다 — 그러면 캐시를 켠
      대가로 원장이 끊긴다. 캐시는 켜고 원장은 종전대로 `render_job_id` 로 묶는다.
    """
    return None if str(kind) == REPORT else directive_id
