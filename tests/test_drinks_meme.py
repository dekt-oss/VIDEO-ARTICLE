"""밈 제작 엔진(engine/drinks_meme.py) — 틀·검사·게시 문·렌더. 돈·네트워크·DB 없음.
DB 규칙(거부·전이·권한)은 web/lib/drinks/meme.db.test.ts 가 실제 Postgres(PGlite)로 본다.
"""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import config
from engine import drinks_meme as dm
from engine.drinks_collect import DbError
from scripts import meme_rehearsal as rh

ROOT = Path(__file__).resolve().parent.parent
SQL = (ROOT / "supabase" / "migrations" / "0066_drinks_meme_engine.sql").read_text(encoding="utf-8")
TS = (ROOT / "web" / "lib" / "drinks" / "meme.ts").read_text(encoding="utf-8")
SRC = (ROOT / "engine" / "drinks_meme.py").read_text(encoding="utf-8")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


def joke(**kw):
    base = dict(frame="top_text", top_line="POV: 와인 고르는 척하는 나",
                beats=[{"text": "앞면을 본다", "ms": 3000}, {"text": "가격표만 기억난다", "keyword": "가격표", "ms": 4000}], caption="다들 이러잖아요")
    base.update(kw)
    return dm.build_spec(**base)


def codes(rep):
    return [f.code for f in rep.blocks]


# ── 구성 ──

def test_fixture_composition_is_what_the_operator_decided():
    groups = [f["group"] for f in rh.fixtures()]
    assert groups.count("sync_free") == 4 and groups.count("sync_required") == 1 and groups.count("info") == 1


def test_all_fixtures_pass_their_rules():
    for f in rh.fixtures():
        rep = dm.check_safety(f["spec"], claims=f.get("claims"), sources=f.get("sources"), card=f["card"])
        assert rep.ok, (f["card"]["id"], codes(rep))
        assert config.DRINKS_MEME_MIN_SEC <= dm.total_ms(f["spec"]) / 1000 <= config.DRINKS_MEME_MAX_SEC


# ── 박자 맞춤: 자동 게시 차단 ──

def test_sync_required_cannot_reach_auto_publish():
    fx = next(f for f in rh.fixtures() if f["group"] == "sync_required")
    gate = dm.publish_gate(fx["spec"])
    assert gate["auto_publish"] is False and gate["next_status"] == "manual_audio" and gate["code"] == "sync_required"
    with pytest.raises(dm.MemeStop) as e:
        dm.assert_auto_publishable(fx["spec"])
    assert e.value.code == "sync_required"


def test_sync_free_goes_to_publish_waiting():
    assert dm.publish_gate(joke())["next_status"] == "publish_waiting"
    dm.assert_auto_publishable(joke())


def test_app_manual_audio_never_auto_publishes_even_if_grade_is_mislabeled():
    s = joke(audio={"mode": "app_manual", "title": "x", "start_hint_sec": 1})
    assert s["sync_grade"] == "sync_free"
    assert dm.publish_gate(s)["auto_publish"] is False
    assert "meme_invalid" in codes(dm.check_safety(s))


def test_sync_required_needs_audio_name_and_start():
    s = joke(sync_grade="sync_required", audio={"mode": "app_manual"})
    assert "meme_sync_blocked" in codes(dm.check_safety(s))


def test_card_that_needs_sync_cannot_be_labeled_free():
    card = {"fields": {"music_sync": {"value": "박자에 맞춰야 함(필수)"}}}
    assert "meme_sync_blocked" in codes(dm.check_safety(joke(), card=card))
    assert dm.card_requires_sync(card) and not dm.card_requires_sync({"fields": {"music_sync": {"value": "무관"}}}) and not dm.card_requires_sync(None)


def test_manual_guide_only_repeats_what_the_spec_says():
    fx = next(f for f in rh.fixtures() if f["group"] == "sync_required")
    guide = dm.manual_audio_guide(fx["spec"])
    assert "(리허설용 가짜 음원)" in guide and "12초 지점" in guide and "3.0초" in guide and "6.0초" in guide and "그냥 포도 맛" in guide


def test_publish_worker_is_not_bridged_without_the_gate():
    """게시 워커에 밈을 연결하는 날 게이트를 빠뜨리지 않게 한다. 지금은 연결돼 있지 않다."""
    pub = (ROOT / "engine" / "drinks_publish.py").read_text(encoding="utf-8")
    if "drink_meme" in pub or "drinks_meme" in pub:
        assert "assert_auto_publishable" in pub
    assert "drink_publication_requests" not in re.sub(r"--.*", "", SQL), "0066 은 게시 요청을 만들지 않는다"


# ── 안전 검사 ──

@pytest.mark.parametrize("text,code", [
    ("오늘은 원샷 가자", "meme_encourages_drinking"), ("한 잔 더 해", "meme_encourages_drinking"), ("같이 마시자", "meme_encourages_drinking"),
    ("고등학생 때 얘기", "meme_minor"), ("교복 입고", "meme_minor"), ("수능 끝난 날", "meme_minor"),
    ("어제 필름 끊겼다", "meme_overdrinking"), ("완전 꽐라", "meme_overdrinking"), ("소주 3병은 기본", "meme_overdrinking"), ("기억이 안 나", "meme_overdrinking"),
    ("음주 운전", "meme_drunk_driving"), ("임산부도", "meme_pregnancy"),
])
def test_unsafe_jokes_are_blocked_anywhere(text, code):
    assert code in codes(dm.check_safety(joke(top_line=text)))
    assert code in codes(dm.check_safety(joke(beats=[{"text": text, "ms": 7000}])))
    assert code in codes(dm.check_safety(joke(caption=text)))


@pytest.mark.parametrize("text", ["가격표만 기억난다", "뭐가 나는지는 모른다", "막걸리 병 앞에서 고민 중", "나도 잘 몰라", "3초 고민"])
def test_plain_jokes_are_not_blocked(text):
    assert dm.check_safety(joke(top_line=text)).ok


# ── 정보 밈: 근거 없으면 멈춤 ──

def _info():
    return next(f for f in rh.fixtures() if f["group"] == "info")


def test_info_meme_without_evidence_stops(tmp_path):
    f = _info()
    bad = {**f["spec"], "claim_ids": []}
    res = dm.produce(bad, str(tmp_path / "o"), card=f["card"])
    assert res.status == "stopped" and res.error_code == "meme_evidence_missing" and not res.files
    assert not (tmp_path / "o" / "final.mp4").exists()


def test_info_claim_must_exist_and_be_a_real_quote():
    f = _info()
    assert "meme_evidence_missing" in codes(dm.check_safety(f["spec"], claims=[], sources=f["sources"]))
    derived = [{"claim_id": "c1", "kind": "calc", "original_quote": "(계산) 10"}]
    assert "derived_claim_cited" in codes(dm.check_safety(f["spec"], claims=derived, sources=f["sources"]))


def test_info_number_must_be_in_the_quote():
    f = _info()
    s = copy.deepcopy(f["spec"])
    s["beats"][0]["text"] = "알코올 20% 이상 음료는"
    assert "number_unsupported" in codes(dm.check_safety(s, claims=f["claims"], sources=f["sources"]))


def test_unmarked_information_is_stopped():
    assert "meme_info_undeclared" in codes(dm.check_safety(joke(top_line="연구에 따르면 소주는")))
    assert "meme_info_undeclared" in codes(dm.check_safety(joke(beats=[{"text": "도수가 40% 라서", "ms": 7000}])))


def test_caption_advice_or_number_is_stopped_like_the_publish_worker():
    assert "advice_unsupported" in codes(dm.check_safety(joke(caption="이렇게 해 보세요")))
    assert "number_unsupported" in codes(dm.check_safety(joke(caption="30년 된 이야기")))


# ── 남의 영상·장면 ──

def test_foreign_media_cannot_enter_the_spec():
    s = joke(scene={"source": "text_bg", "palette": "amber", "ref": "https://www.instagram.com/reel/ABCDE/"})
    assert "meme_foreign_media" in codes(dm.check_safety(s))


def test_scene_asset_must_be_ours(tmp_path):
    p = tmp_path / "c.mp4"
    p.write_bytes(b"x")
    from engine.drinks_render import sha256_file

    ok = dm.SceneAsset(str(p), sha256_file(str(p)), "generated_paid", {"provider": "gemini"})
    dm.validate_scene_asset(ok)
    for bad in (dm.SceneAsset(str(p), ok.sha256, "unknown"), dm.SceneAsset(str(p), ok.sha256, "own", {"source": "https://instagram.com/reel/x"})):
        with pytest.raises(dm.MemeStop) as e:
            dm.validate_scene_asset(bad)
        assert e.value.code == "meme_foreign_media"
    with pytest.raises(dm.MemeStop) as e:
        dm.validate_scene_asset(dm.SceneAsset(str(p), "0" * 64, "own"))
    assert e.value.code == "scene_corrupt"


def test_engine_has_no_download_or_paid_path():
    for banned in ("httpx", "requests", "urllib", "yt_dlp", "apify", "Apify", "providers.video", "providers.image", "drinks_paid", "create_container", "provider_for"):
        assert banned not in SRC, banned
    wf = (ROOT / ".github" / "workflows" / "drinks-meme.yml").read_text(encoding="utf-8")
    for banned in ("cron:", "GEMINI", "ANTHROPIC", "DEEPSEEK", "FB_TOKEN", "APIFY", "--text"):
        assert banned not in wf.split("name: drinks-meme")[1], banned


def test_copying_the_original_text_is_stopped():
    hook = "POV: 와인 고르는 척하는 나"
    assert "meme_copied_text" in codes(dm.check_safety(joke(), hooks=[hook]))


# ── 반응 장면: 경로만, 부르지 않는다 ──

def test_reaction_scene_is_off_and_quoted():
    q = dm.reaction_quote()
    assert q["total_usd"] == pytest.approx(0.443, abs=0.001)
    called = []
    with pytest.raises(dm.MemeStop) as e:
        dm.buy_reaction_scene("p", approval_id="a", buyer=lambda *a, **k: called.append(1))
    assert e.value.code == "paid_disabled" and not called
    assert config.DRINKS_MEME_REACTION_PAID_ENABLED is False


def test_bought_scene_requires_ai_label():
    s = joke(scene={"source": "bought_reaction", "asset_id": "x", "beat": 0})
    assert "meme_ai_label_missing" in codes(dm.check_safety(s))


# ── 모양 ──

@pytest.mark.parametrize("beats", [[{"text": "짧다", "ms": 2000}], [{"text": "길다", "ms": 8000}, {"text": "길다", "ms": 8000}]])
def test_duration_limits(beats):
    assert "meme_duration" in codes(dm.check_safety(joke(beats=beats)))


def test_top_text_must_fit_one_line():
    ly = dm.build_layers(joke(top_line="정말 정말 정말 정말 정말 정말 길어서 절대로 한 줄에 안 들어가는 윗줄 문장입니다 그렇죠"))
    assert ly[0]["overflow"] is True


def test_subtitles_break_on_meaning_units_without_changing_words():
    ly = dm.layout_text("최소 보존 기한을 안 적어도 돼요", config.DRINKS_MEME_BEAT_FULL, center_x=540, y=900, anchor=8)
    assert " ".join(ly["lines"]).replace(" ", "") == "최소보존기한을안적어도돼요" and len(ly["lines"]) >= 1 and not ly["overflow"]


def test_text_stays_in_safe_area_for_all_fixtures():
    for f in rh.fixtures():
        assert dm._text_box_problems(dm.build_layers(f["spec"])) == [], f["card"]["id"]


def test_keyword_is_colored_with_frame_accent():
    ass = dm.build_ass(joke(), dm.build_layers(joke()))
    assert "\\c&H303BFF&" in ass  # #FF3B30 → BGR
    s = joke(frame="full_title", title_keyword="POV")
    assert "\\c&H00E0FF&" in dm.build_ass(s, dm.build_layers(s))


def test_llm_output_is_reduced_to_text_only():
    s = dm.spec_from_llm({"top_line": "제목", "beats": [{"text": "하나", "keyword": "하나", "url": "https://x"}], "caption": "c", "scene": "남의 영상"}, frame="full_title")
    assert s["scene"]["source"] == "text_bg" and "url" not in s["beats"][0] and s["audio"]["mode"] == "ambient_local"
    assert dm.spec_from_llm({"beats": [{"text": "a"}]}, frame="top_text", card={"name": "n", "fields": {"music_sync": {"value": "필수"}}})["sync_grade"] == "sync_required"
    with pytest.raises(dm.MemeStop):
        dm.spec_from_llm({"beats": []}, frame="top_text")


def test_llm_beats_are_fitted_into_the_length_limits():
    short = dm.spec_from_llm({"top_line": "t", "beats": [{"text": "a"}, {"text": "b"}]}, frame="top_text")
    assert dm.total_ms(short) == 6000
    long = dm.spec_from_llm({"top_line": "t", "beats": [{"text": "가" * 40} for _ in range(4)]}, frame="top_text")
    assert dm.total_ms(long) == 15000 and not [f for f in dm.validate_spec(long) if f.code == "meme_duration"]
    fixed = dm.spec_from_llm({"top_line": "t", "beats": [{"text": "a"}, {"text": "b"}]}, frame="top_text", card={"fields": {"cut_lengths": {"value": "4,3"}}})
    assert [b["ms"] for b in fixed["beats"]] == [4000, 3000]


def test_card_beat_ms_reads_only_plain_numbers():
    assert dm.card_beat_ms({"fields": {"cut_lengths": {"value": "3, 2.5"}}}) == [3000, 2500]
    assert dm.card_beat_ms({"fields": {"cut_lengths": {"value": "대략 빠르게"}}}) == []


# ── 글 초안 LLM: 가짜 응답 · 결재 안에서만 ──

class FakeRpc:
    def __init__(self, hold_error=None):
        self.calls, self.hold_error = [], hold_error

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        if fn == "drinks_meme_hold":
            if self.hold_error:
                raise DbError(self.hold_error, "막힘")
            return {"hold_id": "h1"}
        return {"status": p.get("outcome", "ok")}

    def names(self):
        return [c[0] for c in self.calls]


JOB = {"draft_id": "d1", "lease_token": "t1", "frame": "top_text", "card": {"name": "라벨", "structure": "pov", "fields": {"caption_hook": {"value": "원본 문장입니다 그대로"}}}, "topic": None}
GOOD = {"top_line": "라벨 앞에서 작아지는 나", "beats": [{"text": "앞면을 본다"}, {"text": "뒷면도 본다"}, {"text": "모르겠다", "keyword": "모르겠다"}], "caption": "저만 그런가요"}


def test_text_path_holds_then_settles_and_saves_as_draft_only():
    rpc = FakeRpc()
    res = dm.write_text(JOB, rpc, call=lambda s, u: GOOD)
    assert rpc.names() == ["drinks_meme_hold", "drinks_develop_settle", "drinks_meme_finish_text"]
    final = rpc.calls[-1][1]
    assert final["outcome"] == "ok" and final["spec"]["top_line"] == GOOD["top_line"] and res["status"] == "ok"
    assert not any("approve" in n for n in rpc.names())


def test_text_path_does_not_call_the_model_without_a_hold():
    called = []
    rpc = FakeRpc(hold_error="budget_exceeded")
    with pytest.raises(DbError):
        dm.write_text(JOB, rpc, call=lambda s, u: called.append(1) or GOOD)
    assert not called


def test_text_path_retries_once_then_stops_on_unsafe_text():
    calls = []

    def fake(s, u):
        calls.append(u)
        return {**GOOD, "top_line": "오늘은 원샷"}

    rpc = FakeRpc()
    dm.write_text(JOB, rpc, call=fake)
    assert len(calls) == 2 and "meme_encourages_drinking" in calls[1]
    assert rpc.calls[-1][1]["outcome"] == "stopped" and rpc.calls[-1][1]["error_code"] == "meme_encourages_drinking"
    assert rpc.names().count("drinks_meme_hold") == 2


def test_text_prompt_has_no_media_address():
    p = dm.text_prompt({"name": "n", "fields": {"caption_hook": {"value": "훅"}}, "permalink": "https://www.instagram.com/reel/x"}, None)
    assert "instagram" not in p


# ── 워커 ──

class MemStore:
    def __init__(self):
        self.keys = {}

    def put(self, path, key, mime):
        assert key.startswith("drinks/memes/")
        self.keys[key] = mime
        return key


@needs_ffmpeg
@pytest.mark.parametrize("group,outcome", [("sync_free", "rendered"), ("sync_required", "rendered")])
def test_worker_renders_and_lets_db_decide(group, outcome):
    fx = next(f for f in rh.fixtures() if f["group"] == group)
    rpc, store = FakeRpc(), MemStore()
    job = {"draft_id": "d1", "lease_token": "abcdef12-x", "spec": fx["spec"], "card": fx["card"], "hooks": [], "claims": [], "sources": []}
    dm.process_render_job(job, rpc, store)
    fn, p = rpc.calls[-1]
    assert fn == "drinks_meme_finish" and p["outcome"] == outcome
    assert "status" not in p and "next_status" not in p, "어디로 갈지는 DB 가 정한다"
    assert {f["role"] for f in p["files"]} >= {"final_video", "cover"}
    assert (p["guide"] is not None) == (group == "sync_required")
    assert all(k.startswith("drinks/memes/d1/abcdef12/") for k in store.keys)


def test_worker_stops_unsafe_before_rendering():
    rpc, store = FakeRpc(), MemStore()
    job = {"draft_id": "d1", "lease_token": "t", "spec": joke(top_line="오늘은 원샷")}
    dm.process_render_job(job, rpc, store)
    assert rpc.calls[-1][1]["outcome"] == "stopped" and not store.keys


# ── 렌더 ──

@needs_ffmpeg
def test_render_measures_out_as_a_valid_reel(tmp_path):
    fx = next(f for f in rh.fixtures() if f["card"]["id"] == "fake-02")
    res = dm.produce(fx["spec"], str(tmp_path / "o"), card=fx["card"])
    assert res.status == "publish_waiting", res.error_message
    p = res.qa["probe"]
    assert (p["width"], p["height"]) == (1080, 1920) and p["video_codec"] == "h264" and p["audio_codec"] == "aac" and p["audio_sample_rate"] == 48000
    assert p["duration_sec"] == pytest.approx(10.5, abs=0.1)
    assert res.qa["moov_first"] is True and res.qa["blocks"] == []
    assert res.qa["mean_volume_db"] > -40, "분위기 음원이 들어 있어야 한다"


@needs_ffmpeg
def test_no_audio_mode_is_silent_track(tmp_path):
    res = dm.produce(joke(audio={"mode": "none"}), str(tmp_path / "o"))
    assert res.status == "publish_waiting" and res.qa["mean_volume_db"] < -60 and res.qa["probe"]["audio_streams"] == 1


@needs_ffmpeg
def test_missing_glyph_stops_instead_of_tofu(tmp_path):
    res = dm.produce(joke(top_line="술 🍶 마실까"), str(tmp_path / "o"))
    assert res.status == "stopped" and res.error_code == "glyph_missing"


@needs_ffmpeg
def test_bought_scene_path_renders_with_own_clip_and_drops_its_sound(tmp_path):
    """산 장면 자리: ffmpeg 시험 영상을 '우리 파일'로 넣는다. 공급자를 부르지 않는다."""
    clip = tmp_path / "own.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=24:d=4", "-f", "lavfi", "-i", "sine=frequency=880:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)], check=True)
    from engine.drinks_render import sha256_file

    asset = dm.SceneAsset(str(clip), sha256_file(str(clip)), "own", {"provider": "test"})
    s = joke(scene={"source": "bought_reaction", "asset_id": "a1", "beat": 1, "palette": "wine"}, caption="AI 생성 영상", audio={"mode": "none"})
    res = dm.produce(s, str(tmp_path / "o"), scene_asset=asset)
    assert res.status == "publish_waiting", res.error_message
    assert res.qa["mean_volume_db"] < -60, "산 장면의 소리는 버린다"
    with_missing = dm.produce(s, str(tmp_path / "o2"))
    assert with_missing.status == "stopped" and with_missing.error_code == "scene_missing"


# ── 값 대조 (config ↔ SQL ↔ TS) ──

def test_rules_match_sql():
    for code, label, pattern in config.DRINKS_MEME_UNSAFE_RULES:
        assert f"('{code}', '{label}', '{pattern}')" in SQL, code
    assert f"'{config.DRINKS_MEME_INFO_PATTERN}'" in SQL
    assert f"'{config.DRINKS_MEME_FOREIGN_MEDIA_PATTERN}'" in SQL
    assert f"'{config.DRINKS_MEME_SYNC_REQUIRED_PATTERN}'" in SQL
    limits = re.search(r"drinks_meme_limits\(\).*?jsonb_build_object\((.*?)\)\n\$\$", SQL, re.S).group(1)
    for key, want in (("'min_ms', 6000", config.DRINKS_MEME_MIN_SEC * 1000 == 6000), ("'max_ms', 15000", config.DRINKS_MEME_MAX_SEC * 1000 == 15000),
                      (f"'beat_min_ms', {config.DRINKS_MEME_BEAT_MIN_MS}", True), (f"'beat_max_ms', {config.DRINKS_MEME_BEAT_MAX_MS}", True),
                      (f"'max_beats', {config.DRINKS_MEME_MAX_BEATS}", True), (f"'text_max_chars', {config.DRINKS_MEME_TEXT_MAX_CHARS}", True),
                      (f"'text_max_usd_per_draft', {config.DRINKS_MEME_TEXT_MAX_USD_PER_DRAFT}", True),
                      (f"'text_max_calls_per_draft', {config.DRINKS_MEME_TEXT_MAX_CALLS_PER_DRAFT}", True)):
        assert want and key in limits, key
    for r in config.DRINKS_MEME_SCENE_RIGHTS:
        assert f"'{r}'" in SQL


def test_values_match_ts():
    assert f"MEME_MIN_SEC = {config.DRINKS_MEME_MIN_SEC:g}" in TS and f"MEME_MAX_SEC = {config.DRINKS_MEME_MAX_SEC:g}" in TS
    assert f"MEME_BEAT_MS_PER_CHAR = {config.DRINKS_MEME_BEAT_MS_PER_CHAR}" in TS and f"MEME_BEAT_FLOOR_MS = {config.DRINKS_MEME_BEAT_FLOOR_MS}" in TS
    assert f"MEME_BEAT_MAX_MS = {config.DRINKS_MEME_BEAT_MAX_MS}" in TS
    palettes = json.loads("[" + re.search(r"MEME_PALETTES = \[(.*?)\]", TS).group(1) + "]")
    assert set(palettes) == set(config.DRINKS_MEME_PALETTES)


def test_migration_is_additive_and_guards_the_gate():
    assert "drink_meme_sync_gate_ck check (status <> 'publish_waiting' or sync_grade = 'sync_free')" in SQL
    assert "운영 적용은 따로" in SQL and "되돌리기" in SQL
    # 워커 함수는 승인을 부르지 않는다
    for fn in ("drinks_meme_claim", "drinks_meme_finish", "drinks_meme_finish_text", "drinks_meme_hold"):
        body = re.search(rf"function {fn}\(p jsonb\).*?end \$\$;", SQL, re.S).group(0)
        assert "'approve'" not in body and "drinks_meme_draft_action" not in body
