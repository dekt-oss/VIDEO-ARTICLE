import json

import pytest


PAPER_ID = "d64d86ef-2698-4b80-b8b7-bd393d29795e"


def _draft():
    return {
        "paper_id": PAPER_ID,
        "fact_sheet": {"claims": [{"claim_id": "C01", "text": "실제 주장"}]},
        "script_md": "실제 초안 대본",
        "video_flow": {"content_plan": {"selected_mode": "series_split"}},
        "video_prompts": [{"scene_no": 1, "visual_prompt": "실제 장면"}],
    }


def _generated():
    return {
        "version_type": "photo",
        "header": {
            "approval_blocked": False,
            "block_reasons": [],
            "photo_gate": {"warnings": []},
        },
        "cuts": [{"cut_no": 1, "visual_prompt": "a real laboratory"}],
    }


def test_regenerate_reads_actual_draft_and_persists_generated_directive(monkeypatch):
    from scripts import regen_from_draft

    draft = _draft()
    generated = _generated()
    inserted_rows = []

    monkeypatch.setattr(regen_from_draft.db, "get_draft_full", lambda paper_id: draft)
    monkeypatch.setattr(
        regen_from_draft.directive,
        "generate",
        lambda draft_row, version_type: generated
        if draft_row is draft and version_type == "photo"
        else (_ for _ in ()).throw(AssertionError("실제 draft/photo가 아님")),
    )
    monkeypatch.setattr(
        regen_from_draft.db,
        "insert_directive",
        lambda row: inserted_rows.append(row) or "directive-123",
    )

    directive_id, result = regen_from_draft.regenerate(PAPER_ID)

    assert directive_id == "directive-123"
    assert result is generated
    assert inserted_rows == [{
        "paper_id": PAPER_ID,
        "version_type": "photo",
        "header": generated["header"],
        "cuts": generated["cuts"],
        "status": "draft",
    }]


def test_main_prints_saved_id_and_contract_result(monkeypatch, capsys):
    from scripts import regen_from_draft

    generated = _generated()
    monkeypatch.setattr(
        regen_from_draft,
        "regenerate",
        lambda paper_id: ("directive-123", generated),
    )

    assert regen_from_draft.main([PAPER_ID]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "paper_id": PAPER_ID,
        "directive_id": "directive-123",
        "version_type": "photo",
        "cut_count": 1,
        "approval_blocked": False,
        "block_reasons": [],
        "photo_gate_warnings": [],
    }


def test_regenerate_rejects_insert_without_saved_directive_id(monkeypatch):
    from scripts import regen_from_draft

    monkeypatch.setattr(regen_from_draft.db, "get_draft_full", lambda paper_id: _draft())
    monkeypatch.setattr(regen_from_draft.directive, "generate", lambda draft, version: _generated())
    monkeypatch.setattr(regen_from_draft.db, "insert_directive", lambda row: "")

    with pytest.raises(RuntimeError, match="directive 저장 응답에 id 없음"):
        regen_from_draft.regenerate(PAPER_ID)
