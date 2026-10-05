from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import compare_explanation_v2


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.operations = []

    def select(self, columns):
        self.operations.append(("select", columns))
        return self

    def eq(self, field, value):
        self.operations.append(("eq", field, value))
        return self

    def order(self, field, desc=False):
        self.operations.append(("order", field, desc))
        return self

    def limit(self, value):
        self.operations.append(("limit", value))
        return self

    def execute(self):
        self.operations.append(("execute",))
        return _Response(self.rows)


class _Client:
    def __init__(self, rows):
        self.query = _Query(rows)

    def table(self, name):
        self.query.operations.append(("table", name))
        return self.query


def test_latest_directive_query_is_select_only_and_scoped_to_exact_content_id():
    client = _Client([{"id": "dir-1", "paper_id": "paper-1", "cuts": []}])

    row = compare_explanation_v2.latest_directive(client, "paper", "paper-1")

    assert row["id"] == "dir-1"
    assert client.query.operations == [
        ("table", "directives"),
        ("select", "id, paper_id, version_type, header, cuts, status, created_at"),
        ("eq", "paper_id", "paper-1"),
        ("order", "created_at", True),
        ("limit", 1),
        ("execute",),
    ]


def test_latest_directive_rejects_blank_content_id():
    with pytest.raises(ValueError, match="content_id_required"):
        compare_explanation_v2.latest_directive(_Client([]), "report", "")


def test_script_help_runs_from_repository_root():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "scripts/compare_explanation_v2.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--with-model" in completed.stdout


# ─── Phase 11 리뷰 후속 ─────────────────────────────────────────────

PAPER_ID = "11111111-2222-3333-4444-555555555555"


def _forbid_database(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("database accessed")
    monkeypatch.setattr(compare_explanation_v2.db, "get_draft_full", boom)
    monkeypatch.setattr(compare_explanation_v2.report_db, "get_report_draft", boom)
    monkeypatch.setattr(compare_explanation_v2.db, "client", boom)


@pytest.mark.parametrize("bad_id", ["", "   ", "../../etc/passwd", "latest", "paper-1"])
def test_cli_rejects_non_uuid_content_id_before_database_access(monkeypatch, tmp_path, bad_id):
    _forbid_database(monkeypatch)
    with pytest.raises(ValueError, match="content_id_"):
        compare_explanation_v2.main(["paper", bad_id, "--output-dir", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_exact_directive_is_scoped_to_the_same_content():
    client = _Client([])
    with pytest.raises(ValueError, match="directive_not_found_for_content"):
        compare_explanation_v2.exact_directive(client, "paper", PAPER_ID, "dir-x")
    assert ("eq", "id", "dir-x") in client.query.operations
    assert ("eq", "paper_id", PAPER_ID) in client.query.operations


def _fake_run(**kwargs):
    from engine import cost
    # 실제 모델 경로가 하는 일을 흉내 낸다: 원장 1행.
    cost.record(cost.text_attempt(model_id="gemini-x", purpose="spoken_narration_shadow",
                                  input_tokens=10, output_tokens=5))
    return {
        "contract_version": "t", "domain": kwargs["domain"], "content_id": kwargs["content_id"],
        "run_status": "BLOCKED", "error": None, "run": {}, "legacy": {"cuts": []},
        "phase_status": {}, "shadow": {}, "non_claims": [],
        "seen_plan": kwargs["production_content_plan"],
        "seen_override": kwargs["series_split_override_reason"],
    }


def _patch_load(monkeypatch, draft):
    monkeypatch.setattr(compare_explanation_v2, "_load",
                        lambda domain, content_id, directive_id=None: (draft, {}, "test"))


def test_cli_reports_real_ledger_writes_and_passes_stored_content_plan(monkeypatch, tmp_path, capsys):
    rows = []
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt", rows.append)
    _patch_load(monkeypatch, {"fact_sheet": {}, "video_flow": {"content_plan": {"selected_mode": "flash"}}})
    monkeypatch.setattr(compare_explanation_v2.explanation_shadow_pipeline, "run", _fake_run)

    code = compare_explanation_v2.main(["paper", PAPER_ID, "--with-model", "--output-dir", str(tmp_path)])

    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(rows) == 1
    assert printed["database_writes"] == {"generation_attempts": 1}
    saved = json.loads(Path(printed["json"]).read_text(encoding="utf-8"))
    assert saved["side_effects"]["database_writes"] == {"generation_attempts": 1}
    assert saved["seen_plan"] == {"selected_mode": "flash"}
    # 계수 래퍼는 실행 뒤 원래 함수로 돌아간다.
    assert compare_explanation_v2.db.insert_generation_attempt == rows.append


def test_failed_ledger_insert_is_not_counted(monkeypatch, tmp_path, capsys):
    def fail(row):
        raise RuntimeError("rls")
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt", fail)
    _patch_load(monkeypatch, {"fact_sheet": {}})
    monkeypatch.setattr(compare_explanation_v2.explanation_shadow_pipeline, "run", _fake_run)

    compare_explanation_v2.main(["paper", PAPER_ID, "--output-dir", str(tmp_path)])

    assert json.loads(capsys.readouterr().out)["database_writes"] == {"generation_attempts": 0}


def test_reruns_never_overwrite_earlier_dossiers(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt", lambda row: None)
    _patch_load(monkeypatch, {"fact_sheet": {}})
    monkeypatch.setattr(compare_explanation_v2.explanation_shadow_pipeline, "run", _fake_run)

    compare_explanation_v2.main(["paper", PAPER_ID, "--with-model", "--output-dir", str(tmp_path)])
    compare_explanation_v2.main(["paper", PAPER_ID, "--output-dir", str(tmp_path)])

    names = sorted(path.name for path in tmp_path.iterdir())
    assert len(names) == 4
    assert any("-model-" in name for name in names) and any("-dry-" in name for name in names)


def test_cli_end_to_end_dry_run_writes_dossier_without_model_calls(monkeypatch, tmp_path, capsys):
    from engine import llm
    import test_explanation_shadow_pipeline as fixtures

    def no_model(**kwargs):
        raise AssertionError("model called")
    monkeypatch.setattr(llm, "call_json", no_model)
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt",
                        lambda row: (_ for _ in ()).throw(AssertionError("db write")))
    _patch_load(monkeypatch, {"script_md": "운영 대본", "fact_sheet": fixtures._paper_fact_sheet()})

    code = compare_explanation_v2.main(["paper", PAPER_ID, "--output-dir", str(tmp_path)])

    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["run_status"] == "MODEL_CALL_REQUIRED"
    assert printed["database_writes"] == {"generation_attempts": 0}
    markdown = Path(printed["markdown"]).read_text(encoding="utf-8")
    assert "운영 대본" in markdown and "동일 Fact Sheet revision: 미검증" in markdown


def test_cli_passes_series_split_override_reason(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt", lambda row: None)
    _patch_load(monkeypatch, {"fact_sheet": {}})
    monkeypatch.setattr(compare_explanation_v2.explanation_shadow_pipeline, "run", _fake_run)

    compare_explanation_v2.main(["paper", PAPER_ID, "--override-series-split", "비교용",
                                 "--output-dir", str(tmp_path)])

    saved = json.loads(Path(json.loads(capsys.readouterr().out)["json"]).read_text(encoding="utf-8"))
    assert saved["seen_override"] == "비교용"


def test_cli_reads_render_qa_from_the_render_job_for_phase13(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(compare_explanation_v2.db, "insert_generation_attempt", lambda row: None)
    _patch_load(monkeypatch, {"fact_sheet": {}})
    monkeypatch.setattr(compare_explanation_v2.explanation_shadow_pipeline, "run", _fake_run)
    seen = []

    def get_job(job_id):
        seen.append(job_id)
        return {"id": job_id, "qa": {"hard_fail": ["오디오 트랙 없음"], "warnings": []}}

    monkeypatch.setattr(compare_explanation_v2.db, "get_render_job", get_job)
    job_id = "99999999-8888-7777-6666-555555555555"
    compare_explanation_v2.main(["paper", PAPER_ID, "--render-job-id", job_id,
                                 "--output-dir", str(tmp_path)])

    out = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(out["json"]).read_text(encoding="utf-8"))
    render = next(s for s in saved["publish_gate"]["stages"] if s["stage"] == "render")
    assert seen == [job_id]
    assert render["status"] == "FAIL" and render["fails"] == ["오디오 트랙 없음"]
