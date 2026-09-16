"""컷별 렌더 manifest 선언·대조 (작업지시서 영상엔진품질 v3 §8-1).

무엇을 고정하는가: 지금까지 "이 컷에 무엇이 있어야 했는가"가 선언된 곳이 없어서, 요소가
조용히 빠져도 아무도 몰랐다. 여기서는 ① 선언이 실제 라우팅과 어긋나지 않는지 ② 그려진
placement 가 전부 어느 레이어인지 밝혀지는지 ③ 결측·폴백이 실제로 잡히는지 ④ 그리고
**이 관측이 렌더를 죽이지 않는지**를 본다.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from engine import board_render, component_registry as cr, config, render_manifest as rm
from engine.board_layout import Box, Placement


def _fonts_available() -> bool:
    from engine import visual_contract as vc

    return all(os.path.exists(os.path.join(vc.FONT_DIR, f)) for f in vc.FONT_FILES.values())


needs_fonts = pytest.mark.skipif(not _fonts_available(), reason="폰트 자산 없음")


# ── 선언이 라우팅과 어긋나지 않는가 ──────────────────────────
def test_declared_core_component_matches_the_router():
    """라우팅 표만 바꾸고 manifest 를 안 고치면 선언이 거짓말을 한다."""
    for board in config.EXPLAINER_CODE_RENDER_BOARDS:
        got = rm.declare(board, {"pay": {}})
        core = next(x for x in got["expected_layers"] if x["layer_id"] == "core")
        assert core["component"] == cr.resolve_for_board(board, allow_draft=False).component


def test_every_declared_component_is_registered():
    for board in config.EXPLAINER_CODE_RENDER_BOARDS:
        for layer in rm.declare(board, {"pay": {}})["expected_layers"]:
            if layer["component"]:
                cr.get_component(layer["component"])   # 미등록이면 KeyError


def test_criticality_comes_from_the_registry_not_a_per_cut_field():
    """컷마다 손으로 적기 시작하면 유지가 안 된다 — 역할 단위로만 산다."""
    assert cr.get_component("section_kicker").criticality == "important"
    assert cr.get_component("number_count").criticality == "critical"
    assert set(rm.CRITICALITY_BY_LAYER) == {"title", "sowhat", "backdrop"}
    for spec in cr.CORE_COMPONENTS.values():
        assert spec.criticality in ("critical", "important", "decorative")


def test_source_layer_is_unobservable_not_missing():
    """출처는 보드가 아니라 ASS footer 로 나간다. missing 으로 세면 **모든 컷이** 걸린다."""
    declared = rm.declare("NUMBER_BOARD", {"pay": {}})
    src = next(x for x in declared["expected_layers"] if x["layer_id"] == "source")
    assert src["observable"] is False
    out = rm.reconcile(declared, [])
    assert out["unobservable"] == ["source"]
    assert "source" not in [m["layer_id"] for m in out["missing"]]


# ── 대조 ────────────────────────────────────────────────────
def _pl(layer_id: str, component: str = "") -> Placement:
    p = Placement(kind="text", box=Box(100, 600, 900, 700), band="CORE", text="x")
    return rm.tag([p], layer_id, component)[0]


def test_missing_critical_layer_is_counted():
    declared = rm.declare("NUMBER_BOARD", {"pay": {"sowhat": ""}, "title_text": "제목"})
    out = rm.reconcile(declared, [_pl("backdrop")])
    assert {m["layer_id"] for m in out["missing"]} >= {"core", "title"}
    assert out["counts"]["critical"] >= 2


def test_fallback_is_recorded_when_a_different_component_drew():
    declared = rm.declare("NUMBER_BOARD", {"pay": {}})
    out = rm.reconcile(declared, [_pl("core", "text_core")])
    assert out["fallback"] == [{"layer_id": "core", "from": "number_count", "to": "text_core"}]


def test_untagged_placements_are_counted():
    """새 그리기 지점을 스탬프 없이 추가하면 여기서 드러난다."""
    declared = rm.declare("HOOK_BOARD", {"pay": {}})
    stray = Placement(kind="text", box=Box(100, 600, 900, 700), band="CORE", text="y")
    assert rm.reconcile(declared, [stray])["untagged_placements"] == 1


def test_reconcile_is_record_only():
    """판정을 만들지 않는다 — layout_qa 처럼 fail/warn 키를 내면 안 된다."""
    out = rm.reconcile(rm.declare("HOOK_BOARD", {"pay": {}}), [])
    assert out["policy"] == "record_only"
    assert "fail" not in out and "warn" not in out


# ── 실제 렌더와의 배선 ───────────────────────────────────────
@needs_fonts
def test_every_drawn_placement_belongs_to_a_declared_layer():
    from scripts.preview_board import DEMO_CUTS, DEMO_HEADER

    with tempfile.TemporaryDirectory() as d:
        for i, cut in enumerate(DEMO_CUTS):
            res = board_render.render_board(cut, DEMO_HEADER, None, d, i, total_sec=2.0)
            assert res.manifest["untagged_placements"] == 0, cut["board"]
            assert res.manifest["unexpected"] == [], cut["board"]


@needs_fonts
def test_dataless_number_board_records_fallback_that_drew_nothing():
    """★ 실측 결함: 숫자 없는 NUMBER_BOARD 는 text_core 로 폴백하지만, 그 보드에는 `core`
    단계가 없어 폴백조차 아무것도 못 그린다(core_fill 0.00). §8-2 의 "재시도→폴백" 처방이
    현 코드에서 실효가 없다는 뜻이라, 승격 전에 기록으로 세워 둔다.
    """
    from scripts.preview_board import DEMO_HEADER

    cut = {"cut_no": 9, "board": "NUMBER_BOARD", "beat_role": "EVIDENCE",
           "number_claim_refs": []}
    with tempfile.TemporaryDirectory() as d:
        res = board_render.render_board(cut, DEMO_HEADER, None, d, 0, total_sec=2.0)

    core = next(x for x in res.manifest["layers"] if x["layer_id"] == "core")
    assert core["status"] == "fallback_empty", "폴백 시도와 단순 결측은 원인이 다르다"
    assert res.manifest["fallback"] == [
        {"layer_id": "core", "from": "number_count", "to": "text_core"}]
    assert res.core_fill == 0.0


@needs_fonts
def test_manifest_never_blocks_the_render():
    """결측이 있어도 manifest 때문에 죽지 않는다 — 판정은 충전율 게이트가 따로 한다."""
    from scripts.preview_board import DEMO_HEADER

    cut = {"cut_no": 9, "board": "NUMBER_BOARD", "beat_role": "EVIDENCE",
           "number_claim_refs": []}
    with tempfile.TemporaryDirectory() as d:
        res = board_render.render_board(cut, DEMO_HEADER, None, d, 0, total_sec=2.0)

    assert res.frame_paths, "예외 없이 프레임이 나와야 한다"
    assert not any("manifest" in f for f in res.layout_qa["fail"]), \
        "manifest 는 판정에 한 글자도 넣지 않는다"


def test_manifest_reaches_the_job_record():
    """qa.board 로 흘러가지 않으면 기록을 켠 의미가 없다(schema_parity 관례와 같은 소스 검사)."""
    import inspect

    from engine import render

    assert '"manifest": res.manifest' in inspect.getsource(render._gen_cut_assets)


# ── §8-2 판정 승격 — done 은 critical 이 전부 있을 때만 ──────────
def _cut(cut_no: int, *missing: tuple[str, str]) -> dict:
    return {"cut_no": cut_no,
            "manifest": {"missing": [{"layer_id": lid, "criticality": crit}
                                     for lid, crit in missing]}}


def test_clean_render_is_done():
    assert rm.terminal_status([_cut(1), _cut(2)]) == ("done", [])
    assert rm.terminal_status([])[0] == "done"
    assert rm.terminal_status(None)[0] == "done"


def test_missing_critical_layer_fails_the_job():
    """§8-3 'done = critical QA 전부 PASS 일 때만'."""
    status, reasons = rm.terminal_status([_cut(3, ("core", "critical"))])
    assert status == "failed"
    assert reasons == ["missing_critical:core#3"], "컷·레이어·사유가 기록에 남아야 한다"


def test_missing_important_layer_needs_human_approval():
    status, reasons = rm.terminal_status([_cut(5, ("meta", "important"))])
    assert status == "degraded"
    assert reasons == ["missing_important:meta#5"]


def test_critical_wins_over_important():
    status, _ = rm.terminal_status([_cut(1, ("meta", "important")),
                                    _cut(2, ("core", "critical"))])
    assert status == "failed"


def test_decorative_alone_does_not_hold_the_job():
    """장식이 빠졌다고 사람을 부르면 승인이 일상이 되고, 일상이 되면 아무도 안 본다."""
    assert rm.terminal_status([_cut(1, ("backdrop", "decorative"))]) == ("done", [])


def test_unobservable_source_layer_cannot_fail_every_cut():
    """★ 이 승격이 성립하는 이유가 UNOBSERVABLE_LAYERS 한 줄에 걸려 있다.

    출처는 보드가 아니라 ASS footer 로 나가 placements 로 관측이 안 된다. missing 에서
    빼지 않으면 **모든 컷이 critical 누락**이 되어 승격 첫날 전부 failed 가 된다.
    """
    declared = rm.declare("NUMBER_BOARD", {"pay": {}})
    out = rm.reconcile(declared, [])
    assert "source" not in [m["layer_id"] for m in out["missing"]]
    assert "source" in out["unobservable"]


def test_both_render_paths_use_the_same_judgement():
    """논문·리포트 두 워커가 각자 판정하면 같은 결함이 한쪽에서만 잡힌다."""
    import inspect

    from engine import render, report_render

    assert "terminal_status" in inspect.getsource(render.process_job)
    assert "terminal_status" in inspect.getsource(report_render.process_job)


def test_a_job_waiting_for_a_human_is_not_marked_finished():
    """finished=True 는 '더 볼 일 없음'이다. degraded 를 그렇게 닫으면 승인 자체가 무의미하다."""
    import inspect

    from engine import render, report_render

    for fn in (render.process_job, report_render.process_job):
        src = inspect.getsource(fn)
        assert "RENDER_STATUS_AWAITING_HUMAN" in src, f"{fn.__qualname__}: 사람 대기를 구분 안 한다"


# ── §21 K5 편당 비용 캡 · EN 출처 라벨 (2026-08-03 감사에서 나온 미배선 2건) ──
def test_explainer_has_a_lower_cost_cap():
    """★ 실측 결함: EXPLAINER_COST_CAP_USD 를 읽는 곳이 한 군데도 없었다(grep 0건).
    실제로 작동하던 캡은 RENDER_BUDGET_CAP_USD 하나 — 명세값(§21 K5 $0.25)의 5배였다."""
    assert config.render_budget_cap("explainer") == config.EXPLAINER_COST_CAP_USD
    assert config.render_budget_cap("comic") == config.RENDER_BUDGET_CAP_USD
    assert config.render_budget_cap("") == config.RENDER_BUDGET_CAP_USD
    assert config.EXPLAINER_COST_CAP_USD < config.RENDER_BUDGET_CAP_USD


def test_report_render_uses_the_version_aware_cap():
    """캡 함수를 만들어 놓고 워커가 안 쓰면 배선이 안 된 것과 같다."""
    import inspect

    from engine import report_render

    src = inspect.getsource(report_render.process_job)
    assert "render_budget_cap(version_type)" in src
    assert "RENDER_BUDGET_CAP_USD" not in src, "버전 무관 캡을 그대로 쓰면 K5 가 죽는다"


def test_cost_warning_fires_before_the_cap_kills_the_job():
    """캡은 잡을 죽인다. 설명판형 실측 비용이 아직 없으므로, 죽기 전에 '얼마까지 왔는지'가
    로그에 남아야 캡을 사후 교정할 수 있다."""
    import inspect

    from engine import report_render

    src = inspect.getsource(report_render.process_job)
    assert "RENDER_COST_WARN_RATIO" in src
    assert 0.0 < config.RENDER_COST_WARN_RATIO < 1.0


def test_english_video_gets_an_english_source_label():
    """★ 실측 결함: 면책 문구는 en 으로 갈리는데 "출처"만 한글로 남아, 영어 영상 하단에
    `출처 하나증권 · For information only…` 가 나갔다."""
    from engine import report_render as rr

    en = rr._disclaimer_footer("Hana Securities", "en")
    assert en.startswith("Source Hana Securities")
    assert "출처" not in en
    assert "For information only" in en

    ko = rr._disclaimer_footer("하나증권", "ko")
    assert ko.startswith("출처 하나증권")
    assert "투자 권유가 아닙니다" in ko


def test_footer_without_broker_has_no_dangling_label():
    """증권사가 비면 라벨도 빼야 한다 — `Source  · For information…` 은 깨져 보인다."""
    from engine import report_render as rr

    assert rr._disclaimer_footer("", "en") == "For information only. Not investment advice."
    assert rr._disclaimer_footer("", "ko") == config.REPORT_DISCLAIMER_TEXT


# ── 허전한 보드는 죽이지 않고 사람에게 넘긴다 (2026-08-19) ────

def test_underfilled_board_becomes_degraded_not_failed():
    """설명판형 렌더 8건 중 5건이 이 사유 하나로 죽고 두 주간 멈춰 있었다.

    판정 자체는 옳다(빈 보드는 발행되면 안 된다). 바꾼 것은 처리 방식이다 — 이미지·TTS·조립
    비용을 다 쓴 뒤 산출물을 버리는 대신, 영상을 만들어 두고 사람이 ⑥ 화면에서 보고 정한다.
    """
    status, reasons = rm.terminal_status(
        [{"cut_no": 6, "layout_fail": ["core_underfilled:0.18"], "manifest": {}}])
    assert status == "degraded"
    assert reasons and "core_underfilled" in reasons[0]


def test_full_board_still_passes():
    status, reasons = rm.terminal_status([{"cut_no": 1, "layout_fail": [], "manifest": {}}])
    assert (status, reasons) == ("done", [])


# ── I2V 연쇄 · 실사형 상한 (2026-08-20) ──────────────────────

def test_last_frame_command_reads_from_the_end():
    """연쇄의 재료는 클립의 **마지막** 프레임이다. -sseof 로 끝에서 되짚어야 한다."""
    from engine import assemble
    argv = assemble.build_last_frame_command("clip.mp4", "frame.png")
    assert "-sseof" in argv, "끝에서 되짚지 않으면 첫 프레임이 나온다"
    assert argv[argv.index("-i") + 1] == "clip.mp4"
    assert argv[-1] == "frame.png"


def test_photo_gets_a_higher_clip_limit_than_the_mode_table():
    """실사형은 '움직이는 화면'이 문법이라 기본 상한(모드별 최대 4개)이 정체성을 깎는다.

    ★ 상한이 두 겹이라 한쪽만 풀면 다른 쪽이 다시 4개로 자른다 — 둘 다 본다.
    """
    from engine import directive as dv

    def _cuts():
        return [{"cut_no": i, "motion_source": "video"} for i in range(1, 11)]

    photo = _cuts()
    dv.enforce_mode_video_budget(photo, "standard", "photo")
    dv.enforce_video_clip_cap(photo, "photo")
    assert sum(1 for c in photo if c["motion_source"] == "video") == 8

    comic = _cuts()
    dv.enforce_mode_video_budget(comic, "standard", "comic")
    dv.enforce_video_clip_cap(comic, "comic")
    assert sum(1 for c in comic if c["motion_source"] == "video") == 2, "만화식은 그대로여야 한다"


def test_photo_budget_cap_is_higher_because_it_has_more_cuts():
    """캡은 하드 스톱이라 넘으면 렌더가 죽고 이미 쓴 돈은 못 돌려받는다.

    실사형은 컷 10~14개 + 클립 비중이 높아 기존 $1.2 로는 12컷·4클립($1.27)에서 이미 터진다.
    """
    assert config.render_budget_cap("photo") > config.render_budget_cap("comic")
    assert config.render_budget_cap("explainer") < config.render_budget_cap("comic")


def test_photo_video_budget_is_raised_in_all_three_places():
    """상한이 세 겹이라 하나만 풀면 나머지가 다시 자른다 — 실제로 세 번 겪었다.

    개수 상한 두 개를 8개로 올렸는데도 지시서가 계속 영상 2개로 나왔고, 범인은 초수 예산
    (standard 8초 ÷ 4초 티어 = 2개)이었다.
    """
    from engine import content_mode

    base = content_mode.resolve_cost_plan("standard")
    sec, cost = config.video_budget_for("photo", base)
    assert sec >= 8 * config.VEO_CLIP_MAX_TIER_SEC, "8개 클립을 담을 초수여야 한다"
    assert cost > base["max_video_cost_usd"]
    # 만화식은 모드 예산 그대로.
    assert config.video_budget_for("comic", base) == (
        base["max_video_generated_sec"], base["max_video_cost_usd"])


def test_photo_clip_tier_covers_the_narration_instead_of_freezing():
    """정지 구간의 직접 원인을 막는다.

    실측(실사형 C형 시험작): 컷 4 의 나레이션이 5.76초인데 클립은 4초만 샀다. 남는 1.76초는
    마지막 프레임을 얼려 때웠고, 운영자가 바로 그 구간을 지적했다. 길이 보정 모듈
    (engine/clip_fit.py)이 미구현이라 핑퐁 루프도 못 쓰므로, 클립을 나레이션 길이에 맞춰
    사는 것이 지금 할 수 있는 해법이다.
    """
    from engine.providers import video

    for narration in (4.06, 5.18, 5.76):
        tier = video.pick_clip_tier(narration, max_sec=config.clip_tier_max("photo"))
        assert tier >= narration, f"{narration}초 나레이션에 {tier}초 클립이면 얼어붙는다"
    # 만화식은 그대로 4초 상한(비용 가드) — 화면이 바뀌면 안 된다.
    assert video.pick_clip_tier(5.76, max_sec=config.clip_tier_max("comic")) == 4


def test_photo_video_budget_leaves_room_under_the_render_cap():
    """티어를 올려도 예산이 캡을 넘으면 렌더가 도중에 죽는다(하드 스톱)."""
    from engine import content_mode

    _, cost = config.video_budget_for("photo", content_mode.resolve_cost_plan("standard"))
    assert cost < config.render_budget_cap("photo"), "영상 예산만으로 캡을 다 쓰면 스틸 몫이 없다"


def test_photo_preflight_prices_clips_at_the_version_tier_not_four_seconds():
    """예산 계산과 실제 구매가 같은 티어를 써야 한다 (2026-08-21).

    ★ 실측한 어긋남: 렌더(engine/render.py)는 `clip_tier_max(version)` 로 실사형 8초 클립을
      사는데, 지시서 단계의 preflight 과 cost_plan 은 그 인자를 안 넘겨 4초로 계산했다.
      결과 ① ⑤ 확인 모달이 실제의 절반을 보여주고(운영자가 총액을 보는 유일한 지점),
      ② preflight 이 초수 예산을 절반으로 세어 캡을 넘는 컷을 통과시킨다 → 렌더가 돈을 쓴 뒤
      하드 캡에서 죽는다.
    """
    from engine import directive as directive_mod

    cuts = [
        {"cut_no": i + 1, "motion_source": "video", "estimated_sec": 6,
         "asset_strategy": "new_asset"}
        for i in range(6)
    ]
    from engine.providers import video

    # 티어는 "나레이션 이상인 최소 티어"다 — 6초 컷이면 실사형 6초, 만화식은 상한 4초.
    photo_tier = video.pick_clip_tier(6, max_sec=config.clip_tier_max("photo"))
    comic_tier = video.pick_clip_tier(6, max_sec=config.clip_tier_max("comic"))
    assert photo_tier > comic_tier, "실사형은 나레이션을 덮는 티어를 살 수 있어야 한다"

    plan = directive_mod.compute_cost_plan([dict(c) for c in cuts], "standard", "photo")
    assert plan["video_generated_sec"] == 6 * photo_tier, (
        "버전을 안 넘기면 4초로 계산돼 실제보다 싸게 보인다")
    comic = directive_mod.compute_cost_plan([dict(c) for c in cuts], "standard", "comic")
    assert comic["video_generated_sec"] == 6 * comic_tier, "만화식 산정은 불변"
    assert plan["estimated_video_cost_usd"] > comic["estimated_video_cost_usd"]

    # preflight 도 같은 티어로 조인다 — 예산 초수를 실제 구매 티어로 나눈 개수만 남아야 한다.
    # ★ 2026-08-31: 승인 예산을 48 → 110 초로 올리면서(등급제 품질 구성을 담으려고)
    #   **제약이 예산에서 컷 수로 옮겨 갔다.** 종전 단언은 "예산이 항상 먼저 묶는다"를
    #   전제했는데 그건 그때 숫자에서만 참이었다. 이 테스트가 지키려는 것은
    #   "예산 계산과 실제 구매가 **같은 티어**를 쓴다"이므로 그 의도만 남기고,
    #   묶는 쪽이 둘 중 어느 것이든 맞게 비교한다.
    from engine import content_mode
    max_sec, max_cost = config.video_budget_for("photo", content_mode.resolve_cost_plan("standard"))
    many = [dict(c, cut_no=i + 1) for i, c in enumerate(cuts * 2)]  # 12컷 전부 video
    directive_mod.preflight_video_budget(many, "image_preferred", max_sec, max_cost, "photo")
    kept = sum(1 for c in many if c["motion_source"] == "video")
    assert kept == min(len(many), max_sec // photo_tier), (
        f"{max_sec}초 예산 ÷ {photo_tier}초 티어 = {max_sec // photo_tier}개여야 하는데 {kept}개")
