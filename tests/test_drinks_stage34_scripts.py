"""3·4단계 준비 스크립트 — 카드 대본 가짜 실행(0원)·질문 지도 검사기·음원 시험 게시 안전장치. 네트워크·DB·모델·게시 0."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import config
from engine import drinks_script_check as script_check
from scripts import card_plan_run as cpr
from scripts import card_reel_trial_publish as trial

ROOT = Path(__file__).resolve().parents[1]


def test_offline_job_runs_the_worker_path_without_db_or_model(tmp_path, monkeypatch):
    monkeypatch.setattr(cpr, "load_live_job", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("DB 를 읽으면 안 된다")))
    rc = cpr.main(["--offline", "--out", str(tmp_path)])
    assert rc == 0
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "succeeded" and rep["db_writes"] == {"plan_saves": 0, "cost_ledger_rows_attempted": 0} and rep["saved_to_db"] is False and rep["actual_usd"] == 0.0
    assert "drinks_develop_save_plan" in rep["rpc_calls"] and not any(re.search(r"approve|submit|select", c) for c in rep["rpc_calls"])
    assert rep["estimate_usd_per_call"] * (1 + config.DRINKS_DEVELOP_MAX_REWRITES) <= config.DRINKS_CARD_PLAN_RUN_CAP_USD, "한 소재는 상한 $0.15 안에서 다시 쓰기까지 된다"
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert plan["pages"][0]["role"] == "cover" and plan["pages"][-1]["role"] == "source" and plan["reel"]["hook_title"].endswith("?")
    assert (tmp_path / "source_table.md").exists() and (tmp_path / "question_map_check.md").exists()


def test_question_map_checker_catches_all_four_operator_rules():
    qm = cpr.question_map_check()
    assert qm["questions"] == sum(len(qs) for *_, qs in config.DRINKS_QUESTION_MAP) == 48, "8유형 × 3주종 × 2질문"
    assert qm["all_rules_caught_and_good_passes"], [r for r in qm["rows"] if not r["good"]["ok"] or not all(r[k]["caught"] for k in cpr.EXPECT)]


def test_formal_style_now_catches_every_nida_ending():
    """질문 지도 검사에서 드러난 구멍: '못합니다' 가 안 잡혔다. '아니다' 는 문어체가 아니다."""
    for s in ("미생물이 자라지 못합니다", "도수가 높습니다", "위스키입니다", "그렇게 됩니다", "술이 갑니다."):
        assert script_check._FORMAL.search(s), s
    for s in ("그건 술이 아니다", "도수가 높아요", "상하지 않는다"):
        assert not script_check._FORMAL.search(s), s


def test_live_call_needs_approval_words_and_cap(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(cpr, "load_live_job", lambda *_a, **_k: cpr.offline_job())
    monkeypatch.setattr(cpr.cp, "llm_write_card_plan", lambda *a, **k: called.append(1) or {})
    assert cpr.main(["--yes", "--out", str(tmp_path)]) == 2, "결재 문장 없으면 부르지 않는다"
    monkeypatch.setattr(config, "DRINKS_CARD_PLAN_RUN_CAP_USD", 0.0001)
    assert cpr.main(["--yes", "--approve", "해 봐", "--out", str(tmp_path)]) == 2, "예상액이 상한을 넘으면 부르지 않는다"
    assert called == []


def test_fake_plan_speaks_plainly_and_cites_each_claim():
    job = cpr.offline_job()
    plan = cpr.fake_card_plan(job["topic"]["question"], job["review"]["claims"], job["review"]["brief"])
    for p in plan["pages"]:
        if p["role"] == "explain":
            assert p["claim_ids"] and not script_check._FORMAL.search(p["body"].splitlines()[-1])
            assert all(len(l.replace(" ", "")) <= config.DRINKS_CARD_LINE_MAX_CHARS for l in p["body"].split("\n")), "뜻 단위·한 줄 상한"
    assert "왜" in plan["reel"]["hook_title"]


# ── 음원 시험 게시 ──

def test_trial_publish_has_no_publish_without_yes_and_warns_public():
    src = (ROOT / "scripts" / "card_reel_trial_publish.py").read_text(encoding="utf-8")
    assert "비공개로 올릴 수 없" in src and "공개 게시" in src
    assert src.index("if not args.yes:") < src.index("pub.run("), "--yes 분기 전에는 게시 코드가 없다"
    assert "max_items=1" in src, "1건만"
    assert "first_claimable" in src and "DRINKS_IG_LIVE" in src
    assert "drinks_publication_action" not in src and "approve" not in src.split("CHECKLIST")[1].split("def ")[0], "승인을 대신하지 않는다"
    assert len(trial.CHECKLIST) >= 8 and any("음원" in c for c in trial.CHECKLIST) and any("시작" in c for c in trial.CHECKLIST)


def test_trial_publish_filters_to_card_reels_with_audio():
    class Res:
        def __init__(self, data): self.data = data

    class Q:
        def __init__(self, table, store): self.t, self.s, self.f = table, store, {}
        def select(self, *_a): return self
        def eq(self, k, v): self.f[k] = v; return self
        def in_(self, k, v): self.f[k] = v; return self
        def lte(self, k, v): return self
        def order(self, *_a, **_k): return self
        def limit(self, _n): return self
        def execute(self):
            rows = self.s[self.t]
            for k, v in self.f.items():
                rows = [r for r in rows if (r.get(k) in v if isinstance(v, list) else r.get(k) == v)]
            return Res(rows)

    class Cli:
        def __init__(self, store): self.s = store
        def table(self, t): return Q(t, self.s)

    store = {
        "drink_publication_requests": [
            {"id": "r1", "topic_id": "t", "manifest_id": "m1", "post_type": "reel", "status": "scheduled", "audio": {"audio_id": "a", "audio_volume": 90, "video_volume": 10, "sync_grade": "sync_free"}, "account_id": "acc"},
            {"id": "r2", "topic_id": "t", "manifest_id": "m1", "post_type": "reel", "status": "scheduled", "audio": None, "account_id": "acc"},
            {"id": "r3", "topic_id": "t", "manifest_id": "m2", "post_type": "reel", "status": "scheduled", "audio": {"audio_id": "a"}, "account_id": "acc"},
        ],
        "drink_asset_manifests": [{"id": "m1", "format": "carousel"}, {"id": "m2", "format": "video"}],
        "drink_manifest_assets": [{"manifest_id": "m1", "role": "page"}, {"manifest_id": "m1", "role": "final_video"}, {"manifest_id": "m2", "role": "final_video"}],
        "drink_social_accounts": [{"id": "acc", "display_name": "시험", "connection": "fake", "external_account_id": "fake_1", "status": "verified", "publish_enabled": True}],
        "drink_topics": [{"id": "t", "title": "위스키"}],
    }
    cands = trial.find_candidates(Cli(store))
    assert [c["id"] for c in cands] == ["r1"], "음원이 없거나(r2) 카드 묶음이 아닌(r3) 것은 뺀다"
    assert "공개" not in trial.describe(cands[0]) and "음원 90 / 영상 10" in trial.describe(cands[0])
