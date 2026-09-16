"""영상 프롬프트가 **화면 그래픽을 요구하지 못하게** 한다 (2026-08-31 G2·G4 실측 반영).

★ 무엇을 막는가: 골든B 컷5 의 이 한 문장이 게이트를 그냥 통과했다.

    "…then a graphic overlay appears indicating a crater diameter, whip-pan up…"

  그 컷으로 만든 클립 **넷 전부**가 달 표면 실사에서 "받침대 위 분화구 다이어그램"
  으로 끝났고 화면에 `DIAMETER`·`AGENT ZERO` 같은 지어낸 글자가 박혔다
  (docs/실측_품질/G2·G4/결과.md · world_drift 0.80~1.00).

★ 두 가지가 동시에 깨졌다:
  ① 글자 번인 — 오버레이가 수치를 담으니 필연이었다
  ② **세계 이탈** — 다이어그램은 그 장면이 아니다. I2V 가 시작 프레임을 버렸다

★ 근본 원인은 Veo 가 아니라 **우리 지시**다. 수치는 코드 정밀 레이어가 그린다는
  R1 원칙과 `no text` 네거티브가 같은 프롬프트 안에서 서로 모순돼 있었다.
"""

from __future__ import annotations

import re

from engine import directive as dv, photo_contract as pc


def _cut(no, motion="", visual="a rocket above the lunar surface"):
    return {"cut_no": no, "visual_prompt": visual, "motion_prompt": motion,
            "visual_role": "MECHANISM", "narration_ko": "설명", "narration_en": "x"}


def _blocked(cuts):
    res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"}, cuts, {})
    return [b for b in res["block_reasons"] if b.startswith("photo_forbidden_screen_request")]


# ── 실제로 사고를 낸 그 문장 ─────────────────────────────────
def test_the_exact_sentence_that_broke_four_clips_is_blocked():
    """★★ 회귀 방지의 본체. 이 문장이 통과하면 같은 사고가 다시 난다."""
    cut = _cut(5, "the rocket impacts the surface, then a graphic overlay appears "
                  "indicating a crater diameter, whip-pan up from the impact site")
    assert _blocked([cut]), "네 클립을 망친 그 문장이 여전히 통과한다"


def test_a_request_does_not_need_a_contradiction_to_be_caught():
    """★★ 종전 결함 — 이 패턴을 **모순일 때만** 검사했다.

    금지문("no text…")은 `build_motion_prompt` 가 발주 직전에 붙이므로 컷의 저장된
    프롬프트에는 없다. 그래서 요구만 있고 금지문이 없는 컷은 **아무 사유 없이
    통과했다.** 요구는 모순이 아니어도 요구다.
    """
    cut = _cut(5, "a graphic overlay appears indicating a crater diameter")
    assert "no text" not in cut["motion_prompt"]      # 금지문이 없다
    assert _blocked([cut])


def test_the_same_family_of_requests_is_covered():
    for motion in ("a data overlay appears with the figures",
                   "annotation lines mark the crater rim",
                   "a readout shows the rotation period",
                   "a HUD appears over the engine",
                   "dimension lines measure the crater"):
        assert _blocked([_cut(1, motion)]), motion


# ── 오탐 방지 — 옳게 한 것을 벌하지 않는다 ────────────────────
def test_plain_camera_motion_is_not_punished():
    """★ 이 저장소의 설계원칙: 옳게 한 것을 벌하는 게이트는 반드시 무시당한다."""
    for motion in ("the camera pushes in rapidly as dust settles",
                   "slow dolly-in towards the Moon, the stage tumbles steadily",
                   "the camera moves laterally alongside the rocket"):
        assert not _blocked([_cut(1, motion)]), motion


def test_correctly_forbidding_graphics_is_not_punished():
    """★ 부정문은 준수다 — 요구와 반대로 읽으면 안 된다."""
    cut = _cut(1, "slow push-in, no text, no captions, no labels, no numbers")
    assert not _blocked([cut])


def test_a_contradiction_is_reported_once_not_twice():
    """★ 같은 컷이 두 사유로 두 번 뜨면 노이즈가 되고, 노이즈가 되면 무시당한다.

    더 구체적인 쪽(모순 — 고치는 법이 다르다)이 이긴다.
    """
    cut = _cut(1, "a graphic overlay appears indicating the value, no on-screen text")
    res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"}, [cut], {})
    reasons = res["block_reasons"]
    assert any(r.startswith("photo_text_request_conflict") for r in reasons), reasons
    assert not any(r.startswith("photo_forbidden_screen_request") for r in reasons), reasons


# ── 프롬프트 쪽에서도 막는다 (게이트만 믿지 않는다) ────────────
def test_the_directive_prompt_forbids_it_too():
    """★ 게이트 어휘는 **유한 목록**이라 다른 말로 쓰면 통과한다(§9-9 Q7 의 한계).

    그래서 지시서 프롬프트에서도 금지한다 — 양쪽에서 막아야 실제로 줄어든다.
    """
    src = dv.SCREEN_GRAPHIC_BAN_GUIDANCE
    assert "화면 그래픽 금지" in src
    assert "graphic overlay appears" in src, "금지 예시가 구체적이지 않으면 모델이 못 알아본다"
    assert "overlay_plan 이 코드로" in src


def test_the_ban_is_not_scoped_to_one_field():
    """★★ 이번 회귀의 본체다.

    종전 금지문은 "[motion_prompt 금지]" 로 시작했다. 모델은 그것을 **motion_prompt
    에만 걸린 규칙**으로 읽었고, 같은 요구를 visual_prompt 에 그대로 썼다 —
    재생성 실측(2026-08-31) 위반 3건이 **전부** visual_prompt 였다.
    게이트는 처음부터 두 필드를 다 봤다(`_raw_text_of`). 반쪽이었던 것은 프롬프트다.

    그러므로 금지문은 **필드 이름으로 범위를 만들면 안 된다.**
    """
    src = dv.SCREEN_GRAPHIC_BAN_GUIDANCE
    assert "visual_prompt" in src and "motion_prompt" in src, "두 필드를 다 지목해야 한다"
    assert "둘 다" in src
    # 금지문이 특정 필드 전용으로 읽히는 옛 형태로 되돌아가지 않았는지
    assert "[motion_prompt 금지]" not in src


def test_the_ban_actually_reaches_the_photo_prompt():
    """★ 상수로 뽑아 놓고 **어디에도 안 붙이는** 것이 이 저장소의 단골 실패다.

    등급제를 켜는 버전(photo)의 실제 프롬프트 문자열에 들어 있는지 본다.
    """
    assert dv.SCREEN_GRAPHIC_BAN_GUIDANCE in dv.VERSION_GUIDANCE["photo"]


def test_the_gate_vocabulary_and_the_prompt_agree():
    """★ 프롬프트가 예시로 든 문장은 게이트가 실제로 잡아야 한다.

    한쪽만 고치면 "금지했다고 적어 놓고 통과시키는" 상태가 된다 — 이 저장소가
    logos·timers 로 이미 두 번 겪은 실패다(photo_contract 주석).
    """
    src = dv.SCREEN_GRAPHIC_BAN_GUIDANCE
    # 작은따옴표·큰따옴표 예시를 모두 걷는다(옛 테스트는 작은따옴표만 봤다).
    examples = re.findall(r"'([^']+…?)'", src) + re.findall(r'"([^"]+)"', src)
    checked = 0
    for example in examples:
        probe = example.replace("…", " the value")
        if not any(w in probe.lower() for w in
                   ("overlay", "annotation", "readout", "logo", "word", "screen showing")):
            continue
        checked += 1
        assert (pc._TEXT_REQUEST.search(probe)
                or pc._FORBIDDEN_SCREEN.search(probe)
                or pc._FORBIDDEN_NUMBER_ON_SCREEN.search(probe)),             f"프롬프트가 든 예시를 게이트가 못 잡는다: {example}"
    assert checked >= 5, f"검사한 예시가 너무 적다({checked}) — 예시가 지워졌나?"


def test_the_gate_catches_the_three_violations_that_slipped_through():
    """★ 재생성 실측(2026-08-31)에서 visual_prompt 로 빠져나간 세 문장.

    게이트는 이미 잡고 있었다(그래서 승인이 막혔다). 프롬프트를 고친 뒤에도
    게이트가 계속 잡는지 — 즉 **금지를 느슨하게 해서 푼 것이 아닌지** 박아 둔다.
    """
    slipped = [
        "A modern university campus building with a subtle logo of a fictional university",
        "Abstract, dynamic text animation of the word 'Astonishing', no on-screen text.",
        "A close-up of a computer screen showing a data visualization of the effect.",
    ]
    for visual in slipped:
        res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"},
                          [_cut(1, visual=visual)], {})
        assert any(r.startswith(("photo_forbidden_screen_request",
                                 "photo_text_request_conflict"))
                   for r in res["block_reasons"]), f"게이트가 놓친다: {visual}"


# ── 컷 수: 프롬프트와 게이트가 같은 식을 말하는가 ────────────
def test_the_prompt_tells_the_model_the_cut_count_rule():
    """★ 실측(2026-08-31): 모델이 61초·11컷을 냈고 게이트 하한은 12였다.

    프롬프트는 "40~50초면 10~14컷"으로 **고정**돼 있었고 게이트는 매번
    `total_estimated_sec` 에서 역산했다 — 모델은 자기가 몇 컷을 내야 하는지
    알 수가 없었다. 영상 상한·에셋 상한에서 이미 두 번 겪은 실패의 세 번째다.
    """
    g = dv._mode_guidance({"selected_mode": "standard"}, "photo", 12)
    assert "[컷 수]" in g
    assert str(dv.config.PHOTO_CUT_SEC_MAX) in g, "역산에 쓰는 숫자를 알려줘야 한다"
    # 게이트가 실제로 쓰는 함수와 같은 범위를 말하는가
    lo, hi = dv.content_mode.duration_range("standard")
    c_lo, _ = pc.target_cut_range(lo)
    _, c_hi = pc.target_cut_range(hi)
    assert f"**{c_lo}~{c_hi}개**" in g


def test_the_stated_rule_matches_what_the_gate_enforces():
    """★ 프롬프트가 말한 식대로 컷을 만들면 실제로 통과해야 한다.

    "말은 이렇게 하고 검사는 저렇게 한다"가 이 저장소의 반복 실패다.
    """
    for total in (40, 55, 61, 80):
        lo, _ = pc.target_cut_range(total)
        # 프롬프트가 알려준 식: 컷 수 >= 전체초수 / PHOTO_CUT_SEC_MAX
        assert lo >= round(total / dv.config.PHOTO_CUT_SEC_MAX) or lo == pc.config.PHOTO_MIN_CUTS
        cuts = [_cut(i + 1) for i in range(lo)]
        for c in cuts:
            c["estimated_sec"] = total / lo
        res = pc.evaluate({"version_type": "photo", "hook_ko": "훅",
                           "total_estimated_sec": total}, cuts, {})
        assert not any(r.startswith("photo_cut_count_low")
                       for r in res["block_reasons"]), (total, res["block_reasons"])


# ── 초안 장면의 시각 제안이 실사형으로 계승되던 경로 (2026-09-02) ──
#
# ★ 실측: 실제 초안(Moon Impactor)으로 재생성했더니 화면 그래픽 위반 3건이 남았는데,
#   세 문장이 전부 draft.video_prompts[] 의 image_prompt/video_prompt 에 **그대로**
#   있었다 — 그중 하나는 8/31 G2·G4 클립 4개를 망친 바로 그 문장이다:
#       "a graphic overlay appears indicating a crater diameter of '~40m'"
#   프롬프트는 금지문과 "흐름·근거를 최대한 계승 … 통째로 버리지 말 것"을 동시에
#   말하고 있었고, 모델은 **계승을 골랐다.** 금지 어휘를 더 쌓아도 못 이긴다 —
#   입력에서 빼는 것이 구조적 답이다.

_SCENE = {
    "scene": 1, "narration_ko": "나레이션 원문", "evidence_role": "primary_result",
    "claim_ids": ["C01"], "duration_sec": 6,
    "image_prompt": "ZZUNIQUE a graphic overlay appears indicating a crater diameter",
    "image_prompt_ko": "WWUNIQUE 한글 시각 제안",
    "video_prompt": "YYUNIQUE a digital timer overlay displays the period",
    "video_prompt_ko": "VVUNIQUE 한글 영상 제안",
}
_DRAFT = {"script_md": "문장 하나입니다. 두 번째 문장입니다.",
          "fact_sheet": {"claims": []}, "video_prompts": [_SCENE], "video_flow": {}}
_MARKERS = ("ZZUNIQUE", "YYUNIQUE", "WWUNIQUE", "VVUNIQUE")


def test_photo_prompt_drops_the_drafts_visual_suggestions():
    """실사형 입력에서 초안의 시각 제안 4필드가 빠진다."""
    p = dv.directive_user_prompt(_DRAFT, "photo")
    for m in _MARKERS:
        assert m not in p, f"초안 시각 제안이 실사형 입력에 남아 있다: {m}"


def test_photo_prompt_keeps_narration_and_evidence():
    """★ 빼는 것은 **시각 제안뿐**이다. 나레이션·근거·역할을 같이 버리면
    "통째로 버리지 말 것"이라는 원래 의도를 깨고 흐름이 끊긴다."""
    p = dv.directive_user_prompt(_DRAFT, "photo")
    assert "나레이션 원문" in p
    assert "primary_result" in p and "C01" in p


def test_other_versions_still_get_the_full_scenes():
    """만화식·나열식은 종전대로다 — 이 사고는 실사형 계약에서만 났다."""
    for version in ("comic", "image_sequence"):
        p = dv.directive_user_prompt(_DRAFT, version)
        for m in _MARKERS:
            assert m in p, f"{version} 에서 초안 장면이 사라졌다: {m}"


def test_the_stripped_fields_are_named_in_one_place():
    """필드 목록이 두 곳에 흩어지면 한쪽만 늘어난다 — 이 저장소의 단골 실패."""
    assert dv._DRAFT_SCENE_VISUAL_FIELDS == frozenset(
        {"image_prompt", "image_prompt_ko", "video_prompt", "video_prompt_ko"})


# ── meter: 계기판인가 길이 단위인가 (2026-09-02 실측) ──
#
# ★ 실측: 실사형 컷 12 의 "a large, circular crater, approximately 40 meters in
#   diameter" 가 `photo_forbidden_screen_request` 로 승인을 막았다. 분화구의 실제
#   크기를 말한 것이고 화면에 계기판을 요구한 적이 없다. 게이트에 `meters?` 가
#   **맨몸으로** 들어 있어서 길이 단위를 계기판으로 읽었다.
# ★★ 이건 "게이트를 느슨하게" 하는 것이 아니다 — 크기·스케일 서술은 실사형이
#   **권장하는** 표현이라(크기 대비·전후 비교), 막으면 옳게 한 컷을 벌한다.
#   원래 잡으려던 계기판은 아래 두 테스트가 같이 박아 둔다.

def test_physical_dimensions_are_not_a_screen_request():
    """길이 단위는 화면 요구가 아니다 — 실사형이 권장하는 크기 서술이다."""
    for s in ("a large, circular crater, approximately 40 meters in diameter",
              "the rocket is 70 meters tall",
              "a 3 meter wide sample beside a human hand for scale",
              "debris scattered over 200 meters"):
        assert not pc._FORBIDDEN_SCREEN.search(s), f"오탐: {s}"
        res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"},
                          [_cut(1, visual=s)], {})
        assert not any(r.startswith("photo_forbidden_screen_request")
                       for r in res["block_reasons"]), (s, res["block_reasons"])


def test_instrument_meters_are_still_caught():
    """계기 의미의 meter 는 그대로 잡는다 — 좁힌 것이지 뺀 것이 아니다."""
    for s in ("a power meter showing the output",
              "a meter reading 42 on the panel",
              "a light meter in the corner",
              "a speed meter displaying the velocity"):
        assert pc._FORBIDDEN_SCREEN.search(s), f"놓친다: {s}"


def test_the_original_timer_case_still_blocks():
    """★ 이 규칙이 생긴 계기(2026-08-30): 타이머가 화면에 숫자를 그렸다.

    meters 를 좁히면서 이게 같이 풀리지 않았는지 확인한다.
    """
    s = "a digital timer overlay next to it displays a consistent rotation period"
    assert pc._FORBIDDEN_SCREEN.search(s)
    res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"},
                      [_cut(1, visual=s)], {})
    assert any(r.startswith(("photo_forbidden_screen_request",
                             "photo_text_request_conflict"))
               for r in res["block_reasons"]), res["block_reasons"]


# ── axis: 도표 축인가 회전축인가 (2026-09-03 실측, meters 와 같은 계열) ──
#
# ★ 실측: 실사형 컷 6 의 "a glowing ring around its axis"(로켓 **회전축**)가 차단됐다.
#   도표 축을 요구한 적이 없고 그 컷은 "No on-screen text" 까지 적어 뒀다.
#   회전축·대칭축·장축은 3D 도해가 당연히 쓰는 말이다.

def test_physical_axes_are_not_a_chart_request():
    for s in ("a glowing ring around its axis",
              "the rocket spins on its axis",
              "rotation axis of the drum",
              "the long axis of the bone",
              "an axial cross-section of the stem",
              "principal axes of the crystal"):
        assert not pc._FORBIDDEN_SCREEN.search(s), f"오탐: {s}"
        res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"},
                          [_cut(1, visual=s)], {})
        assert not any(r.startswith("photo_forbidden_screen_request")
                       for r in res["block_reasons"]), (s, res["block_reasons"])


def test_chart_axes_are_still_caught():
    for s in ("the y-axis shows the count",
              "the horizontal axis is labeled",
              "an axis label reading 42",
              "a plot axis with a scale"):
        assert pc._FORBIDDEN_SCREEN.search(s), f"놓친다: {s}"


def test_a_real_chart_is_still_blocked_by_other_words():
    """★ axis 를 좁혀도 진짜 차트는 chart·graph·gridlines·legend 가 잡는다."""
    for s in ("a bar chart with a labeled x-axis",
              "a graph with gridlines and a legend",
              "a line chart showing the trend"):
        res = pc.evaluate({"version_type": "photo", "hook_ko": "훅"},
                          [_cut(1, visual=s)], {})
        assert any(r.startswith(("photo_forbidden_screen_request",
                                 "photo_text_request_conflict"))
                   for r in res["block_reasons"]), (s, res["block_reasons"])


# ── 컷 수 역산이 등급제와 어긋나 있었다 (2026-09-03 실측) ──
#
# ★ `photo_cut_count_low` 는 전체 길이를 PHOTO_CUT_SEC_MAX(5초)로 나눠 최소 컷 수를
#   구했다. 그런데 시퀀스 등급제는 invest 컷에 **8초**를 준다(TIER_PROFILE).
#   즉 등급제를 제대로 쓴 지시서일수록 컷이 길어지고, 길어진 만큼 차단됐다.
#   실측: 13컷 71초(8초 컷 4개)가 `photo_cut_count_low:13<14` 로 막혔다.
#   저장소 스스로 8초를 허용한다 — PHOTO_CUT_SEC_WARN 이 8 이라 경고조차 안 난다.
#   **한 상수는 8을 허용하고 다른 상수는 5로 나누고 있었다.**
#   "승인 예산이 등급제를 막았다"(2026-08-31)와 같은 계열이다.

def test_tier_granted_long_cuts_are_credited():
    """8초 컷이 있는 지시서가 컷 수 부족으로 막히지 않는다."""
    cuts = [{"estimated_sec": s} for s in (6, 3, 5, 3, 8, 5, 3, 8, 3, 4, 8, 7, 8)]
    total = sum(c["estimated_sec"] for c in cuts)          # 71초 · 13컷
    lo, _ = pc.target_cut_range(pc.effective_runtime(cuts, total))
    assert len(cuts) >= lo, f"13컷 71초가 막힌다: 필요 {lo}"


def test_a_slideshow_is_still_blocked():
    """★ 크레딧을 무제한으로 주면 14초짜리 5컷 슬라이드쇼가 통과한다 — 상한이 있어야 한다."""
    cuts = [{"estimated_sec": 14} for _ in range(5)]        # 70초 · 5컷
    lo, _ = pc.target_cut_range(pc.effective_runtime(cuts, 70))
    assert len(cuts) < lo, "슬라이드쇼가 통과한다"


def test_credit_is_capped_at_the_warn_threshold():
    """크레딧 상한은 새 숫자가 아니라 기존 두 상수의 차(WARN − MAX)다."""
    cap = pc.config.PHOTO_CUT_SEC_WARN - pc.config.PHOTO_CUT_SEC_MAX
    one_long = [{"estimated_sec": 60}]
    assert pc.effective_runtime(one_long, 60) == 60 - cap


def test_normal_short_cuts_are_unchanged():
    """5초 이하 컷만 있으면 종전과 같은 계산이다(회귀 없음)."""
    cuts = [{"estimated_sec": 4} for _ in range(10)]
    assert pc.effective_runtime(cuts, 40) == 40


# ── 연결 문장 처방 (프롬프트) ──
def test_the_prompt_gives_a_recipe_for_connective_sentences():
    """★ 금지만 있고 대안이 없으면 모델은 글자를 굽는다 — 이 저장소가 이미 배운 것.

    실측: '…영향을 미쳤습니다' 3초 컷이 "word 'IMPACT' 텍스트 애니메이션"으로,
    '그냥 점수놀이가 아니었습니다' 가 "score counter dropping to zero" 로 나왔다.
    """
    g = dv.VERSION_GUIDANCE["photo"]
    assert "연결 문장 처방" in g
    assert "앞 컷의 세계를 이어라" in g          # 대안 ①
    assert "실제로 벌어진 자리" in g             # 대안 ②
    assert "영상 클립을 배정하지 마라" in g       # 예산 낭비 방지


def test_the_prompt_bans_icon_infographics_too():
    """★ 실측(2026-09-03): 글자를 막았더니 **아이콘 인포그래픽**으로 도망갔다.

    "personality icons connecting with a dynamic line, leading to a rising 'ad quality'
    gauge, clean digital interface" — 글자만 안 썼을 뿐 같은 회피다.
    실사형은 REALITY 와 MECHANISM 둘뿐이고 인포그래픽은 셋째 선택지가 아니다.
    """
    g = dv.VERSION_GUIDANCE["photo"]
    assert "아이콘 인포그래픽도 같은 금지다" in g
    assert "인포그래픽은 셋째 선택지가" in g
    assert "REALITY 다" in g          # 대안을 준다(금지만 하지 않는다)


def test_the_gate_catches_the_infographic_words_the_prompt_names():
    """프롬프트가 든 금지 어휘를 게이트가 실제로 잡는가(logos·timers 에서 겪은 실패 방지)."""
    for s in ("a rising ad quality gauge",
              "two bar graphs rise below the card",
              "a dashboard-like panel on the right"):
        assert pc._FORBIDDEN_SCREEN.search(s), f"게이트가 놓친다: {s}"
