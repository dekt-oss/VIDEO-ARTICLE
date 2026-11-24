"""술째리고 유튜브 쇼츠 계정(0090) + 영어 논문 라인 일시 중지(2026-11-24)."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import config, publish
from engine.providers import drinks_youtube as dy
from engine.providers.instagram import PublishError, provider_for

ROOT = Path(__file__).resolve().parents[1]
YT_ACCOUNT = {"account_id": "a1", "connection": "google_oauth", "external_account_id": "UCU9XJcPFQtGXZAENFOMS7QQ",
              "credential_ref": "YOUTUBE_REFRESH_TOKEN_EN"}


def test_title_is_first_non_hashtag_line_without_angle_brackets():
    assert dy.video_title("\n#술 #위스키\n위스키는 <왜> 안 상할까\n본문") == "위스키는 왜 안 상할까"
    assert dy.video_title("#해시태그만") == config.DRINKS_YT_FALLBACK_TITLE
    assert len(dy.video_title("가" * 300)) == config.YOUTUBE_TITLE_MAX


def test_provider_for_youtube_needs_live_switch(monkeypatch):
    monkeypatch.delenv("DRINKS_YT_LIVE", raising=False)
    with pytest.raises(PublishError) as e:
        provider_for(YT_ACCOUNT)
    assert e.value.code == "provider_disabled"
    monkeypatch.setenv("DRINKS_YT_LIVE", "1")
    assert isinstance(provider_for(YT_ACCOUNT), dy.DrinksYouTube)


class _Guarded(dy.DrinksYouTube):
    def __init__(self, channel_id: str):
        super().__init__()
        self._cid = channel_id

    def verify(self, account):   # 네트워크 없이 채널 확인 결과만 바꿔 끼운다
        return {"id": self._cid, "username": "x"}


def test_channel_guard_runs_before_publish_and_only_reels(monkeypatch):
    monkeypatch.setattr(dy, "_download", lambda url, dest: open(dest, "wb").close())
    ok = _Guarded(YT_ACCOUNT["external_account_id"])
    cid = ok.create_container(YT_ACCOUNT, kind="reel", url="https://x/v.mp4", caption="c")
    assert ok.container_status(YT_ACCOUNT, cid) == "FINISHED"
    with pytest.raises(PublishError) as e:
        ok.create_container(YT_ACCOUNT, kind="carousel", children=["a"])
    assert e.value.code == "unsupported_post_type"
    with pytest.raises(PublishError) as e:
        _Guarded("UC_other").create_container(YT_ACCOUNT, kind="reel", url="https://x/v.mp4", caption="c")
    assert e.value.code == "provider_mismatch"   # 게시 호출 전 → paused, 다른 채널로 올라가지 않는다


def test_reconcile_never_guesses_and_audio_is_refused():
    p = dy.DrinksYouTube()
    assert p.find_published(YT_ACCOUNT, ["yt-1"], "c") == ("unknown", None)
    with pytest.raises(PublishError):
        p.check_audio(YT_ACCOUNT, "123")


def test_english_paper_upload_is_refused(monkeypatch):
    monkeypatch.setattr(publish.db, "get_render_job", lambda _id: {"status": "done", "output_url": "https://x", "lang": "en"})
    with pytest.raises(ValueError, match="일시 중지"):
        publish.process_upload({"id": "r1", "render_job_id": "j1", "lang": "en"})


def test_paused_langs_match_web_table():
    web = (ROOT / "web/lib/langPause.ts").read_text(encoding="utf-8")
    assert all(f'"{lg}"' in web.split("PAUSED_LANGS")[1].split(";")[0] for lg in config.YOUTUBE_PAUSED_LANGS)


def test_migration_ties_youtube_platform_to_google_oauth():
    sql = (ROOT / "supabase/migrations/0090_drinks_youtube_account.sql").read_text(encoding="utf-8")
    assert "(platform = 'youtube') = (connection = 'google_oauth')" in sql


def test_drinks_publish_workflow_carries_youtube_secrets():
    wf = (ROOT / ".github/workflows/drinks-publish.yml").read_text(encoding="utf-8")
    for name in ("DRINKS_YT_LIVE", "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN_EN", "google-api-python-client"):
        assert name in wf


def test_download_failure_is_before_publish_called(monkeypatch):
    def boom(url, dest):
        raise OSError("net")
    monkeypatch.setattr(dy, "_download", boom)
    with pytest.raises(PublishError) as e:   # create_container 단계 = 게시 호출 전 → failed(재시도 가능), unknown 아님
        _Guarded(YT_ACCOUNT["external_account_id"]).create_container(YT_ACCOUNT, kind="reel", url="https://x/v.mp4", caption="c")
    assert e.value.code == "file_download_failed"
