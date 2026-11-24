"""모션그래픽(motion) 리포트 엔진 — docs/plans/2026-11-24-motion-graphics-engine.md §3·§8.

렌더(npx·Edge TTS)는 돌리지 않는다. 정규화·숫자 검문·템플릿 HTML·배선(그림 API 0회)만 본다.
실렌더 확인: python -m scripts.motion_preview tests/fixtures/motion_usedcar.json
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from engine import config
from engine.motion import build, schema, templates

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "motion_usedcar.json").read_text(encoding="utf-8"))


def _norm(directive=None, fs=None):
    return schema.normalize_motion_directive(directive or FX["directive"], fs or FX["fact_sheet"], FX["broker"])


def test_fixture_normalizes_clean_and_keeps_motion_fields():
    d = _norm()
    assert d["version_type"] == "motion" and d["header"]["mode_warnings"] == []
    assert [c["motion"]["template"] for c in d["cuts"]] == [
        "stamp_card", "card_stack", "scale_tilt", "vs_split", "stamp_card", "cycle3", "stamp_card"]
    assert all(c["scene_kind"] == "motion_graphic" and c["visual_prompt"] == "" for c in d["cuts"])
    assert d["header"]["title_lines"] == ["현대차 중고차가격", "떡락한다구요?"]
    assert d["header"]["cost_plan"]["estimated_total_generation_cost_usd"] == 0.0


def test_source_page_comes_only_from_fact_sheet():
    d = _norm()
    srcs = [c["motion"]["source"] for c in d["cuts"]]
    assert srcs[4] == "자료: 삼성증권 p9"          # number_facts 에 source_page=9
    assert all(s == "자료: 삼성증권" for i, s in enumerate(srcs) if i != 4)   # 쪽수 없는 사실 → 쪽수 안 붙인다


def test_ungrounded_number_turns_cut_into_text_card_without_digits():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][3]["motion"]["slots"]["left"]["value"] = "99조"   # Fact Sheet 에 없는 숫자
    d = _norm(raw)
    c = d["cuts"][3]
    assert c["motion"]["template"] == "text_card"
    assert any(w.startswith("motion_number_ungrounded:4:99조") for w in d["header"]["mode_warnings"])
    assert not any(ch.isdigit() for ch in json.dumps(c["motion"]["slots"], ensure_ascii=False))


def test_number_with_matching_unit_passes():
    assert schema.number_gate({"subtitle": "주행 7.7만km"}, [FX["fact_sheet"]["number_facts"][0]]) == []
    assert schema.number_gate({"v": "7.7%"}, [FX["fact_sheet"]["number_facts"][0]]) == ["7.7%"]


def test_layout_position_is_not_a_number_but_bar_height_is():
    assert schema.number_gate({"highlight": 0, "icon": "car"}, []) == []
    assert schema.number_gate({"items": [{"label": "A", "rel": 10.2}]}, []) == ["10.2"]   # 막대 높이는 양이다


# ── 코덱스 코드 리뷰(2026-11-24) 회귀 ──
_F = [{"display": "매출 15조원, 증가율 -15.9%, 주행 7.7만km"}]


def test_exact_tokens_not_substrings():
    assert schema.number_gate({"v": "5조"}, _F) == ["5조"]            # '15조' 안의 '5조' 가 아니다
    assert schema.number_gate({"v": "15조원"}, _F) == []
    assert schema.number_gate({"v": "7.7만달러"}, _F) != []          # 근거는 7.7만km


def test_screen_sign_is_strict_but_speech_is_not():
    assert schema.number_gate({"v": "15.9%"}, _F) == ["15.9%"]
    assert schema.number_gate({"v": "-15.9%"}, _F) == []
    assert schema.number_gate("판매가 15.9% 줄었어요.", _F, strict_sign=False) == []


def test_korean_spoken_amounts_match_fact_notation():
    f = [{"display": "SDC 1.1조원, 2027~2028년 타이트, 영업이익 100조원"}]
    assert schema.number_gate("디스플레이는 1조 1천억 원 흑자예요.", f, strict_sign=False) == []
    assert schema.number_gate("2027년부터 2028년까지 빠듯해요.", f, strict_sign=False) == []
    assert schema.number_gate("한 분기에 100조 원을 번다.", f, strict_sign=False) == []


def test_ungrounded_number_sentence_is_removed_from_narration():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][2]["narration_ko"] = "그런데 앞으로는 기준이 바뀐다고 봅니다. 중고값이 99조 원 줄어요. 자율주행이 업데이트로 좋아지는 차냐, 아니냐로요."
    d = _norm(raw)
    assert "99" not in d["cuts"][2]["narration_ko"]
    assert any(w.startswith("motion_narration_number_dropped:3") for w in d["header"]["mode_warnings"])


def test_icon_counts_come_from_values_not_llm():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][0]["source_facts"] = ["e"]
    fs = dict(FX["fact_sheet"], e="BYD 고용 100만 명, 현대차·기아 20만 명")
    raw["cuts"][0]["motion"] = {"template": "icon_ratio", "cue_words": [],
                                "slots": {"a": {"label": "BYD", "value": "100만 명", "count": 10},
                                          "b": {"label": "현대", "value": "20만 명", "count": 1}}}
    raw["cuts"][0]["narration_ko"] = "직원 수를 비교해 봅니다."
    c = _norm(raw, fs)["cuts"][0]
    assert c["motion"]["template"] == "icon_ratio"
    assert (c["motion"]["slots"]["a"]["count"], c["motion"]["slots"]["b"]["count"]) == (5, 1)


def test_icon_ratio_without_values_falls_back():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][0]["motion"] = {"template": "icon_ratio", "slots": {"a": {"label": "A", "count": 10}, "b": {"label": "B", "count": 1}}}
    d = _norm(raw)
    assert d["cuts"][0]["motion"]["template"] == "text_card"


# ── 독립 검사(페이블, 2026-11-24) 회귀 ──
_G = [{"display": "74.5조 투자", "source_page": 9, "period": "2027E", "validation": {"matches": 3}}]


def test_split_number_and_unit_are_checked_together():
    assert schema.number_gate({"number": "74.5", "unit": "억"}, _G) == ["74.5억"]
    assert schema.number_gate({"number": "74.5", "unit": "조"}, _G) == []


def test_page_period_validation_are_not_evidence():
    assert schema.number_gate({"number": "9", "unit": "조"}, _G) == ["9조"]
    assert schema.number_gate({"number": "2027", "unit": "조"}, _G) == ["2027조"]


def test_unknown_unit_on_screen_is_a_unit():
    assert schema.number_gate({"v": "74.5곳"}, _G) == ["74.5곳"]


def test_bar_without_values_falls_back():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][0]["motion"] = {"template": "bar_compare", "slots": {"items": [{"label": "a", "rel": 3}, {"label": "b", "rel": 9}]}}
    d = _norm(raw)
    assert d["cuts"][0]["motion"]["template"] == "text_card"


def test_title_numbers_are_checked():
    raw = copy.deepcopy(FX["directive"])
    raw["header"] = {"title_lines": ["999조 시장", "정말?"], "hook_ko": "999조 시장, 정말?"}
    h = _norm(raw)["header"]
    assert h["title_lines"] == ["시장", "정말?"] and "999" not in h["hook_ko"]
    assert any(w.startswith("motion_title_number_dropped") for w in h["mode_warnings"])


# ── 독립 재검사(2026-11-24) 회귀 ──
def test_amount_glued_to_korean_is_still_a_number():
    assert schema.number_gate({"v": "약999조"}, _G) == ["999조"]
    assert schema.number_gate({"v": "총999조원"}, _G) == ["999조"]
    assert schema.number_gate("시장은 무려999조다.", _G, strict_sign=False) == ["999조"]


def test_model_names_glued_to_english_are_not_numbers():
    assert schema.number_gate({"v": "EV6·HBM4·Level2+"}, []) == []


def test_title_unknown_unit_number_is_removed_with_its_unit():
    w: list = []
    assert schema._scrub_title("999곳 시장", _G, w) == "시장" and w


def test_same_text_as_evidence_passes_even_with_unlisted_units():
    f = [{"display": "거점 12곳, 점유율 3위, 2차전지 5GWh, 2027E"}]
    assert schema.number_gate({"a": "12곳", "b": "3위", "c": "2차전지", "d": "5GWh", "e": "2027E"}, f) == []


def test_bar_with_mixed_units_falls_back():
    fs = dict(FX["fact_sheet"], e="매출 15조, 성장률 30%")
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][0]["source_facts"] = ["e"]
    raw["cuts"][0]["narration_ko"] = "비교해 봅니다."
    raw["cuts"][0]["motion"] = {"template": "bar_compare", "slots": {"items": [{"label": "a", "value": "15조"}, {"label": "b", "value": "30%"}]}}
    assert _norm(raw, fs)["cuts"][0]["motion"]["template"] == "text_card"


def test_approval_screen_gets_a_korean_screen_summary():
    c = _norm()["cuts"][3]
    assert c["visual_prompt_ko"].startswith("[좌우 비교]") and "옵션 차만" in c["visual_prompt_ko"]


def test_unresolved_key_and_unknown_template_and_cue_warnings():
    raw = copy.deepcopy(FX["directive"])
    raw["cuts"][0]["source_facts"] = ["nope[9]"]
    raw["cuts"][1]["motion"]["template"] = "spinning_globe"
    raw["cuts"][2]["motion"]["cue_words"] = ["없는낱말"]
    d = _norm(raw)
    w = " ".join(d["header"]["mode_warnings"])
    assert "motion_fact_key_unresolved:1:nope[9]" in w
    assert "motion_unknown_template:2:spinning_globe" in w
    assert "motion_cue_not_in_narration:3:없는낱말" in w
    assert d["cuts"][1]["motion"]["template"] == "text_card"
    assert d["cuts"][2]["motion"]["cue_words"] == []


def test_every_template_renders_registered_timeline_and_escapes_text():
    for name in templates.TEMPLATES:
        html = templates.render_scene("s1", name, {"title": "<b>x</b>", "items": ["<u>y</u>"], "nodes": ["a", "b", "c"]},
                                      lambda n: 1.0 + n, 6.0, "자료: X")
        assert 'window.__timelines["s1"]' in html and 'data-composition-id="s1"' in html
        assert "<b>x</b>" not in html and "<u>y</u>" not in html


def test_end_card_is_fixed_from_meta():
    html = templates.end_card("s9", FX["meta"])
    assert "투자 권유 아님" in html and "자세한 내용은 리포트 원문을 확인하세요" in html
    assert FX["meta"]["title"] in html


def test_caption_chunks_keep_keyword_and_cap_length():
    ch = build.caption_chunks("그래서 업종 의견은 중립으로 낮췄습니다, 다만 1조 4천억 매출 추정이에요.", keep="1조 4천억")
    assert any("1조 4천억" in c for c in ch)
    assert all(len(c.replace(" ", "").replace(" ", "")) <= config.MOTION_CAPTION_MAX_CHARS + 10 for c in ch)


def test_char_to_time_is_monotonic_within_speech():
    spans = [(0.0, 1.0), (1.5, 3.0)]
    ts = [build.char_to_time(spans, f / 10) for f in range(11)]
    assert ts == sorted(ts) and ts[0] == 0.0 and ts[-1] == 3.0


def test_render_rejects_english():
    with pytest.raises(ValueError):
        build.render(_norm(), "x", FX["meta"], lang="en")


def test_tts_failure_raises_instead_of_silence(monkeypatch, tmp_path):
    import edge_tts

    class Boom:
        def __init__(self, *a, **k):
            pass

        async def save(self, path):
            raise RuntimeError("NoAudioReceived")

    monkeypatch.setattr(edge_tts, "Communicate", Boom)
    with pytest.raises(RuntimeError, match="모션 TTS 실패"):
        build._tts("안녕", str(tmp_path / "a.mp3"))


def test_report_directive_routes_motion_without_picture_pipeline(monkeypatch):
    from engine import report_directive
    from engine.motion import directive as md

    monkeypatch.setattr(report_directive, "_generate_with_retry",
                        lambda *a, **k: pytest.fail("모션이 그림 정규화로 갔다"))
    monkeypatch.setattr(md, "call_json", lambda **k: FX["directive"])
    d = report_directive.generate({"fact_sheet": FX["fact_sheet"], "script_md": "x"}, "motion", {"broker": "삼성증권"})
    assert d["version_type"] == "motion" and len(d["cuts"]) == 7
    assert "warning_summary" in d["header"]


def test_requested_versions_accepts_motion(monkeypatch):
    from engine import report_draft
    monkeypatch.setattr(config, "DRAFT_CHAINS_DIRECTIVE", True)
    assert report_draft.requested_versions({"version_types": ["motion", "photo", "bogus"]}) == ["motion", "photo"]


def test_motion_render_job_uses_no_image_or_video_api(monkeypatch, tmp_path):
    from engine import render, report_db, report_render
    from engine.motion import build as mb

    mp4 = tmp_path / "final.mp4"
    mp4.write_bytes(b"x")
    calls: dict = {"jobs": [], "dir": []}
    d = _norm()
    d.update({"id": "d1", "report_id": "r1"})
    monkeypatch.setattr(report_db, "get_report_directive", lambda _id: d)
    monkeypatch.setattr(report_db, "get_report", lambda _id: {"title": "T", "broker": "B", "analyst": "A"})
    monkeypatch.setattr(report_db, "get_report_draft", lambda _id: {"fact_sheet": {"source": "B · A · 2026.11.18"}})
    monkeypatch.setattr(report_db, "update_report_directive_status", lambda i, s: calls["dir"].append(s))
    monkeypatch.setattr(report_db, "update_report_render_job", lambda i, **k: calls["jobs"].append(k))
    monkeypatch.setattr(report_db, "upload_render", lambda p, dest: "https://x/" + dest)
    monkeypatch.setattr(render, "_render_cut_clips", lambda *a, **k: pytest.fail("그림 렌더 경로를 탔다"))
    monkeypatch.setattr(report_render.render_qa, "run_qa", lambda p: {"passed": True, "hard_fail": [], "warnings": []})
    seen = {}

    def fake_render(directive, work_dir, meta, lang="ko"):
        seen["meta"] = meta
        return {"mp4": str(mp4), "total_sec": 60.0, "cut_map": [], "warnings": []}

    monkeypatch.setattr(mb, "render", fake_render)
    url = report_render.process_job("j1", "d1", "ko")
    assert url.endswith("report/d1/j1_ko.mp4")
    assert calls["jobs"][-1]["status"] == "done" and calls["jobs"][-1]["cost_estimate"] == 0.0
    assert calls["dir"] == ["rendering", "rendered"]
    assert seen["meta"] == {"title": "T", "date": "B · A · 2026.11.18", "broker": "", "analyst": ""}
