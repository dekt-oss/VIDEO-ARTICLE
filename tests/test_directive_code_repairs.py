"""지시서 단계에서 **코드가 고치는** 반복 차단 두 가지(2026-09-14, 성격 유전 372055db 손 수정 이관).

① 앞 stage 에 없던 선언 개체를 state_before 에 적음 → APPEAR 변이로 옮긴다.
   저장 지시서 실측: 시퀀스 있는 29편 중 7편(24%)이 막혔고 문제 키 전부가 선언 개체·CONTINUE_WORLD.
② 이미지 프롬프트의 퍼센트 수치 → 같은 숫자를 카드가 그리는 컷에서만 지운다.
   같은 논문 세 편 연속 같은 자리에서 막혔고 세 번 다 손으로 숫자만 지웠다.
"""
from engine import directive as dv
from engine import photo_contract as pc
from engine import visual_sequence as vs
from engine import visual_sequence_contract as vc


def _seq(stage2_mode="CONTINUE_WORLD", stage2_before=None, entities=("BRAIN", "PATHS"), third=False):
    stages = [
        {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
         "observable_change": "뇌 모형이 돈다", "entity_refs": ["BRAIN"],
         "state_before": {"BRAIN": "resting on the table"},
         "mutations": [{"entity_id": "BRAIN", "operation": "ROTATE",
                        "visible_change": True, "result_state": "turned to show the front"}]},
        {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C2"],
         "continuity_mode": stage2_mode, "continuity_from": "S1",
         "observable_change": "경로가 흐려진다", "entity_refs": ["BRAIN", "PATHS"],
         "state_before": stage2_before if stage2_before is not None else
         {"BRAIN": "turned to show the front", "PATHS": "light trails, initially active"},
         "mutations": [{"entity_id": "PATHS", "operation": "SHRINK",
                        "visible_change": True, "result_state": "faded"}]},
    ]
    if third:
        stages.append(
            {"stage_id": "S3", "cut_refs": [3], "claim_ids": ["C3"],
             "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S2",
             "observable_change": "경로가 옮겨간다", "entity_refs": ["PATHS"],
             "state_before": {"PATHS": "faded"},
             "mutations": [{"entity_id": "PATHS", "operation": "MOVE",
                            "visible_change": True, "result_state": "moved to the back"}]})
    return {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
            "world": {"world_id": "W"},
            "entities": [{"entity_id": e, "visual_identity": e.lower()} for e in entities],
            "stages": stages}


def _lineage_blocks(seqs, n=2):
    got = vc.evaluate(seqs, cuts=[{"cut_no": i} for i in range(1, n + 1)])
    return [r for r in got["block_reasons"] if r.startswith("vseq_state_lineage_mismatch")]


def test_declared_entity_missing_upstream_becomes_an_appear():
    seqs = vs.normalize_all([_seq()])
    assert _lineage_blocks(seqs), "전제: 수리 전에는 막혀야 한다"
    fixed = vs.repair_lineage_appears(seqs)
    assert fixed == ["SEQ1/S2(PATHS)"]
    st = seqs[0]["stages"][1]
    assert st["mutations"][0]["operation"] == "APPEAR"
    assert st["mutations"][0]["entity_id"] == "PATHS"
    assert "PATHS" not in st["state_before"]
    assert not _lineage_blocks(seqs)


def test_later_stage_inherits_the_repaired_entity():
    """고친 뒤 계보를 다시 계산해야 뒤 stage 가 그 개체를 정상으로 물려받는다."""
    seqs = vs.normalize_all([_seq(third=True)])
    vs.repair_lineage_appears(seqs)
    assert not _lineage_blocks(seqs, n=3)
    assert seqs[0]["stages"][2]["mutations"][0]["operation"] == "MOVE"   # S3 는 손대지 않는다


def test_undeclared_entity_is_not_invented():
    seqs = vs.normalize_all([_seq(entities=("BRAIN",))])
    assert vs.repair_lineage_appears(seqs) == []
    assert _lineage_blocks(seqs)


def test_return_world_is_left_to_the_gate():
    """되돌아가며 없던 것을 적은 것은 원본을 잘못 가리킨 것일 수 있다 — 덮지 않는다."""
    seqs = vs.normalize_all([_seq(stage2_mode="RETURN_WORLD")])
    assert vs.repair_lineage_appears(seqs) == []
    assert _lineage_blocks(seqs)


def test_no_x_visible_is_absence_not_inheritance():
    """저장 지시서 4baede40: 'No NAD+ molecules visible.' 가 물려받기로 세어졌다."""
    assert vs._is_absence("No NAD+ molecules visible.")
    assert not vs._is_absence("Numerous glowing red IGF1 molecules are present")
    seqs = vs.normalize_all([_seq(stage2_before={"BRAIN": "turned to show the front",
                                                 "PATHS": "No light trails visible yet."})])
    assert vs.repair_lineage_appears(seqs) == []
    assert not _lineage_blocks(seqs)


# ── ② 퍼센트 수치 ─────────────────────────────────────────────
def _cut(prompt, overlay_text="최대 13.3%"):
    return {"cut_no": 5, "visual_prompt": prompt, "motion_prompt": "",
            "overlay_plan": [{"type": "number_punch", "text": overlay_text}] if overlay_text else []}


def test_percent_drawn_by_the_card_is_removed():
    c = _cut("A ripple spreads from the cluster and rises to 13.3%. No on-screen text.")
    assert pc.normalize_prompt_numbers([c]) == ["컷5"]
    assert "13.3" not in c["visual_prompt"]
    assert c["visual_prompt"].startswith("A ripple spreads from the cluster and rises.")
    assert not pc._FORBIDDEN_NUMBER_ON_SCREEN.search(pc._text_of(c))


def test_percent_of_keeps_the_sentence_grammatical():
    c = _cut("A segment of the ripple is highlighted to represent 13.3% of variance.")
    pc.normalize_prompt_numbers([c])
    assert c["visual_prompt"] == "A segment of the ripple is highlighted to represent a share of variance."


def test_percent_the_card_does_not_show_is_kept():
    """카드에 없는 숫자를 지우면 수치가 화면에서 사라진다 — 게이트가 되묻게 둔다."""
    c = _cut("The pile grows by 40% compared with the left.", overlay_text="최대 13.3%")
    assert pc.normalize_prompt_numbers([c]) == []
    assert "40%" in c["visual_prompt"]
    no_card = _cut("The pile grows by 13.3%.", overlay_text="")
    assert pc.normalize_prompt_numbers([no_card]) == []


def test_repair_clears_the_block_in_the_contract():
    header = {"hook_ko": "훅"}
    c = {**_cut("Two tabletop models; the right stack rises to 13.3%."),
         "visual_role": "REALITY", "narration_ko": "최대 13.3%를 설명합니다"}
    before = pc.evaluate(header, [dict(c)])["block_reasons"]
    assert any(r.startswith("photo_forbidden_screen_request") for r in before)
    pc.normalize_prompt_numbers([c])
    after = pc.evaluate(header, [c])["block_reasons"]
    assert not any(r.startswith("photo_forbidden_screen_request") for r in after), after


# ── ③ 빠진 필수 주장은 재생성을 띄우고 원문을 되먹인다 ─────────────────
def _claims_directive(missing):
    return {"header": {"photo_gate": {"block_reasons": []},
                       "visual_sequence_gate": {"block_reasons": []},
                       "evidence_coverage": {"missing_claim_ids": missing}}, "cuts": []}


def test_missing_required_claims_triggers_the_retry():
    """승인은 막으면서 재생성·처방이 없었다 — b699ba0b 는 C04 를 손으로 넣었다."""
    assert dv._contract_reasons(_claims_directive(["C04"])) == ["missing_required_claims:C04"]
    assert dv._contract_reasons(_claims_directive([])) == []


def test_missing_claims_feedback_quotes_the_fact_sheet():
    fs = {"claims": [{"claim_id": "C04", "claim_ko": "변이는 성격 분산의 최대 13.3%를 설명한다."},
                     {"claim_id": "C01", "claim_ko": "다른 주장"}]}
    fb = dv.missing_claims_feedback(_claims_directive(["C04"]), fs)
    assert "C04" in fb and "최대 13.3%를 설명한다" in fb
    assert "다른 주장" not in fb
    assert dv.missing_claims_feedback(_claims_directive([]), fs) == ""


# ── ④ 비용 원장 키는 렌더 작업마다 달라야 한다 ──────────────────────
def test_ledger_key_does_not_collide_across_jobs():
    """실측: 5c1ba14f 의 `stage:S8_LIFE_OUTCOMES#clip0` 이 있어 최종 렌더(0e808e83)의 같은
    이름 stage 행이 unique 위반으로 거부됐다 — 원장이 돈 낸 클립을 빠뜨렸다."""
    from engine import render
    a = render.ledger_key("stage:S8_LIFE_OUTCOMES#clip0", "job-A", "dir-1")
    b = render.ledger_key("stage:S8_LIFE_OUTCOMES#clip0", "job-B", "dir-2")
    same_dir_rerender = render.ledger_key("stage:S8_LIFE_OUTCOMES#clip0", "job-C", "dir-1")
    assert len({a, b, same_dir_rerender}) == 3
    assert render.ledger_key("stage:S1#clip0", None, "dir-1").startswith("dir-1:")
    import inspect
    src = inspect.getsource(render)
    assert 'idempotency_key=f"stage:' not in src, "stage 클립 키가 다시 작업 번호 없이 쓰였다"


# ── ⑤ 리포트 라인도 실사형 차단이면 1회 재생성한다(2026-09-14 되살림) ──────────
def _report_row():
    return {"script_md": "문장 하나.", "fact_sheet": {}, "scenes": [], "financial_reasoning": None}


def test_report_photo_block_triggers_one_retry_with_prescription(monkeypatch):
    from engine import report_directive as rd
    from tests.test_photo_contract import _raw
    calls = []

    def fake_call_json(**kw):
        calls.append(kw["user"])
        return _raw("" if len(calls) == 1 else "좋은 훅")

    monkeypatch.setattr(rd, "call_json", fake_call_json)
    out = rd.generate(_report_row(), "photo")
    assert len(calls) == 2
    assert "header.hook_ko" in calls[1], "처방이 되먹임에 실려야 한다"
    assert out["header"]["contract_retry"]["attempted"] is True
    assert not any(r.startswith("photo_hook_missing") for r in out["header"]["block_reasons"])


def test_report_no_retry_when_clean_or_not_photo(monkeypatch):
    from engine import report_directive as rd
    from tests.test_photo_contract import _raw
    calls = []
    monkeypatch.setattr(rd, "call_json", lambda **kw: (calls.append(1), _raw("좋은 훅"))[1])
    rd.generate(_report_row(), "photo")
    assert len(calls) == 1, "정상인데 재생성하면 비용이 두 배다"
