"""Phase 3 렌더 배선 — 시퀀스가 **실제로 화면을 잇는가** (v3, 2026-08-30).

★ 이 파일이 막는 것은 정본 작업지시서가 경고한 실패 그 자체다:
  **"schema field 를 만들었지만 renderer 가 무시하고 있지 않은가."**
  Phase 1·2 가 `resolved_visual_plan` 과 `visual_sequences` 를 만들었는데, 저장소 지도를
  떠 보니 렌더 경로에서 그 세 필드의 참조가 **정확히 0곳**이었다. 그 상태를 고정으로 막는다.

★ 전부 순수 판정이라 라이브 키 없이 돈다. 실제 화면이 이어지는지는 코드가 답할 수 없다 —
  그것은 Mini Render 뒤 사람 눈과 멀티모달 QA 의 몫이다.
"""

from __future__ import annotations

import base64
import os
import tempfile

from engine import (config, generation_spec, sequence_render as sr,
                    visual_sequence as vs, visual_sequence_contract as vc)
from engine import config
from engine.providers import image as image_provider


def _stage(sid, mode="NEW_WORLD", frm="", cuts=(1,), **kw):
    base = {"stage_id": sid, "continuity_mode": mode, "continuity_from": frm,
            "cut_refs": list(cuts), "operation": "TRANSFER", "camera_operation": "HOLD",
            "observable_change": "무언가 달라진다", "claim_ids": ["C1"],
            "mutations": [{"entity_id": "A", "operation": "MOVE",
                           "visible_change": True, "result_state": "on the right"}],
            "state_after_computed": {"A": "on the right"}}
    base.update(kw)
    return base


def _header(*stages):
    return {"version_type": "photo",
            "visual_sequences": [{"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
                                  "world": {"world_id": "W"},
                                  "entities": [{"entity_id": "A", "visual_identity": "a disc"}],
                                  "stages": list(stages)}]}


# ── 판정: 이 컷을 무엇으로 만드는가 ──────────────────────────────
def test_a_cut_outside_any_sequence_is_untouched():
    """시퀀스 없는 지시서는 **종전 경로 그대로**다(D6). 렌더가 달라지면 안 된다."""
    got = sr.reference_decision({"cut_no": 9}, {"version_type": "photo"}, {})
    assert got["kind"] == "none" and got["ref_asset"] == "" and got["degraded"] == []


def test_a_new_world_stage_needs_no_reference():
    header = _header(_stage("S1"))
    got = sr.reference_decision({"cut_no": 1}, header, {})
    assert got["kind"] == "new_world" and got["stage_id"] == "S1"


def test_a_continuing_stage_takes_the_previous_stage_image():
    """★ v3 의 핵심: 같은 세계의 다음 상태는 **앞 stage 의 그림에서** 만든다."""
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "reference"
    assert got["ref_stage"] == "S1" and got["ref_asset"] == "/tmp/s1.png"
    assert got["reference_key"]                      # 캐시 키가 붙는다


def test_a_missing_previous_frame_degrades_instead_of_killing_the_render():
    """★ 그림 하나가 없다고 편 전체를 죽이지 않는다. 대신 **그 사실을 남긴다.**

    판정 불가와 실패를 섞지 않는 이 저장소의 규율이 렌더에도 그대로 적용된다.
    """
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {})     # S1 그림이 아직 없다
    assert got["kind"] == "new_world"
    assert got["degraded"] == ["degraded_no_reference_frame"]


def _still_stage(sid, mode, frm, cuts):
    """**아무것도 달라지지 않는** stage — 변이도 서술도 없다(순수 되돌아가기)."""
    return _stage(sid, mode, frm, cuts=cuts, mutations=[], observable_change="",
                  state_before={}, state_after={}, state_after_computed={})


def test_return_world_derives_instead_of_generating():
    """★ 되돌아가는 세계는 **다시 만들지 않는다** — 같은 픽셀에서 파생하는 편이 정확하고 공짜다.

    단 이것은 **변화를 선언하지 않은** 컷일 때의 이야기다(아래 테스트 참조).
    """
    header = _header(_stage("S1"), _still_stage("S2", "RETURN_WORLD", "S1", (2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "derive" and got["ref_asset"] == "/tmp/s1.png"
    assert got["reference_key"], "파생이 실패해 생성으로 떨어질 때 쓸 캐시 키가 없다"


def test_returning_to_a_world_while_declaring_a_change_is_not_a_copy():
    """★★ 2026-08-30 골든B 완성본 실측 — **선언한 변화가 화면에서 사라졌다.**

    컷6 은 "궤적선 하나가 강조되어 기준점이 된다"를 `HIGHLIGHT` / `visible_change: true`
    로 선언했다. 그런데 RETURN_WORLD 라는 이유로 파생 경로로 갔고, 파생은 크롭 선언이
    없으면 앞 그림을 **바이트 복사**한다. 화면에 나간 것은 S1 그림 그대로였다.

    게이트는 전부 통과했다(`degraded_continuity: {}`) — **조립해서 눈으로 봐야** 보였다.
    작업계획서 §9-9 Q9 가 예고한 그 퇴행이다: "렌더가 파일 복사로 구현하면 퇴행한다."

    변화를 선언했으면 참조 조건 생성으로 간다 — 세계는 유지하고 변화만 일으킨다.
    """
    header = _header(_stage("S1"), _stage("S2", "RETURN_WORLD", "S1", cuts=(2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "reference", "변화를 선언한 컷이 앞 그림 복사로 처리된다"
    assert got["ref_asset"] == "/tmp/s1.png", "세계를 잃었다 — 참조가 안 붙었다"
    assert got["reference_key"]


def test_the_declared_change_reaches_the_prompt_of_a_returning_cut():
    """★ 판정만 바꾸고 프롬프트가 변화를 안 실으면 고친 것이 아니다(만들어 놓고 한쪽만 연결).

    컷6 이 실제로 받게 될 문자열에 그 변이가 들어 있는지 본다.
    """
    stage = _stage("S2", "RETURN_WORLD", "S1", cuts=(2,),
                   mutations=[{"entity_id": "TRAJECTORY_LINE", "operation": "HIGHLIGHT",
                               "visible_change": True,
                               "result_state": "One trajectory line stands out"}])
    assert "TRAJECTORY_LINE" in sr.change_prose(stage)
    assert "One trajectory line stands out" in sr.change_prose(stage)


def test_batch_mode_cannot_carry_a_reference_and_says_so(monkeypatch):
    """★★ Batch 는 렌더 **시작 전에** 요청을 제출한다 — 참조로 쓸 그림이 그때 없다.

    이 예외를 명시하지 않으면 기본 모드(batch)에서 시퀀스 컷이 조용히 텍스트 전용으로
    그려지고, **연속성이 사라진 것을 아무도 모른다.**
    """
    monkeypatch.setattr(config, "SEQUENCE_REFERENCE_FORCES_REALTIME", False)
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"},
                                generation_mode="batch")
    assert got["kind"] == "new_world" and got["degraded"] == ["degraded_batch_mode"]


def test_forcing_realtime_keeps_the_reference_even_in_batch_mode():
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    got = sr.reference_decision({"cut_no": 2}, header, {"S1": "/tmp/s1.png"},
                                generation_mode="batch")
    assert got["kind"] == "reference"                # 기본값이 강제 실시간이다


# ── 캐시: 참조로 만든 그림과 텍스트로 만든 그림은 다른 키여야 한다 ──
def test_a_reference_conditioned_still_does_not_collide_with_a_text_only_one():
    """★★ 이 저장소는 같은 교훈을 이미 한 번 배웠다.

    `VideoSpec.start_asset_hash` 가 없던 시절 I2V 연쇄에서 **앞 컷이 바뀌어도 뒤 컷이 옛
    클립을 재사용**했다. 참조 조건 생성을 이미지에 붙이면 똑같은 구멍이 이미지 쪽에 생긴다 —
    앞 stage 그림이 바뀌어도 이 컷은 옛 그림을 쓴다. 그러면 연속성이 캐시 우연에 달린다.
    """
    cut = {"visual_role": "MECHANISM"}
    plain = generation_spec.image_spec(cut).cache_fields()
    ref = generation_spec.image_spec(cut, reference_key="abc123").cache_fields()
    assert plain != ref
    assert plain["reference_key"] == "" and ref["reference_key"] == "abc123"


def test_the_reference_key_moves_when_the_upstream_stage_changes():
    a = sr.reference_key(_stage("S2", "CONTINUE_WORLD", "S1"), "S1")
    b = sr.reference_key(_stage("S2", "CONTINUE_WORLD", "S9"), "S9")
    assert a != b


def test_the_reference_key_ignores_how_the_model_worded_the_change():
    """★ 계산된 상태를 키에 쓴다 — 같은 변화를 다르게 적기만 해도 캐시가 깨지면 안 된다."""
    a = _stage("S2", "CONTINUE_WORLD", "S1", observable_change="디스크가 오른쪽으로 간다")
    b = _stage("S2", "CONTINUE_WORLD", "S1", observable_change="원반이 우측으로 이동한다")
    assert sr.reference_key(a, "S1") == sr.reference_key(b, "S1")


# ── 요청 형태: Phase 0 이 실측으로 검증한 그대로 ────────────────
def test_the_reference_image_part_comes_before_the_text_part():
    """★ Phase 0(scripts/probe_continuity.py)이 검증한 배치다. 순서를 바꿔도 되는지는
    재 본 적이 없으므로 바꾸지 않는다."""
    cut = {"visual_prompt": "the disc moves right", "visual_role": "MECHANISM"}
    header = {"global_style": "clean 3d", "version_type": "photo"}
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\nfake")
        ref = f.name
    try:
        body = image_provider._image_request_body(cut, header, ref_path=ref)
        parts = body["contents"][0]["parts"]
        assert list(parts[0]) == ["inlineData"]
        assert list(parts[1]) == ["text"]
        assert parts[0]["inlineData"]["mimeType"] == "image/png"
        assert base64.b64decode(parts[0]["inlineData"]["data"]) == b"\x89PNG\r\n\x1a\nfake"
    finally:
        os.unlink(ref)


def test_the_reference_instruction_is_only_added_when_a_reference_is_attached():
    """★ Phase 0 실측: 이 문구가 없으면 모델이 참조를 받고도 **장면을 다시 그린다.**
    반대로 참조 없는 컷에 붙이면 붙일 그림이 없는데 "attached image" 를 말하게 된다."""
    cut = {"visual_prompt": "a rocket", "visual_role": "MECHANISM"}
    header = {"global_style": "clean 3d", "version_type": "photo"}
    plain = image_provider._image_request_body(cut, header)
    assert not plain["contents"][0]["parts"][0]["text"].startswith("Use the attached")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"x")
        ref = f.name
    try:
        withref = image_provider._image_request_body(cut, header, ref_path=ref)
        assert withref["contents"][0]["parts"][1]["text"].startswith("Use the attached image")
    finally:
        os.unlink(ref)


def test_batch_requests_never_carry_a_reference():
    """★ Batch 바디에 참조가 실리면 **존재하지 않는 파일**을 읽으려 든다. 구조로 막는다."""
    cuts = [{"cut_no": 1, "visual_prompt": "a rocket", "visual_role": "MECHANISM"}]
    reqs = image_provider.build_batch_requests("dir1", cuts, {"version_type": "photo"})
    parts = reqs[0]["request"]["contents"][0]["parts"]
    assert len(parts) == 1 and list(parts[0]) == ["text"]


# ── 변화 서술 ────────────────────────────────────────────────
def test_the_change_prose_prefers_the_structured_mutations():
    """★ 구조가 서술보다 정확하다. 서술은 옛 지시서 하위호환 폴백이다."""
    st = _stage("S2", "CONTINUE_WORLD", "S1")
    prose = sr.change_prose(st)
    assert "A" in prose and "move" in prose and "on the right" in prose


def test_the_change_prose_falls_back_to_the_written_description():
    st = _stage("S2", "CONTINUE_WORLD", "S1", mutations=[],
                observable_change="토큰이 오른쪽으로 쌓인다")
    assert sr.change_prose(st) == "토큰이 오른쪽으로 쌓인다"


# ── 요약 지표 ────────────────────────────────────────────────
def test_the_summary_counts_world_resets_and_degradations():
    """★ world_reset 을 세는 것이 v3 의 핵심 지표다 — 세계를 자주 새로 만들면
    "시퀀스"라고 부르지만 실은 컷 나열이다."""
    got = sr.degraded_summary([
        {"stage_id": "S1", "kind": "new_world", "degraded": []},
        {"stage_id": "S2", "kind": "reference", "degraded": []},
        {"stage_id": "S3", "kind": "derive", "degraded": []},
        {"stage_id": "S4", "kind": "new_world", "degraded": ["degraded_no_reference_frame"]},
    ])
    assert got["stages_rendered"] == 4
    assert got["reference_conditioned"] == 1 and got["derived"] == 1
    assert got["world_reset"] == 2
    assert got["degraded_continuity"] == {"degraded_no_reference_frame": 1}


# ── ★★ 렌더러가 정본을 **실제로 읽는가** (적대적 자기리뷰 Q5) ──
def test_the_render_path_actually_reads_the_resolved_plan_and_sequences():
    """★★ 리뷰 §23 Q5: "Renderer 가 실제로 새 resolved plan 을 소비하는가."

    Phase 2 직후의 답은 **아니오** 였다 — `resolved_visual_plan`·`visual_sequences` 의
    참조가 렌더 경로에 0곳이었다. 정본 작업지시서가 경고한 "schema field 를 만들었지만
    renderer 가 무시한다"가 실제 상태였던 것이다.

    이 테스트는 그 상태로 **되돌아가는 것**을 막는다. 소비 지점이 사라지면 여기서 깨진다.
    """
    import inspect

    from engine import render
    src = inspect.getsource(render)
    assert "sequence_render.reference_decision" in src, "렌더가 시퀀스 판정을 부르지 않는다"
    assert "seq_decision" in src, "판정 결과가 컷 생성으로 전달되지 않는다"
    assert "stage_assets" in src, "stage 그림 색인이 없다 — 참조를 이을 수 없다"

    sig = inspect.signature(render._gen_still)
    assert "ref_path" in sig.parameters, "_gen_still 이 참조를 받지 못한다"
    assert "reference_key" in sig.parameters, "_gen_still 이 캐시 키를 받지 못한다"

    # sequence_render 는 header.visual_sequences 를 읽는 유일한 렌더측 소비자다.
    assert "visual_sequences" in inspect.getsource(sr)


def test_a_failed_derive_keeps_the_world_instead_of_starting_over():
    """★★ 파생이 실패했을 때 **세계를 잃지 않는다.**

    종전에는 `kind == "reference"` 일 때만 참조를 실었다. 그래서 파생이 실패하면
    (원본 파일이 없거나 크롭이 깨지면) **텍스트 전용 생성**으로 떨어졌다.
    RETURN_WORLD 는 "이미 그린 세계로 돌아간다"는 뜻인데 그 세계를 통째로 잃는 것이
    가장 나쁜 결말이다 — 파생이든 참조든 우리가 가진 것은 같은 앞 그림 하나다.
    """
    import unittest.mock as mock

    from engine import render

    seen: dict = {}

    def fake_gen(cut, header, img_path, *a, **kw):
        seen.update(ref_path=kw.get("ref_path"), reference_key=kw.get("reference_key"))
        return 0.0

    # ref_asset 이 실재하지 않는 경로라 _derive_from_stage 는 False 를 돌려준다.
    dec = {"kind": "derive", "ref_stage": "S1", "ref_asset": "/nonexistent/s1.png",
           "reference_key": "k123", "stage_id": "S2", "degraded": []}
    with mock.patch.object(render, "_gen_still", fake_gen):
        render._obtain_still({"cut_no": 2}, {"version_type": "photo"}, "/tmp/out.png",
                             asset_index=None, seq_decision=dec,
                             directive_id=None, render_job_id=None, render_job_kind="paper")
    assert seen["ref_path"] == "/nonexistent/s1.png", "파생 실패가 세계를 버렸다"
    assert seen["reference_key"] == "k123", "참조 생성이 텍스트 생성과 같은 캐시 키를 갖는다"


def test_a_cut_without_a_sequence_calls_the_provider_exactly_as_before():
    """★★ D6 보증: **시퀀스 없는 지시서는 종전 경로 그대로다.**

    2026-08-30 실측: `ref_path` 를 무조건 넘겼더니 기존 테스트 5개가 깨졌다. 표면적으로는
    테스트 페이크의 시그니처 문제지만 드러난 것은 더 중요하다 — 인자를 못 받는 호출부가
    있으면 **TypeError 가 재시도 루프에 삼켜져 placeholder 로 떨어진다.**
    조용히 그림이 사라지는 경로다.

    그래서 참조가 없으면 인자 자체를 넘기지 않는다. 3인자만 받는 페이크로 이것을 못박는다.
    """
    from engine import render

    seen: list[tuple] = []

    def only_three_args(cut, header, out_path):        # ref_path 를 못 받는 옛 시그니처
        seen.append((cut.get("cut_no"), out_path))
        with open(out_path, "wb") as f:
            f.write(b"png")
        return out_path, 0.0

    import unittest.mock as mock
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "cut.png")
        with mock.patch.object(render.image_provider, "generate_image", only_three_args), \
             mock.patch.object(render.config, "IMAGE_PROVIDER", "gemini"):
            render._gen_still({"cut_no": 1, "visual_role": ""}, {"version_type": "photo"}, img)
    assert len(seen) == 1, "참조 없는 컷이 옛 호출 형태로 생성되지 않았다"


def test_the_model_choice_follows_the_resolved_plan_not_the_legacy_label():
    """★★ 리뷰 §12 권한 충돌의 **실제 대가**. 2026-08-30 Mini Render 비용 산정 중 발견.

    정본(`resolved_visual_plan`)을 만들어 놓고 **돈과 화질을 정하는 자리**는 여전히
    모델이 붙인 옛 `visual_role` 을 읽고 있었다. 골든B 재생성의 컷1·10 이 정확히
    그 상태였다 — 라우터는 기전 시퀀스로 판정했는데 라벨이 REALITY 라 **싼 flash
    이미지 모델**이 잡혔다. flash 는 3D 도해에 깨진 글자 라벨을 그린다(실측).

    내가 만든 `vseq_route_contract_conflict` 경고가 그 두 컷을 짚고 있었는데,
    경고만 하고 고치지는 않고 있었다.
    """
    # ★ 2026-09-03 개정: 승격 조건에 **자를 구조가 선언돼 있는가**가 붙었다. 골든B 의 두 컷은
    #   실제로 도해였으므로 구조가 있다 — 그 경우는 그대로 승격된다(이 테스트의 원래 의도).
    #   구조 없이 시퀀스 소속만으로 뒤집던 경로가 첫 실사형 렌더를 망쳤다(아래 회귀 테스트).
    cut = {"visual_role": "REALITY",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True},
           "mechanism": {"subject": "battery cell", "components": ["anode", "separator"],
                         "relationship": "ions cross the separator",
                         "transformation": "layer peels open", "initial_state": "sealed"}}
    assert generation_spec.effective_visual_role(cut) == "MECHANISM"
    assert generation_spec.image_spec(cut).model == config.image_model_for("MECHANISM")


def test_sequence_membership_alone_does_not_make_a_cut_a_3d_render():
    """★★ 첫 실사형 렌더 실측(2026-09-03, $5.39): 모델이 REALITY 로 라벨한 컷 10개 중 5개가
    라우터의 `in_visual_sequence` 하나로 MECHANISM 으로 뒤집혀 "isometric cutaway,
    no photorealistic texture, no people in focus" 를 받았다. 사무실의 실제 사람들이
    회색 마네킹이 든 아이소메트릭 단면으로 나왔고 참조 사슬이 그 룩을 뒤 컷까지 끌고 갔다.

    시퀀스 소속은 **연속성** 판정이지 화풍 판정이 아니다. 자를 구조가 없는 REALITY 컷은
    세계는 잇되 사진으로 그린다.
    """
    cut = {"visual_role": "REALITY",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True,
                                    "reasons": ["in_visual_sequence"]}}
    assert generation_spec.effective_visual_role(cut) == "REALITY"
    assert generation_spec.image_spec(cut).model != config.image_model_for("MECHANISM") \
        or config.image_model_for("MECHANISM") == config.IMAGE_MODEL


def test_a_directive_without_beats_keeps_its_legacy_label():
    """★ beat 를 안 쓴 지시서의 base 는 판정이 아니라 **합성된 기본값**이다.

    비용 산정에서 같은 실수를 이미 한 번 했다 — 만화식 3컷이 전부 CODE_VIZ 로 세어졌다.
    같은 값을 모델 선택에까지 쓰면 만화식 컷이 프리미엄 모델로 그려진다.
    """
    cut = {"visual_role": "REALITY",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": False}}
    assert generation_spec.effective_visual_role(cut) == "REALITY"


def test_a_legacy_cut_with_no_plan_at_all_is_unchanged():
    assert generation_spec.effective_visual_role({"visual_role": "MECHANISM"}) == "MECHANISM"
    assert generation_spec.effective_visual_role({}) == ""


def test_the_provider_is_told_which_model_to_use_not_left_to_guess():
    """★★ 2026-08-30 Mini Render 실측이 잡은 결함. 예상 $0.346 vs 실제 $0.251 이 드러냈다.

    `generation_spec` 만 고치고 **공급자의 자체 모델 선택은 그대로 뒀다.** 그래서 정본이
    기전 시퀀스로 판정한 컷1이 `visual_role="REALITY"` 라벨 때문에 **flash 로 그려졌다** —
    사양·원장은 pro 라고 적으면서.

    이 저장소가 이미 한 번 고친 버그의 재발이다: "호출은 역할별 모델, 원장은 다른 값".
    `generation_spec` 이 모델을 고르는 **유일한 자리**라는 계약을 호출로 강제한다.
    """
    from engine import render

    seen: list[str] = []

    def capture(cut, header, out_path, model="", ref_path=None):
        seen.append(model)
        with open(out_path, "wb") as f:
            f.write(b"png")
        return out_path, 0.0

    import unittest.mock as mock
    # ★ 2026-09-03: 승격 조건에 "자를 구조가 선언돼 있는가"가 붙었다(첫 실사형 렌더 실측).
    #   이 테스트가 지키려는 것은 **공급자가 정본의 모델을 받는가**이므로, 정본이 실제로
    #   기전이라는 근거(mechanism 구조)를 픽스처에 채워 의도를 그대로 유지한다.
    cut = {"cut_no": 1, "visual_role": "REALITY",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True},
           "mechanism": {"subject": "rocket stage", "components": ["hull", "insulation"],
                         "relationship": "insulation wraps the hull",
                         "transformation": "the hull peels open", "initial_state": "sealed"}}
    with tempfile.TemporaryDirectory() as d:
        img = os.path.join(d, "cut.png")
        with mock.patch.object(render.image_provider, "generate_image", capture), \
             mock.patch.object(render.config, "IMAGE_PROVIDER", "gemini"):
            render._gen_still(cut, {"version_type": "photo"}, img)
    assert seen == [config.image_model_for("MECHANISM")], (
        f"공급자가 정본의 모델을 못 받았다: {seen}")


def test_a_connective_cut_is_not_reference_conditioned_into_the_world():
    """★★ Mini Render B 가 실측으로 잡은 결함(2026-08-30). **렌더 없이는 못 찾았다.**

    골든B 컷3 은 "arXiv 논문"을 그리라고 한다. 라우터는 그 컷이 주장을 지불하지 않으므로
    `connective_in_world` 로 판정했다 — 배경 세계는 물려받되 기전 도해는 아니다.
    그런데 `reference_decision` 이 **정본을 안 보고** stage 의 continuity_mode 만 봐서
    앞 stage 의 우주 프레임을 시작 화면으로 줬다.

    결과: 모델이 둘을 억지로 합쳐 **우주를 모니터에 띄운 회의실**을 그렸고, 그 모니터에
    'arXiv' 글자가 박혔다. 세계가 이어진 게 아니라 오염됐다.

    "같은 세계를 잇는다"와 "이 컷이 그 세계를 그린다"는 다른 말이다.
    """
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    cut = {"cut_no": 2,
           "resolved_visual_plan": {"base": "OVERLAY", "beat_declared": True}}
    got = sr.reference_decision(cut, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "connective"
    assert got["ref_asset"] == "", "연결 컷에 참조 그림이 붙었다"
    assert got["degraded"] == [], "연결 컷은 저하가 아니라 **정상**이다"


def test_a_mechanism_cut_in_the_same_stage_still_gets_the_reference():
    """★ 반대 방향: 고치면서 진짜 기전 컷까지 끊으면 v3 가 통째로 무의미해진다."""
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    cut = {"cut_no": 2,
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True}}
    got = sr.reference_decision(cut, header, {"S1": "/tmp/s1.png"})
    assert got["kind"] == "reference" and got["ref_asset"] == "/tmp/s1.png"


def test_asking_for_a_logo_is_asking_the_image_model_to_draw_text():
    """★★ Mini Render B: 컷3 프롬프트가 "research paper with 'arXiv' logo visible" 을
    요구했고 화면에 'arXiv' 가 그대로 박혔다.

    부정문 목록(`_BANNED_NOUN`)에는 `logos` 가 **이미 있었다** — 금지는 인정하면서
    요구는 못 잡고 있었다. 같은 어휘가 한쪽 목록에만 있으면 게이트가 반쪽이 된다.
    """
    from engine import photo_contract as pc
    bad = {"visual_prompt": "a research paper with 'arXiv' logo visible", "motion_prompt": ""}
    assert pc._FORBIDDEN_SCREEN.search(pc._text_of(bad))
    ok = {"visual_prompt": "a research paper on a desk. No logos or watermarks.",
          "motion_prompt": ""}
    assert not pc._FORBIDDEN_SCREEN.search(pc._text_of(ok))


def test_the_style_does_not_flip_in_the_middle_of_a_sequence():
    """★★ 2026-08-30 프롬프트 실측이 잡은 결함. **돈을 쓰지 않고 눈으로 보였다.**

    프롬프트를 뽑아 놓으니 골든B 의 1단계와 2단계가 정면으로 모순이었다:

        1단계(라벨 REALITY)   … not an illustration, no 3D render, no painting
        2단계(라벨 MECHANISM) … not a photograph, no photorealistic texture

    그러면서 2단계는 "앞 이미지와 SAME setting/lighting/materials 를 유지하라"고 말한다 —
    **사진으로 만든 그림을 첨부하고 사진이면 안 된다고 하는 것**이다. 사슬이 이어질 수 없다.

    모델 선택은 정본을 따르게 고쳤는데 **화풍 선택은 옛 라벨을 보고 있었다.**
    같은 버그의 세 번째 자리였다(판정 → 모델 → 화풍).
    """
    header = {"global_style": "clean", "version_type": "photo"}
    cut = {"visual_prompt": "a rocket", "visual_role": "REALITY",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True},
           "mechanism": {"subject": "rocket stage", "components": ["hull", "insulation"],
                         "relationship": "insulation wraps the hull",
                         "transformation": "the hull peels open", "initial_state": "sealed"}}
    prompt = image_provider._build_image_prompt(cut, header)
    assert "not a photograph" in prompt, "정본이 기전인데 실사 화풍이 붙었다"
    assert "no 3D render" not in prompt, "같은 프롬프트가 3D 를 요구하며 금지한다"


# ── 사장님이 Gemini 채팅에서 만든 6장이 드러낸 것 (2026-08-30, API 비용 0) ──
def test_a_digital_timer_request_is_a_text_request():
    """★★ 채팅 실측: 6장 중 한 장에 **`3.456 s` 가 큰 글자로 박혔다.**

    프롬프트는 "no text, no numbers" 라고 하면서 동시에 "a digital timer overlay next to it
    displays a consistent rotation period" 를 요구했다. Phase 0 의 `35°` 번인과 같은 계열이다.
    게이트는 차트·라벨·로고는 잡으면서 **계기판·타이머는 못 잡고 있었다.**
    """
    from engine import photo_contract as pc
    bad = {"visual_prompt": "a digital timer overlay displays the rotation period",
           "motion_prompt": ""}
    assert pc._FORBIDDEN_SCREEN.search(pc._text_of(bad))


def test_correctly_forbidding_a_timer_is_not_punished():
    """★ 반대 방향. 로고를 고칠 때 배운 것을 바로 다음 수정에서 또 어겼다 —
    요구 목록에만 넣었더니 "No timers or gauges." 라고 **옳게 쓴 것**이 차단됐다.
    두 목록(_BANNED_NOUN / _FORBIDDEN_SCREEN)은 같은 어휘를 담아야 한다.
    """
    from engine import photo_contract as pc
    ok = {"visual_prompt": "a rocket tumbling in space. No timers, gauges or numbers.",
          "motion_prompt": ""}
    assert not pc._FORBIDDEN_SCREEN.search(pc._text_of(ok))


def test_the_reference_prompt_carries_the_change_not_the_whole_scene():
    """★★ 채팅 실측: 6장에서 구도가 계속 헤맸다.

    참조 프롬프트가 `Change ONLY the following:` 이라고 해놓고 **뒤에 장면 전체 묘사**를
    붙이고 있었다("medium shot of the Falcon 9 upper stage spinning steadily, …").
    "이것만 바꿔라" 하고 전부 바꾸라고 한 셈이다.

    변화는 이미 구조로 있다(stage.mutations). `change_prose` 를 만들어 놓고 **배선하지
    않았던 것**을 잇는다.
    """
    header = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    cut = {"cut_no": 2, "visual_prompt": "a completely different wide establishing shot",
           "visual_role": "MECHANISM"}
    prompt = image_provider._build_image_prompt(cut, header, referenced=True)
    assert "on the right" in prompt, "변화 서술이 프롬프트에 없다"
    assert "completely different wide establishing shot" not in prompt, (
        "참조 컷인데 장면 전체 묘사가 그대로 들어갔다")


def test_the_camera_lock_is_lifted_when_the_stage_moves_the_camera():
    """★ 채팅 실측: "SAME camera angle" 이라고 못박아 놓고 컷은 "extreme close-up" 을
    요구했다. 서로 반대말이다. 카메라는 구조화돼 있으니(camera_operation) 그 값을 본다."""
    hold = _header(_stage("S1"), _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,)))
    moving = _header(_stage("S1"),
                     _stage("S2", "CONTINUE_WORLD", "S1", cuts=(2,), camera_operation="DOLLY_IN"))
    cut = {"cut_no": 2, "visual_role": "MECHANISM"}
    assert "SAME camera angle" in image_provider._build_image_prompt(cut, hold, referenced=True)
    assert "camera may move" in image_provider._build_image_prompt(cut, moving, referenced=True)


def test_the_gate_inspects_the_string_that_will_actually_be_sent():
    """★★ 검사 대상과 전송 대상이 다르면 게이트는 있으나 마나다.

    컷 프롬프트에서 타이머 요구를 막았더니 같은 요구가 **변이 선언**에 남아 있었다:
    `TIMER_OVERLAY appear to Digital timer showing changing rotation period`.
    참조 컷의 프롬프트 꼬리는 이제 그 변이에서 만들어지므로, 게이트도 거기를 봐야 한다.
    """
    seq = {"sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
           "world": {"world_id": "W"},
           "entities": [{"entity_id": "BAR", "visual_identity": "a bar"}],
           "stages": [
               {"stage_id": "S1", "cut_refs": [1], "claim_ids": ["C1"],
                "observable_change": "막대가 자란다", "entity_refs": ["BAR"],
                "state_before": {"BAR": "short"},
                "mutations": [{"entity_id": "BAR", "operation": "GROW", "visible_change": True,
                               "result_state": "short"}]},
               {"stage_id": "S2", "cut_refs": [2], "claim_ids": ["C2"],
                "continuity_mode": "CONTINUE_WORLD", "continuity_from": "S1",
                "observable_change": "막대가 더 자란다", "entity_refs": ["BAR"],
                "state_before": {"BAR": "short"},
                # 프롬프트로 나갈 문장에 정확한 비율이 들어 있다.
                "mutations": [{"entity_id": "BAR", "operation": "GROW", "visible_change": True,
                               "result_state": "exactly 15 percent taller than before"}]}]}
    got = vc.evaluate(vs.normalize_all([seq]), cuts=[{"cut_no": 1}, {"cut_no": 2}])
    assert any(r.startswith("vseq_quantitative_visual") and "S2" in r
               for r in got["block_reasons"]), got["block_reasons"]


def test_a_newly_appearing_entity_carries_its_declared_look():
    """★★ 채팅 실측 2차(2026-08-30). **고치다가 다른 것을 떨어뜨렸다.**

    참조 프롬프트를 "변화만" 말하도록 고치면서 **개체가 어떻게 생겼는지를 같이 뺐다.**
    궤적선을 `Glowing blue line` 이라고 선언해 뒀는데 프롬프트에 안 실려서 화면엔
    **주황색**으로 나왔다 — 화풍 접미사의 `single amber accent color` 가 대신 결정한 것이다.

    선언은 이미 구조로 있었다(entities[].visual_identity). `visual_sequence.entity_prose` 도
    이미 있었다. **만들어 놓고 배선하지 않은 것이 이번이 세 번째다**(change_prose ·
    entity_prose · effective_visual_role).
    """
    header = {
        "version_type": "photo",
        "visual_sequences": [{
            "sequence_id": "SEQ1", "sequence_role": "MECHANISM_SEQUENCE",
            "world": {"world_id": "W"},
            "entities": [{"entity_id": "LINE",
                          "visual_identity": "Glowing blue line representing orbital path"}],
            "stages": [
                {"stage_id": "S1", "cut_refs": [1], "continuity_mode": "NEW_WORLD",
                 "observable_change": "x", "mutations": []},
                {"stage_id": "S2", "cut_refs": [2], "continuity_mode": "CONTINUE_WORLD",
                 "continuity_from": "S1", "observable_change": "선이 나타난다",
                 "mutations": [{"entity_id": "LINE", "operation": "APPEAR",
                                "visible_change": True, "result_state": "traced back"}]}]}]}
    prompt = image_provider._build_image_prompt(
        {"cut_no": 2, "visual_role": "MECHANISM"}, header, referenced=True)
    assert "Glowing blue line" in prompt, "새로 등장하는 개체의 외형이 프롬프트에 없다"


def test_an_entity_already_on_screen_is_not_redescribed():
    """★ 이미 화면에 있는 개체는 **참조 이미지가 이미 보여 주고 있다.**
    그 외형을 또 말하면 "바꾸라"는 신호로 읽힐 수 있다 — 새로 등장하는 것만 싣는다."""
    from engine import sequence_render as s
    stage = {"mutations": [{"entity_id": "ROCKET", "operation": "MOVE", "visible_change": True}]}
    seq = {"entities": [{"entity_id": "ROCKET", "visual_identity": "a white rocket"}]}
    assert s.appearing_entity_prose(stage, seq) == ""


def test_the_repaint_clause_is_dropped_when_continuing_a_world():
    """★★ 채팅 3차 실측(2026-08-30): 은색이던 엔진·노즐이 통째로 **금색**이 됐다.

    MECHANISM 화풍에 `single amber accent color on the part being explained` 이 있다.
    이것은 "설명 중인 부품을 호박색으로 칠하라"는 뜻이고, **컷마다 설명 대상이 바뀌므로
    정의상 물체 색이 매 컷 달라진다.** 그런데 같은 프롬프트가 `keep the SAME materials`
    라고 말한다 — 두 지시가 정면으로 싸운다.

    첫 컷에서는 옳은 규칙이다(설명 대상을 눈에 띄게 한다). 이어지는 컷에서는 참조
    이미지가 이미 재질을 확정했으므로 다시 칠할 이유가 없다.
    """
    cut = {"visual_prompt": "a rocket", "visual_role": "MECHANISM"}
    header = {"version_type": "photo"}
    first = image_provider._build_image_prompt(cut, header)
    cont = image_provider._build_image_prompt(cut, header, referenced=True)
    # ★ 2026-09-18 색 규약으로 문구가 바뀌었다(config.STYLE_CLAUSES_DROPPED_WHEN_REFERENCED 가 정본).
    #   검사의 뜻은 그대로다 — 첫 컷에는 있고 참조 컷에는 없다.
    clause = config.STYLE_CLAUSES_DROPPED_WHEN_REFERENCED[0]
    assert clause in first
    assert clause not in cont
    # 비교용 두 색은 참조 컷에서도 **남는다** — 집단 색이 컷마다 바뀌면 범례가 거짓이 된다.
    assert "muted blue and muted coral" in cont
    # 나머지 화풍은 그대로여야 한다 — 참조 컷만 다른 그림체가 되면 그것도 단절이다.
    # ★ 화풍 문자열은 2026-09-07 에 바뀌었다(운영자 지시로 두 역할을 한 언어로 통일).
    #   검사의 뜻은 그대로다 — 참조 컷만 다른 그림체가 되면 그것도 단절이다.
    assert "stylized 3D render" in cont
    assert "isometric cutaway" in cont
    assert "matte surfaces with minimal micro-texture" in cont


# ── 영상 프롬프트도 같은 규율을 쓴다 (2026-08-30) ────────────────
def test_the_video_prompt_says_animate_not_redraw():
    """★★ Phase 0 이 관찰한 "Veo 가 애니메이트한 게 아니라 다시 그린 쪽에 가깝다" 는
    **Veo 한계가 아니라 우리 지시 탓일 수 있다.**

    고치기 전 영상 프롬프트는 이랬다:
        global_style + role_style + visual_prompt + motion_prompt
    즉 시작 이미지를 주면서 동시에 **장면 전체를 다시 묘사**하고 있었다.
    이미지 경로에서 고친 것과 똑같은 결함이 영상 경로에 그대로 있었다.
    """
    from engine.providers import video as vp
    cut = {"visual_role": "MECHANISM",
           "visual_prompt": "a completely different establishing shot of a factory",
           "motion_prompt": "the trajectory line draws itself backwards"}
    got = vp.build_motion_prompt(cut, {"global_style": "clean", "version_type": "photo"})
    assert got.startswith("Animate the attached still image")
    assert "Do not redraw" in got
    assert "the trajectory line draws itself backwards" in got
    # 장면 묘사는 넣지 않는다 — 시작 프레임이 이미 장면이다.
    assert "factory" not in got


def test_the_video_prompt_uses_the_resolved_role_and_drops_the_repaint_clause():
    """★ 옛 라벨을 읽으면 첫 프레임과 클립의 화풍이 갈린다. 그리고 '설명 대상을 다시
    칠하라'를 클립에 넣으면 **클립 안에서 색이 변한다** — 시작 프레임이 이미 재질을 정했다."""
    from engine.providers import video as vp
    cut = {"visual_role": "REALITY", "motion_prompt": "slow drift",
           "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE", "beat_declared": True},
           "mechanism": {"subject": "rocket stage", "components": ["hull", "insulation"],
                         "relationship": "insulation wraps the hull",
                         "transformation": "the hull peels open", "initial_state": "sealed"}}
    got = vp.build_motion_prompt(cut, {"version_type": "photo"})
    assert "isometric cutaway" in got     # 정본의 역할(MECHANISM)을 따랐다
    assert "amber accent color on the part being explained" not in got


def test_video_cuts_go_through_the_same_still_path_as_image_cuts():
    """★★ 다섯 번째 같은 종류 버그(2026-08-30). Phase 3 배선을 **스틸 컷 분기에만** 넣었다.

    `motion_source == "video"` 컷은 그보다 위에서 따로 처리되는데 거기엔 참조가 안 실렸다.
    그런데 **실사형 영상은 대부분이 영상 컷**이다 — 내가 만든 연속성이 정작 주 경로에서
    안 돌고 있었다.

    원인은 **두 곳이 갈라져 있다는 것 자체**다(판정 → 모델 → 화풍 → 영상 프롬프트 →
    여기). 그래서 "이 컷의 첫 그림을 어떻게 얻는가"를 함수 하나로 모았다.
    갈라져 있지 않으면 한쪽만 고칠 수가 없다.
    """
    import inspect

    from engine import render
    src = inspect.getsource(render._gen_cut_assets)
    # 두 분기가 **같은 함수**를 부른다.
    assert src.count("_obtain_still(") == 2, "첫 그림을 얻는 경로가 다시 갈라졌다"
    # 그리고 그 함수만이 _gen_still 을 부른다 — 우회로가 생기면 여기서 깨진다.
    assert "_gen_still(" not in src, "_gen_cut_assets 가 _obtain_still 을 우회한다"
    assert "ref_path" in inspect.getsource(render._obtain_still)


def test_a_declared_precision_layer_must_have_a_card_that_fills_it(monkeypatch):
    """★★ 여섯 번째 같은 종류 결함(2026-08-30 훑기).

    코덱스 리뷰 R1 의 간판 변경이 "수치는 세계를 끊지 않고 코드 오버레이로 얹힌다"인데,
    `precision_layer` 를 읽는 곳이 **비용 계산 한 군데뿐**이었다 — 그리는 코드가 없다.

    실제로 숫자를 화면에 올리는 것은 기존 `overlay_plan` 이다. 즉 기능이 없는 게 아니라
    **둘이 따로 놀고 있었다.** 따로 놀면 언젠가 어긋난다.
    정본이 레이어를 선언했으면 그것을 채우는 카드가 반드시 있어야 한다.
    """
    # ★ 근거 카드는 2026-09-08 운영자 지시로 **기본 꺼짐**이다
    #   (config.EVIDENCE_OVERLAY_ENABLED). 이 테스트가 지키는 것은 "카드를 쓰기로 한
    #   날 그 규칙이 제대로 도는가" 이므로 스위치를 켜고 검사한다 — 규칙 자체는 살려 둔다.
    monkeypatch.setattr(config, "EVIDENCE_OVERLAY_ENABLED", True)
    from engine import photo_contract as pc
    base = {"cut_no": 1, "visual_role": "MECHANISM", "narration_ko": "궤도를 되짚습니다",
            "visual_prompt": "a cutaway showing the flow of the traced path",
            "estimated_sec": 5, "mechanism": {"subject": "궤적", "components": ["로켓"],
                                              "relationship": "역추적", "initial_state": "앞",
                                              "transformation": "되짚음", "final_state": "뒤",
                                              "highlighted_element": "선"}}
    naked = {**base, "resolved_visual_plan": {"base": "MECHANISM_SEQUENCE",
                                              "precision_layer": "CODE_OVERLAY"},
             "overlay_plan": []}
    got = pc.evaluate({"hook_ko": "훅"}, [naked], None)
    assert any(r.startswith("photo_number_without_overlay") for r in got["block_reasons"]), (
        f"정밀 레이어를 선언했는데 채우는 카드가 없어도 통과했다: {got['block_reasons']}")

    filled = {**naked, "overlay_plan": [{"type": "number_punch", "text": "7분 → 8초",
                                         "claim_ids": ["C1"], "start_sec": 1.0,
                                         "duration_sec": 2.0, "priority": "primary"}]}
    got2 = pc.evaluate({"hook_ko": "훅"}, [filled], None)
    assert not any(r.startswith("photo_number_without_overlay") for r in got2["block_reasons"])
