"""주류 카드뉴스 형식 엔진(0065) — 카드 제작안 초안 워커·코드 검사·릴스 렌더·음원 전달. 모델·네트워크·실제 인스타 호출 0(전부 가짜)."""
from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

from engine import config
from engine import drinks_card_plan as cp
from engine import drinks_card_reel as cr
from engine import drinks_cards as dc
from engine import drinks_develop as dd
from engine import drinks_publish as pub
from engine.drinks_collect import DbError
from engine.drinks_render import RenderError
from engine.providers import instagram as ig


@pytest.fixture(autouse=True)
def _text_layout(monkeypatch):
    """이 파일은 글자 카드(card-reel-v1) 계약을 본다. 사진형 초안 규칙은 test_drinks_photo_cards.py 가 본다."""
    monkeypatch.setattr(config, "DRINKS_CARD_LAYOUT", "text")

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0065_drinks_card_reels.sql").read_text(encoding="utf-8")
ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg 없음")

QUOTE1 = "Spirits such as whisky do not spoil the way wine does because their high alcohol content of 40 percent prevents microbes from growing."
QUOTE2 = "Once a bottle is opened, the air in the bottle slowly changes the flavour of the whisky over time."
QUOTE3 = "Labels on spirits may show a production or bottling lot instead of an expiry date."
CLAIMS = [{"claim_id": f"c{i}", "text": t, "claim_type": "process", "source_refs": [{"snapshot_id": "s1", "original_quote": q}]}
          for i, (t, q) in enumerate((("도수가 높아 안 상한다", QUOTE1), ("열면 맛이 바뀐다", QUOTE2), ("라벨에 번호가 있다", QUOTE3)), 1)]
REVIEW = {"review_id": "r1", "status": "draft", "claims": CLAIMS, "core_claim_ids": ["c1", "c2", "c3"],
          "sources": [{"snapshot_id": "s1", "title": "보관 안내", "publisher": "시험 출처", "url": "https://example.org/a"}],
          "brief": {"selected_claim_ids": ["c1", "c2", "c3"], "required_claims": {"carousel": ["c1", "c2"]}}}
TOPIC = {"id": "t1", "title": "위스키에도 유통기한이 있을까?", "question": "위스키는 왜 안 상할까?"}


def good_plan():
    return {"pages": [
        {"role": "cover", "heading": "위스키는 왜 안 상할까요?", "body": "", "claim_ids": []},
        {"role": "explain", "heading": "술이 세서 그래요", "body": "도수가 40도쯤이라\n미생물이 못 자라요", "claim_ids": ["c1"]},
        {"role": "explain", "heading": "그럼 맛도 그대로일까요?", "body": "병을 따면 달라져요\n공기가 맛을 천천히 바꿔요", "claim_ids": ["c2"]},
        {"role": "explain", "heading": "날짜가 없다면요?", "body": "제조 번호가\n적혀 있을 수 있어요", "claim_ids": ["c3"]},
        {"role": "source", "heading": "출처", "body": "", "claim_ids": []},
    ], "reel": {"hook_title": "위스키는 왜 안 상할까요?", "share_line": "오래된 병 고민하는 친구에게 보내 주세요"},
        "viewer_conclusion": {"text": "도수가 높아 잘 안 상하지만, 열면 맛이 바뀌어요", "claim_ids": ["c1", "c2"]}}


def codes(plan, review=REVIEW, topic=TOPIC):
    rep = cp.check_card_plan(plan, review, topic)
    return [f.code for f in rep.blocks], [f.code for f in rep.warns]


def changed(fn):
    p = copy.deepcopy(good_plan())
    fn(p)
    return p


# ── 대본 품질 규칙(운영자 지시) ──

def test_good_plan_passes_with_no_blocks():
    assert codes(good_plan()) == ([], [])


@pytest.mark.parametrize("edit,code", [
    (lambda p: p["pages"][1].update(body="도수가 80도라서\n미생물이 못 자라요"), "number_unsupported"),                     # 원문에 없는 숫자
    (lambda p: p["pages"][2].update(body="물을 세 티스푼 넣어요"), "quantity_unsupported"),                                  # 원문에 없는 양
    (lambda p: p["pages"][2].update(body="병을 따면 빨리 드세요"), "advice_unsupported"),                                     # 지어낸 처방
    (lambda p: p["pages"][1].update(body="도수가 높아 상하지 않습니다"), "formal_style"),                                     # 문어체
    (lambda p: p["pages"][1].update(claim_ids=[]), "fact_page_no_claim"),                                                   # 사실인데 근거 없음
    (lambda p: p["pages"][1].update(claim_ids=["zz"]), "claim_not_allowed"),
    (lambda p: p["pages"][1].update(claim_ids=["c3"]), "required_claim_missing"),                                           # 필수 주장 누락
    (lambda p: p["pages"].insert(0, p["pages"].pop(1)), "cover_position"),
    (lambda p: p["pages"].pop(), "source_position"),
    (lambda p: p["reel"].update(hook_title="위스키 보관법"), "hook_not_question"),
    (lambda p: p["reel"].update(share_line="이 글을 읽어 주세요"), "share_line_no_action"),
    (lambda p: p["reel"].update(share_line="100번 저장해 두세요"), "number_unsupported"),
    (lambda p: p["reel"].update(share_line="저장하고 오늘 한잔 해요"), "drinking_encouraged"),
    (lambda p: p.update(viewer_conclusion={"text": "결론", "claim_ids": []}), "conclusion_unsupported"),
    (lambda p: p.pop("viewer_conclusion"), "conclusion_missing_dev"),
    (lambda p: p["pages"][1].update(heading="가" * 40), "heading_long"),
    (lambda p: p["pages"][1].update(body="가" * 200), "body_long"),
])
def test_rules_block(edit, code):
    assert code in codes(changed(edit))[0]


def test_number_must_be_in_the_quote_of_that_page_not_any_page():
    p = changed(lambda x: x["pages"][2].update(body="40도라서 맛이 바뀌어요"))   # 40 은 c1 인용에만 있다. 이 페이지는 c2
    assert "number_unsupported" in codes(p)[0]


def test_rule_talk_is_a_side_note_unless_the_topic_asks_about_it():
    p = changed(lambda x: (x["pages"][1].update(body="표시 기준에 따라 적어요"), x["pages"][2].update(body="고시에 나와 있어요")))
    assert "rule_not_side_note" in codes(p)[0]
    only_one = changed(lambda x: x["pages"][1].update(body="표시 기준에 따라 적어요"))
    assert "rule_not_side_note" not in codes(only_one)[0]
    assert "rule_not_side_note" not in codes(p, topic={"title": "사케 표시 기준", "question": "표시 기준은 왜 있나"})[0]


def test_hook_without_why_and_long_lines_are_notes_not_blocks():
    p = changed(lambda x: (x["reel"].update(hook_title="위스키에 유통기한이 있나요?"), x["pages"][1].update(body="가나다라마바사아자차카타파하가나다라마바사아자차카타파하")))
    blocks, warns = codes(p)
    assert blocks == []
    assert set(warns) == {"hook_no_why", "line_long"}


def test_share_line_may_say_save_it_but_drink_advice_is_still_blocked():
    assert codes(changed(lambda x: x["reel"].update(share_line="저장해 두세요")))[0] == []
    assert "advice_unsupported" in codes(changed(lambda x: x["pages"][1].update(body="물을 타세요")))[0]


def test_required_claims_rule_matches_sql():
    assert cp.required_claims({"required_claims": {"carousel": ["a"], "video": ["b"]}}) == ["a"]
    assert cp.required_claims({"required_claims": {"video": ["b"]}}) == ["b"]
    assert cp.required_claims({"selected_claim_ids": ["1", "2", "3", "4"]}) == ["1", "2", "3"]
    assert config.DRINKS_DEVELOP_REQUIRED_CLAIMS == 3 and "where o <= 3" in SQL, "SQL drinks_format_required 의 앞 N개"


def test_prompt_states_the_operator_rules():
    s = cp.system_prompt()
    for phrase in ("왜", "곁가지", "구어체", "뜻이 끊기는", "만들지 않는다", "저장"):
        assert phrase in s, phrase


# ── 워커 ──

class Rpc:
    def __init__(self):
        self.calls = []
        self.saved = None
        self.finish = None
        self.holds = 0

    def __call__(self, fn, p):
        self.calls.append(fn)
        if fn in ("drinks_heartbeat_develop", "drinks_develop_context"):   # 0076: 부가 정보(수정 지시 없음)
            return {}
        if fn == "drinks_develop_hold":
            self.holds += 1
            return {"hold_id": f"h{self.holds}"}
        if fn == "drinks_develop_settle":
            return {}
        if fn == "drinks_develop_save_plan":
            self.saved = p
            return {"revision_id": "pl1", "coverage": {"ok": True}}
        if fn == "drinks_finish_develop":
            self.finish = p
            return {"status": p["outcome"], "result": p.get("result")}
        raise AssertionError(fn)


def job(**kw):
    return {"request_id": "q1", "lease_token": "l1", "kind": "plan", "budget_id": "b1", "topic": TOPIC, "review": REVIEW,
            "format_intent": "card", "draft_evidence": True, **kw}


def deps(**kw):
    def boom(*a, **k):
        raise AssertionError("이 경로에서 부르면 안 된다")
    return dd.Deps(**{"extract_claims": boom, "write_plan": boom, "write_card_plan": boom, "jev_check": lambda n, s: None,
                      "factcheck": lambda *a: {"assertions": [], "claim_checks": []}, **kw})


def test_worker_writes_card_plan_saves_and_never_approves():
    r = Rpc()
    res = dd.process_job(job(), r, deps(write_card_plan=lambda q, c, b, f=None: good_plan()))
    assert res["status"] == "succeeded", r.finish
    plan = r.saved["plan_json"]
    assert [p["role"] for p in plan["pages"]] == ["cover", "explain", "explain", "explain", "source"]
    assert plan["reel"]["hook_title"].endswith("?")
    assert "viewer_conclusion" not in plan and "시청자 결론" in plan["notes"]
    assert r.saved["core_takeaway_draft"].startswith("도수가")
    assert r.finish["result"]["source_table"][1]["claims"][0]["quotes"][0]["quote"] == QUOTE1, "페이지 → 근거 → 원문 대조표가 남는다"
    assert not any(re.search(r"approve|submit|review_action|plan_action|select", n) for n in r.calls), "워커는 승인·제출·편성을 부르지 않는다"


def test_blocked_draft_is_rewritten_once_then_not_saved():
    r = Rpc()
    seen = []

    def bad(q, c, b, f=None):
        seen.append(f)
        return changed(lambda x: x["pages"][1].update(body="80도라서 물을 세 티스푼 넣어요"))

    res = dd.process_job(job(), r, deps(write_card_plan=bad))
    assert res["status"] == "blocked"
    assert r.finish["error_code"] == "script_check_failed"
    assert r.saved is None, "막힌 대본은 저장하지 않는다"
    assert len(seen) == 2 and seen[0] is None and any("number_unsupported" in m for m in seen[1]), "딱 한 번, 이유를 알려 주고 다시 쓴다"
    assert r.holds == 2


def test_no_budget_means_no_model_call():
    r = Rpc()
    res = dd.process_job(job(budget_id=None), r, deps())
    assert res["status"] == "blocked" and r.finish["error_code"] == "budget_missing"
    assert r.holds == 0


def test_unflagged_request_is_not_a_card_path_and_refuses_draft_evidence():
    r = Rpc()
    res = dd.process_job(job(draft_evidence=False), r, deps())   # boom: 어떤 모델이든 부르면 실패
    assert res["status"] == "blocked" and r.finish["error_code"] == "review_not_approved"


def test_explainer_intent_stays_on_the_video_path():
    r = Rpc()
    res = dd.process_job(job(format_intent="explainer"), r, deps(write_plan=lambda *a, **k: {"scenes": []}))
    assert res["status"] == "blocked" and r.finish["error_code"] == "script_check_failed"
    assert r.finish["result"]["rejected_plan"] == {"scenes": []}, "카드 경로로 새지 않는다"


def test_save_rejection_keeps_the_paid_draft():
    class R(Rpc):
        def __call__(self, fn, p):
            if fn == "drinks_develop_save_plan":
                self.calls.append(fn)
                raise DbError("review_changed", "근거가 바뀌었습니다")
            return super().__call__(fn, p)

    r = R()
    res = dd.process_job(job(), r, deps(write_card_plan=lambda q, c, b, f=None: good_plan()))
    assert res["status"] == "failed" and r.finish["result"]["unsaved_plan"]["reel"]["hook_title"]


# ── 렌더 ──

def test_page_timings_stay_in_range_and_sum_to_15_30():
    (lo, hi), (tlo, thi) = config.DRINKS_CARD_REEL_PAGE_SECONDS, config.DRINKS_CARD_REEL_SECONDS
    for n in range(config.DRINKS_CARD_REEL_LIMITS["min_pages"], config.DRINKS_CARD_REEL_LIMITS["max_pages"] + 1):
        for body in ("", "가" * 120):
            t = cr.page_timings([{"heading": "제목", "body": body}] * n)
            assert all(lo - 1e-3 <= x <= hi + 1e-3 for x in t), (n, t)
            assert tlo - 1e-2 <= sum(t) <= thi + 1e-2, (n, sum(t))
    with pytest.raises(RenderError) as e:
        cr.page_timings([{"heading": "x"}] * 3)
    assert e.value.code == "card_reel_duration"
    with pytest.raises(RenderError):
        cr.page_timings([{"heading": "x"}] * 13)


def test_lines_end_at_meaning_units_and_keep_written_breaks():
    im = Image.new("RGB", (10, 10))
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    f = dc._font("body", 56)
    assert cr.meaning_lines(d, "첫 줄이에요\n둘째 줄이에요", f, cr.TEXT_W) == ["첫 줄이에요", "둘째 줄이에요"]
    long = "위스키는 도수가 높아서 미생물이 자라지 못하기 때문에 와인처럼 쉽게 상하지 않아요"
    lines = cr.meaning_lines(d, long, f, cr.TEXT_W)
    assert len(lines) >= 2 and all(d.textlength(x, font=f) <= cr.TEXT_W for x in lines)
    assert " ".join(lines).replace(" ", "") == long.replace(" ", ""), "글자를 잃지 않는다"
    assert not any(x.endswith(("미생물이", "와인처럼 쉽게")) for x in lines), f"꾸미는 말을 끝에 남기지 않는다: {lines}"


def test_frames_stay_inside_the_safe_area_even_at_max_length(tmp_path):
    reel = {"hook_title": "가나다라마바사아자차카타파하가나다라마바사아자차?"[: config.DRINKS_CARD_HOOK_MAX_CHARS], "share_line": "저" * config.DRINKS_CARD_SHARE_MAX_CHARS}
    words = ("가나다라 마바사아 자차카타 " * 12)[: config.DRINKS_CARD_BODY_MAX_CHARS + 30]
    pages = [{"role": "cover", "heading": "제목"}, {"role": "explain", "heading": "가" * config.DRINKS_CARD_HEADING_MAX_CHARS, "body": words},
             {"role": "checklist", "heading": "볼 것", "body": "\n".join(["항목 하나 둘 셋"] * 6)},
             {"role": "source", "heading": "출처"}]
    sources = [{"publisher": f"발행처 {i}", "title": "아주 긴 출처 제목이 여기 들어가서 줄을 넘깁니다 " * 2} for i in range(4)]
    for i, pg in enumerate(pages, 1):
        q = cr.draw_frame(pg, i, len(pages), reel, sources, str(tmp_path / f"{i}.png"))
        assert q["safe_area_violations"] == [], (i, q)
        assert q["truncated"] is False, f"{i}쪽: 코드 검사 상한 안의 글은 잘리지 않아야 한다"
        assert Image.open(tmp_path / f"{i}.png").size == (1080, 1920)


def test_hook_starts_in_the_upper_20_to_25_percent_and_is_big(tmp_path):
    path = tmp_path / "hook.png"
    cr.draw_frame({"role": "cover", "heading": "제목"}, 1, 5, {"hook_title": "위스키는 왜 안 상할까요?", "share_line": "저장"}, [], str(path))
    im = Image.open(path).convert("L")
    # 윗줄(브랜드·쪽 번호) 아래에서 처음 나오는 밝은 글자 줄 = 훅 제목의 시작. 강조 막대는 어두운 회색이라 문턱으로 거른다.
    rows = [y for y in range(cr.TOP_ROW_Y + 70, 1920) if im.crop((0, y, 1080, y + 1)).getextrema()[1] > 220]
    assert 0.20 <= rows[0] / 1920 <= 0.25, rows[0]
    assert rows[-1] - rows[0] > 2 * 128, "두 줄 이상 차지하는 큰 제목"


def test_reel_refuses_plans_that_cannot_make_a_reel(tmp_path):
    job_ = {"topic": TOPIC, "sources": [], "plan": {"pages": [{"position": 1, "role": "cover", "heading": "x"}], "reel": {"hook_title": "x?", "share_line": "저장"}}}
    with pytest.raises(RenderError) as e:
        cr.render_card_reel(job_, str(tmp_path))
    assert e.value.code == "invalid_plan"
    job_["plan"] = {"pages": [{"position": i, "role": "explain", "heading": "x"} for i in range(1, 6)], "reel": {"hook_title": "", "share_line": "저장"}}
    with pytest.raises(RenderError):
        cr.render_card_reel(job_, str(tmp_path))


def test_old_card_plan_without_reel_makes_no_video(tmp_path):
    plan = cp.clean_plan(good_plan())
    plan.pop("reel")
    r = dc.render_carousel({"topic": TOPIC, "claims": CLAIMS, "sources": REVIEW["sources"], "plan": plan}, str(tmp_path / "p"))
    assert {f["role"] for f in r.files} == {"page"}
    assert "card_reel" not in r.qa
    assert [c["kind"] for c in r.costs] == ["card"]


@ffmpeg
def test_render_makes_pages_plus_vertical_reel_at_zero_cost(tmp_path):
    from engine.drinks_render import _probe

    r = dc.render_carousel({"topic": TOPIC, "claims": CLAIMS, "sources": REVIEW["sources"], "plan": cp.clean_plan(good_plan())}, str(tmp_path / "p"))
    roles = [f["role"] for f in r.files]
    assert roles.count("page") == 5 and roles.count("final_video") == 1 and roles.count("cover") == 1
    video = next(f for f in r.files if f["role"] == "final_video")
    p = _probe(video["path"])
    assert (p["width"], p["height"]) == (1080, 1920)
    assert 15 <= p["duration_sec"] <= 30
    assert p["video_codec"] == "h264" and p["audio_codec"] == "aac" and p["audio_streams"] == 1, "무음 트랙 — 나레이션 없음"
    assert r.qa["warnings"] == [], r.qa["warnings"]
    assert r.qa["reel_spec"]["moov_first"] is True
    assert r.qa["card_reel"]["narration"] is False and r.qa["card_reel"]["safe_area"]["app_checked"] is False
    assert r.qa["card_reel"]["page_claims"]["2"] == ["c1"], "화면에 나간 사실 → 근거 연결이 남는다"
    assert all(c["cost_usd"] == 0 for c in r.costs)
    cover = next(f for f in r.files if f["role"] == "cover")
    assert Image.open(cover["path"]).format == "JPEG"


@ffmpeg
def test_motion_really_moves_between_pages(tmp_path):
    """전환 움직임 실측: 전환 구간의 프레임은 앞·뒤 페이지 어느 쪽과도 다르다."""
    import subprocess

    from PIL import ImageChops

    plan = cp.clean_plan(good_plan())
    r = dc.render_carousel({"topic": TOPIC, "claims": CLAIMS, "sources": [], "plan": plan}, str(tmp_path / "p"))
    video = next(f for f in r.files if f["role"] == "final_video")["path"]
    t0 = r.qa["card_reel"]["timings_sec"][0]

    def at(sec, name):
        out = str(tmp_path / name)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{sec:.3f}", "-i", video, "-frames:v", "1", out], check=True)
        return Image.open(out).convert("L")

    a, mid, b = at(t0 - 0.5, "a.png"), at(t0 + config.DRINKS_CARD_REEL_TRANSITION_SEC / 2, "m.png"), at(t0 + config.DRINKS_CARD_REEL_TRANSITION_SEC + 0.3, "b.png")
    for other in (a, b):
        assert ImageChops.difference(mid, other).getbbox() is not None
    assert ImageChops.difference(a, b).getbbox() is not None


@ffmpeg
def test_produce_worker_registers_reel_and_cover_with_the_pages(tmp_path):
    """제작 워커 경로: 카드 작업 하나가 페이지 + 영상 + 표지를 묶음으로 끝낸다(가짜 DB·로컬 저장)."""
    from engine import drinks_produce as dp

    calls = []

    def rpc(fn, p):
        calls.append((fn, p))
        if fn == "drinks_heartbeat_render":
            return {"renderable": None}
        if fn == "drinks_register_asset":
            return {"asset_id": f"a{len(calls)}"}
        if fn == "drinks_finish_render":
            return {"status": "succeeded" if p["outcome"] == "succeeded" else "failed", **{k: p[k] for k in ("assets", "qa") if k in p}}
        return {}

    job_ = {"job_id": "11111111-2222", "lease_token": "l", "format": "carousel", "renderer": "local", "renderer_version": "v", "topic": TOPIC,
            "claims": CLAIMS, "sources": REVIEW["sources"], "plan": cp.clean_plan(good_plan())}
    res = dp.process_job(job_, rpc, dp.Storage("local", str(tmp_path)))
    assert res["status"] == "succeeded", res
    assert sorted(a["role"] for a in res["assets"]) == ["cover", "final_video"] + ["page"] * 5
    regs = [p["asset"] for fn, p in calls if fn == "drinks_register_asset"]
    assert {r["mime"] for r in regs} == {"image/png", "video/mp4", "image/jpeg"}
    assert all(r["rights"] == "generated_local" for r in regs)
    assert res["qa"]["probe"]["height"] == 1920


# ── 값 대조 ──

def test_reel_limits_match_sql_and_web():
    m = re.search(r"drinks_card_reel_limits\(\).*?jsonb_build_object\('min_pages', (\d+), 'max_pages', (\d+), 'hook_max', (\d+), 'share_max', (\d+)\)", SQL, re.S)
    lim = config.DRINKS_CARD_REEL_LIMITS
    assert tuple(map(int, m.groups())) == (lim["min_pages"], lim["max_pages"], lim["hook_max"], lim["share_max"])
    assert config.DRINKS_CARD_HOOK_MAX_CHARS <= lim["hook_max"] and config.DRINKS_CARD_SHARE_MAX_CHARS <= lim["share_max"], "워커 초안 상한이 DB 상한 안"
    lo, hi = config.DRINKS_CARD_PAGES
    assert lim["min_pages"] <= lo and hi <= lim["max_pages"]
    audio_ts = (ROOT / "web" / "lib" / "drinks" / "audio.ts").read_text(encoding="utf-8")
    assert f"CARD_REEL_AUDIO_VOLUME = {config.DRINKS_CARD_REEL_AUDIO_VOLUME};" in audio_ts
    assert f"CARD_REEL_VIDEO_VOLUME = {config.DRINKS_CARD_REEL_VIDEO_VOLUME};" in audio_ts


def test_migration_keeps_safety_rules_and_applies_nothing():
    assert "운영 DB 적용은 따로 결재" in SQL
    assert "되돌리기" in SQL
    for fn in ("drink_plans_guard", "drinks_plan_action", "drinks_plan_renderable", "drink_review_evidence_edited", "drinks_plan_coverage"):
        assert f"function {fn}(" not in SQL, f"{fn} 은 고치지 않는다"
    assert "review_not_approved" in SQL, "표시 없는 대본 요청의 규칙이 그대로다"
    # 끝나지 않은 공개 게시 경로를 켜지 않는다
    assert "publish_enabled = true" not in SQL


# ── 음원 전달(가짜 공급자 — 공개 게시 없음) ──

class PubRpc:
    def __init__(self):
        self.calls = []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_publication_step":
            return {"proceed": True}
        return {"status": p.get("outcome")}

    def finish(self):
        return next(p for fn, p in self.calls if fn == "drinks_finish_publication")

    def stages(self):
        return [p.get("stage") for fn, p in self.calls if fn == "drinks_publication_step"]


class FakeStorage:
    def signed_url(self, key, expires_sec=3600):
        return f"https://signed.example/{key}"


ACC = {"account_id": "a1", "connection": "fake", "external_account_id": "fake_1"}
AUDIO = {"mode": "ig_audio", "audio_id": "aud1", "audio_type": "music", "title_snapshot": "노래", "artist_snapshot": "가수",
         "audio_volume": 90, "video_volume": 10, "sync_grade": "sync_free"}
FILES = [{"role": "final_video", "position": 1, "storage_key": "drinks/j/v.mp4"}, {"role": "cover", "position": 1, "storage_key": "drinks/j/c.jpg"},
         {"role": "page", "position": 1, "storage_key": "drinks/j/p1.png"}]


def req(**kw):
    return {"request_id": "r1", "lease_token": "l1", "post_type": "reel", "caption": "", "account": dict(ACC), "files": FILES, "claims": [], "sources": [],
            "audio": dict(AUDIO), "audio_required": True, **kw}


@pytest.fixture
def fake(tmp_path):
    f = ig.FakeInstagram(str(tmp_path / "fake_ig.json"))
    f.add_account("fake_1", "술째리고시험")
    return f


def run(fake, r):
    rpc = PubRpc()
    res = pub.publish_one(r, rpc, FakeStorage(), lambda a: fake, wait_sec=1, poll_sec=0)
    return rpc, res


def containers(fake):
    return list(fake._load()["containers"].values())


def test_saved_audio_goes_to_the_provider_unchanged(fake):
    rpc, _ = run(fake, req())
    assert rpc.finish()["outcome"] == "published"
    c = containers(fake)
    assert len(c) == 1 and c[0]["kind"] == "reel"
    assert c[0]["audio_configuration"] == {"audio_id": "aud1", "audio_volume": 90, "video_volume": 10}, "값을 고치거나 채우지 않는다"
    assert c[0]["url"].endswith("v.mp4") and c[0]["cover_url"].endswith("c.jpg")
    assert rpc.stages()[0] == "audio_verified", "재조회가 컨테이너보다 먼저다"


@pytest.mark.parametrize("fault", ["unavailable", "timeout"])
def test_recheck_failure_stops_before_any_container(fake, fault):
    fake.inject("audio_check", fault)
    rpc, _ = run(fake, req())
    f = rpc.finish()
    assert f["outcome"] == "paused" and f["error_code"] == "audio_failed"
    assert containers(fake) == [], "음원 없이 올리지 않는다"
    assert "audio_verified" not in rpc.stages()


def test_recheck_auth_error_sends_account_to_reauth(fake):
    fake.inject("audio_check", "auth_error")
    rpc, _ = run(fake, req())
    assert rpc.finish()["error_code"] == "account_reauth"
    assert any(fn == "drinks_account_verified" for fn, _ in rpc.calls)


def test_container_failure_with_audio_pauses_instead_of_retrying_without_audio(fake):
    fake.inject("container", "error")
    rpc, _ = run(fake, req())
    f = rpc.finish()
    assert f["outcome"] == "paused" and f["error_code"] == "audio_failed"
    assert containers(fake) == []


def test_container_failure_without_audio_keeps_the_old_failed_path(fake):
    fake.inject("container", "error")
    rpc, _ = run(fake, req(audio=None, audio_required=False))
    assert rpc.finish()["outcome"] == "failed"


@pytest.mark.parametrize("over,msg", [
    ({"audio": None, "audio_required": True}, "필수"),
    ({"audio": {"mode": "none"}, "audio_required": True}, "필수"),
    ({"audio": {**AUDIO, "sync_grade": "sync_required"}}, "박자"),
    ({"audio": {**AUDIO, "video_volume": None}}, "빠진 칸"),
    ({"account": {**ACC, "connection": "instagram_login"}}, "Facebook"),
])
def test_worker_refuses_unsafe_audio_even_if_the_db_let_it_through(fake, over, msg):
    rpc, _ = run(fake, req(**over))
    f = rpc.finish()
    assert f["outcome"] == "paused" and f["error_code"] == "audio_failed" and msg in f["error_message"]
    assert containers(fake) == []


def test_narrated_reel_without_audio_still_publishes_with_no_audio_config(fake):
    rpc, _ = run(fake, req(audio=None, audio_required=False))
    assert rpc.finish()["outcome"] == "published"
    assert containers(fake)[0]["audio_configuration"] is None


def test_carousel_ignores_audio_and_is_unchanged(fake):
    rpc, _ = run(fake, req(post_type="carousel", audio=None, audio_required=False))
    assert rpc.finish()["outcome"] == "published"
    assert "audio_verified" not in rpc.stages()
    assert [c["kind"] for c in containers(fake)] == ["image", "carousel"]


def test_failure_after_publish_call_stays_unknown(fake):
    fake.inject("publish", "timeout_after")
    rpc, _ = run(fake, req())
    assert rpc.finish()["outcome"] == "unknown", "게시 호출 뒤 규칙은 음원 기능이 바꾸지 않는다"


def test_graph_sends_audio_as_json_and_token_in_header_only(monkeypatch):
    secret = "IGQ-secret"
    monkeypatch.setenv("IG_TOKEN_T", secret)
    seen = []

    def handler(r):
        seen.append(r)
        return httpx.Response(200, json={"id": "c1"})

    g = ig.GraphInstagram(client=httpx.Client(transport=httpx.MockTransport(handler)))
    acc = {"connection": "facebook_login", "external_account_id": "1784", "credential_ref": "IG_TOKEN_T"}
    cfg = {"audio_id": "aud1", "audio_volume": 90, "video_volume": 10}
    g.check_audio(acc, "aud1")
    g.create_container(acc, kind="reel", url="https://x.example/v.mp4", caption="c", audio_configuration=cfg)
    assert seen[0].url.path.endswith("/aud1") and seen[0].url.params["user_id"] == "1784"
    body = httpx.QueryParams(seen[1].content.decode())
    assert json.loads(body["audio_configuration"]) == cfg
    assert body["media_type"] == "REELS"
    for r in seen:
        assert secret not in str(r.url) and r.headers["authorization"] == f"Bearer {secret}"
    with pytest.raises(ig.PublishError):
        g.create_container(acc, kind="carousel", children=["a"], audio_configuration=cfg)


def test_rewrite_instruction_reaches_the_writer_and_saves_through_the_superseding_rpc():
    """0076 스튜디오 [이 방향으로 수정]: 지시와 지금 초안이 프롬프트에 실리고, 저장은 옛 초안을 막는 RPC 로 한 트랜잭션."""
    class RewriteRpc(Rpc):
        def __call__(self, fn, p):
            if fn == "drinks_develop_context":
                self.calls.append(fn)
                return {"instruction": "더 짧고 친근하게", "supersedes_plan_id": "old1", "current_plan": {"pages": [{"heading": "옛 표지"}]}}
            if fn == "drinks_develop_save_rewrite":
                self.calls.append(fn)
                self.saved = p
                return {"revision_id": "pl2", "coverage": {"ok": True}, "superseded_plan_id": "old1"}
            return super().__call__(fn, p)

    r = RewriteRpc()
    seen = []

    def write(q, c, b, f=None):
        seen.append(cp.user_prompt(q, c, b, f))
        return good_plan()

    res = dd.process_job(job(), r, deps(write_card_plan=write))
    assert res["status"] == "succeeded", r.finish
    assert "더 짧고 친근하게" in seen[0] and "옛 표지" in seen[0]
    assert "drinks_develop_save_rewrite" in r.calls and "drinks_develop_save_plan" not in r.calls


# ── 사진형 카드 초안(2026-11-08 복구 — PR 126 사진형이 브랜치 삭제로 자동 닫혀 빠졌던 것) ──

def _photo(plan):
    for i, pg in enumerate(plan["pages"]):
        if pg["role"] != "source":
            pg["image_prompt"] = f"A sake bottle on a wooden counter, scene {i}"
            pg["heading"] = pg["heading"].replace("왜", "[왜]", 1) if "왜" in pg["heading"] else f"[{pg['heading']}]"
    return plan


def test_photo_layout_requires_english_photo_prompt_one_highlight_and_two_body_lines(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_CARD_LAYOUT", "photo")
    assert codes(_photo(good_plan()))[0] == []
    no_prompt = _photo(good_plan()); no_prompt["pages"][1].pop("image_prompt")
    korean = _photo(good_plan()); korean["pages"][1]["image_prompt"] = "사케 병"
    lines = _photo(good_plan()); lines["pages"][1]["body"] = "한 줄\n두 줄\n세 줄"
    two = _photo(good_plan()); two["pages"][1]["heading"] = "[술이] [세서]"
    assert "photo_prompt_missing" in codes(no_prompt)[0]
    assert "photo_prompt_not_english" in codes(korean)[0]
    assert "photo_body_lines" in codes(lines)[0]
    assert "photo_highlight" in codes(two)[0]


def test_photo_layout_clean_plan_keeps_layout_and_prompts_but_not_on_the_source_page(monkeypatch):
    monkeypatch.setattr(config, "DRINKS_CARD_LAYOUT", "photo")
    out = cp.clean_plan({**_photo(good_plan()), "viewer_conclusion": {"text": "x", "claim_ids": ["c1"]}})
    assert out["layout"] == "photo" and out["template_version"] == config.DRINKS_CARD_PHOTO_TEMPLATE
    assert all(p.get("image_prompt") for p in out["pages"] if p["role"] != "source")
    assert "image_prompt" not in out["pages"][-1]
    assert "image_prompt" in cp.system_prompt() and "[대괄호]" in cp.system_prompt()


def test_photo_card_reel_uses_the_rendered_photo_pages_as_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DRINKS_CARD_LAYOUT", "photo")
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg 없음")
    plan = cp.clean_plan({**_photo(good_plan()), "viewer_conclusion": {"text": "x", "claim_ids": ["c1"]}})
    plan["reel"] = {"hook_title": "위스키는 왜 안 상할까?", "share_line": "친구에게 보내 보세요"}
    seen = []
    real = cr.draw_photo_frame
    monkeypatch.setattr(cr, "draw_frame", lambda *a, **k: pytest.fail("사진형은 글자 카드 틀로 다시 그리지 않는다"))
    monkeypatch.setattr(cr, "draw_photo_frame", lambda png, *a, **k: (seen.append(png), real(png, *a, **k))[1])
    job = {"job_id": "j" * 8, "plan": plan, "topic": TOPIC, "claims": [], "sources": REVIEW["sources"]}
    r = dc.render_carousel(job, str(tmp_path))
    pages = [f["path"] for f in r.files if f["role"] == "page"]
    assert seen == pages and any(f["role"] == "final_video" for f in r.files)
    with Image.open([f["path"] for f in r.files if f["role"] == "cover"][0]) as im:
        assert im.size == (1080, 1920)
