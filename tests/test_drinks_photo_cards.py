"""주류 카드뉴스 사진형(card-photo-v1) — 배치·강조·경고·출처 장·유료 4:5 그림·캡션. 네트워크·유료 호출·ffmpeg 없음."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from engine import config
from engine import drinks_caption as cap
from engine import drinks_cards as dc
from engine import drinks_cards_photo as ph
from engine import drinks_paid as dpaid
from engine import drinks_produce as dp
from engine import drinks_script_check as sc

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "docs" / "drinks-pilot" / "gi-sake-v1.json").read_text(encoding="utf-8"))
PUBLISH_SQL = (ROOT / "supabase" / "migrations" / "0055_drinks_publish_loop.sql").read_text(encoding="utf-8")

PAGES = [
    {"position": 1, "role": "cover", "kicker": "술째리고 · 위스키 상식", "category": "물 한 방울의 과학",
     "heading": "위스키에 물 몇 방울,\n왜 [맛이 더 좋아질까]?", "body": "2017년 과학 논문이 밝힌 이유", "photo_shift": -110,
     "image_prompt": "A droplet of water falling into a nosing glass"},
    {"position": 2, "role": "explain", "heading": "위스키 고수들은\n마시기 전에\n[물 한두 방울]을 떨어뜨려요",
     "body": "맛을 더 끌어올리려는 습관이에요.\n그런데 왜 그런지는 잘 밝혀지지 않았어요.", "image_prompt": "A hand holding a dropper"},
    {"position": 3, "role": "explain", "heading": "스모키한 향의 정체는\n[과이아콜]이라는\n작은 분자예요",
     "body": "위스키의 스모키한 풍미는 페놀류,\n그중에서도 과이아콜에서 나와요.", "image_prompt": "Peat smoke drifting in a malt kiln"},
    {"position": 4, "role": "source", "body": "Karlsson, B. & Friedman, R. (2017).\nScientific Reports 7, 6489."},
]
PLAN = {"layout": "photo", "pages": PAGES,
        "caption": {"title": "위스키에 물 몇 방울, 왜 맛이 더 좋아질까?", "emoji": "💧",
                    "intro": "위스키 고수들이 잔에 물 한두 방울 떨어뜨리는 이유, 2017년 연구가 분자 수준에서 설명했어요.",
                    "points": ["스모키한 향 분자(과이아콜)는 알코올이 진하면 술 속에 숨어요",
                               "물이 들어가면 이 분자가 표면으로 올라와요",
                               "술은 표면부터 입에 닿아서 향과 맛이 더 잘 느껴져요", "네 번째는 잘려야 해요"],
                    "limit": "사람이 맛본 실험이 아닌 컴퓨터 시뮬레이션 연구예요.", "share_target": "위스키",
                    "hashtags": ["위스키", "#위스키상식", "싱글몰트", "술상식", "물", "술째리고"]}}
JOB = {"topic": {"title": "t"}, "claims": [], "sources": [], "plan": PLAN}


def _photo(path, size=(896, 1152), color=(120, 80, 40)):
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse([size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4], fill=(200, 150, 80))
    im.save(path)
    return str(path)


def _images(tmp_path, positions=(1, 2, 3)):
    return {p: _photo(tmp_path / f"src{p}.png") for p in positions}


def _texts(monkeypatch):
    """그린 글자 덩어리를 가로챈다(화면 글자 확인용)."""
    seen: list[str] = []
    orig = ph.make_block

    def spy(d, text, *a, **k):
        seen.append(text)
        return orig(d, text, *a, **k)
    monkeypatch.setattr(ph, "make_block", spy)
    return seen


def test_photo_layout_renders_pages_in_order_at_card_size(tmp_path):
    r = dc.render_carousel(JOB, str(tmp_path / "p"), images=_images(tmp_path))
    assert [f["position"] for f in r.files] == [1, 2, 3, 4]
    assert all(Image.open(f["path"]).size == (1080, 1350) for f in r.files)
    assert r.qa["template_version"] == "card-photo-v1"
    assert r.qa["warnings"] == [] and r.qa["missing_glyphs"] == []
    assert r.qa["ai_images"] is True and r.qa["generated_pages"] == [1, 2, 3]


def test_template_version_alone_selects_photo_layout_and_default_is_card_v1(tmp_path):
    by_version = {**JOB, "plan": {"template_version": "card-photo-v1", "pages": PAGES}}
    assert dc.render_carousel(by_version, str(tmp_path / "a")).qa["template_version"] == "card-photo-v1"
    plain = {**JOB, "plan": {"pages": [{"position": 1, "role": "cover", "heading": "표지"}]}}
    assert dc.render_carousel(plain, str(tmp_path / "b")).qa["template_version"] == "card-v1"


def test_card_v1_output_is_unchanged_even_when_images_are_passed(tmp_path):
    plain = {**JOB, "plan": {"pages": [{"position": 1, "role": "cover", "heading": "다이긴조"},
                                       {"position": 2, "role": "explain", "heading": "정미율", "body": "쌀을 깎은 비율"}]}}
    a = dc.render_carousel(plain, str(tmp_path / "a"))
    b = dc.render_carousel(plain, str(tmp_path / "b"), images=_images(tmp_path, (1, 2)))
    sha = lambda r: [hashlib.sha256(Path(f["path"]).read_bytes()).hexdigest() for f in r.files]  # noqa: E731
    assert sha(a) == sha(b), "글자 카드(card-v1)는 사진 인자와 무관 — 바이트까지 같다"
    assert "photo_missing" not in b.qa["warnings"] and "ai_images" not in b.qa


def test_missing_photo_is_a_warning_not_an_error(tmp_path):
    r = dc.render_carousel(JOB, str(tmp_path / "p"), images={1: _photo(tmp_path / "only1.png"), 2: str(tmp_path / "nope.png")})
    assert "photo_missing" in r.qa["warnings"]
    assert r.qa["photo_missing_pages"] == [2, 3], "없는 파일·안 넘긴 쪽 모두. 출처 장(4)은 사진이 필요 없다"
    assert all(Image.open(f["path"]).size == (1080, 1350) for f in r.files)
    assert r.qa["generated_pages"] == [1]


def test_bracket_highlight_survives_wrapping_without_breaking_words():
    im = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(im)
    f = ph.font_for("가", "head", 70)
    text = "왜 [맛이 더 좋아질까 정말로 궁금해요]?"
    lines = ph.layout_lines(d, text, f, 520)
    assert len(lines) >= 3, "좁은 폭에서 강조 구간이 여러 줄에 걸친다"
    hot = "".join(t for line in lines for t, h in line if h)
    assert hot.replace(" ", "") == "맛이더좋아질까정말로궁금해요"
    plain = " ".join("".join(t for t, _ in line) for line in lines)
    assert "[" not in plain and "]" not in plain
    assert plain.split() == ["왜", "맛이", "더", "좋아질까", "정말로", "궁금해요?"], "낱말(띄어쓰기) 안에서 끊지 않는다"
    assert all(d.textlength("".join(t for t, _ in line), font=f) <= 520 for line in lines)
    # 낱말 안에서 강조가 끝나는 경우 — 조사는 강조가 아니다
    only = ph.layout_lines(d, "[물 한두 방울]을 떨어뜨려요", f, 2000)[0]
    assert only[0] == ("물 한두 방울", True) and only[1][0].startswith("을")
    assert ph.parse_hot("짝 없는 [대괄호") == [(c, False) for c in "짝 없는 [대괄호"]


def test_overlong_headline_is_truncated_and_reported(tmp_path):
    long = {**JOB, "plan": {"layout": "photo", "pages": [
        {"position": 1, "role": "explain", "heading": "아주 긴 제목 " * 30, "body": "본문입니다 " * 80}]}}
    r = dc.render_carousel(long, str(tmp_path / "q"))
    assert r.qa["truncated_pages"] == [1] and "text_truncated" in r.qa["warnings"]


def test_missing_glyph_is_reported_in_photo_layout(tmp_path):
    bad = {**JOB, "plan": {"layout": "photo", "pages": [{"position": 1, "role": "explain", "heading": "☐ 상자", "body": "x"}]}}
    r = dc.render_carousel(bad, str(tmp_path / "g"))
    assert "glyph_missing" in r.qa["warnings"] and "☐" in r.qa["missing_glyphs"]


def test_source_page_has_handle_cta_warning_and_ai_notice_only_with_ai_photos(tmp_path, monkeypatch):
    seen = _texts(monkeypatch)
    dc.render_carousel(JOB, str(tmp_path / "ai"), images=_images(tmp_path))
    joined = "\n".join(seen)
    assert "@sooljjerigo" in seen and config.DRINKS_CARD_FOLLOW_LINE1 in seen and config.DRINKS_CARD_FOLLOW_LINE3 in seen
    assert "참조자료" in seen and "Karlsson, B. & Friedman, R. (2017).\nScientific Reports 7, 6489." in seen
    assert "경고: 지나친 음주는 뇌졸중, 기억력 손상이나 치매를 유발합니다." in joined and "임신 중 음주는 기형아 출생 위험을 높입니다." in joined
    assert config.DRINKS_CARD_AI_NOTICE in joined
    seen.clear()
    r = dc.render_carousel(JOB, str(tmp_path / "noai"))
    joined = "\n".join(seen)
    assert config.DRINKS_CARD_AI_NOTICE not in joined and "경고: 지나친 음주는" in joined, "사진이 없으면 AI 고지는 빠지고 경고는 남는다"
    assert r.qa["ai_images"] is False


def test_source_page_falls_back_to_job_sources_and_handle_env_override(tmp_path, monkeypatch):
    seen = _texts(monkeypatch)
    monkeypatch.setattr(config, "DRINKS_IG_HANDLE", "other_account")
    job = {**JOB, "sources": [{"publisher": "Sci Rep", "title": "Dilution of whisky", "url": "https://example.org/x"}],
           "plan": {"layout": "photo", "pages": [{"position": 1, "role": "source"}]}}
    dc.render_carousel(job, str(tmp_path / "s"))
    assert "@other_account" in seen
    assert "Sci Rep Dilution of whisky\nhttps://example.org/x" in seen


def test_handle_env_default_is_sooljjerigo():
    assert config.DRINKS_IG_HANDLE == "sooljjerigo"


# ─────────────────────────────────────────────────────────────
# 캡션
# ─────────────────────────────────────────────────────────────

CLAIMS = [{"claim_id": "c1", "kind": "fact", "source_refs": [{"original_quote": "In 2017 a study found that adding a few drops of water to whisky"}]}]


def test_caption_has_the_approved_shape_without_warning_line():
    out = cap.build_caption(PLAN, {"title": "t"}, handle="sooljjerigo", ai_images=True)
    blocks = out.split("\n\n")
    assert blocks[0] == "위스키에 물 몇 방울, 왜 맛이 더 좋아질까? 💧"
    assert blocks[1].startswith("위스키 고수들이 잔에 물 한두 방울")
    assert blocks[2].splitlines() == ["1. 스모키한 향 분자(과이아콜)는 알코올이 진하면 술 속에 숨어요",
                                      "2. 물이 들어가면 이 분자가 표면으로 올라와요",
                                      "3. 술은 표면부터 입에 닿아서 향과 맛이 더 잘 느껴져요"], "요점은 3개까지, 제작안 문장 그대로"
    assert blocks[3] == "※ 사람이 맛본 실험이 아닌 컴퓨터 시뮬레이션 연구예요. 출처는 마지막 장에 있어요."
    assert blocks[4].splitlines() == ["📌 저장해 두고, 위스키 좋아하는 친구에게 공유해 주세요",
                                      "🥃 술 궁금증, 근거로 풀어 드려요 → @sooljjerigo 팔로우"]
    assert blocks[5] == "*생성형 AI 이미지 포함"
    assert blocks[6] == "#위스키 #위스키상식 #싱글몰트 #술상식 #술째리고"
    assert "경고" not in out and "뇌졸중" not in out and "임신" not in out and "DM" not in out


def test_caption_ai_line_toggles_and_hashtags_are_capped_with_brand_last():
    off = cap.build_caption(PLAN, {}, handle="@sooljjerigo", ai_images=False)
    assert "생성형 AI" not in off and "@sooljjerigo 팔로우" in off and "@@" not in off
    tags = off.split("\n\n")[-1].split()
    assert len(tags) <= config.DRINKS_CAPTION_MAX_HASHTAGS and tags[-1] == "#술째리고" and len(set(tags)) == len(tags)
    many = {**PLAN, "caption": {**PLAN["caption"], "hashtags": [f"태그{i}" for i in range(20)]}}
    t2 = cap.build_caption(many, {}, handle="h", ai_images=False).split("\n\n")[-1].split()
    assert len(t2) == config.DRINKS_CAPTION_MAX_HASHTAGS and t2[-1] == "#술째리고"


def test_caption_fallbacks_come_only_from_the_plan():
    bare = {"pages": PAGES}   # caption 칸이 없다
    out = cap.build_caption(bare, {"title": "주제"}, handle="sooljjerigo", ai_images=False)
    assert out.startswith("위스키에 물 몇 방울, 왜 맛이 더 좋아질까?\n\n2017년 과학 논문이 밝힌 이유\n\n1. 위스키 고수들은 마시기 전에 물 한두 방울을 떨어뜨려요")
    assert "※ 출처는 마지막 장에 있어요." in out and "[" not in out and out.endswith("#술째리고")
    assert cap.build_caption({"pages": []}, {"title": "주제"}, handle="h", ai_images=False).startswith("주제\n\n※")
    with pytest.raises(ValueError):
        cap.build_caption({"caption": {"title": "가" * 3000}}, {}, handle="h", ai_images=False)


def test_caption_passes_publish_check_and_respects_db_limits():
    out = cap.build_caption(PLAN, {}, handle="sooljjerigo", ai_images=True)
    rep = sc.check_caption(out, CLAIMS)
    assert rep.ok, sc.summary_ko(rep)
    assert re.search(r"'caption_max',\s*(\d+)", PUBLISH_SQL).group(1) == str(config.DRINKS_CAPTION_MAX_CHARS)
    assert re.search(r"'hashtag_max',\s*(\d+)", PUBLISH_SQL).group(1) == str(config.DRINKS_CAPTION_DB_HASHTAG_MAX)
    assert len(out) <= config.DRINKS_CAPTION_MAX_CHARS
    assert len(re.findall(r"#[^\s#]+", out)) <= config.DRINKS_CAPTION_DB_HASHTAG_MAX
    # 번호 목록 머리("1.")는 숫자 근거 검사에 걸리지 않지만, 본문의 근거 없는 숫자는 여전히 막는다
    bad = sc.check_caption("1. 알코올 99% 이상이에요\n2. 물이 들어가요", CLAIMS)
    assert [f.code for f in bad.blocks] == ["number_unsupported"] and "99" in bad.blocks[0].message


# ─────────────────────────────────────────────────────────────
# 유료 4:5 그림
# ─────────────────────────────────────────────────────────────

# 기준 커밋(06c155d)에서 잰 값 — 영상 주문 항목의 해시·주문서 해시는 이 변경으로 달라지면 안 된다(이미 산 그림을 못 알아본다)
BASE_VIDEO_HASHES = {
    "scene-01-reality": "b7f73e7921f94334337e4b42fd9e5d5f4f8d4edbee59870fbda1893724cac868",
    "scene-02-mechanism": "9271b02a172583d16b1b63fb40d5ea8d28f6965bff3696b88c9406f95fee4d52",
    "scene-03-reality": "b52c041928ad4b4c9f81bd938291e1d62e8a6649cb23c7b9a72d6df5c5e8ae0a",
    "scene-04-reality": "8afc0fea2c0da2109b46a0e7b2258d9563895e7ee61664d979ce18063ba87f05",
    "scene-05-reality": "b8743797a5e0834c2a4674bf995560d3986c962e35228c0b9855d8aac7178150",
}
BASE_ORDER_HASH = "1fcbced6ea2d7dd5ef1a5ec41eea96fbe0332890593a86d58d58271f131696c2"


def test_existing_video_order_hashes_are_unchanged():
    items = dpaid.build_image_items(SPEC["scenes"])
    assert {i.item_key: i.prompt_hash for i in items} == BASE_VIDEO_HASHES
    assert dpaid.order_hash(items) == BASE_ORDER_HASH
    assert all(i.aspect == "" for i in items), "영상 항목은 종횡비를 따로 갖지 않는다(엔진 전역 9:16)"


def test_card_items_are_4x5_raw_prompt_with_common_style_and_distinct_hash():
    it = dpaid.card_image_item(2, "A hand holding a dropper")
    assert it.aspect == "4:5" == config.DRINKS_CARD_ASPECT and it.kind == "image" and it.item_key == "page-02-photo"
    assert it.prompt == f"A hand holding a dropper {config.DRINKS_CARD_IMAGE_STYLE}" == it.cut["raw_prompt"]
    assert "Vertical 4:5" in it.prompt and "9:16" not in it.prompt
    assert it.model == config.image_model_for("REALITY") and it.est_usd == config.DRINKS_PAID_PRICES["image_reality"]
    video_like = dpaid.image_item(2, "reality", "A hand holding a dropper")
    assert video_like.prompt_hash != it.prompt_hash
    # 종횡비가 해시에 들어간다: 같은 문장·모델이라도 9:16 이면 다른 그림
    assert dpaid._image_hash(it.model, it.prompt, None, "9:16") != it.prompt_hash
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.card_image_item(1, "  ")
    assert e.value.code == "visual_prompt_missing"


def test_build_card_items_skips_source_and_pages_without_prompt():
    pages = [dict(p) for p in PAGES] + [{"position": 5, "role": "explain", "heading": "x"}]
    assert [i.position for i in dpaid.build_card_image_items(pages)] == [1, 2, 3]
    with pytest.raises(dpaid.PaidError) as e:
        dpaid.build_card_image_items([{"position": 1, "role": "source"}, {"position": 2, "role": "explain", "heading": "x"}])
    assert e.value.code == "visual_prompt_missing"


def test_aspect_is_applied_only_inside_the_paid_call_and_raw_prompt_is_sent_as_is():
    from engine.providers import image as imgp

    before = config.ASPECT_RATIO
    it = dpaid.card_image_item(1, "A droplet")
    with dpaid._paid_provider("image", it.aspect):
        assert config.ASPECT_RATIO == "4:5"
        body = imgp._image_request_body(it.cut, dpaid.HEADER)
        assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "4:5"
    assert config.ASPECT_RATIO == before
    assert body["contents"][0]["parts"][-1]["text"] == it.prompt
    # raw_prompt 가 없는 컷(영상)은 예전 조립 그대로 — 9:16 문구가 붙는다
    assert "vertical 9:16 portrait aspect ratio" in imgp._build_image_prompt({"cut_no": 1, "visual_prompt": "x"}, dpaid.HEADER)


class _Rpc:
    def __init__(self, cache=None):
        self.calls: list[tuple[str, dict]] = []
        self.cache = cache or []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_heartbeat_render":
            return {"cancel_requested": False, "renderable": True}
        if fn == "drinks_find_generated":
            return [c for c in self.cache if c["prompt_hash"] in p["prompt_hashes"]]
        if fn == "drinks_hold_spend":
            return {"hold_id": f"h{len(self.calls)}"}
        if fn == "drinks_register_generated":
            return {"asset_id": "g1"}
        if fn == "drinks_register_asset":
            return {"asset_id": f"a{len(self.calls)}"}
        if fn == "drinks_finish_render":
            return {"status": "succeeded" if p.get("outcome") == "succeeded" else "failed", **p}
        return {}

    def of(self, fn):
        return [p for f, p in self.calls if f == fn]


def _paid_job(**over):
    return {"job_id": "11111111-2222-3333-4444-555555555555", "lease_token": "t", "format": "carousel", "renderer": "paid",
            "spend_approval_id": "ap1", "renderer_version": "v1", "topic": {"title": "t"}, "claims": [], "sources": [],
            "plan": PLAN, **over}


def test_paid_card_job_buys_one_4x5_image_per_prompted_page_and_renders_them(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key="TEST-not-real"))
    from engine.providers import image as imgp

    seen: list[tuple] = []

    def fake_generate_image(cut, header, out, model="", ref_path=None):   # 공급자 호출만 가짜 — 진짜 _generate 가 설정을 켠다
        seen.append((config.IMAGE_PROVIDER, config.ASPECT_RATIO, cut.get("raw_prompt"), model))
        _photo(Path(out), (864, 1080))
        return out, config.DRINKS_PAID_PRICES["image_reality"]
    monkeypatch.setattr(imgp, "generate_image", fake_generate_image)
    rpc = _Rpc()
    out = dp.process_job(_paid_job(), rpc, dp.Storage("local", str(tmp_path)))
    assert out["status"] == "succeeded", out
    holds = rpc.of("drinks_hold_spend")
    assert [h["item_key"] for h in holds] == ["page-01-photo", "page-02-photo", "page-03-photo"]
    assert all(h["approval_id"] == "ap1" and h["kind"] == "image" and h["provider"] == "gemini" for h in holds)
    assert [(x[0], x[1]) for x in seen] == [("gemini", "4:5")] * 3, "산 그림은 4:5 로 주문한다"
    assert all(x[2].endswith(config.DRINKS_CARD_IMAGE_STYLE) for x in seen)
    assert config.ASPECT_RATIO == "9:16" and config.IMAGE_PROVIDER != "gemini", "호출이 끝나면 원래대로"
    costs = rpc.of("drinks_record_cost")
    assert [c["cost"]["kind"] for c in costs] == ["image"] * 3 + ["card"]
    assert all(c["cost"]["provider"] == "gemini" for c in costs[:3]) and "쪽" in costs[0]["cost"]["note"]
    fin = rpc.of("drinks_finish_render")[-1]
    assert fin["qa"]["template_version"] == "card-photo-v1" and "photo_missing" not in fin["qa"]["warnings"]
    assert fin["qa"]["generated_pages"] == [1, 2, 3] and fin["qa"]["ai_images"] is True
    reg = rpc.of("drinks_register_asset")
    assert len(reg) == 4 and all(r["asset"]["rights"] == "generated_paid" for r in reg)
    # 그림은 재사용 목록에 4:5 크기 그대로 올라간다
    assert all((g["asset"]["width"], g["asset"]["height"]) == (864, 1080) for g in rpc.of("drinks_register_generated"))


def test_paid_card_job_reuses_already_bought_images_for_free(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))   # 키가 없어도 재사용은 된다
    from engine.drinks_render import sha256_file

    storage = dp.Storage("local", str(tmp_path / "st"))
    items = dpaid.build_card_image_items(PAGES)
    cache = []
    for it in items:
        src = Path(tmp_path / f"c{it.position}.png")
        _photo(src, (864, 1080))
        key = storage.put(str(src), f"drinks/generated/{it.prompt_hash[:2]}/{it.prompt_hash}.png", "image/png")
        cache.append({"prompt_hash": it.prompt_hash, "storage_key": key, "sha256": sha256_file(str(src)), "asset_id": "g0"})
    rpc = _Rpc(cache)
    monkeypatch.setattr(dpaid, "_generate", lambda *a: pytest.fail("사면 안 된다"))
    out = dp.process_job(_paid_job(), rpc, storage)
    assert out["status"] == "succeeded"
    assert not rpc.of("drinks_hold_spend")
    assert all(c["cost"]["cost_usd"] == 0 for c in rpc.of("drinks_record_cost"))


def test_paid_card_job_failures_stop_before_spending(tmp_path, monkeypatch):
    # 그림 지시문이 하나도 없다 → 아무것도 사기 전에 실패
    bare = {"layout": "photo", "pages": [{"position": 1, "role": "cover", "heading": "x"}, {"position": 2, "role": "source"}]}
    rpc = _Rpc()
    out = dp.process_job(_paid_job(plan=bare), rpc, dp.Storage("local", str(tmp_path)))
    assert out["status"] == "failed" and out["error_code"] == "visual_prompt_missing"
    assert not rpc.of("drinks_hold_spend") and not rpc.of("drinks_find_generated")
    # 키가 없으면 가잡기 전에 PaidError 코드 그대로
    monkeypatch.setattr(config, "SECRETS", config.Secrets(gemini_api_key=""))
    rpc2 = _Rpc()
    out2 = dp.process_job(_paid_job(), rpc2, dp.Storage("local", str(tmp_path)))
    assert out2["error_code"] == "api_key_missing" and not rpc2.of("drinks_hold_spend")


def test_local_card_job_and_text_card_plan_never_buy(tmp_path, monkeypatch):
    monkeypatch.setattr(dpaid, "buy", lambda *a, **k: pytest.fail("사면 안 된다"))
    rpc = _Rpc()
    local = dp.process_job(_paid_job(renderer="local", spend_approval_id=None), rpc, dp.Storage("local", str(tmp_path / "a")))
    assert local["status"] == "succeeded" and "photo_missing" in rpc.of("drinks_finish_render")[-1]["qa"]["warnings"]
    plain = _paid_job(plan={"pages": [{"position": 1, "role": "cover", "heading": "표지"}]})
    assert dp.process_job(plain, _Rpc(), dp.Storage("local", str(tmp_path / "b")))["status"] == "succeeded"
