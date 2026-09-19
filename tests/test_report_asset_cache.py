"""리포트 라인의 에셋 캐시 배선 (2026-09-19).

무엇이 문제였나: 두 공장이 같은 렌더 경로를 쓰는데 캐시 표의 FK 가 다르다
(`render_assets` → `directives`, `report_render_assets` → `report_directives`).
리포트 워커는 그래서 `directive_id=None` 으로 불러 **캐시를 통째로 포기**했다 —
0020 마이그레이션이 표까지 만들어 두고 "PF2 v1 미배선"이라 적은 그 자리다.

대가는 돈이었다: 리포트는 다시 렌더할 때마다 그림을 다시 샀고, 언어를 늘려도 공유가 없었다
(논문 라인은 공유한다). 시퀀스 하나만 먼저 사 보고 나중에 편 전체를 조립하는 것도 불가능했다.

여기서 못박는 것은 넷이다:
  ① 표를 **kind 로 가른다**(리포트 id 가 논문 표에 가면 FK 위반이다)
  ② 원장(generation_attempts)에는 리포트 id 가 **가지 않는다** — 그 표의 FK 는 논문 하나뿐이라
     넣으면 insert 가 통째로 거부된다(이 저장소가 겪은 "$1.47 쓰고 원장 0행"의 재발)
  ③ 리포트 워커가 **실제로** directive_id 를 넘긴다(배선이 코드에 남아 있는지)
  ④ 공짜 제공자(placeholder·reuse)는 **유료로 취급되지 않는다**
"""

from __future__ import annotations

import pathlib

from engine import asset_cache, config, cost

SRC = pathlib.Path(__file__).resolve().parents[1] / "engine"


# ── ① 표를 kind 로 가른다 ───────────────────────────────────────────
def test_the_two_factories_read_and_write_different_tables():
    from engine import db, report_db

    assert asset_cache._store("report") is report_db
    assert asset_cache._store("paper") is db
    assert asset_cache._store("") is db, "모르는 kind 는 논문 쪽(기존 동작)으로 둔다"


def test_the_report_table_is_the_one_whose_foreign_key_points_at_report_directives():
    """표 이름을 문자열로 못박는다 — 여기를 잘못 고치면 **FK 위반으로 캐시가 통째로 죽는다.**"""
    src = (SRC / "report_db.py").read_text(encoding="utf-8")
    assert 'table("report_render_assets")' in src
    mig = (SRC.parent / "supabase" / "migrations" / "0020_report_render.sql"
           ).read_text(encoding="utf-8")
    assert "report_render_assets" in mig and "references report_directives(id)" in mig


def test_report_assets_do_not_collide_with_paper_assets_in_storage():
    """같은 버킷을 쓰므로 경로가 갈려야 한다 — 두 공장의 uuid 가 겹칠 일은 없지만,
    사람이 버킷을 열어 볼 때 어느 공장 것인지 보이는 편이 낫다(mp4 가 이미 report/ 아래다)."""
    assert asset_cache.storage_prefix("report", "abc") == "report/abc"
    assert asset_cache.storage_prefix("paper", "abc") == "abc"


# ── ② 원장은 FK 경계를 넘지 않는다 ─────────────────────────────────
def test_the_ledger_never_carries_a_report_directive_id():
    """`generation_attempts.directive_id` 는 논문 `directives` **하나만** 참조한다(0016).
    리포트 id 를 실으면 insert 가 거부되고, 캐시를 켠 대가로 원장이 끊긴다."""
    row = cost.build_attempt(
        asset_type="image", provider="gemini", model_id=config.IMAGE_MODEL,
        generation_mode="realtime", unit_type="image_standard", requested_units=1,
        directive_id="11111111-1111-1111-1111-111111111111",
        render_job_id="job-1", render_job_kind="report", cut_no=3)
    assert row["directive_id"] is None
    assert row["render_job_id"] == "job-1", "리포트 행은 잡 번호로 묶인다"
    assert row["render_job_kind"] == "report"


def test_the_paper_ledger_keeps_its_directive_id():
    row = cost.build_attempt(
        asset_type="image", provider="gemini", model_id=config.IMAGE_MODEL,
        generation_mode="realtime", unit_type="image_standard", requested_units=1,
        directive_id="22222222-2222-2222-2222-222222222222",
        render_job_id="job-2", render_job_kind="paper", cut_no=3)
    assert row["directive_id"] == "22222222-2222-2222-2222-222222222222"


# ── ③ 리포트 워커가 실제로 배선돼 있다 ─────────────────────────────
def test_the_report_worker_passes_its_directive_id_now():
    src = (SRC / "report_render.py").read_text(encoding="utf-8")
    assert "directive_id=directive_id, lang=lang" in src, (
        "리포트 워커가 다시 directive_id=None 으로 돌아가면 캐시가 통째로 죽는다 — "
        "조용히 죽는 종류라(비용만 늘어난다) 여기서 막는다")
    assert 'render_job_kind="report"' in src


def test_the_renderer_routes_the_cache_through_asset_cache_not_db_directly():
    """`db.get_render_asset` 을 직접 부르면 리포트 렌더가 논문 표를 친다 — FK 위반이다."""
    src = (SRC / "render.py").read_text(encoding="utf-8")
    assert "db.get_render_asset(" not in src
    assert "db.upsert_render_asset(" not in src
    assert "asset_cache.get(render_job_kind" in src
    assert "asset_cache.put(render_job_kind" in src


# ── ④ 공짜 제공자를 유료로 세지 않는다 ─────────────────────────────
def test_reuse_and_placeholder_are_free(monkeypatch):
    """★ `reuse` 는 지난 렌더의 PNG 를 **복사만** 한다. 예전에는 판정이 여섯 자리에 흩어져
    `("placeholder", "")` 만 봤고, 그래서 reuse 가 유료로 취급됐다 — 한 푼도 안 나갔는데
    비용 원장에 정가가 쌓이고, 캐시를 켜면 빌려 온 그림이 정본 자리에 앉을 수 있었다."""
    for p in ("placeholder", "reuse", ""):
        monkeypatch.setattr(config, "IMAGE_PROVIDER", p)
        assert config.image_is_paid() is False, p
    monkeypatch.setattr(config, "IMAGE_PROVIDER", "gemini")
    assert config.image_is_paid() is True
    for p in ("placeholder", "reuse", ""):
        monkeypatch.setattr(config, "VIDEO_PROVIDER", p)
        assert config.video_is_paid() is False, p
    monkeypatch.setattr(config, "VIDEO_PROVIDER", "veo")
    assert config.video_is_paid() is True
