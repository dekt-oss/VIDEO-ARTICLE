"""채널 레지스트리 + 채널 가드 순수 로직 테스트 (명세서 A3).

네트워크·구글 라이브러리 없이 돈다 — youtube 클라이언트는 스텁으로 대체한다.
가드의 핵심 계약 3가지를 고정한다:
  1) 채널이 다르면 **업로드 전에** 막는다.
  2) 스코프 부족(§9-6)은 막지 않는다 — 기존 upload-only 토큰 경로를 깨지 않기 위해.
  3) 조회 실패(네트워크 등)도 막지 않는다 — 가드 때문에 업로드가 멈추면 안 된다.
"""

from __future__ import annotations

import pytest

from engine import youtube_channels as yc
from engine.youtube_types import ChannelMismatchError, MissingTokenError


class _Stub:
    """googleapiclient 의 youtube.channels().list(...).execute() 체인을 흉내낸다."""

    def __init__(self, *, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    def channels(self):
        return self

    def list(self, **_kwargs):
        return self

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


def _ok(channel_id: str, title: str = "채널"):
    return {"items": [{"id": channel_id, "snippet": {"title": title}}]}


def test_registry_keys_are_self_consistent():
    for key, spec in yc.CHANNEL_REGISTRY.items():
        assert spec["key"] == key
        assert spec["channel_id"].startswith("UC"), key
        assert spec["secret_env"] in yc._SECRET_ATTR_BY_ENV, key
        assert spec["lang"] in ("ko", "en"), key


def test_registry_covers_three_channels():
    assert set(yc.CHANNEL_REGISTRY) == {"paper_ko", "paper_en", "report_ko"}


def test_report_ko_targets_paper_ko_channel_by_design():
    """채널 통합(2026-07-30) — report_ko 의 목적지는 paper_ko 와 같은 채널이다.

    ★ 이 중복은 의도된 것이다. 키는 출처(공장), 값은 목적지(채널)라 역할이 다르다.
      되돌릴 때는 여기 세 값만 컨센선스 채널로 바꾼다
      (docs/specs/20260730-report-merge-into-paper-ko.md §4).
    """
    paper_ko = yc.get_channel("paper_ko")
    report_ko = yc.get_channel("report_ko")
    assert report_ko["channel_id"] == paper_ko["channel_id"]
    assert report_ko["secret_env"] == paper_ko["secret_env"]
    # 출처 식별자는 살아 있어야 성과 측정·되돌리기가 가능하다.
    assert report_ko["key"] == "report_ko"


def test_paper_en_is_a_distinct_channel():
    """EN 채널만은 반드시 달라야 한다 — 음성 테스트의 유일한 대상이다(명세서 §2-3)."""
    en = yc.get_channel("paper_en")
    for other in ("paper_ko", "report_ko"):
        assert en["channel_id"] != yc.get_channel(other)["channel_id"]
        assert en["secret_env"] != yc.get_channel(other)["secret_env"]


def test_get_channel_rejects_unknown_key():
    with pytest.raises(KeyError):
        yc.get_channel("nope")  # type: ignore[arg-type]


def test_missing_token_message_names_the_env_var(monkeypatch):
    # config.SECRETS 는 frozen dataclass 라 필드를 못 바꾼다 — 객체 자체를 갈아끼운다.
    class _EmptySecrets:
        youtube_refresh_token_ko = ""

    monkeypatch.setattr(yc.config, "SECRETS", _EmptySecrets())
    with pytest.raises(MissingTokenError) as exc:
        yc.refresh_token_for("report_ko")
    # 스택트레이스가 아니라 "무엇을 채우라"가 보여야 한다(명세서 DoD).
    assert "YOUTUBE_REFRESH_TOKEN_KO" in str(exc.value)
    assert "runbook" in str(exc.value)


def test_guard_passes_when_channel_matches():
    spec = yc.get_channel("report_ko")
    yc.assert_correct_channel(_Stub(result=_ok(spec["channel_id"])), "report_ko")


def test_guard_blocks_when_channel_differs():
    """음성 테스트(명세서 §2-3) — paper_en 토큰으로 report_ko 업로드를 시도하면 막힌다.

    채널 통합 후 paper_ko ↔ report_ko 는 같은 채널이라 음성 테스트로 쓸 수 없다.
    서로 다른 채널로 남은 조합은 EN 뿐이다.
    """
    en = yc.get_channel("paper_en")["channel_id"]
    with pytest.raises(ChannelMismatchError) as exc:
        yc.assert_correct_channel(_Stub(result=_ok(en, "a Paper a Day")), "report_ko")
    msg = str(exc.value)
    assert "하루지식하나" in msg              # 기대 채널(통합 목적지)
    assert "a Paper a Day" in msg            # 실제 토큰의 채널
    assert "YOUTUBE_REFRESH_TOKEN_KO" in msg


def test_guard_warns_but_passes_on_scope_error():
    """§9-6: upload-only 토큰(기존 논문 채널)에서 가드가 업로드를 막으면 안 된다."""
    err = Exception("insufficientPermissions: Request had insufficient authentication scopes.")
    yc.assert_correct_channel(_Stub(error=err), "paper_ko")


def test_guard_passes_on_transient_lookup_failure():
    yc.assert_correct_channel(_Stub(error=Exception("503 backend error")), "paper_ko")


def test_guard_passes_on_empty_items():
    yc.assert_correct_channel(_Stub(result={"items": []}), "paper_ko")


def test_classify_auth_error_maps_invalid_grant():
    out = yc.classify_auth_error(Exception("invalid_grant: Token has been expired"), "report_ko")
    assert type(out).__name__ == "TokenRevokedError"
    assert "YOUTUBE_REFRESH_TOKEN_KO" in str(out)


def test_classify_auth_error_passes_through_others():
    original = Exception("connection reset")
    assert yc.classify_auth_error(original, "report_ko") is original


def test_cli_registry_matches_engine_registry():
    """tools/get_youtube_refresh_token.py 는 단독 실행을 위해 레지스트리 사본을 갖는다.

    사본이라 한쪽만 고치면 CLI 가 엉뚱한 채널을 기대하게 된다 — 그 드리프트를 여기서 잡는다.
    CLI 는 engine 을 임포트하지 않으므로 파일 경로로 직접 로드한다.
    """
    import importlib.util
    from pathlib import Path

    cli_path = Path(__file__).resolve().parent.parent / "tools" / "get_youtube_refresh_token.py"
    spec = importlib.util.spec_from_file_location("_yt_token_cli", cli_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert set(mod.CHANNELS) == set(yc.CHANNEL_REGISTRY)
    for key, engine_spec in yc.CHANNEL_REGISTRY.items():
        cli_spec = mod.CHANNELS[key]
        for field in ("key", "title", "channel_id", "secret_env"):
            assert cli_spec[field] == engine_spec[field], f"{key}.{field} 가 어긋났다"

    # CLI 는 업로드 + 조회 두 스코프를 요청해야 채널 대조가 가능하다(§9-6).
    assert yc.config.YOUTUBE_UPLOAD_SCOPE in mod.SCOPES
    assert yc.config.YOUTUBE_READONLY_SCOPE in mod.SCOPES


def test_token_check_script_registry_matches_engine_registry():
    """scripts/check_youtube_tokens.py 도 단독 실행용 사본을 갖는다 — 같은 드리프트 방지."""
    from scripts import check_youtube_tokens as chk

    by_key = {c["key"]: c for c in chk.CHANNELS}
    assert set(by_key) == set(yc.CHANNEL_REGISTRY)
    for key, engine_spec in yc.CHANNEL_REGISTRY.items():
        for field in ("key", "title", "channel_id", "secret_env"):
            assert by_key[key][field] == engine_spec[field], f"{key}.{field} 가 어긋났다"


def test_fit_tags_prefers_core_tags_and_respects_limit():
    """공통 태그 + 영상별 태그가 500자 상한을 넘지 않는다(명세서 §3-3).

    앞쪽(공통 태그)이 우선 살아남아야 한다 — 채널 통합 후 두 공장 영상이 같은 채널에
    쌓이므로 공통 태그가 잘리면 통합의 의미가 없다.
    """
    from engine.providers.youtube import _fit_tags
    from engine import config

    core = list(config.CHANNEL_CORE_TAGS_KO)
    extra = [f"태그{i}" * 20 for i in range(40)]        # 일부러 상한을 넘긴다
    out = _fit_tags(core + extra)

    total = sum(len(t) for t in out) + max(0, len(out) - 1)
    assert total <= config.YOUTUBE_TAGS_TOTAL_MAX
    assert out[: len(core)] == core, "공통 태그가 먼저 살아남아야 한다"


def test_fit_tags_drops_blanks_and_duplicates():
    from engine.providers.youtube import _fit_tags

    assert _fit_tags(["  a ", "a", "", "  ", "b"]) == ["a", "b"]


# ── 갱신 스코프(운영 장애 재발 방지) ──
# 증상: 리포트 업로드가 "invalid_scope: Bad Request" 로 실패했다.
# 원인: 업로드 경로가 갱신 요청에 upload+readonly 를 실었는데, 채널 통합 후 report_ko 가 쓰는
#      YOUTUBE_REFRESH_TOKEN_KO 는 upload 만 승인받은 토큰이다. RFC 6749 §6 상 승인 범위를
#      넘는 scope 는 거부되고, 구글은 갱신 자체를 막는다 — channels.list 403 을 전제한
#      §9-6 폴백(WARN 후 통과)이 돌 기회조차 없다.
def test_load_credentials_does_not_request_scopes_by_default(monkeypatch):
    """갱신 요청에 scope 를 싣지 않아야 승인 범위가 좁은 토큰도 살아난다."""
    captured: dict[str, object] = {}

    class _FakeCredentials:
        def __init__(self, **kw):
            captured.update(kw)

    import sys, types
    mod = types.ModuleType("google.oauth2.credentials")
    mod.Credentials = _FakeCredentials  # type: ignore[attr-defined]
    pkg = types.ModuleType("google"); oauth2 = types.ModuleType("google.oauth2")
    monkeypatch.setitem(sys.modules, "google", pkg)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", mod)
    # Secrets 는 frozen dataclass 라 필드를 못 바꾼다 — 인스턴스 자체를 스텁으로 교체한다.
    class _Secrets:
        youtube_client_id = "cid"
        youtube_client_secret = "csec"

        def require(self, *names):
            return None

    monkeypatch.setattr(yc.config, "SECRETS", _Secrets())
    monkeypatch.setattr(yc, "refresh_token_for", lambda key: "rt")

    yc.load_credentials("report_ko")
    # None 이어야 google-auth 가 refresh body 에 scope 를 넣지 않는다(_client.refresh_grant).
    assert captured["scopes"] is None, captured["scopes"]


def test_upload_path_does_not_widen_scopes():
    """업로드 경로가 load_credentials 에 스코프를 넘기지 않는가(소스 계약).

    ★ 여기에 스코프를 다시 적어 넣으면 upload-only 토큰의 갱신이 다시 죽는다.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "engine" / "providers" / "youtube.py").read_text(
        encoding="utf-8")
    upload_section = src.split("if channel_key:", 1)[1].split("else:", 1)[0]
    assert "yc.load_credentials(channel_key)" in upload_section
    assert "YOUTUBE_READONLY_SCOPE" not in upload_section
