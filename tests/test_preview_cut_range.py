"""편을 전반·후반으로 나눠 사기 — 컷 범위 미리보기(2026-10-08). 네트워크 없음."""

from __future__ import annotations

import pytest

from scripts import preview_sequence as ps


def _directive():
    return {"version_type": "photo",
            "header": {"visual_sequences": [
                {"sequence_id": "SEQ1", "stages": [{"stage_id": "S1", "cut_refs": [1, 2]},
                                                   {"stage_id": "S2", "cut_refs": [3, 4]}]},
                {"sequence_id": "SEQ2", "stages": [{"stage_id": "S3", "cut_refs": [5, 6]},
                                                   {"stage_id": "S4", "cut_refs": [7, 8]}]}]},
            "cuts": [{"cut_no": n, "motion_source": "video"} for n in range(1, 9)]}


def test_first_half_keeps_original_numbers_and_whole_stages_only():
    mini = ps.slice_range(_directive(), 1, 5, want_video=True)
    assert [c["cut_no"] for c in mini["cuts"]] == [1, 2, 3, 4, 5]          # 번호 그대로(캐시 키가 본 렌더와 같다)
    assert [s["sequence_id"] for s in mini["header"]["visual_sequences"]] == ["SEQ1"]
    assert [st["stage_id"] for st in mini["header"]["visual_sequences"][0]["stages"]] == ["S1", "S2"]


def test_second_half_and_stills_mode():
    mini = ps.slice_range(_directive(), 5, 8, want_video=False)
    assert [c["cut_no"] for c in mini["cuts"]] == [5, 6, 7, 8]
    assert all(c["motion_source"] == "still" for c in mini["cuts"])
    assert [st["stage_id"] for st in mini["header"]["visual_sequences"][0]["stages"]] == ["S3", "S4"]


def test_range_parsing():
    assert ps.parse_range("1-8") == (1, 8) and ps.parse_range("3") == (3, 3)
    with pytest.raises(SystemExit):
        ps.parse_range("8-1")


def test_scattered_cuts_for_a_sample():
    assert ps.parse_cuts("1,7-8") == {1, 7, 8}
    mini = ps.slice_cuts(_directive(), {1, 5, 6}, want_video=True)
    assert [c["cut_no"] for c in mini["cuts"]] == [1, 5, 6]
    assert [st["stage_id"] for seq in mini["header"]["visual_sequences"] for st in seq["stages"]] == ["S3"]
