"""렌더 뒤 성적표 다시 매기기 — 모델을 다시 부르지 않고 렌더 칸만 채운다."""

from __future__ import annotations

import json
from pathlib import Path

from engine import explanation_shadow_pipeline as pipeline
from scripts import publish_gate_v2 as rescore
import test_publish_gate_v2


def _dossier(tmp_path: Path) -> Path:
    result = pipeline.run(domain="paper", content_id="11111111-2222-3333-4444-555555555555",
                          fact_sheet={}, legacy_draft={}, legacy_directive=None)
    ready = test_publish_gate_v2._ready()          # 대본·화면까지 통과한 실행으로 바꿔 렌더 칸만 남긴다
    result.update(run_status=ready["run_status"], error=None, phase_status=ready["phase_status"])
    result["shadow"].update(ready["shadow"])
    path = tmp_path / "paper-x-dry.json"
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return path


def test_rescore_attaches_render_qa_from_the_render_job(monkeypatch, tmp_path, capsys):
    source = _dossier(tmp_path)
    original = source.read_text(encoding="utf-8")
    seen = []

    def get_job(job_id):
        seen.append(job_id)
        return {"qa": {"hard_fail": [], "warnings": ["정지 화면 4.0s"]}}

    monkeypatch.setattr(rescore.compare_explanation_v2.db, "get_render_job", get_job)
    job = "99999999-8888-7777-6666-555555555555"
    assert rescore.main([str(source), "--render-job-id", job]) == 0

    out = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(out["json"]).read_text(encoding="utf-8"))
    render = next(s for s in saved["publish_gate"]["stages"] if s["stage"] == "render")
    assert seen == [job]
    assert saved["run"]["render_job_id"] == job
    assert render["status"] == "WARN" and render["warnings"] == ["정지 화면 4.0s"]
    assert saved["publish_gate"]["verdict"] == "NEEDS_REVIEW"
    assert "## 최종 발행 관문" in Path(out["markdown"]).read_text(encoding="utf-8")
    assert source.read_text(encoding="utf-8") == original, "원래 비교 자료는 덮어쓰지 않는다"


def test_rescore_requires_a_render_input(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        rescore.main([str(_dossier(tmp_path))])
