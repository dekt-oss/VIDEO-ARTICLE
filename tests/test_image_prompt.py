"""이미지 요청 바디·프롬프트 (engine/providers/image.py) — 라이브 키 없이 도는 층.

1차 샘플 실패 둘을 여기서 구조적으로 막는다.
1. 8장 전부 1024×1024 → 종횡비가 프롬프트 텍스트에만 있었다. **파라미터로** 실리는지 단언한다.
2. 컷마다 화풍이 튐 → 부정어가 없었다. webtoon 프롬프트에 6개 부정어가 실리는지 단언한다.

★ Batch 경로도 함께 단언한다. 실시간과 Batch 가 `_image_request_body` 를 공유하므로 지금은
  같이 고쳐지지만, 나중에 누가 한쪽만 손대면 그때 이 테스트가 잡는다.
"""

import pytest

from engine import config
from engine.providers import image as image_provider

CUT = {"cut_no": 3, "visual_prompt": "a red sphere beside a dark fragment"}


def _header(version: str) -> dict:
    return {"version_type": version, "global_style": "korean webtoon illustration"}


# ── 종횡비: 프롬프트가 아니라 파라미터로 ─────────────────────

def _aspect_of(body: dict) -> str | None:
    gc = body.get("generationConfig") or {}
    if "imageConfig" in gc:
        return gc["imageConfig"].get("aspectRatio")
    if "responseFormat" in gc:
        return gc["responseFormat"].get("image", {}).get("aspectRatio")
    return None


def test_realtime_body_carries_aspect_ratio_parameter():
    body = image_provider._image_request_body(CUT, _header("webtoon"))
    assert _aspect_of(body) == config.ASPECT_RATIO == "9:16"


def test_batch_body_carries_the_same_aspect_ratio():
    # Batch 는 별도 함수를 통과한다 — 한쪽만 고쳐지는 상황을 잡는 단언이다.
    reqs = image_provider.build_batch_requests("dir-1", [CUT], _header("webtoon"))
    assert _aspect_of(reqs[0]["request"]) == config.ASPECT_RATIO


def test_aspect_parameter_can_be_switched_off_for_rollback():
    # 라이브에서 400(미지의 필드)이 나면 env 한 줄로 되돌아갈 수 있어야 한다.
    prev = config.IMAGE_ASPECT_RATIO_PARAM
    config.IMAGE_ASPECT_RATIO_PARAM = False
    try:
        body = image_provider._image_request_body(CUT, _header("webtoon"))
        assert _aspect_of(body) is None
        assert body["generationConfig"]["responseModalities"] == ["IMAGE"]
    finally:
        config.IMAGE_ASPECT_RATIO_PARAM = prev


def test_both_documented_field_shapes_are_supported():
    prev = config.IMAGE_ASPECT_CONFIG_SHAPE
    try:
        config.IMAGE_ASPECT_CONFIG_SHAPE = "image_config"
        body = image_provider._image_request_body(CUT, _header("webtoon"))
        assert body["generationConfig"]["imageConfig"]["aspectRatio"] == config.ASPECT_RATIO

        config.IMAGE_ASPECT_CONFIG_SHAPE = "response_format"
        body = image_provider._image_request_body(CUT, _header("webtoon"))
        assert (body["generationConfig"]["responseFormat"]["image"]["aspectRatio"]
                == config.ASPECT_RATIO)
    finally:
        config.IMAGE_ASPECT_CONFIG_SHAPE = prev


# ── 화풍 부정어 ──────────────────────────────────────────────

def test_webtoon_prompt_carries_every_style_negative():
    prompt = image_provider._build_image_prompt(CUT, _header("webtoon"))
    for phrase in ("NOT photorealistic", "no 3D render", "no lens flare",
                   "no depth of field", "no cinematic photography", "no realistic texture"):
        assert phrase in prompt, f"webtoon 프롬프트에 부정어 누락: {phrase}"


def test_webtoon_prompt_drops_the_photoreal_quality_suffix():
    prompt = image_provider._build_image_prompt(CUT, _header("webtoon"))
    assert "high detail" not in prompt      # 실사를 유도한다
    assert "clean flat colors" in prompt


def test_comic_prompt_is_byte_identical_to_the_legacy_string():
    """comic 이 바뀌면 A/B 비교에 화면 설계 말고 다른 변수가 끼어든다. 문자열을 고정한다."""
    expected = (
        "korean webtoon illustration, a red sphere beside a dark fragment, "
        "vertical 9:16 portrait aspect ratio, high detail, "
        + config.BURN_IN_NEGATIVE_PROMPT
    )
    assert image_provider._build_image_prompt(CUT, _header("comic")) == expected
    # 레거시 버전도 같은 형태여야 한다(저장된 옛 지시서 재렌더).
    assert "high detail" in image_provider._build_image_prompt(CUT, _header("image_sequence"))


def test_burn_in_negative_survives_in_every_version():
    for version in ("comic", "webtoon", "image_sequence", "photo", "explainer"):
        prompt = image_provider._build_image_prompt(CUT, _header(version))
        assert config.BURN_IN_NEGATIVE_PROMPT in prompt


# ── 실사형(photo) ────────────────────────────────────────────

def test_photo_prompt_asks_for_a_photograph_not_a_drawing():
    prompt = image_provider._build_image_prompt(CUT, _header("photo"))
    assert "photorealistic cinematic still" in prompt
    for phrase in ("not an illustration", "no cartoon", "no anime", "no webtoon"):
        assert phrase in prompt, f"실사형 프롬프트에 부정어 누락: {phrase}"


def test_photo_prompt_never_carries_the_webtoon_negative():
    """실사형에 'NOT photorealistic' 이 붙으면 정확히 반대로 동작한다.

    예전 코드는 품질 접미사 표에 키가 있는지로 webtoon 부정어를 붙였다 — 실사형이 그 표에
    들어가는 순간 이 사고가 난다. 표를 분리한 이유이자, 분리가 유지되는지 지키는 단언이다.
    """
    prompt = image_provider._build_image_prompt(CUT, _header("photo"))
    assert "NOT photorealistic" not in prompt
    assert "no realistic texture" not in prompt


def test_photo_prompt_drops_the_generic_quality_suffix():
    prompt = image_provider._build_image_prompt(CUT, _header("photo"))
    assert "high detail" not in prompt


# ── 실측 헬퍼 ────────────────────────────────────────────────

@pytest.mark.parametrize("size,expected", [
    ((1024, 1024), False),      # 1차 실패의 실제 크기
    ((1080, 1920), True),       # 렌더 규격
    ((1088, 1920), True),       # 모델이 살짝 어긋나게 준 경우 — 허용
    ((1920, 1080), False),      # 가로 — 명백히 틀림
    ((0, 1920), False),
])
def test_is_portrait_916(size, expected):
    assert image_provider.is_portrait_916(*size) is expected


def test_measure_aspect_returns_none_for_unreadable_file(tmp_path):
    # 실측 실패가 렌더를 세우면 안 된다.
    bogus = tmp_path / "not-an-image.png"
    bogus.write_text("nope")
    assert image_provider.measure_aspect(str(bogus)) is None


# ── 컷 화면 역할: 3D 도해 vs 실사 (2026-08-20) ────────────────

def _role_cut(role: str) -> dict:
    return {"cut_no": 3, "visual_prompt": "a battery cell", "visual_role": role}


def test_mechanism_cut_asks_for_a_cutaway_render_not_a_photo():
    """운영자 지적의 핵심 — 화면이 설명을 해야 한다.

    벤치마크 채널의 화면은 실사가 아니라 3D 렌더다. 그래서 지반 단면·조립 순서를 보여줄 수
    있다(사진으로는 못 찍는다). 도해 컷은 사진 쪽으로 밀리면 안 된다.
    """
    prompt = image_provider._build_image_prompt(_role_cut("MECHANISM"), _header("photo"))
    assert "cutaway" in prompt
    assert "not a photograph" in prompt
    assert "photorealistic cinematic still" not in prompt


def test_reality_cut_is_a_stylized_render_not_a_photograph():
    """★ 계약이 **뒤집혔다**(2026-09-07 운영자 지시).

    옛 이름은 `test_reality_cut_still_asks_for_a_photograph` 였고 REALITY 가 사진을
    요구하는지 봤다. 그런데 운영자 판정이 이것이다 —
    "실사가 너무 실사 같아서 못 보겠다. 특히 쥐. 벤치마킹하던 건축 도해처럼 반실사 CG 로 가자."
    실측에서 진짜 쥐 사진이 나왔고 그게 못 보겠다고 한 그 화면이다.

    그래서 REALITY 도 이제 **무광 CG** 다. 사진을 요구하지 않는다.
    """
    prompt = image_provider._build_image_prompt(_role_cut("REALITY"), _header("photo"))
    assert "stylized 3D render" in prompt
    assert "photorealistic cinematic still" not in prompt
    assert "not a photograph" in prompt


def test_the_two_roles_share_materials_and_differ_only_in_viewpoint():
    """★★ 이것이 이번 변경의 **목적**이다(핸드오프 §1-②).

    "컷7(실사 쥐) → 컷8(3D 세포)에서 화면이 튄다"가 출발점이었다. 두 역할이 재질·조명을
    공유해야 한 영상 안에서 같은 작품으로 보인다. 다른 것은 시점(단면)뿐이어야 한다.
    """
    mech = image_provider._build_image_prompt(_role_cut("MECHANISM"), _header("photo"))
    real = image_provider._build_image_prompt(_role_cut("REALITY"), _header("photo"))
    for shared in ("stylized 3D render", "matte surfaces with minimal micro-texture",
                   "simplified geometric forms"):
        assert shared in mech and shared in real, shared
    assert "isometric cutaway" in mech and "isometric cutaway" not in real


def test_role_beats_the_version_suffix():
    """같은 실사형 안에서도 컷마다 화풍이 갈려야 한다 — 버전 접미사가 이기면 안 된다."""
    mech = image_provider._build_image_prompt(_role_cut("MECHANISM"), _header("photo"))
    real = image_provider._build_image_prompt(_role_cut("REALITY"), _header("photo"))
    assert mech != real


def test_cut_without_a_role_keeps_the_old_path():
    """역할을 선언하지 않는 버전(만화식·웹툰·설명판형·레거시)은 화면이 그대로여야 한다."""
    plain = image_provider._build_image_prompt(CUT, _header("comic"))
    expected = (
        "korean webtoon illustration, a red sphere beside a dark fragment, "
        "vertical 9:16 portrait aspect ratio, high detail, "
        + config.BURN_IN_NEGATIVE_PROMPT
    )
    assert plain == expected


# ─────────────────────────────────────────────────────────────
# 역할별 이미지 모델 (2026-08-28) — "3D 영상 퀄리티를 올려달라"
# ─────────────────────────────────────────────────────────────

def test_3D_도해_컷만_프리미엄_모델을_쓴다():
    """돈은 설명력이 갈리는 곳에만 쓴다. 실사·기타 컷은 기존 모델 그대로."""
    assert config.image_model_for("MECHANISM") == "gemini-3-pro-image"
    assert config.image_model_for("REALITY") == config.IMAGE_MODEL
    assert config.image_model_for("") == config.IMAGE_MODEL
    assert config.image_model_for(None) == config.IMAGE_MODEL


def test_역할별_단가가_단가표에서_나온다():
    """원장 비용이 실제 모델 단가와 어긋나면 예산 가드가 헛돈다."""
    assert config.image_cost_for("MECHANISM") == config.PRICING["gemini-3-pro-image"]["image_standard"]
    assert config.image_cost_for("REALITY") == config.PRICING[config.IMAGE_MODEL]["image_standard"]
    # 도해가 더 비싸다 — 그래서 캡에 여유가 필요하다
    assert config.image_cost_for("MECHANISM") > config.image_cost_for("REALITY")


def test_실사형_캡이_예상비용보다_크다():
    """캡은 하드 스톱이다. 빠듯하면 렌더 도중에 죽고 쓴 돈은 못 돌려받는다."""
    video = config.VIDEO_SEC_MAX_BY_VERSION["photo"] * config.VEO_COST_PER_SEC_USD
    stills = 4 * config.image_cost_for("MECHANISM") + 2 * config.image_cost_for("REALITY")
    assert config.render_budget_cap("photo") > video + stills, \
        f"실사형 캡 ${config.render_budget_cap('photo')} < 예상 ${video + stills:.2f}"


def test_기본_캡은_photo_캡과_다르다():
    """render.py 가 전역 캡을 직접 읽던 버그의 회귀 가드."""
    assert config.render_budget_cap("photo") == config.PHOTO_COST_CAP_USD
    assert config.render_budget_cap("comic") == config.RENDER_BUDGET_CAP_USD
    assert config.render_budget_cap("photo") != config.render_budget_cap("comic")


# ─────────────────────────────────────────────────────────────
# 2026-08-29 실측: 프리미엄 모델이 503 이면 도해가 회색 placeholder 로 나갔다
# ─────────────────────────────────────────────────────────────
def test_role_model_failure_falls_back_to_the_base_model(monkeypatch, tmp_path):
    """유료 렌더에서 '덜 좋은 그림'과 '그림 없음'은 비교 대상이 아니다.

    실측: gemini-3-pro-image 가 503("high demand")로 8회 전부 실패하는 동안 flash 는 정상이었다.
    그런데 재시도만 하고 placeholder 로 떨어져, 3D 도해 컷이 회색 상자로 나갔다.
    """
    from engine import config, render

    monkeypatch.setattr(config, "IMAGE_PROVIDER", "gemini")
    monkeypatch.setattr(config, "IMAGE_MODEL_FALLBACK", True)
    tried: list[str] = []

    def fake_generate(cut, header, out_path, model="", ref_path=None):
        eff = model or config.image_model_for(cut.get("visual_role"))
        tried.append(eff)
        if eff == config.IMAGE_MODEL_BY_ROLE["MECHANISM"]:
            raise RuntimeError("503 from gemini image")
        open(out_path, "wb").write(b"png")
        return out_path, 0.039

    monkeypatch.setattr(render.image_provider, "generate_image", fake_generate)
    monkeypatch.setattr(render.cost_ledger, "record", lambda row: None)
    render._gen_still({"cut_no": 1, "visual_role": "MECHANISM", "visual_prompt": "p"},
                      {"version_type": "photo"}, str(tmp_path / "a.png"), directive_id=None)
    assert config.IMAGE_MODEL in tried, "기본 모델로 폴백해 실제 이미지를 만들어야 한다"
    assert tried.count(config.IMAGE_MODEL_BY_ROLE["MECHANISM"]) >= 1


def test_fallback_image_is_cached_under_the_fallback_key(monkeypatch, tmp_path):
    """폴백 그림을 프리미엄 키에 저장하면, 프리미엄이 살아난 뒤에도 flash 그림이 재사용되어
    상향이 **영구히** 묻힌다. 실제로 쓴 모델의 키에 저장해야 다음 렌더가 다시 시도한다."""
    from engine import assemble, config, generation_spec

    cut = {"cut_no": 1, "visual_role": "MECHANISM", "visual_prompt": "p"}
    header = {"version_type": "photo"}
    premium_key = assemble.content_hash(cut, header)
    fallback_key = assemble.content_hash({**cut, "visual_role": ""}, header)
    assert premium_key != fallback_key
    assert generation_spec.image_spec({**cut, "visual_role": ""}).model == config.IMAGE_MODEL
