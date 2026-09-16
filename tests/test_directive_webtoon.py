"""웹툰 버전 — 크롭·톤 정규화와 비용 계상 (docs/수정명세서_웹툰버전_v1.md §2).

여기서 지키려는 불변식 셋:
1. 모델이 상한 밖 값을 줘도 **조용히 삼키지 않는다** — 깎되 경고를 남긴다.
2. 크롭은 **재사용 컷에만** 붙는다. 새로 생성한 이미지를 잘라내는 일이 없어야 한다.
3. 파생 컷은 비용 계상에서 빠진다 — 확인 모달이 보여줄 금액이 여기서 정해진다.
"""

from engine import config, directive as dv


def _cut(no: int, **kw):
    base = {
        "cut_no": no,
        "narration_ko": f"컷 {no}",
        "narration_en": f"cut {no}",
        "estimated_sec": 6,
        "visual_prompt": "korean webtoon illustration, a red sphere",
        "asset_strategy": "new_asset",
    }
    base.update(kw)
    return base


def _normalize(cuts, version="webtoon"):
    return dv.normalize_directive({"header": {}, "cuts": cuts}, version)


# ── normalize_crop 단위 ──────────────────────────────────────

def test_crop_out_of_range_is_clamped_and_reported():
    got, clamped = dv.normalize_crop({"cx": 1.7, "cy": -3, "scale": 9})
    assert clamped is True
    assert got == {"cx": 1.0, "cy": 0.0, "scale": config.CROP_MAX_SCALE}


def test_crop_within_range_is_not_flagged():
    got, clamped = dv.normalize_crop({"cx": 0.5, "cy": 0.42, "scale": 2.2})
    assert clamped is False
    assert got == {"cx": 0.5, "cy": 0.42, "scale": 2.2}


def test_crop_scale_one_is_dropped_as_no_work():
    # 배율 1 = 잘라낼 것 없음. 의미 없는 필드를 지시서에 남기지 않는다.
    assert dv.normalize_crop({"cx": 0.5, "cy": 0.5, "scale": 1.0}) == (None, False)
    assert dv.normalize_crop("2.2배") == (None, False)
    assert dv.normalize_crop(None) == (None, False)


def test_crop_garbage_values_fall_back_to_defaults():
    got, _ = dv.normalize_crop({"cx": "왼쪽", "cy": None, "scale": 2.0})
    assert got == {"cx": config.CROP_DEFAULT_CENTER, "cy": config.CROP_DEFAULT_CENTER,
                   "scale": 2.0}


def test_tone_grade_outside_enum_is_none():
    assert dv.sanitize_tone_grade("magenta") == config.DEFAULT_TONE_GRADE
    assert dv.sanitize_tone_grade("") == config.DEFAULT_TONE_GRADE
    assert dv.sanitize_tone_grade("WARM") == "warm"


# ── normalize_directive 관통 ─────────────────────────────────

def test_clamped_crop_surfaces_in_mode_warnings():
    out = _normalize([
        _cut(1),
        _cut(2, asset_strategy="reuse_zoom", base_asset_ref="1",
             crop={"cx": 0.5, "cy": 0.5, "scale": 9.0}),
    ])
    assert "crop_clamped#2" in out["header"]["mode_warnings"]
    assert out["cuts"][1]["crop"]["scale"] == config.CROP_MAX_SCALE


def test_crop_on_new_asset_cut_is_dropped():
    # 새로 생성하는 컷에 크롭이 붙으면 갓 만든 이미지를 잘라내는 셈이라 의도와 어긋난다.
    out = _normalize([_cut(1, crop={"cx": 0.3, "cy": 0.3, "scale": 2.0}, tone_grade="red")])
    assert out["cuts"][0]["crop"] is None
    assert out["cuts"][0]["tone_grade"] == config.DEFAULT_TONE_GRADE


def test_broken_reuse_ref_clears_crop_and_tone():
    """참조가 앞을 가리키면 new_asset 으로 강등되는데, 이때 크롭이 남으면 **새 이미지가 잘린다.**

    강등 자체는 예전부터 있었다. 크롭까지 지우는 것이 이번에 더한 방어다.
    """
    out = _normalize([
        _cut(1, asset_strategy="reuse_crop", base_asset_ref="5",   # 뒤 컷 참조 — 무효
             crop={"cx": 0.2, "cy": 0.2, "scale": 2.0}, tone_grade="red"),
        _cut(5),
    ])
    demoted = out["cuts"][0]
    assert demoted["asset_strategy"] == config.DEFAULT_ASSET_STRATEGY
    assert demoted["crop"] is None
    assert demoted["tone_grade"] == config.DEFAULT_TONE_GRADE
    assert "invalid_reuse_ref#1" in out["header"]["mode_warnings"]


def test_valid_backward_reuse_keeps_crop():
    out = _normalize([
        _cut(1),
        _cut(2, asset_strategy="reuse_zoom", base_asset_ref="1",
             crop={"cx": 0.5, "cy": 0.42, "scale": 2.2}, tone_grade="warm"),
    ])
    assert out["cuts"][1]["asset_strategy"] == "reuse_zoom"
    assert out["cuts"][1]["crop"] == {"cx": 0.5, "cy": 0.42, "scale": 2.2}
    assert out["cuts"][1]["tone_grade"] == "warm"


def test_comic_directive_shape_is_unchanged_by_the_new_fields():
    """기존 comic 지시서가 새 필드 때문에 달라지지 않아야 한다(A/B 비교의 단일 변수 원칙)."""
    out = _normalize([_cut(1), _cut(2)], version="comic")
    for cut in out["cuts"]:
        assert cut["crop"] is None
        assert cut["tone_grade"] == config.DEFAULT_TONE_GRADE


# ── 비용 계상 — 확인 모달이 보여줄 바로 그 숫자 ───────────────

def test_derived_cuts_do_not_count_as_paid_assets():
    """장면 4장 + 파생 4컷 → 유료 에셋은 4개다. 8개가 나오면 모달 금액이 두 배로 틀린다."""
    cuts = [_cut(i) for i in (1, 2, 3, 4)] + [
        _cut(5, asset_strategy="reuse_zoom", base_asset_ref="1",
             crop={"cx": 0.5, "cy": 0.4, "scale": 2.2}),
        _cut(6, asset_strategy="reuse_crop", base_asset_ref="2",
             crop={"cx": 0.3, "cy": 0.6, "scale": 1.8}),
        _cut(7, asset_strategy="reuse_zoom", base_asset_ref="3",
             crop={"cx": 0.5, "cy": 0.5, "scale": 1.5}),
        _cut(8, asset_strategy="reuse_with_state_change", base_asset_ref="1",
             tone_grade="red"),
    ]
    plan = dv.compute_cost_plan(_normalize(cuts)["cuts"], "standard")
    assert plan["unique_asset_count"] == 4
    assert plan["reuse_count"] == 4
    assert plan["asset_reuse_ratio"] == 0.5
    # 이미지 비용은 고유 에셋 4개분만 — 파생 4컷은 생성 호출이 없다.
    only_four = dv.compute_cost_plan([_cut(i) for i in (1, 2, 3, 4)], "standard")
    assert plan["estimated_image_cost_usd"] == only_four["estimated_image_cost_usd"]
