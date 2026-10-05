"""V2 narration → existing Production directive generator (design review A). Zero cost: stubbed generator."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from engine import explanation_shadow_pipeline, script_revision, v2_directive_bridge

import test_explanation_shadow_pipeline as fixtures
import test_explanation_v2_realistic_model as realistic
import test_spoken_numbers as number_fixtures


def _ready(domain: str = "report") -> dict:
    if domain == "paper":
        return explanation_shadow_pipeline.run(
            domain="paper", content_id="paper-1", fact_sheet=fixtures._paper_fact_sheet(),
            legacy_draft={"paper_id": "paper-1", "fact_sheet": fixtures._paper_fact_sheet()},
            legacy_directive={}, allow_model_calls=True,
            narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller)
    sheet, reasoning = number_fixtures._number_heavy_report()
    return explanation_shadow_pipeline.run(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning,
        legacy_draft={"report_id": "report-numbers", "fact_sheet": sheet},
        legacy_directive={}, allow_model_calls=True,
        narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller)


def _echo_generator(seen: list):
    """기존 생성기 대역: 대본 문장마다 컷 하나(실제 cut_skeleton 처럼) + 받은 초안을 기록."""
    def generate(draft: dict) -> dict:
        seen.append(deepcopy(draft))
        cuts = []
        for paragraph in draft["script_md"].split("\n\n"):
            for sentence in [s for s in paragraph.replace("? ", "?\n").replace(". ", ".\n").split("\n") if s]:
                cuts.append({"cut_no": len(cuts) + 1, "narration_ko": sentence,
                             "staging_ko": "장면", "visual_prompt": "scene"})
        return {"version_type": "photo",
                "header": {"approval_blocked": False, "block_reasons": [], "total_estimated_sec": 40},
                "cuts": cuts}
    return generate


# ─── 1단계: 초안 모양 ─────────────────────────────────────────

def test_report_draft_keeps_scenes_aligned_and_maps_reasoning_to_broker_ids():
    result = _ready("report")
    assert result["run_status"] == "READY"

    draft = v2_directive_bridge.report_draft(result["shadow"], {"report_id": "r"},
                                             number_fixtures._number_heavy_report()[1])

    # 장면이 대본 문단과 1:1 이어야 기존 생성기가 장면을 프롬프트에 싣는다.
    assert script_revision.scenes_match_script(draft["scenes"], draft["script_md"])
    rids = [scene["reasoning_id"] for scene in draft["scenes"] if scene["reasoning_id"]]
    assert rids and all(rid.startswith("R") and not rid.startswith("XR") for rid in rids)
    cards = [card for scene in draft["scenes"] for card in scene["screen_facts"]]
    assert cards == [number_fixtures.MEMORY]


def test_paper_draft_builds_its_own_plan_from_claims_actually_used():
    result = _ready("paper")
    assert result["run_status"] == "READY"

    draft = v2_directive_bridge.paper_draft(result["shadow"], {"paper_id": "p", "fact_sheet": {}})

    plan = draft["video_flow"]["content_plan"]
    assert plan["primary_claim_id"] == "C01"          # V2 대본이 실제로 쓴 근거
    assert plan["supporting_claim_ids"] == []
    assert plan["selected_mode"] in ("flash", "standard", "deep", "extended")
    assert plan["selected_mode"] != "series_split"
    assert [scene["claim_ids"] for scene in draft["video_prompts"]][1] == ["C01"]


def test_bridge_refuses_unaccepted_narration():
    result = _ready("report")
    shadow = deepcopy(result["shadow"])
    shadow["narration"]["generation_status"] = "REJECTED_DRAFT"

    with pytest.raises(ValueError, match="v2_narration_not_accepted"):
        v2_directive_bridge.report_draft(shadow, {}, {})


# ─── 2단계: 추적 정보 재부착 ─────────────────────────────────

def test_trace_is_reattached_to_every_generated_cut():
    seen: list = []
    result = _ready("report")

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {"report_id": "r"},
        financial_reasoning=number_fixtures._number_heavy_report()[1],
        generator=_echo_generator(seen))

    assert generated["trace"]["untraced_cuts"] == 0
    traced = [cut["v2_trace"] for cut in generated["directive"]["cuts"]]
    assert all(t["matched"] for t in traced)
    assert any("report:num_tp" in t["evidence_ids"] for t in traced)
    assert any(t["screen_facts"] == [number_fixtures.MEMORY] for t in traced)


def test_untraceable_cut_is_marked_not_dropped():
    result = _ready("report")

    def rewriting(draft):
        return {"header": {}, "cuts": [{"cut_no": 1, "narration_ko": "대본에 없는 새 문장"}]}

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {}, financial_reasoning={}, generator=rewriting)

    assert generated["directive"]["cuts"][0]["v2_trace"] == {"matched": False}
    assert generated["trace"]["untraced_cuts"] == 1


# ─── 3단계: 비교 도구 연결 ───────────────────────────────────

def _pipeline(**overrides) -> dict:
    sheet, reasoning = number_fixtures._number_heavy_report()
    kwargs = dict(
        domain="report", content_id="report-numbers", fact_sheet=sheet,
        financial_reasoning=reasoning, legacy_draft={"report_id": "report-numbers"},
        legacy_directive={}, allow_model_calls=True,
        narration_caller=realistic.realistic_narrator(), critic_caller=fixtures._critic_caller,
        with_directive=True, directive_generator=_echo_generator([]),
    )
    kwargs.update(overrides)
    return explanation_shadow_pipeline.run(**kwargs)


def test_pipeline_generates_directive_only_when_asked_and_ready():
    assert _pipeline()["phase_status"]["production_generator"] == "READY"
    assert "production_generator" not in _pipeline(with_directive=False)["phase_status"]

    calls = []
    blocked = _pipeline(
        narration_caller=realistic.realistic_narrator(realistic._read_screen_numbers),
        directive_generator=lambda draft: calls.append(draft) or {"header": {}, "cuts": []})
    assert blocked["phase_status"]["production_generator"] == "NOT_RUN"
    assert calls == []                                   # 막힌 대본은 생성기에 가지 않는다


def test_generator_failure_is_recorded_without_hiding_the_script_verdict():
    def boom(draft):
        raise TimeoutError("directive model timeout")

    result = _pipeline(directive_generator=boom)

    assert result["run_status"] == "READY"
    assert result["phase_status"]["production_generator"] == "ERROR"
    assert result["shadow"]["generated_error"]["type"] == "TimeoutError"
    markdown = explanation_shadow_pipeline.render_markdown(result)
    assert "생성 실패: TimeoutError" in markdown


def test_markdown_shows_generated_directive_next_to_production():
    result = _pipeline()
    markdown = explanation_shadow_pipeline.render_markdown(result)

    assert "## V2 지시서 (기존 생성기로 만든 것)" in markdown
    assert "같은 생성기" in markdown
    assert "승인 가능 여부: 통과" in markdown
    assert "출처) V2 NB" in markdown
    assert "## V2 추적 골격 (간이 화면 계획 — 렌더용 아님)" in markdown


def test_cli_rejects_with_directive_without_with_model(tmp_path):
    from scripts import compare_explanation_v2

    with pytest.raises(SystemExit):
        compare_explanation_v2.main(["report", "11111111-2222-3333-4444-555555555555",
                                     "--with-directive", "--output-dir", str(tmp_path)])


def test_generator_cost_is_labelled_as_the_bridge():
    from engine import llm

    result = _ready("report")
    labels = []
    v2_directive_bridge.generate(
        "report", result["shadow"], {}, financial_reasoning={},
        generator=lambda draft: labels.append(llm._TEXT_PURPOSE.get("value")) or {"header": {}, "cuts": []})
    assert labels == ["v2_directive_bridge"]


# ─── 대사 고정(운영자 결정 ①, 2026-10-05) ────────────────────────────

from engine import cut_skeleton, decide, report_directive  # noqa: E402


def test_lock_restores_rewritten_narration_when_cut_count_matches():
    bones = cut_skeleton.build("첫 문장입니다. 둘째 문장입니다.")
    cuts = [{"narration_ko": "모델이 바꾼 첫 문장"}, {"narration_ko": "둘째 문장입니다"}]

    report = cut_skeleton.lock_narration(cuts, bones)

    assert report["status"] == "LOCKED"
    assert [c["narration_ko"] for c in cuts] == ["첫 문장입니다.", "둘째 문장입니다."]
    assert report["restored"] == [{"cut_no": 1, "model_text": "모델이 바꾼 첫 문장"}]
    assert cut_skeleton.lock_reason(report) == ""


def test_lock_blocks_when_cut_count_differs():
    bones = cut_skeleton.build("첫 문장입니다. 둘째 문장입니다.")
    cuts = [{"narration_ko": "하나로 합친 문장"}]

    report = cut_skeleton.lock_narration(cuts, bones)

    assert report["status"] == "CUT_COUNT_MISMATCH"
    assert cuts[0]["narration_ko"] == "하나로 합친 문장"          # 어느 칸인지 모르면 손대지 않는다
    assert cut_skeleton.lock_reason(report) == "narration_lock_cut_count:1!=2"


def _report_draft(lock: bool) -> dict:
    result = _ready("report")
    draft = v2_directive_bridge.report_draft(result["shadow"], {"report_id": "r"},
                                             number_fixtures._number_heavy_report()[1])
    if not lock:
        draft.pop(cut_skeleton.NARRATION_LOCK_KEY)
    return draft


def test_production_prompt_is_unchanged_without_the_lock_marker():
    plain = report_directive.report_directive_user_prompt(_report_draft(lock=False), "photo")
    locked = report_directive.report_directive_user_prompt(_report_draft(lock=True), "photo")

    assert "[대사 고정" not in plain
    assert report_directive.LOCKED_SCENES_NOTE not in plain
    assert "[대사 고정" in locked
    assert locked.replace(locked[locked.index("\n\n[대사 고정"):locked.index("대본(script_md)")], "") \
        .count("대본(script_md)") == plain.count("대본(script_md)")


def _stub_report_llm(monkeypatch, *, drop_one: bool = False):
    def fake_call_json(**kwargs):
        bones = cut_skeleton.build(kwargs["user"].split("대본(script_md):\n", 1)[1].split("\n\nFact Sheet", 1)[0])
        rows = bones[:-1] if drop_one else bones
        return {"header": {}, "cuts": [
            {"cut_no": b["cut_no"], "narration_ko": "모델이 새로 쓴 문장 " + str(b["cut_no"]),
             "visual_prompt": "fab", "staging_ko": "장면", "visual_role": "REALITY"} for b in rows]}

    monkeypatch.setattr(report_directive, "call_json", fake_call_json)
    monkeypatch.setattr(decide, "enabled", lambda: False)


def test_real_report_generator_keeps_v2_narration_word_for_word(monkeypatch):
    _stub_report_llm(monkeypatch)
    result = _ready("report")
    draft_script = v2_directive_bridge.report_draft(
        result["shadow"], {}, number_fixtures._number_heavy_report()[1])["script_md"]

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {"report_id": "r"},
        financial_reasoning=number_fixtures._number_heavy_report()[1])

    narrations = [cut["narration_ko"] for cut in generated["directive"]["cuts"]]
    assert narrations == [b["sentence"] for b in cut_skeleton.build(draft_script)]
    assert generated["narration_lock"]["status"] == "LOCKED"
    assert len(generated["narration_lock"]["restored"]) == len(narrations)
    assert generated["trace"]["untraced_cuts"] == 0


def test_real_report_generator_blocks_when_cuts_are_merged(monkeypatch):
    _stub_report_llm(monkeypatch, drop_one=True)
    result = _ready("report")

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {"report_id": "r"},
        financial_reasoning=number_fixtures._number_heavy_report()[1])

    assert generated["approval_blocked"] is True
    assert any(r.startswith("narration_lock_cut_count:") for r in generated["block_reasons"])


# ─── 컷 수 바닥값·원리 도해 제안(2026-10-05 후속) ─────────────────────────────

SAMSUNG_LIKE = (
    "왜 이 증권사는 이런 전망을 하는 걸까요?\n\n"
    "유안타증권은 메모리 가격이 크게 상승할 것으로 추정했습니다. "
    "이러한 메모리 가격 상승과 HBM4 판매 본격화에 힘입어, DS부문의 예상 영업이익이 대폭 늘어날 것으로 예상했습니다. "
    "DS부문의 실적 개선이 전사 실적을 견인하면서 전사 영업이익도 높아질 것으로 전망했습니다.\n\n"
    "그 결과 유안타증권은 목표주가를 630,000원으로 상향 조정했습니다."
)


def test_lock_skeleton_splits_at_connective_comma_without_changing_words():
    plain = cut_skeleton.build(SAMSUNG_LIKE)
    locked = cut_skeleton.lock_skeleton(SAMSUNG_LIKE)

    assert len(locked) > len(plain)
    assert cut_skeleton._same_words(" ".join(b["sentence"] for b in plain),
                                    " ".join(b["sentence"] for b in locked))
    assert any(b["sentence"].endswith("힘입어,") for b in locked)


def test_number_list_commas_are_never_split():
    text = "DRAM 가격은 18.0%, NAND 가격은 16.0% 오를 것으로 추정했습니다."
    assert cut_skeleton._split_at_connective_comma(text) == [text]


def test_lock_skeleton_is_unchanged_when_the_floor_is_already_met():
    many = " ".join(f"문장 {i}번은 짧게 끝납니다." for i in range(1, 12))
    assert [b["sentence"] for b in cut_skeleton.lock_skeleton(many)] == \
        [b["sentence"] for b in cut_skeleton.build(many)]


def test_mechanism_hint_only_on_causal_slots():
    hints = [{"text": SAMSUNG_LIKE.split("\n\n")[1], "hint": "MECHANISM"}]
    block = cut_skeleton.lock_block(cut_skeleton.lock_skeleton(SAMSUNG_LIKE), hints)
    hinted = [line for line in block.splitlines() if "← 화면 제안: MECHANISM" in line]

    assert hinted and all(("힘입어" in line) or ("견인" in line) for line in hinted)
    assert not any("크게 상승할 것으로 추정" in line for line in hinted)   # 숫자 문장은 도해 후보가 아니다


def test_bridge_passes_v2_mechanism_modes_as_hints():
    result = _ready("report")
    draft = v2_directive_bridge.report_draft(result["shadow"], {}, number_fixtures._number_heavy_report()[1])

    value = draft[cut_skeleton.NARRATION_LOCK_KEY]
    assert isinstance(value, dict) and value                       # 참 값이어야 고정이 켜진다
    modes = {row["beat_id"]: row["visual_mode"] for row in result["shadow"]["visual_plan"]["visual_beats"]}
    assert len(value["visual_hints"]) == sum(1 for mode in modes.values() if mode == "MECHANISM")


# ─── 화면 숫자 카드(다음 단계 S1, 2026-10-05) ──────────────────────────────

from engine import config as cfg, evidence_overlay, subtitles  # noqa: E402


@pytest.mark.parametrize("text, card", [
    ("테스트증권은 2026년 3분기 DRAM 가격이 18.0%, NAND 가격이 16.0% 오를 것으로 전망했다.",
     "DRAM 가격 18.0% · NAND 가격 16.0%"),
    ("SK증권은 조선 3사의 합산 영업이익이 2028년 13.7조원으로 과거 고점의 약 2배에 달할 것으로 전망한다.",
     "합산 영업이익 13.7조원 · 고점 약 2배"),
    ("인간은 발 앞부분이 먼저 닿을 때 대사 에너지를 26%에서 41% 더 많이 소비한다.", "대사 에너지 26%~41%"),
])
def test_screen_card_text_labels_numbers_and_merges_ranges(text, card):
    assert v2_directive_bridge.screen_card_text(text) == card


def test_screen_number_card_is_attached_to_the_cut_that_says_it():
    result = _ready("report")

    generated = v2_directive_bridge.generate(
        "report", result["shadow"], {"report_id": "r"},
        financial_reasoning=number_fixtures._number_heavy_report()[1],
        generator=_echo_generator([]))

    cards = [(cut["cut_no"], item["text"]) for cut in generated["directive"]["cuts"]
             for item in cut.get("overlay_plan") or [] if item.get("type") == "screen_fact"]
    assert cards and cards[0][1] == "DRAM 가격 18.0% · NAND 가격 16.0%"
    assert generated["trace"]["screen_cards"] == 1


def test_screen_fact_renders_as_a_fading_card_even_with_evidence_cards_off():
    cut = {"cut_no": 1, "overlay_plan": [{"type": "screen_fact", "text": "DRAM 18.0%"}]}

    cues = evidence_overlay.build_overlay_cues(
        [cut], [10.0], [5.0], only_types=set(cfg.OVERLAY_ANNOTATION_TYPES))

    # S3 이후: 숫자가 0 에서 올라가는 프레임들 + 마지막 고정 카드.
    assert {c[3] for c in cues} == {"ScreenFact"}
    assert cues[0][0] == pytest.approx(10.0 + cfg.OVERLAY_SCREEN_FACT_DELAY_SEC)   # 살짝 늦게 떠오른다
    assert cues[0][2].endswith("DRAM 0.0%")
    start, end, text, style = cues[-1]
    assert end == 15.0
    assert text.startswith(r"{\fad(0,") and text.endswith("DRAM 18.0%")
    assert "Style: ScreenFact," in subtitles.build_ass([], overlays=cues)


def test_production_prompts_do_not_offer_screen_fact():
    assert "screen_fact" not in cfg.OVERLAY_TEXT_TYPES
    from engine import directive, photo_prompt
    assert "screen_fact" not in directive._OVERLAY_TYPES_HELP
    assert "screen_fact" not in photo_prompt._OVERLAY_TYPES
