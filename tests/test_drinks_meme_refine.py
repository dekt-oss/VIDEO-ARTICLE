"""밈 틀 정밀화(Apify B + 영상 분석, 0070) — 돈·남의 영상·저장 범위를 코드로 못박는다. 네트워크·Apify·모델 호출 0(전부 가짜)."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import pytest

from engine import config
from engine import drinks_meme as dm
from engine import drinks_meme_refine as rf

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0070_drinks_apify_refine.sql").read_text(encoding="utf-8")
SRC = (ROOT / "engine" / "drinks_meme_refine.py").read_text(encoding="utf-8")
WF = (ROOT / ".github" / "workflows" / "drinks-apify.yml").read_text(encoding="utf-8")
ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg 없음")

URLS = ["https://www.instagram.com/reel/AAAAAAAA1/", "https://www.instagram.com/reel/AAAAAAAA2/", "https://www.instagram.com/reel/AAAAAAAA3/"]


def job(**kw):
    return {"request_id": "r1", "lease_token": "l1", "kind": "meme_refine", "cap_usd": config.DRINKS_APIFY_RUN_CAP_USD["meme_refine"],
            "card": {"id": "c1", "name": "x", "fields": {}}, "reels": [{"media_id": f"m{i}", "permalink": u, "view_count": 10 - i} for i, u in enumerate(URLS)], **kw}


# ── 돈: 실행 상한·월 상한·단가는 config = SQL ──

def test_three_reels_fit_the_click_cap():
    assert rf.estimate_usd(3) <= config.DRINKS_APIFY_RUN_CAP_USD["meme_refine"], "릴스 3개 + 분석 3편이 [쓰자] 1회 상한 $0.02 안이어야 한다"
    assert rf.estimate_usd(3, analyze=False) == pytest.approx(3 * 0.0026 + 0.001)
    rf.run_cap_check(job(), 3)
    with pytest.raises(rf.RefineStop) as e:
        rf.run_cap_check(job(cap_usd=0.005), 3)
    assert e.value.code == "run_cap_exceeded"


def test_limits_match_sql():
    m = re.search(r"drinks_apify_limits\(\).*?select jsonb_build_object\((.*?)\)\s*\$\$", SQL, re.S)
    assert m
    body = m.group(1)
    assert f"'month_cap_usd', {config.DRINKS_APIFY_MONTH_CAP_USD:.2f}" in body
    for k, v in config.DRINKS_APIFY_RUN_CAP_USD.items():
        assert f"'{k}', {v:.2f}" in body, k
    assert f"'max_reels', {config.DRINKS_APIFY_MAX_REELS_PER_RUN}" in body
    assert f"'reel_usd', {config.DRINKS_APIFY_REEL_USD}" in body and f"'start_usd', {config.DRINKS_APIFY_START_USD}" in body
    assert f"'analysis_est_usd', {config.DRINKS_APIFY_ANALYSIS_EST_USD}" in body
    assert f"'lease_sec', {config.DRINKS_APIFY_LEASE_SEC}" in body


def test_plan_inputs_only_official_instagram_urls_up_to_cap():
    j = job(reels=[{"permalink": "https://evil.example/x"}, {"permalink": URLS[0]}, {"permalink": URLS[0]}, {"permalink": URLS[1]}, {"permalink": URLS[2]},
                   {"permalink": "https://www.instagram.com/reel/EXTRA0001/"}])
    assert rf.plan_inputs(j) == URLS, "인스타 주소만, 중복 없이, 상한 3개"
    assert rf.plan_inputs(job(reels=[])) == []


# ── 저장 범위: 주소는 떨어지고 상태는 남는다 ──

def test_result_rows_drop_video_urls_and_keep_failures_visible():
    items = [
        {"inputUrl": URLS[0], "videoDuration": 12.3, "videoPlayCount": 100, "videoUrl": "https://scontent.cdninstagram.com/v/x.mp4",
         "audioUrl": "https://x.fbcdn.net/a.m4a", "musicInfo": {"audio_id": "77", "uses_original_audio": True}, "timestamp": "2026-10-30T00:00:00.000Z"},
        {"inputUrl": URLS[1], "error": "age-restricted"},
    ]
    rows = rf.result_rows(items, URLS)
    assert [r["status"] for r in rows] == ["ok", "age_restricted", "failed"], "응답에 없는 주소는 failed — 0건으로 바꾸지 않는다"
    assert rows[0] == {"input_url": URLS[0], "status": "ok", "duration_sec": 12.3, "play_count": 100, "audio_id": "77", "uses_original_audio": True,
                       "posted_at": "2026-10-30T00:00:00.000Z", "has_video": True}
    assert set(rows[0]) == set(rf.RESULT_KEYS)
    rf.assert_no_media_url(rows)
    with pytest.raises(rf.RefineStop) as e:
        rf.assert_no_media_url({"results": rows, "analysis": {"x": "https://scontent.cdninstagram.com/v/x.mp4"}})
    assert e.value.code == "media_url_rejected"


def test_sql_rejects_media_urls_and_grants_nothing_public():
    low = SQL.lower()
    assert "drink_apify_no_media_url_ck" in low and "cdninstagram" in low and "videourl" in low
    assert "media_url_rejected" in SQL
    assert not re.search(r"grant[^;]*to[^;]*\b(anon|authenticated|public)\b", low)
    assert "create policy" not in low
    assert "alter table drink_apify_requests enable row level security" in low
    assert "apify_budget_exhausted" in SQL and "drinks_apify_month_spent" in SQL
    code = re.sub(r"^--.*$", "", SQL, flags=re.M)
    assert "drink_ig_trend_runs" not in code, "T4 는 정상 관측일 표에 적지 않는다"
    assert "drink_publication_requests" not in code and "drinks_meme_draft_action" not in code, "정밀화는 게시·승인을 만들지 않는다"
    assert "evidence <> 'operator'" in SQL, "운영자가 넣은 칸은 덮지 않는다"
    assert "drinks_text(it, 'evidence') <> 'video'" in SQL, "정밀화는 영상 근거로만 칸을 채운다"


# ── 모델 답은 걸러 쓴다(§6-5 근거 없는 필드 생성률 0%) ──

def test_fields_from_analysis_keeps_only_allowed_vocabulary():
    measured = {"duration_sec": 11.5, "cut_lengths": [3.0, 3.2, 5.3], "beat_count": 3, "bytes": 1}
    ans = {"twist_at_sec": 99, "structure": "montage", "music_sync": "maybe", "cover_text": "https://x.cdninstagram.com/a", "first_1_5s": "", "frame": "weird"}
    fields = rf.fields_from_analysis(measured, ans)
    assert [f["field"] for f in fields] == ["beat_count", "cut_lengths"], "허용 어휘 밖·범위 밖·주소는 칸을 만들지 않는다"
    assert all(f["evidence"] == "video" and f["confidence"] == "high" for f in fields)
    good = rf.fields_from_analysis(measured, {"twist_at_sec": 6.2, "structure": "pov", "music_sync": "required", "cover_text": "POV", "first_1_5s": "손이 병을 든다"})
    by = {f["field"]: f for f in good}
    assert by["twist_at"]["value"] == "6.2초" and by["twist_at"]["confidence"] == "low"
    assert re.search(config.DRINKS_MEME_SYNC_REQUIRED_PATTERN, by["music_sync"]["value"]), "모델이 required 라 하면 밈 엔진의 박자 맞춤 판정에 걸리는 말로 적는다"
    assert dm.card_requires_sync({"fields": {"music_sync": {"value": by["music_sync"]["value"]}}})
    assert dm.card_beat_ms({"fields": {"cut_lengths": {"value": by["cut_lengths"]["value"]}}}) == [3000, 3200, 5300]
    assert set(f["field"] for f in good) <= set(rf.VIDEO_FIELDS) | {"structure", "cover_text"}
    assert rf.fields_from_analysis(measured, None) == fields, "모델이 없으면 ffmpeg 측정만"


def test_frame_summary_rejects_unknown_words():
    assert rf.frame_summary({"frame": "top_text", "text_position": "top", "notes": "n"}) == {"frame": "top_text", "text_position": "top", "notes": "n"}
    assert rf.frame_summary({"frame": "x", "text_position": "y"}) == {"frame": None, "text_position": None, "notes": None}


def test_analysis_prompt_asks_format_only():
    assert "사실" in rf.ANALYSIS_SYSTEM and "추측하지 않는다" in rf.ANALYSIS_SYSTEM
    p = rf.analysis_prompt(11.5, [3.0, 3.2, 5.3])
    assert "11.5초" in p and "[3.0, 3.2, 5.3]" in p


# ── 파일 수명(§6-7) ──

def test_borrowed_videos_are_deleted_and_old_tmp_is_swept(tmp_path):
    old = tmp_path / f"{rf.TMP_PREFIX}old"
    old.mkdir()
    (old / "a.mp4").write_bytes(b"x")
    os.utime(old, (time.time() - 30 * 3600, time.time() - 30 * 3600))
    fresh = tmp_path / f"{rf.TMP_PREFIX}fresh"
    fresh.mkdir()
    gone = rf.sweep_old_tmp(str(tmp_path))
    assert gone == [str(old)] and not old.exists() and fresh.exists()
    with rf.BorrowedVideos(str(tmp_path)) as box:
        p = Path(box.path) / "reel0.mp4"
        p.write_bytes(b"video")
        assert p.exists()
    assert box.deleted and not Path(box.path).exists()


def _code(src: str) -> str:
    """주석·머리말 문서를 뺀 코드만(설명 문장의 낱말까지 걸리지 않게)."""
    body = src.split('"""', 2)[2] if src.startswith('"""') else src
    return "\n".join(l.split("#", 1)[0] for l in body.splitlines())


def test_module_never_stores_or_publishes_and_has_no_cron():
    code = _code(SRC)
    for bad in ("Storage", "storage.put", ".upload(", "drinks/memes", "create_container", "provider_for", "drinks_paid", "SOOLJJERIGO"):
        assert bad not in code, bad
    assert "maxTotalChargeUsd" in code and "Authorization" in code
    assert "print(" not in code.split("def main")[0], "토큰·주소가 찍힐 수 있는 출력은 워커 본체에 없다"
    meme_src = (ROOT / "engine" / "drinks_meme.py").read_text(encoding="utf-8")
    assert "drinks_meme_refine" not in meme_src, "제작 엔진은 정밀화 모듈을 import 하지 않는다(tests/test_drinks_meme.py 의 apify 금지가 그대로 산다)"
    body = WF.split("name: drinks-apify")[1]
    assert "workflow_dispatch" in body and "cron:" not in body and "schedule:" not in body
    assert "APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}" in WF and "--yes" in WF
    for bad in ("FB_TOKEN", "DRINKS_STORAGE", "DRINKS_IG_LIVE", "ANTHROPIC", "DEEPSEEK"):
        assert bad not in body, bad
    collect = (ROOT / ".github" / "workflows" / "drinks-collect.yml").read_text(encoding="utf-8")
    for use in re.findall(r"uses:\s*(\S+)", WF):
        assert use in collect, f"{use}: drinks-collect 와 같은 고정 SHA"


def test_cli_without_yes_calls_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(rf, "run_queue", lambda *a, **k: called.append(1))
    monkeypatch.setattr("engine.drinks_collect.supabase_rpc", lambda: (lambda *a, **k: called.append(2)))
    assert rf.main([]) == 0
    assert called == []


# ── 흐름: 가짜 Apify + 가짜 분석 → DB 끝내기 호출 모양 ──

class Rpc:
    def __init__(self):
        self.calls = []

    def __call__(self, fn, p):
        self.calls.append((fn, p))
        return {"status": p.get("outcome"), "precision": "precise"}


def test_no_reels_stops_without_spending():
    r = Rpc()
    res = rf.process_job(job(reels=[]), r, provider=rf.FakeApify(items=[]), analyzer=rf.no_analyzer)
    fn, p = r.calls[-1]
    assert fn == "drinks_apify_finish" and p["outcome"] == "stopped" and p["error_code"] == "no_reels" and p["actual_usd"] == 0.0


def test_all_restricted_is_failed_but_billed():
    prov = rf.FakeApify(items=[{"inputUrl": u, "error": "age-restricted"} for u in URLS], usage_usd=0.0088)
    r = Rpc()
    rf.process_job(job(), r, provider=prov, analyzer=rf.no_analyzer)
    p = r.calls[-1][1]
    assert p["outcome"] == "failed" and p["error_code"] == "age_restricted" and p["actual_usd"] == pytest.approx(0.0088)
    assert [x["status"] for x in p["results"]] == ["age_restricted"] * 3 and p["fields"] == []
    # 리뷰 R2(의도한 변경): Apify 에는 상한 전체가 아니라 분석 예약액을 뺀 몫만 준다.
    assert prov.calls[0]["cap_usd"] == pytest.approx(rf.split_budget(config.DRINKS_APIFY_RUN_CAP_USD["meme_refine"], 3)["apify_cap_usd"])


def test_unknown_usage_is_recorded_as_the_apify_cap_not_estimate():
    """리뷰 R2(의도한 변경): 사용액을 못 읽으면 예상액($0.0088)이 아니라 Apify 에 건 상한으로 적는다 — 작게 적지 않는다."""
    prov = rf.FakeApify(items=[{"inputUrl": u, "error": "x"} for u in URLS], usage_usd=None)
    r = Rpc()
    rf.process_job(job(), r, provider=prov, analyzer=rf.no_analyzer)
    assert r.calls[-1][1]["actual_usd"] == pytest.approx(prov.calls[0]["cap_usd"])
    assert r.calls[-1][1]["actual_usd"] >= rf.estimate_usd(3, analyze=False)


def test_worker_exception_closes_the_request_as_failed():
    class Boom:
        def run_reels(self, *a, **k):
            raise RuntimeError("x")

    r = Rpc()
    rf.process_job(job(), r, provider=Boom(), analyzer=rf.no_analyzer)
    assert r.calls[-1][1]["outcome"] == "failed" and r.calls[-1][1]["error_code"] == "worker_error"


@ffmpeg
def test_rehearsal_runs_end_to_end_and_shares_the_meme_engine_path(tmp_path):
    from scripts import meme_refine_rehearsal as reh

    report = reh.run(tmp_path / "out")
    assert all(report["checks"].values()), report["checks"]
    assert report["produce"]["status"] == "publish_waiting"
    assert report["tripwire_hits"] == []
    # 같은 코드 경로: 두 리허설과 워커가 전부 drinks_meme.produce 를 부른다.
    for f in ("scripts/meme_rehearsal.py", "scripts/meme_refine_rehearsal.py"):
        assert "dm.produce(" in (ROOT / f).read_text(encoding="utf-8"), f
    worker = (ROOT / "engine" / "drinks_meme.py").read_text(encoding="utf-8")
    assert "res = produce(spec," in worker
    assert not list((tmp_path / "out").glob("_tmp*")) and not list((tmp_path / "out").glob("_fake_videos*")), "빌린 영상·임시 폴더가 남지 않는다"
    saved = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert "cdninstagram" not in json.dumps(saved) and saved["cost_usd"] == 0



# ── 리뷰 R2(2026-11-04): Apify + 분석 합산 상한을 호출 전에 강제한다 ──

def _ok_items():
    return [{"inputUrl": u, "videoUrl": f"/fake/{i}.mp4", "videoDuration": 12.0, "videoPlayCount": 100 - i} for i, u in enumerate(URLS)]


class _Prov(rf.FakeApify):
    def download(self, url, dest, *, max_bytes):
        Path(dest).write_bytes(b"\0" * 64)
        return 64


@pytest.fixture
def fake_measure(monkeypatch):
    monkeypatch.setattr(rf, "measure_video", lambda p: {"duration_sec": 12.0, "cut_lengths": [3.0, 4.0, 5.0], "beat_count": 3, "bytes": 64})


class Counting:
    def __init__(self, usd=0.003, exc=None):
        self.n, self.usd, self.exc = 0, usd, exc

    def __call__(self, path, duration, cuts):
        self.n += 1
        if self.exc:
            raise self.exc
        return {"frame": "selfie", "text_position": "top"}, self.usd


def test_budget_is_split_before_any_call():
    b = rf.split_budget(0.02, 3)
    assert b["analysis_reserve_usd"] == pytest.approx(3 * config.DRINKS_APIFY_ANALYSIS_EST_USD)
    assert b["apify_cap_usd"] + b["analysis_reserve_usd"] <= 0.02 + 1e-9


def test_apify_using_the_whole_cap_means_zero_analysis_calls(fake_measure):
    """재현(리뷰 R2): Apify 실제액이 상한 $0.02 를 다 쓰면 분석은 한 번도 부르지 않는다. 예전엔 $0.023 이 done 이었다."""
    an = Counting()
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.020), analyzer=an)
    p = r.calls[-1][1]
    assert an.n == 0
    assert p["actual_usd"] == pytest.approx(0.020)
    assert all(v.get("skip") == "budget_exhausted" for v in p["analysis"]["per_video"])


def test_overspend_reported_by_provider_is_recorded_not_hidden(fake_measure):
    an = Counting()
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.025), analyzer=an)
    p = r.calls[-1][1]
    assert an.n == 0 and p["actual_usd"] == pytest.approx(0.025)
    assert p["analysis"]["over_cap_usd"] == pytest.approx(0.005)


def test_no_new_call_when_confirmed_plus_reserve_would_cross_the_cap(fake_measure):
    """새 호출은 '확정액 + 분석 1편 예약액 ≤ 승인액'일 때만. 예상보다 비싸게 나온 분석이 쌓이면 다음 분석을 부르지 않는다."""
    reserve = config.DRINKS_APIFY_ANALYSIS_EST_USD
    seen = []

    class Spy(Counting):
        def __call__(self, *a):
            seen.append(round(0.0088 + self.usd * self.n, 4))   # 이 호출 직전의 확정액
            return super().__call__(*a)
    an = Spy(usd=0.0055)
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.0088), analyzer=an)
    p = r.calls[-1][1]
    assert all(before + reserve <= 0.02 + 1e-9 for before in seen), seen
    assert an.n == 2 and p["analysis"]["per_video"][2]["skip"] == "budget_exhausted"
    assert p["actual_usd"] == pytest.approx(0.0088 + 2 * 0.0055)


def test_overrun_of_the_last_allowed_call_is_recorded_with_a_warning(fake_measure):
    """한계(정직하게): 분석 1편 금액에는 공급자 쪽 하드 상한이 없다. 허용된 마지막 호출이 예약액보다 비싸면 그 차이만큼 넘을 수 있고,
    그 금액은 숨기지 않고 over_cap_usd 로 남는다."""
    an = Counting(usd=0.004)
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.0088), analyzer=an)
    p = r.calls[-1][1]
    assert an.n == 3 and p["actual_usd"] == pytest.approx(0.0208)
    assert p["analysis"]["over_cap_usd"] == pytest.approx(0.0008)


@pytest.mark.parametrize("exc", [TimeoutError("응답 늦음"), rf.RefineStop("analysis_unavailable", "503")])
def test_analysis_failure_counts_the_reserve_and_stops_paid_analysis(fake_measure, exc):
    an = Counting(exc=exc)
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.0088), analyzer=an)
    p = r.calls[-1][1]
    assert an.n == 1, "결과를 모르는 분석 뒤에는 유료 분석을 더 부르지 않는다"
    assert p["actual_usd"] == pytest.approx(0.0088 + config.DRINKS_APIFY_ANALYSIS_EST_USD), "0원으로 줄이지 않는다"
    assert [v.get("skip") for v in p["analysis"]["per_video"]] == ["analysis_unknown"] * 3


def test_missing_analysis_usage_is_recorded_as_the_reserve(fake_measure):
    an = Counting(usd=None)
    r = Rpc()
    rf.process_job(job(), r, provider=_Prov(items=_ok_items(), usage_usd=0.0088), analyzer=an)
    assert r.calls[-1][1]["actual_usd"] == pytest.approx(0.0088 + 3 * config.DRINKS_APIFY_ANALYSIS_EST_USD)


def test_gemini_analyzer_without_usage_returns_unknown(monkeypatch):
    monkeypatch.setattr(rf, "gemini_video_json", lambda *a, **k: ({"frame": "selfie"}, {}))
    assert rf.gemini_analyzer("x", 1.0, [])[1] is None


# ── 리뷰 R8(2026-11-04): 남의 영상 삭제 실패를 성공으로 적지 않는다 ──

def _old(tmp_path, name):
    d = tmp_path / f"{rf.TMP_PREFIX}{name}"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"x")
    os.utime(d, (time.time() - 30 * 3600, time.time() - 30 * 3600))
    return d


def test_sweep_reports_a_folder_it_could_not_delete(tmp_path, monkeypatch):
    stuck = _old(tmp_path, "stuck")
    monkeypatch.setattr(rf.shutil, "rmtree", lambda p, **k: None)   # 지우기가 아무 일도 못 하게(권한 오류 흉내)
    res = rf.sweep_tmp(str(tmp_path))
    assert res == {"deleted": [], "failed": [str(stuck)]} and stuck.exists()
    assert rf.sweep_old_tmp(str(tmp_path)) == [], "남은 폴더를 지운 것으로 돌려주지 않는다"


def test_borrowed_videos_reports_failed_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(rf.shutil, "rmtree", lambda p, **k: None)
    with rf.BorrowedVideos(str(tmp_path)) as box:
        (Path(box.path) / "reel0.mp4").write_bytes(b"v")
    assert box.deleted is False and Path(box.path).exists()


@pytest.mark.parametrize("where", ["analysis", "download"])
def test_failure_mid_run_still_deletes_and_reports(tmp_path, fake_measure, where):
    class Breaks(_Prov):
        def download(self, url, dest, *, max_bytes):
            if where == "download":
                Path(dest).write_bytes(b"half")
                raise rf.RefineStop("download_failed", "중간에 끊김")
            return super().download(url, dest, max_bytes=max_bytes)
    an = Counting(exc=RuntimeError("분석 예외")) if where == "analysis" else Counting()
    r = Rpc()
    rf.process_job(job(), r, provider=Breaks(items=_ok_items(), usage_usd=0.0088), analyzer=an, tmp_root=str(tmp_path))
    p = r.calls[-1][1]
    assert p["analysis"]["deleted"] is True and p["analysis"]["tmp_leftovers"] == 0
    assert list(tmp_path.glob(f"{rf.TMP_PREFIX}*")) == []


def test_leftover_from_a_killed_run_is_cleaned_by_the_next_start_and_the_clean_command(tmp_path, monkeypatch, capsys):
    _old(tmp_path, "killed")
    monkeypatch.setattr(rf.tempfile, "gettempdir", lambda: str(tmp_path))
    fresh = tmp_path / f"{rf.TMP_PREFIX}fresh"
    fresh.mkdir()
    assert rf.main(["--clean-tmp"]) == 0, "나이와 상관없이 지운다"
    assert list(tmp_path.glob(f"{rf.TMP_PREFIX}*")) == []
    assert "남음 0개" in capsys.readouterr().out


def test_workflow_cleans_borrowed_videos_even_when_refine_fails():
    assert "--clean-tmp" in WF and "if: always()" in WF


def test_borrowed_videos_never_live_in_the_repo_or_storage():
    """임시 폴더는 시스템 임시 디렉터리 아래다. 저장소(Storage.put)·Git 경로로 가는 코드가 없다."""
    with rf.BorrowedVideos() as box:
        assert not Path(box.path).resolve().is_relative_to(ROOT)
    code = _code(SRC)
    assert "storage.put" not in code and ".put(" not in code
