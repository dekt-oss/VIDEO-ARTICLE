"""engine.directive 순수 로직 테스트 (네트워크/LLM 없음).

normalize_directive 의 신뢰민감 규칙을 검증한다:
- visual_type 은 버전에서 강제
- effects/transition 은 허용 토큰만(밖은 드롭/기본값)
- duration 클램프 [CUT_MIN, CUT_MAX], total 재계산
- source_facts 보존 + 근거 없는 컷 탐지
- 악성/누락 입력에도 안전한 shape
"""

from engine import config
from engine.directive import (
    enforce_scene_variety,
    normalize_directive,
    preflight_video_budget,
    sanitize_effects,
    sanitize_media_policy,
    sanitize_scene_kind,
    sanitize_transition,
    scene_variety_report,
    ungrounded_cuts,
)


def _cut(**kw):
    base = {
        "cut_no": 1,
        "narration_ko": "안녕",
        "narration_en": "hi",
        "estimated_sec": 5,
        "visual_prompt": "a cat",
        "effects": [],
        "transition": "cut",
        "source_facts": ["what_found[0]"],
    }
    base.update(kw)
    return base


def test_visual_type_forced_by_version():
    # ★ 발주 가능한 버전만 본다. VERSION_VISUAL_TYPE 에는 폐기 버전(webtoon·explainer)이
    #   옛 행 렌더용으로 남아 있고, 그것들은 normalize 가 DEFAULT_VERSION 으로 떨어뜨린다.
    for version in config.VIDEO_VERSIONS:
        vt = config.VERSION_VISUAL_TYPE[version]
        out = normalize_directive({"cuts": [_cut(visual_type="WRONG")]}, version)
        assert out["cuts"][0]["visual_type"] == vt
        assert out["version_type"] == version


def test_unknown_version_falls_back_to_default():
    out = normalize_directive({"cuts": [_cut()]}, "nonsense")
    assert out["version_type"] == config.DEFAULT_VERSION


def test_effects_enum_enforced():
    effects = ["ken_burns_zoom_in", "explode_everything", "text_overlay:72의 법칙", "particle:soft"]
    kept = sanitize_effects(effects)
    assert "ken_burns_zoom_in" in kept
    assert "text_overlay:72의 법칙" in kept  # 허용 접두사
    assert "particle:soft" in kept
    assert "explode_everything" not in kept  # 미허용 드롭


def test_effects_accepts_string_and_garbage():
    assert sanitize_effects("highlight") == ["highlight"]
    assert sanitize_effects(None) == []
    assert sanitize_effects(123) == []


def test_transition_defaults_when_invalid():
    assert sanitize_transition("crossfade") == "crossfade"
    assert sanitize_transition("wormhole") == config.DEFAULT_TRANSITION
    assert sanitize_transition("") == config.DEFAULT_TRANSITION


def test_duration_clamped():
    # 근거밀도 개정(§10-2): 상한이 컷 종류별로 갈린다. 한 메시지가 유지되면 8초를 넘겨도 쪼개지 않는다.
    out = normalize_directive(
        {"cuts": [_cut(estimated_sec=999), _cut(cut_no=2, estimated_sec=0)]},
        "image_sequence",
    )
    assert out["cuts"][0]["estimated_sec"] == config.PAPER_CUT_MAX_SEC == 10
    assert out["cuts"][1]["estimated_sec"] == config.CUT_MIN_SEC


def test_duration_cap_varies_by_cut_kind():
    out = normalize_directive({"cuts": [
        _cut(cut_no=1, estimated_sec=999, scene_kind="data_viz"),
        _cut(cut_no=2, estimated_sec=999, scene_kind="broll_stock"),
        _cut(cut_no=3, estimated_sec=999, motion_source="video", motion_value="high"),
    ]}, "image_sequence")
    secs = [c["estimated_sec"] for c in out["cuts"]]
    # data_viz 는 시각화를 충분히 쓰라고 12초, 기본 10초, 영상 컷은 clip_fit 보호로 8초.
    assert secs == [config.DATA_VIZ_CUT_MAX_SEC, config.PAPER_CUT_MAX_SEC, config.VIDEO_CUT_MAX_SEC]
    assert secs == [12, 10, 8]


def test_finance_line_keeps_flat_eight_second_cap():
    # engine/report_directive.py 가 이 인자로 자기 3~8초 계약을 지킨다 — 논문 완화가 새면 안 된다.
    out = normalize_directive(
        {"cuts": [_cut(estimated_sec=999, scene_kind="data_viz")]},
        "image_sequence", cut_max_sec=config.CUT_MAX_SEC,
    )
    assert out["cuts"][0]["estimated_sec"] == config.CUT_MAX_SEC == 8


def test_total_estimated_sec_recomputed():
    out = normalize_directive(
        {"header": {"total_estimated_sec": 9999},
         "cuts": [_cut(estimated_sec=4), _cut(cut_no=2, estimated_sec=6)]},
        "image_sequence",
    )
    assert out["header"]["total_estimated_sec"] == 10  # 모델 자기보고 무시, 합으로 재계산


def test_source_facts_and_ungrounded_detection():
    out = normalize_directive(
        {"cuts": [_cut(cut_no=1, source_facts=["numbers[0]"]),
                  _cut(cut_no=2, source_facts=[]),
                  _cut(cut_no=3, source_facts="what_found[1]")]},  # str 도 리스트로
        "comic",
    )
    assert out["cuts"][2]["source_facts"] == ["what_found[1]"]
    assert ungrounded_cuts(out) == [2]


def test_malformed_input_is_safe():
    out = normalize_directive({"cuts": ["not a dict", None, 42, _cut()]}, "image_sequence")
    assert len(out["cuts"]) == 1  # 비 dict 컷은 버림
    assert out["header"]["aspect_ratio"] == config.ASPECT_RATIO


def test_empty_object_yields_valid_shape():
    out = normalize_directive({}, "image_sequence")
    assert out["cuts"] == []
    assert out["header"]["total_estimated_sec"] == 0
    assert out["header"]["bgm"] == {"mood": "", "track_ref": ""}


def test_header_bgm_and_global_style_preserved():
    out = normalize_directive(
        {"header": {"global_style": "flat webtoon", "bgm": {"mood": "경쾌", "track_ref": "x"}},
         "cuts": [_cut()]},
        "comic",
    )
    assert out["header"]["global_style"] == "flat webtoon"
    assert out["header"]["bgm"] == {"mood": "경쾌", "track_ref": "x"}


# ── ③ scene_kind + 다양성 (DV9) ────────────────────────────────
def test_scene_kind_enum_enforced_with_version_fallback():
    assert sanitize_scene_kind("kinetic_typography", "comic") == "kinetic_typography"
    # 밖의 값 → 버전 기본값.
    assert sanitize_scene_kind("explosions", "image_sequence") == \
        config.VERSION_DEFAULT_SCENE_KIND["image_sequence"]
    assert sanitize_scene_kind("", "image_sequence") == \
        config.VERSION_DEFAULT_SCENE_KIND["image_sequence"]


def test_normalize_defaults_scene_kind_by_version():
    out = normalize_directive({"cuts": [_cut()]}, "comic")
    assert out["cuts"][0]["scene_kind"] == config.VERSION_DEFAULT_SCENE_KIND["comic"]


def test_enforce_scene_variety_breaks_3_consecutive():
    cuts = [{"scene_kind": "broll_stock"} for _ in range(4)]
    enforce_scene_variety(cuts, "image_sequence")
    kinds = [c["scene_kind"] for c in cuts]
    # 3연속 이상 없음.
    assert scene_variety_report(cuts)["max_consecutive"] <= config.SCENE_MAX_CONSECUTIVE_SAME
    assert kinds[2] != "broll_stock"  # 3번째는 교체됨


def test_normalize_applies_variety_end_to_end():
    cuts_in = [_cut(cut_no=i + 1, scene_kind="comic_panel") for i in range(5)]
    out = normalize_directive({"cuts": cuts_in}, "comic")
    assert scene_variety_report(out["cuts"])["max_consecutive"] <= config.SCENE_MAX_CONSECUTIVE_SAME


# ── 작업 B: 영상 정책 + 이중 캡 (명세 §8) ──────────────────────
def test_sanitize_media_policy_enum_and_default():
    for p in config.MEDIA_POLICIES:
        assert sanitize_media_policy(p) == p
    assert sanitize_media_policy("bogus") == config.DEFAULT_MEDIA_POLICY
    assert sanitize_media_policy(None) == config.DEFAULT_MEDIA_POLICY


def test_normalize_directive_defaults_media_policy():
    out = normalize_directive({"cuts": [_cut()]}, "image_sequence")
    assert out["header"]["media_policy"] == config.DEFAULT_MEDIA_POLICY


def _video_cuts(n):
    return [_cut(cut_no=i + 1, motion_source="video") for i in range(n)]


def test_image_only_strips_all_video_cuts():
    cuts = _video_cuts(3)
    preflight_video_budget(cuts, "image_only")
    assert all(c["motion_source"] == "still" for c in cuts)


def test_dual_cap_demotes_cuts_beyond_budget():
    # VEO_CLIP_SEC=4·VEO_COST_PER_SEC_USD=$0.05 기본이면 클립당 4초/$0.20.
    # 캡(8초/$0.40)엔 정확히 2개까지만 들어간다 → 나머지는 스틸 강등(등장 순서 낮은 우선순위부터).
    clip_sec = config.VEO_CLIP_SEC
    per_clip_cost = clip_sec * config.VEO_COST_PER_SEC_USD
    max_fit = min(
        config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC // clip_sec,
        int(config.VIDEO_MAX_COST_USD_PER_TOPIC // per_clip_cost) if per_clip_cost else 0,
    )
    cuts = _video_cuts(max_fit + 2)  # 캡을 확실히 넘도록 2개 초과
    preflight_video_budget(cuts, "image_preferred")
    kept = [c for c in cuts if c["motion_source"] == "video"]
    demoted = [c for c in cuts if c["motion_source"] == "still"]
    assert len(kept) == max_fit
    assert len(demoted) == 2
    # 앞쪽(등장 순서 = 우선순위 높음)이 유지되고 뒤쪽이 강등된다.
    assert [c["cut_no"] for c in kept] == list(range(1, max_fit + 1))


def test_dual_cap_never_exceeded_within_budget():
    cuts = _video_cuts(1)  # 캡보다 훨씬 작은 요청은 그대로 유지.
    preflight_video_budget(cuts, "image_preferred")
    assert cuts[0]["motion_source"] == "video"


def test_video_required_keeps_at_least_one_over_cap():
    # 캡이 극단적으로 작아도(0초/0달러) video_required 는 최우선 1개는 유지한다(사람 결정 대체).
    import engine.directive as directive_mod
    old_sec, old_cost = config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC, config.VIDEO_MAX_COST_USD_PER_TOPIC
    config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC = 0
    config.VIDEO_MAX_COST_USD_PER_TOPIC = 0.0
    try:
        cuts = _video_cuts(3)
        directive_mod.preflight_video_budget(cuts, "video_required")
        kept = [c for c in cuts if c["motion_source"] == "video"]
        assert len(kept) == 1 and kept[0]["cut_no"] == 1  # 최우선(1번) 하나만 강제 유지
    finally:
        config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC = old_sec
        config.VIDEO_MAX_COST_USD_PER_TOPIC = old_cost


def test_preflight_applied_end_to_end_in_normalize():
    # 편당 VEO_MAX_CLIPS_PER_DRAFT(개수 캡)를 다 채워도 이중 캡(초/금액)이 더 강하게 조인다.
    cuts_in = [_cut(cut_no=i + 1, motion_source="video") for i in range(config.VEO_MAX_CLIPS_PER_DRAFT)]
    out = normalize_directive({"cuts": cuts_in}, "image_sequence")
    videos = [c for c in out["cuts"] if c["motion_source"] == "video"]
    clip_sec = config.VEO_CLIP_SEC
    per_clip_cost = clip_sec * config.VEO_COST_PER_SEC_USD
    max_fit = min(config.VIDEO_MAX_GENERATED_SEC_PER_TOPIC // clip_sec,
                  int(config.VIDEO_MAX_COST_USD_PER_TOPIC // per_clip_cost))
    assert len(videos) <= max_fit


def test_hook_cta_transcreation_fields_preserved():
    out = normalize_directive(
        {"header": {"hook_ko": "이거 실화?", "hook_en": "No way this is real",
                    "cta_ko": "저장각", "cta_en": "Save this"},
         "cuts": [_cut()]},
        "image_sequence",
    )
    h = out["header"]
    assert h["hook_ko"] == "이거 실화?" and h["hook_en"] == "No way this is real"
    assert h["cta_ko"] == "저장각" and h["cta_en"] == "Save this"


# ── 상단 훅 ↔ 1컷 나레이션 중복 제거 (화면에 같은 문장이 두 번 뜨는 문제) ──

def _norm(header, cuts):
    from engine.directive import _drop_hook_duplicating_first_cut
    _drop_hook_duplicating_first_cut(header, cuts)
    return header


def test_hook_identical_to_first_cut_is_blanked():
    h = _norm({"hook_ko": "미국이 중국산 로봇 수입을 막는다고요?"},
              [{"narration_ko": "미국이 중국산 로봇 수입을 막는다고요?"}])
    assert h["hook_ko"] == ""


def test_hook_differing_only_in_punctuation_is_blanked():
    """문장부호·공백만 다른 건 화면에서 같은 문장으로 읽힌다."""
    h = _norm({"hook_ko": "하루 만에 유가가 7% 넘게 빠졌다고요"},
              [{"narration_ko": "하루 만에 유가가 7% 넘게 빠졌다고요?"}])
    assert h["hook_ko"] == ""


def test_distinct_hook_is_kept():
    hook = "AI가 진짜 무서운 이유, 터미네이터가 아닙니다."
    h = _norm({"hook_ko": hook},
              [{"narration_ko": "AI가 인류를 지배하는 건, 터미네이터처럼 오지 않습니다."}])
    assert h["hook_ko"] == hook


def test_en_hook_compared_against_en_narration_not_ko():
    """언어를 섞어 비교하면 EN 중복이 절대 안 걸린다 — 같은 언어끼리 본다."""
    h = _norm({"hook_ko": "다른 한국어 훅", "hook_en": "Is the US banning Chinese robots?"},
              [{"narration_ko": "미국이 중국산 로봇 수입을 막는다고요?",
                "narration_en": "Is the US banning Chinese robots?"}])
    assert h["hook_ko"] == "다른 한국어 훅"
    assert h["hook_en"] == ""


def test_empty_cuts_or_narration_is_safe():
    assert _norm({"hook_ko": "훅"}, [])["hook_ko"] == "훅"
    assert _norm({"hook_ko": "훅"}, [{"narration_ko": ""}])["hook_ko"] == "훅"
