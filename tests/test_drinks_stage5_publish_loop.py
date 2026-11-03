"""5단계 게시 연결·크론·성과 루프(0068) — 돈·네트워크·공개 게시 0. docs/deviation-drinks-stage5-publish-loop.md

두 층이다:
  ① 순수 시험: 워커의 형식별 게시 문(밈 게이트·AI 표기), 전략의 형식 묶음, 크론·상수의 파이썬↔워크플로↔SQL 동기화. 언제나 돈다.
  ② 진짜 SQL(PGlite) + 진짜 워커 + 가짜 공급자로 밈·설명형·카드 한 편씩을 게시 요청 → 가짜 게시 → 성과 → 전략까지:
     web/node_modules 와 ffmpeg 가 있을 때만(scripts/publish_loop_rehearsal.py). CI 는 web 잡이 돌린다.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from engine import config
from engine import drinks_publish as pub
from engine import drinks_strategy as ds

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0068_drinks_stage5_publish_loop.sql").read_text(encoding="utf-8")
WF = (ROOT / ".github" / "workflows" / "drinks-publish.yml").read_text(encoding="utf-8")
needs_db = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("node") and (ROOT / "web" / "node_modules" / "@electric-sql" / "pglite").exists()),
                              reason="ffmpeg·node·web/node_modules 필요")


def _spec(**o):
    base = {"frame": "top_text", "top_line": "POV", "beats": [{"text": "a", "ms": 3000}, {"text": "b", "ms": 4000}], "caption": "다들 이러잖아요",
            "scene": {"source": "text_bg", "palette": "wine"}, "sync_grade": "sync_free", "audio": {"mode": "ambient_local"}, "contains_info": False, "claim_ids": []}
    base.update(o)
    return base


# ── 워커의 형식별 게시 문 ──────────────────────────────────────

def test_format_gate_blocks_sync_required_meme_and_missing_spec():
    assert pub.format_gate({"content_format": "meme", "caption": "x", "meme_spec": _spec()}) is None
    code, _msg = pub.format_gate({"content_format": "meme", "caption": "x",
                                  "meme_spec": _spec(sync_grade="sync_required", audio={"mode": "app_manual", "title": "t", "start_hint_sec": 3})})
    assert code == "sync_required", "박자 맞춤은 워커도 다시 막는다(assert_auto_publishable)"
    assert pub.format_gate({"content_format": "meme", "caption": "x"})[0] == "meme_spec_missing"


def test_format_gate_requires_ai_label_for_explainer_and_bought_scene_meme():
    assert pub.format_gate({"content_format": "explainer", "caption": "물 이야기"})[0] == "ai_label_missing"
    assert pub.format_gate({"content_format": "explainer", "caption": f"물 이야기\n{config.DRINKS_AI_LABEL_TEXT}"}) is None
    bought = _spec(scene={"source": "bought_reaction", "asset_id": "a"})
    assert pub.format_gate({"content_format": "meme", "caption": "농담", "meme_spec": bought})[0] == "ai_label_missing"
    assert pub.format_gate({"content_format": "meme", "caption": "농담 — AI 생성 영상", "meme_spec": bought}) is None


def test_format_gate_is_transparent_for_cards_and_pre_0068_rows():
    assert pub.format_gate({"content_format": "card", "caption": "카드"}) is None
    assert pub.format_gate({"caption": "0068 전 DB 는 content_format 을 안 준다"}) is None


def test_publish_one_pauses_meme_before_any_provider_call():
    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        return {"status": "paused", **p} if fn == "drinks_finish_publication" else {}

    class NoProvider:
        def __call__(self, acc):
            raise AssertionError("게시 문에서 막혔으면 공급자를 만들지 않는다")

    req = {"request_id": "r", "lease_token": "l", "account": {"connection": "fake"}, "post_type": "reel", "caption": "x", "content_format": "meme",
           "meme_spec": _spec(sync_grade="sync_required", audio={"mode": "app_manual", "title": "t", "start_hint_sec": 3}), "claims": [], "files": []}
    out = pub.publish_one(req, rpc, storage=None, providers=NoProvider(), wait_sec=0, poll_sec=0)
    assert out["status"] == "paused" and out["error_code"] == "sync_required"
    assert [fn for fn, _ in calls] == ["drinks_finish_publication"], "컨테이너·게시 호출 0"


# ── 전략: 형식 묶음 ───────────────────────────────────────────

LIM = {"strategy_min_group": 3, "strategy_min_total": 6, "strategy_max_step": 0.2, "strategy_max_lift": 0.5, "strategy_bucket": "72h"}


def _post(fmt, saved, cats=("whisky",)):
    return {"categories": list(cats), "post_type": "reel", "lane": "evergreen", "slot": "evening", "question_kind": "general", "format": fmt,
            "values": {"reach": 1000, "saved": saved, "shares": saved // 2}}


def test_strategy_groups_by_content_format():
    posts = [_post("meme", 80), _post("meme", 70), _post("meme", 90), _post("card", 10), _post("card", 12), _post("card", 8)]
    out = ds.propose({"limits": LIM, "active": {"id": "v0", "weights": {}}, "posts": posts})
    assert out["sufficient"] is True
    assert out["weights"]["format"]["meme"] == 0.2 and out["weights"]["format"]["card"] == -0.2
    assert "format" in ds.DIMENSIONS and "콘텐츠 형식" in out["summary_ko"]


def test_strategy_without_format_values_does_not_send_unknown_dimension():
    """0068 전 DB(0055·0058)는 format 값을 주지 않는다 — 옛 DB 가 거부하는 차원 이름을 보내지 않는다(e2e 다리는 0056 까지다)."""
    posts = [{"categories": ["whisky"], "post_type": "carousel", "lane": "evergreen", "slot": "evening", "values": {"reach": 1000, "saved": 50, "shares": 5}}] * 6
    out = ds.propose({"limits": LIM, "active": {"id": "v0", "weights": {"category": {}, "post_type": {}, "lane": {}, "slot": {}}}, "posts": posts})
    assert "format" not in out["weights"] and "question_kind" not in out["weights"]


# ── 파이썬 ↔ 워크플로 ↔ SQL 동기화 ──────────────────────────────

def test_workflow_crons_match_config_and_default_off_gate():
    wf = yaml.safe_load(WF)
    crons = [c["cron"] for c in (wf.get("on") or wf.get(True))["schedule"]]
    assert sorted(crons) == sorted([config.DRINKS_PUBLISH_CRON_PUBLISH, config.DRINKS_PUBLISH_CRON_METRICS, config.DRINKS_PUBLISH_CRON_STRATEGY])
    job = wf["jobs"]["run"]
    assert f"vars.{config.DRINKS_PUBLISH_CRON_VAR} == '1'" in job["if"] and "github.event_name != 'schedule'" in job["if"]
    # 예약 실행이 어느 단계인지는 크론 문자열로 정한다 — 성과·전략 크론이 바뀌면 여기도 바뀌어야 한다
    assert f"github.event.schedule == '{config.DRINKS_PUBLISH_CRON_METRICS}' && 'metrics'" in job["env"]["STEP"]
    assert f"github.event.schedule == '{config.DRINKS_PUBLISH_CRON_STRATEGY}' && 'strategy'" in job["env"]["STEP"]
    steps = {s["name"]: s for s in job["steps"] if "name" in s}
    assert steps["publish"]["if"] == "env.STEP == 'publish'" and steps["metrics"]["if"] == "env.STEP == 'metrics'" and steps["strategy"]["if"] == "env.STEP == 'strategy'"


def test_publish_cron_is_kst_daytime_every_30_minutes_and_metrics_after_collect():
    """총괄계획 §5: 게시는 예약 시각(낮·저녁), 성과는 매일(수집 06:30·트렌드 07:30 뒤), 전략은 주 1회."""
    m = re.fullmatch(r"0,30 (\d+)-23,0-(\d+) \* \* \*", config.DRINKS_PUBLISH_CRON_PUBLISH)
    assert m, "게시 크론은 UTC 저녁~다음날 낮 = KST 아침~밤"
    assert (int(m.group(1)) + 9) % 24 == 7 and int(m.group(2)) + 9 == 23, "KST 07:00 부터 23:30 까지"
    h_metrics = int(config.DRINKS_PUBLISH_CRON_METRICS.split()[1])
    assert (h_metrics + 9) % 24 == 8, "성과 수집은 KST 08시대(06:30 수집·07:30 트렌드 뒤)"
    assert config.DRINKS_PUBLISH_CRON_STRATEGY.split()[-1] == "0", "전략은 주 1회(일요일 UTC 밤 = 월요일 KST 아침)"


def test_sql_constants_match_python():
    assert f"select '{config.DRINKS_AI_LABEL_TEXT}'::text" in SQL
    assert "content_format in ('card','explainer','meme')" in SQL
    for f in config.DRINKS_CONTENT_FORMATS:
        assert f"'{f}'" in SQL
    assert "('category','post_type','lane','slot','question_kind','format')" in SQL, "전략 차원 목록이 engine/drinks_strategy.DIMENSIONS 와 같다"
    assert set(ds.DIMENSIONS) == {"category", "post_type", "lane", "slot", "question_kind", "format"}


def test_sql_keeps_the_meme_gate_three_layers_and_old_digest():
    code = "\n".join(l.split("--", 1)[0] for l in SQL.splitlines())
    assert "status not in ('publish_waiting','published') or sync_grade = 'sync_free'" in code, "표 제약: 게시 대기·게시됨은 박자 무관만"
    assert "'meme_not_publishable'" in code and "d.status = 'publish_waiting'" in code, "게시 직전 재확인"
    assert "meme_sync_blocked" in code, "발행안 작성 때도 박자 맞춤 거부"
    assert "case when r.meme_draft_id is null then '' else '|meme:'" in code, "옛 행의 승인 지문은 글자 하나까지 같다"
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", code.lower()) and "create policy" not in code.lower()
    assert "drinks_create_meme_publication" in code and "drinks_pub_ai_label_missing" in code


def test_worker_has_the_meme_gate_and_rehearsal_exists():
    src = (ROOT / "engine" / "drinks_publish.py").read_text(encoding="utf-8")
    assert "assert_auto_publishable" in src and "format_gate" in src
    assert (ROOT / "scripts" / "publish_loop_rehearsal.py").exists()


# ── ② 진짜 SQL + 진짜 워커 + 가짜 공급자 ─────────────────────────

@needs_db
def test_rehearsal_three_formats_publish_and_metrics(tmp_path):
    from scripts import publish_loop_rehearsal as rh

    report = rh.run(tmp_path / "publish-loop")
    failed = [k for k, v in report["checks"].items() if not v]
    assert not failed, f"실패: {failed}\n{report}"
    assert report["tripwire_hits"] == [] and report["cost_usd"] == 0 and report["public_posts"] == 0
