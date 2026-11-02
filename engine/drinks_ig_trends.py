"""인스타 트렌드 보드 수집 — 인기 음원·관찰 계정·운영자 링크 → 밈 카드. 2026-11-02. docs/deviation-drinks-ig-trend-board.md

    python -m engine.drinks_ig_trends     # drinks-trend-board 워크플로(매일 KST 07:30). 0원, 공식 API 읽기만.

기획 v2 §6·§8. 이 파일은 engine/drinks_trends.py(네이버 카페·뉴스)와 다른 기능이다 — 표도 drink_ig_* 로 따로 쓴다.

수집원:
  T1  GET /ig_audio             노래·원본 소리 각 앞 N쪽. 돌려준 순서는 "인스타가 우리 계정에 준 추천 순서"다(§6-4).
  T2  Business Discovery        활성 관찰 계정의 최근 릴스. 조회수·좋아요·댓글·표지 주소·캡션 첫 줄.
  T3  운영자 링크               서버는 링크를 열지 않는다. 그 계정을 T2 와 같은 공식 호출로 찾아 짧은 코드로 맞춘다.
  T4  없음                      상태 어휘 자리만 있다. 이 파일에 Apify 호출·경로가 없다(§6-1 클릭 승인 미연결).

지키는 것:
  · 토큰은 Authorization 헤더로만 보낸다. debug_token 만 입력값이 주소에 들어가므로 httpx 요청 로그를 끄고,
    오류·로그에는 주소를 싣지 않는다(사유 코드만). 다음 쪽은 응답의 주소를 따라가지 않고 값만 꺼내 다시 만든다.
  · 실패가 0건처럼 보이지 않는다. 수집원마다 날짜마다 상태 5종을 남기고, 돌지 않은 날은 다음 실행이 not_run 으로 채운다.
  · view_count 가 없으면 null 로 두고 판정에서 빼며 뺀 수를 기록한다. 0 으로 채우지 않는다.
  · 남의 영상·음원 파일을 받지 않는다. 영상 주소는 "왔는지"만 기록하고 값은 버린다. 캡션 전문도 저장하지 않는다.
  · LLM·유료 호출 없음. 영상을 봐야 아는 칸(비트 수 등)은 근거 없이 채우지 않는다(코드·DB 둘 다 막는다).

순수 함수(네트워크 없음)와 실행(run)을 나눴다. run 은 요청기(fetcher)와 DB 호출(rpc)을 주입받아 시험에서 네트워크 없이 돈다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

from . import config
from .drinks_collect import DbError
from .drinks_fetch import JSON_TYPES, TEXT_TYPES, FetchError, SafeFetcher
from .providers.instagram import GRAPH_VERSION
from .util import log, today_local

Rpc = Callable[[str, dict[str, Any]], Any]

USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")
AGE_BUCKETS = ("h0_24", "h24_72", "d3_7", "d7_plus")
RUN_STATUSES = ("ok", "ok_empty", "partial", "failed", "not_run")
EVIDENCE = ("video", "cover", "caption", "api_metrics", "operator")
DAILY_SOURCES = ("t1", "t2", "t3")   # T4 는 매일 도는 수집원이 아니다(§6-2). 정상 관측일에도 not_run 채우기에도 넣지 않는다.
GRAPH_RATE_LIMIT_CODES = {4, 17, 32, 613}
GRAPH_TOKEN_CODES = {102, 190}


# ── 나이 구간·기준선·뜨는 릴스 (§6-3) ──

def age_hours(posted_at: Optional[str], now: datetime) -> Optional[float]:
    """올린 뒤 경과 시간. 게시 시각을 못 읽으면 None. 시계 차이로 음수가 되면 0."""
    if not posted_at:
        return None
    try:
        # Graph API 는 '2026-11-01T10:00:00+0000' 형식을 준다 — 파이썬 3.11 미만을 위해 콜론을 넣어 읽는다.
        s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", posted_at.strip().replace("Z", "+00:00"))
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0.0, (now - t).total_seconds() / 3600)


def age_bucket(hours: Optional[float]) -> Optional[str]:
    """0~24시간 / 24~72시간 / 3~7일 / 7일 이상. 경계값은 뒤 구간으로 간다."""
    if hours is None:
        return None
    if hours < 24:
        return "h0_24"
    if hours < 72:
        return "h24_72"
    if hours < 168:
        return "d3_7"
    return "d7_plus"


@dataclass(frozen=True)
class Baseline:
    sample: int
    median: Optional[float]   # 표본이 부족하면 None — 판정하지 않는다

    @property
    def insufficient(self) -> bool:
        return self.median is None


def build_baselines(rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], Baseline]:
    """계정·나이 구간별 조회수 중앙값. rows 는 (릴스, 구간)당 값 하나(merge_observations 결과).
    조회수가 없는 행은 세지 않는다. 그 구간 릴스가 8개 미만이면 insufficient_sample."""
    groups: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        v, bucket = r.get("view_count"), r.get("age_bucket")
        if v is None or bucket is None:
            continue
        groups.setdefault((r["username"], bucket), []).append(float(v))
    out: dict[tuple[str, str], Baseline] = {}
    for key, values in groups.items():
        enough = len(values) >= config.DRINKS_IG_BASELINE_MIN_SAMPLE
        out[key] = Baseline(len(values), statistics.median(values) if enough else None)
    return out


def merge_observations(history: Iterable[dict[str, Any]], today_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """과거 값 + 오늘 값 → (릴스, 구간)당 하나. 오늘 값이 이긴다. 오늘 조회수가 없으면 그 구간의 표본에서 빠진다."""
    merged: dict[tuple[str, Optional[str]], dict[str, Any]] = {}
    for r in history:
        merged[(r["media_id"], r.get("age_bucket"))] = r
    for r in today_rows:
        merged[(r["media_id"], r.get("age_bucket"))] = r
    return list(merged.values())


def judge_reel(view_count: Optional[int], bucket: Optional[str], baseline: Optional[Baseline]) -> dict[str, Any]:
    """{trend_flag, baseline_views, view_multiple}. 기준선 대비 배수로만 판정한다."""
    none = {"baseline_views": None, "view_multiple": None}
    if view_count is None:
        return {"trend_flag": "no_views", **none}
    if bucket is None:
        return {"trend_flag": "no_age", **none}
    if baseline is None or baseline.insufficient:
        return {"trend_flag": "insufficient_sample", **none}
    median = float(baseline.median or 0)
    if median <= 0:   # 기준선 0 이면 배수를 말할 수 없다(3 × 0 은 모든 릴스를 뜨는 릴스로 만든다)
        return {"trend_flag": "normal", "baseline_views": median, "view_multiple": None}
    multiple = round(view_count / median, 2)
    flag = "rising" if view_count >= config.DRINKS_IG_RISING_MULTIPLE * median else "normal"
    return {"trend_flag": flag, "baseline_views": median, "view_multiple": multiple}


def backfill_flag(first_observed_on: Optional[str], today: date) -> bool:
    """새로 추가한(또는 다시 켠) 계정의 첫 관측일에 본 릴스. 새 예시·오르는 중 신호에 넣지 않는다."""
    return first_observed_on is None or first_observed_on == today.isoformat()


# ── 인기 음원 (§6-4) ──

def position_label(position: int) -> str:
    """화면·로그 공용 표기. '순위'라고 부르지 않는다 — 우리 계정에 준 추천 순서 안의 자리일 뿐이다."""
    return f"목록 {position}번째(우리 계정 기준, 오늘)"


def rising_audio_reason(today: date, first_seen_on: Optional[str], ok_days_before: list[str],
                        present_days: Iterable[str]) -> Optional[str]:
    """오르는 음원 = 목록에 처음 들어옴(new) 또는 3일 연속 남음(three_days). 자리 바뀜으로는 판정하지 않는다.

    ok_days_before: 오늘 전 T1 이 ok 였던 날짜(오름차순). '연속'은 달력이 아니라 이 날들로 센다 — 실패한 날이 연속을 끊거나 채우지 않는다.
    첫 관측에서는 전부 처음 보는 음원이므로 '처음 들어옴'이라고 하지 않는다.
    """
    if not ok_days_before:
        return None
    if first_seen_on is None or first_seen_on >= today.isoformat() or first_seen_on > ok_days_before[-1]:
        return "new"
    need = config.DRINKS_IG_AUDIO_CONSECUTIVE_DAYS - 1
    recent = ok_days_before[-need:]
    present = set(present_days)
    if len(recent) == need and all(d in present for d in recent):
        return "three_days"
    return None


def is_generic_audio_title(title: Optional[str]) -> bool:
    """'original audio'·'오리지널 사운드' 같은 이름은 서로 다른 음원에 겹친다. 밈 이름으로 쓰지 않는다."""
    t = (title or "").strip()
    return not t or re.search(config.DRINKS_IG_GENERIC_AUDIO_TITLE, t, re.I) is not None


def is_challenge_title(title: Optional[str]) -> bool:
    return not is_generic_audio_title(title) and re.search(config.DRINKS_IG_CHALLENGE_WORD, title or "", re.I) is not None


# ── 실행 상태·정상 관측일·동결 (§6-2, §6-6) ──

def run_status(attempted: int, succeeded: int, items: int) -> str:
    """시도·성공·결과 수 → 상태. 일부만 성공하면 partial, 전부 실패하면 failed. 성공인데 결과가 없으면 ok_empty."""
    if attempted > 0 and succeeded == 0:
        return "failed"
    if succeeded < attempted:
        return "partial"
    return "ok" if items > 0 else "ok_empty"


def is_normal_day(t1_status: Optional[str], t2_attempted: int, t2_succeeded: int) -> bool:
    """T1 이 ok 이고 T2 계정 성공률이 80% 이상. 활성 계정이 0개면 성공률을 말할 수 없어 정상이 아니다."""
    if t1_status != "ok" or t2_attempted <= 0:
        return False
    return t2_succeeded / t2_attempted >= config.DRINKS_IG_NORMAL_T2_MIN_RATE


def normal_days(runs: Iterable[dict[str, Any]]) -> dict[str, bool]:
    """실행 기록 → {날짜: 정상인가}. 기록이 있는 날만 나온다."""
    by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        by_day.setdefault(str(r["observed_on"])[:10], {})[r["source"]] = r
    out = {}
    for day, src in by_day.items():
        t2 = src.get("t2") or {}
        out[day] = is_normal_day((src.get("t1") or {}).get("status"), int(t2.get("attempted") or 0), int(t2.get("succeeded") or 0))
    return out


@dataclass(frozen=True)
class FreezeState:
    frozen: bool
    missing_streak: int
    last_normal_day: Optional[str]


def freeze_state(runs: Iterable[dict[str, Any]], today: date) -> FreezeState:
    """정상 관측일이 3일 이상 끊겼나. 오늘부터 거슬러 올라가며 정상이 아닌 날(기록 없는 날 포함)을 센다.

    오늘 기록이 아직 없으면 오늘은 세지 않는다(오늘 실행 전일 수 있다). 기록이 하나도 없으면 끊긴 것이 아니라 시작 전이다.
    """
    days = normal_days(runs)
    if not days:
        return FreezeState(False, 0, None)
    normals = [d for d, ok in days.items() if ok]
    last_normal = max(normals) if normals else None
    start = today if today.isoformat() in days else today - timedelta(days=1)
    earliest = date.fromisoformat(min(days))
    streak = 0
    d = start
    while d >= earliest and not days.get(d.isoformat(), False):
        streak += 1
        d -= timedelta(days=1)
    return FreezeState(streak >= config.DRINKS_IG_FREEZE_MISSING_DAYS, streak, last_normal)


def missing_dates(last_run_on: Optional[str], today: date) -> list[date]:
    """마지막 기록 다음 날 ~ 어제. 워크플로가 안 돌아 비어 있는 날(not_run 으로 채울 날). 처음 도는 날은 없다."""
    if not last_run_on:
        return []
    start = date.fromisoformat(str(last_run_on)[:10]) + timedelta(days=1)
    gap = (today - start).days
    if gap <= 0:
        return []
    days = [start + timedelta(days=i) for i in range(gap)]
    return days[-config.DRINKS_IG_NOT_RUN_FILL_MAX_DAYS:]


# ── 카드: 형식 칸 (§6-5) ──

def sanitize_fields(fields: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """값·근거가 없는 칸은 빼고(= null), 영상 전용 칸은 video·operator 근거가 아니면 지운다. 모델을 믿지 않는다(§6-5)."""
    out = []
    for f in fields:
        value = f.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        evidence = f.get("evidence")
        if evidence not in EVIDENCE:
            continue
        if f["field"] in config.DRINKS_IG_VIDEO_ONLY_FIELDS and evidence not in ("video", "operator"):
            continue
        out.append({"field": f["field"], "value": str(value), "evidence": evidence,
                    "confidence": f.get("confidence") if f.get("confidence") in ("high", "low") else "low"})
    return out


def caption_hook(caption: Optional[str]) -> Optional[str]:
    """캡션에서 훅 문장 후보 한 줄: 해시태그·@언급·주소를 뗀 첫 번째 비지 않은 줄. 없으면 None."""
    for line in (caption or "").splitlines():
        s = re.sub(r"https?://\S+|[#@][^\s#@]+", " ", line)
        s = re.sub(r"\s+", " ", s).strip(" -–—·|")
        if re.search(r"[^\W_]", s):
            return s[:config.DRINKS_IG_HOOK_MAX_CHARS]
    return None


def _bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for run in re.findall(r"[^\W_]+", (text or "").lower()):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def hook_similarity(a: Optional[str], b: Optional[str]) -> float:
    """글자 2개 조각의 Jaccard. 겹친 조각이 2개 미만이면 0(짧은 문장끼리 우연히 묶이지 않게)."""
    x, y = _bigrams(a or ""), _bigrams(b or "")
    both = len(x & y)
    if both < 2:
        return 0.0
    return both / len(x | y)


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def find_challenge(caption: Optional[str], names: Iterable[str]) -> Optional[str]:
    """캡션에 오늘 목록의 챌린지 이름이 그대로 있나. 있으면 그 이름. 음원 카드에 붙이는 근거로는 쓰지 않는다(§6-6)."""
    c = _norm_name(caption or "")
    for name in sorted(names, key=lambda n: (-len(n), n)):
        if name and _norm_name(name) in c:
            return name
    return None


# ── 카드: 병합·분리 (§6-6) ──

@dataclass
class Element:
    """카드 하나로 묶일 신호 하나 — 오르는 음원, 뜨는 릴스, 운영자 링크."""
    origin: str                              # audio | rising_reel | operator_link
    name: str
    audio_id: Optional[str] = None
    challenge_name: Optional[str] = None
    structure: Optional[str] = None
    hook: Optional[str] = None
    media_id: Optional[str] = None
    username: Optional[str] = None
    view_multiple: Optional[float] = None
    fields: list[dict[str, Any]] = field(default_factory=list)


def card_key(el: Element, structure_cards: list[dict[str, Any]]) -> tuple[str, str]:
    """(merge_key, kind). 우선순위: ① audio_id ② 챌린지 이름 ③ 구조 + 훅 문장 유사도. 음원 이름은 키로 쓰지 않는다.

    · 같은 audio_id 라도 구조가 다르면 다른 카드다(키에 구조가 들어간다). 연결은 카드의 audio_id 로 표시한다.
    · 같은 이름이라도 audio_id 가 다르면 다른 카드다(이름이 키에 없다).
    · 구조도 audio_id 도 없는 릴스는 합치지 않는다 — 훅 문장만으로 묶을 근거가 없다.
    """
    if el.audio_id:
        key = f"audio:{el.audio_id}"
        return (f"{key}|s:{el.structure}" if el.structure else key), "audio"
    if el.challenge_name:
        return f"challenge:{_norm_name(el.challenge_name)}", "challenge"
    if el.structure and el.hook:
        for c in structure_cards:
            if c.get("structure") == el.structure and hook_similarity(c.get("caption_hook"), el.hook) >= config.DRINKS_IG_HOOK_SIMILAR_MIN:
                return c["merge_key"], "structure_hook"
        return f"hook:{el.structure}:{el.media_id}", "structure_hook"
    return f"reel:{el.media_id}", "single_reel"


# ── 카드: 수명 (§6-6) ──

def next_lifecycle(card: dict[str, Any], *, today: date, new_examples: int, audio_in_list: bool,
                   audio_three_days: bool) -> Optional[dict[str, Any]]:
    """정상 관측일 하루를 반영한 다음 상태. 이미 센 날이면 None. 정상 관측일에만 부른다(DB 도 다른 날은 거부한다).

    새로 뜸 → 오르는 중(2일 연속 예시 증가, 또는 원본 소리가 3일 연속 목록) → 정점(증가가 멈춤) → 식음(7일 동안 활동 없음).
    활동 = 새 예시, 또는 그 음원이 오늘 목록에 있음. 식은 카드에 활동이 다시 생기면 새로 뜸으로 돌아간다.
    """
    day = today.isoformat()
    if str(card.get("last_evaluated_on") or "") >= day:
        return None
    state = card["state"]
    if str(card.get("first_seen_on") or "") == day:   # 처음 묶인 날 — 0→1 은 증가로 세지 않는다
        return {"card_id": card["card_id"], "state": state, "quiet_normal_days": 0, "increase_streak": 0}
    increased = new_examples > 0
    active = increased or audio_in_list
    streak = int(card.get("increase_streak") or 0) + 1 if increased else 0
    quiet = 0 if active else int(card.get("quiet_normal_days") or 0) + 1
    if quiet >= config.DRINKS_IG_COOLED_NORMAL_DAYS:
        nxt = "cooled"
    elif state == "cooled":
        nxt = "new"
    elif streak >= config.DRINKS_IG_RISING_STREAK_DAYS or (state == "new" and audio_three_days):
        nxt = "rising"
    elif state == "rising" and not increased:
        nxt = "peak"
    else:
        nxt = state
    return {"card_id": card["card_id"], "state": nxt, "quiet_normal_days": quiet, "increase_streak": streak}


# ── 토큰 (V-T1) ──

@dataclass(frozen=True)
class TokenInfo:
    status: str                                  # ok | expired | missing | unavailable
    expires_at: Optional[str] = None
    data_access_expires_at: Optional[str] = None
    error_code: Optional[str] = None
    days_left: Optional[int] = None


def _epoch_iso(v: Any) -> Optional[str]:
    """debug_token 의 초 단위 시각. 0 은 '만료 없음'이라 None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return datetime.fromtimestamp(v, timezone.utc).isoformat()


def parse_debug_token(body: dict[str, Any], now: datetime) -> TokenInfo:
    data = body.get("data")
    if not isinstance(data, dict):
        return TokenInfo("unavailable", error_code="bad_shape")
    exp, dax = data.get("expires_at"), data.get("data_access_expires_at")
    iso, dax_iso = _epoch_iso(exp), _epoch_iso(dax)
    left = int((exp - now.timestamp()) // 86400) if iso else None
    expired = data.get("is_valid") is False or (iso is not None and exp <= now.timestamp())
    return TokenInfo("expired" if expired else "ok", iso, dax_iso, "token_expired" if expired else None, left)


def token_warning(info: TokenInfo) -> Optional[str]:
    if info.days_left is not None and info.days_left < config.DRINKS_IG_TOKEN_WARN_DAYS:
        return f"토큰 만료까지 {info.days_left}일 — docs/안내_페이스북로그인전환_2026-10-30.md 4~6번으로 다시 받으세요"
    return None


# ── 그래프 API ──

class GraphError(Exception):
    """사유 코드만 싣는다. 응답 문장·주소는 싣지 않는다(비밀이 섞일 수 있다)."""

    def __init__(self, reason: str, graph_code: Optional[int] = None):
        super().__init__(reason)
        self.reason = reason
        self.graph_code = graph_code


def classify_graph_error(code: Any, message: Optional[str]) -> str:
    """Meta 오류 코드 → 실패 사유. 문장은 분류에만 쓰고 저장·로그에 넣지 않는다."""
    c = code if isinstance(code, int) else None
    msg = (message or "").lower()
    if c in GRAPH_TOKEN_CODES:
        return "token_expired"
    if c in GRAPH_RATE_LIMIT_CODES:
        return "rate_limited"
    if c == 110 or (c == 100 and ("invalid user id" in msg or "cannot find" in msg)):
        return "invalid_user"     # 개인 계정·없는 이름(기획 v1 §1 실측)
    if c == 100:
        return "bad_request"      # 없는 칸을 물은 경우 포함 — DRINKS_IG_MEDIA_FIELDS 를 확인할 것
    if c == 10 or (c is not None and 200 <= c < 300):
        return "permission"
    return "api_error"


def _graph_error_from_body(raw: Optional[bytes]) -> Optional[GraphError]:
    if not raw:
        return None
    try:
        err = json.loads(raw).get("error")
    except (ValueError, AttributeError):
        return None
    if not isinstance(err, dict):
        return None
    return GraphError(classify_graph_error(err.get("code"), err.get("message")),
                      err.get("code") if isinstance(err.get("code"), int) else None)


class GraphClient:
    """토큰은 헤더로만. 오류는 사유 코드(GraphError)로만 올린다 — FetchError 를 그대로 내보내지 않는다."""

    def __init__(self, fetcher: SafeFetcher, token: str):
        # httpx 는 INFO 로 요청 주소를 찍는다. debug_token 은 입력값이 주소에 들어가므로 끈다(시험이 감시).
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        self._fetcher = fetcher
        self._token = token

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"https://{config.DRINKS_IG_GRAPH_HOST}/{GRAPH_VERSION}/{path.lstrip('/')}"
        try:
            res = self._fetcher.get(url, accept=JSON_TYPES + TEXT_TYPES, params=params,
                                    headers={"Authorization": f"Bearer {self._token}"})
        except FetchError as exc:
            graph = _graph_error_from_body(exc.error_body)
            if graph is not None:
                raise graph from None
            if exc.http_status == 429:
                raise GraphError("rate_limited") from None
            reason = {"http_error": "api_error", "timeout": "network", "transport": "network", "request_cap": "request_cap"}.get(exc.code, exc.code)
            raise GraphError(reason) from None
        try:
            body = json.loads(res.body)
        except ValueError:
            raise GraphError("bad_shape") from None
        if not isinstance(body, dict):
            raise GraphError("bad_shape")
        if isinstance(body.get("error"), dict):
            err = body["error"]
            raise GraphError(classify_graph_error(err.get("code"), err.get("message")))
        return body

    def debug_token(self, now: datetime) -> TokenInfo:
        try:
            return parse_debug_token(self.get("debug_token", {"input_token": self._token}), now)
        except GraphError as exc:
            if exc.reason == "token_expired":
                return TokenInfo("expired", error_code="token_expired")
            return TokenInfo("unavailable", error_code=exc.reason)


def next_page_params(body: dict[str, Any]) -> Optional[dict[str, str]]:
    """다음 쪽을 부를 값. 주소(paging.next)는 따라가지 않는다(주소에 토큰이 들어 있을 수 있다).

    ★ 2026-11-02 실측: ig_audio 응답에는 paging.next 가 없고 paging.cursors.after 만 있다(노래 6쪽·원본 소리 5쪽까지 실제로 넘어갔다).
      끝을 알리는 표시도 없어서 마지막 쪽에도 커서가 온다 — 호출부는 빈 쪽 또는 쪽 상한에서 멈춘다."""
    paging = body.get("paging")
    if not isinstance(paging, dict):
        return None
    cursors = paging.get("cursors")
    cursor = cursors.get("after") if isinstance(cursors, dict) else None
    return {"after": str(cursor)} if cursor else None


def business_discovery_fields(username: str) -> str:
    return (f"business_discovery.username({username}){{id,username,followers_count,media_count,"
            f"media.limit({config.DRINKS_IG_MEDIA_LIMIT}){{{','.join(config.DRINKS_IG_MEDIA_FIELDS)}}}}}")


# ── 수집 ──

@dataclass
class Tally:
    attempted: int = 0
    succeeded: int = 0
    items: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    token_dead: bool = False

    def fail(self, reason: str, n: int = 1) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + n
        if reason == "token_expired":
            self.token_dead = True

    @property
    def status(self) -> str:
        return run_status(self.attempted, self.succeeded, self.items)


def collect_audio(graph: GraphClient, ig_user_id: str) -> tuple[list[dict[str, Any]], Tally]:
    """T1. 종류별로 앞 N쪽. 쪽 하나가 실패하면 그 종류의 뒤쪽은 부르지 않는다(이어 부를 값이 없다)."""
    t = Tally()
    seen: dict[str, dict[str, Any]] = {}
    for kind in config.DRINKS_IG_AUDIO_TYPES:
        position = 0
        extra: dict[str, str] = {}
        for _ in range(config.DRINKS_IG_AUDIO_PAGES):
            t.attempted += 1
            try:
                body = graph.get("ig_audio", {**extra, "audio_type": kind, "user_id": ig_user_id})
            except GraphError as exc:
                t.fail(exc.reason)
                log.warning("drinks-ig: T1 %s 쪽 실패(%s)", kind, exc.reason)
                if t.token_dead or exc.reason in ("rate_limited", "request_cap"):
                    t.items = len(seen)
                    return list(seen.values()), t
                break
            rows = body.get("audio")
            if not isinstance(rows, list):
                t.fail("bad_shape")   # 응답 모양이 바뀌었다 — 조용히 0건으로 만들지 않는다
                log.warning("drinks-ig: T1 %s 응답에 audio 목록이 없습니다", kind)
                break
            t.succeeded += 1
            for row in rows:
                position += 1
                audio_id = str(row.get("audio_id") or "") if isinstance(row, dict) else ""
                if not audio_id or audio_id in seen:
                    continue
                seen[audio_id] = {
                    "audio_id": audio_id, "audio_type": kind, "title": row.get("title"),
                    "display_artist": row.get("display_artist"), "ig_username": row.get("ig_username"),
                    "duration_ms": row.get("duration_in_ms") if isinstance(row.get("duration_in_ms"), int) else None,
                    "preview_url": row.get("on_platform_audio_preview_link"),   # download_url(음원 파일)은 받지 않는다
                    "list_position": position,
                }
            extra = next_page_params(body) or {}
            if not extra or not rows:
                break
    t.items = len(seen)
    return list(seen.values()), t


@dataclass
class AccountResult:
    username: str
    followers_count: Optional[int]
    reels: list[dict[str, Any]]
    non_reels: int = 0


def _count(v: Any) -> Optional[int]:
    """API 숫자. 없거나 숫자가 아니면 None — 0 으로 바꾸지 않는다."""
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def parse_account(username: str, body: dict[str, Any], now: datetime) -> AccountResult:
    bd = body.get("business_discovery")
    if not isinstance(bd, dict):
        raise GraphError("no_data")
    media = bd.get("media")
    rows = media.get("data") if isinstance(media, dict) else []
    if not isinstance(rows, list):
        raise GraphError("bad_shape")
    reels: list[dict[str, Any]] = []
    non_reels = 0
    for m in rows:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        product = m.get("media_product_type")
        if product != "REELS" and not (product is None and m.get("media_type") == "VIDEO"):
            non_reels += 1
            continue
        hours = age_hours(m.get("timestamp"), now)
        reels.append({
            "media_id": str(m["id"]), "username": username, "permalink": m.get("permalink"), "posted_at": m.get("timestamp"),
            "caption_hook": caption_hook(m.get("caption")), "media_audio_type": m.get("media_audio_type"),
            "cover_url": m.get("thumbnail_url"), "has_video_url": bool(m.get("media_url")),   # 영상 주소 값은 버린다
            "view_count": _count(m.get("view_count")), "like_count": _count(m.get("like_count")),
            "comments_count": _count(m.get("comments_count")), "age_hours": None if hours is None else round(hours, 2),
            "age_bucket": age_bucket(hours), "_caption": m.get("caption"),
        })
    return AccountResult(username, _count(bd.get("followers_count")), reels, non_reels)


def _db_item(reel: dict[str, Any]) -> dict[str, Any]:
    """DB 로 보낼 값(메모리 전용 칸 제거 — 캡션 전문은 저장하지 않는다)."""
    return {k: v for k, v in reel.items() if not k.startswith("_")}


def judge_reels(reels: list[dict[str, Any]], history: list[dict[str, Any]]) -> None:
    today_rows = [{"username": r["username"], "media_id": r["media_id"], "age_bucket": r["age_bucket"], "view_count": r["view_count"]}
                  for r in reels]
    baselines = build_baselines(merge_observations(history, today_rows))
    for r in reels:
        r.update(judge_reel(r["view_count"], r["age_bucket"], baselines.get((r["username"], r["age_bucket"] or ""))))


def collect_accounts(graph: GraphClient, ig_user_id: str, accounts: list[dict[str, Any]], today: date, now: datetime,
                     rpc: Rpc) -> tuple[dict[str, AccountResult], Tally, dict[str, int]]:
    """T2. 계정마다 1회. 잘못된 계정 하나가 나머지를 막지 않는다. 호출 한도·토큰 문제면 남은 계정을 부르지 않고 실패로 센다."""
    t = Tally(attempted=len(accounts))
    results: dict[str, AccountResult] = {}
    first_seen = {a["username"]: a.get("first_observed_on") for a in accounts}
    stats = {"rising": 0, "insufficient_sample": 0, "no_age": 0, "backfill": 0, "non_reels": 0}
    errors: dict[str, str] = {}
    stop: Optional[str] = None
    for acc in accounts:
        u = acc["username"]
        if stop:
            t.fail(stop)
            errors[u] = stop
            continue
        try:
            if not USERNAME_RE.match(u):
                raise GraphError("invalid_user")
            results[u] = parse_account(u, graph.get(ig_user_id, {"fields": business_discovery_fields(u)}), now)
            t.succeeded += 1
        except GraphError as exc:
            t.fail(exc.reason)
            errors[u] = exc.reason
            log.warning("drinks-ig: T2 %s 실패(%s)", u, exc.reason)
            if exc.reason in ("token_expired", "rate_limited", "request_cap"):
                stop = exc.reason

    reels = [r for res in results.values() for r in res.reels]
    if reels:
        history = rpc("drinks_ig_baseline_rows", {"usernames": sorted(results),
                                                  "since": (today - timedelta(days=config.DRINKS_IG_BASELINE_LOOKBACK_DAYS)).isoformat()}) or []
        judge_reels(reels, history)
    day = today.isoformat()
    for u, res in list(results.items()):
        backfill = backfill_flag(first_seen.get(u), today)
        for r in res.reels:
            r["is_backfill"] = backfill
            stats["backfill"] += 1 if backfill else 0
            if r["trend_flag"] in stats:
                stats[r["trend_flag"]] += 1
        stats["non_reels"] += res.non_reels
        try:
            rpc("drinks_ig_record_media", {"observed_on": day, "username": u, "source": "t2", "items": [_db_item(r) for r in res.reels]})
            rpc("drinks_ig_mark_account", {"observed_on": day, "username": u, "ok": True, "followers_count": res.followers_count})
        except DbError as exc:   # 값 하나가 거절돼도 나머지 계정은 계속한다 - 이 계정은 실패로 센다
            t.succeeded -= 1
            t.fail("record_failed")
            errors[u] = "record_failed"
            results.pop(u, None)
            log.warning("drinks-ig: T2 %s 기록 거절(%s)", u, exc.code)
    for u, reason in errors.items():
        rpc("drinks_ig_mark_account", {"observed_on": day, "username": u, "ok": False, "error_code": reason})
    t.items = sum(len(res.reels) for res in results.values())
    return results, t, stats


def resolve_links(graph: GraphClient, ig_user_id: str, links: list[dict[str, Any]], fetched: dict[str, AccountResult], today: date,
                  now: datetime, rpc: Rpc) -> tuple[list[dict[str, Any]], Tally]:
    """T3. 그 계정을 공식 API 로 찾아 최근 릴스에서 짧은 코드가 맞는 것을 고른다. 링크 주소는 열지 않는다."""
    t = Tally(attempted=len(links))
    resolved: list[dict[str, Any]] = []
    day = today.isoformat()
    cache = dict(fetched)
    judged = {r["media_id"] for res in fetched.values() for r in res.reels}
    stop: Optional[str] = None
    for link in links:
        u = link["username"]
        if stop:
            t.fail(stop)
            continue
        try:
            if u not in cache:
                cache[u] = parse_account(u, graph.get(ig_user_id, {"fields": business_discovery_fields(u)}), now)
        except GraphError as exc:
            t.fail(exc.reason)
            log.warning("drinks-ig: T3 %s 실패(%s)", u, exc.reason)
            if exc.reason in ("token_expired", "rate_limited", "request_cap"):
                stop = exc.reason     # 링크는 pending 으로 남아 다음 실행이 다시 집는다(시도 횟수도 늘리지 않는다)
                continue
            if exc.reason in ("invalid_user", "no_data"):
                t.succeeded += 1      # 답이 확정됐다 - 개인 계정이거나 없는 이름
                rpc("drinks_ig_finish_link", {"link_id": link["link_id"], "status": "account_unavailable", "error_code": exc.reason, "observed_on": day})
            else:
                gave_up = int(link.get("attempts") or 0) + 1 >= config.DRINKS_IG_LINK_MAX_ATTEMPTS
                rpc("drinks_ig_finish_link", {"link_id": link["link_id"], "status": "failed" if gave_up else "pending", "error_code": exc.reason, "observed_on": day})
            continue
        needle = f"/{link['shortcode']}"
        hit = next((r for r in cache[u].reels if needle in str(r.get("permalink") or "")), None)
        t.succeeded += 1
        if hit is None:
            rpc("drinks_ig_finish_link", {"link_id": link["link_id"], "status": "not_found", "error_code": "not_in_recent", "observed_on": day})
            continue
        if hit["media_id"] not in judged:   # T2 에서 이미 판정·기록한 릴스가 아니면 여기서 판정한다(표본이 없으면 insufficient_sample)
            judge_reels([hit], [])
            hit["is_backfill"] = False
        rpc("drinks_ig_record_media", {"observed_on": day, "username": u, "source": "t3", "items": [_db_item(hit)]})
        rpc("drinks_ig_finish_link", {"link_id": link["link_id"], "status": "resolved", "media_id": hit["media_id"], "observed_on": day})
        t.items += 1
        resolved.append({"link_id": link["link_id"], "media_id": hit["media_id"], "username": u, "caption_hook": hit.get("caption_hook"),
                         "media_audio_type": hit.get("media_audio_type"), "view_multiple": hit.get("view_multiple"),
                         "view_count": hit.get("view_count")})
    return resolved, t


# ── 카드 묶기 ──

def audio_elements(audio: list[dict[str, Any]]) -> list[Element]:
    """오르는 원본 소리 중 이름이 있는 것. 노래는 '오르는 음원' 목록에만 나온다(config.DRINKS_IG_CARD_AUDIO_TYPES)."""
    out = []
    for a in sorted(audio, key=lambda x: x["list_position"]):
        if not a.get("rising_reason") or a["audio_type"] not in config.DRINKS_IG_CARD_AUDIO_TYPES or is_generic_audio_title(a.get("title")):
            continue
        out.append(Element(
            origin="audio", name=str(a["title"]), audio_id=a["audio_id"],
            challenge_name=str(a["title"]) if is_challenge_title(a.get("title")) else None,
            fields=[{"field": "audio_type", "value": a["audio_type"], "evidence": "api_metrics", "confidence": "high"}]))
    return out


def _reel_fields(hook: Optional[str], audio_type: Optional[str]) -> list[dict[str, Any]]:
    return [{"field": "caption_hook", "value": hook, "evidence": "caption", "confidence": "high"},
            {"field": "audio_type", "value": audio_type, "evidence": "api_metrics", "confidence": "high"}]


def reel_elements(results: dict[str, AccountResult], attached: set[str], challenges: list[str]) -> list[Element]:
    """뜨는 릴스 → 신호. backfill 은 넣지 않는다. 음원 카드에 자동으로 붙이지 않는다(audio_id 가 없다, §6-6)."""
    out = []
    for res in results.values():
        for r in res.reels:
            if r.get("trend_flag") != "rising" or r.get("is_backfill") or r["media_id"] in attached:
                continue
            ch = find_challenge(r.get("_caption"), challenges)
            out.append(Element(origin="rising_reel", name=ch or r.get("caption_hook") or f"@{r['username']} 릴스", challenge_name=ch,
                               hook=r.get("caption_hook"), media_id=r["media_id"], username=r["username"],
                               view_multiple=r.get("view_multiple"), fields=_reel_fields(r.get("caption_hook"), r.get("media_audio_type"))))
    return out


def link_elements(links: Iterable[dict[str, Any]], attached: set[str]) -> list[Element]:
    """운영자가 본 릴스 — 사람의 눈이 신호라서 배수와 상관없이 카드로 올린다."""
    out = []
    seen: set[str] = set()
    for l in links:
        mid = l.get("media_id")
        if not mid or mid in attached or mid in seen:
            continue
        seen.add(mid)
        out.append(Element(origin="operator_link", name=l.get("caption_hook") or f"@{l.get('username')} 릴스", hook=l.get("caption_hook"),
                           media_id=mid, username=l.get("username"), view_multiple=l.get("view_multiple"),
                           fields=_reel_fields(l.get("caption_hook"), l.get("media_audio_type"))))
    return out


def sync_cards(rpc: Rpc, elements: list[Element], cards: list[dict[str, Any]], today: date) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    """신호 → 카드. (카드별 그날 예시 수, 새로 만든 카드, 상한으로 미룬 수)."""
    day = today.isoformat()
    known = {c["merge_key"] for c in cards}
    structure_cards = [c for c in cards if c.get("kind") == "structure_hook"]
    grouped: dict[str, dict[str, Any]] = {}
    capped = 0
    new_keys = 0
    for el in elements:
        key, kind = card_key(el, structure_cards)
        if key not in known and key not in grouped:
            if new_keys >= config.DRINKS_IG_MAX_NEW_CARDS_PER_RUN:
                capped += 1
                continue
            new_keys += 1
            if kind == "structure_hook":
                structure_cards.append({"merge_key": key, "structure": el.structure, "caption_hook": el.hook})
        g = grouped.setdefault(key, {"observed_on": day, "merge_key": key, "kind": kind, "name": el.name, "audio_id": el.audio_id,
                                     "challenge_name": el.challenge_name, "structure": el.structure, "examples": [], "fields": []})
        if el.media_id:
            g["examples"].append({"media_id": el.media_id, "origin": "operator_link" if el.origin == "operator_link" else "rising_reel",
                                  "view_multiple": el.view_multiple})
        have = {f["field"] for f in g["fields"]}
        g["fields"] += [f for f in sanitize_fields(el.fields) if f["field"] not in have]
    signals: dict[str, int] = {}
    created: list[dict[str, Any]] = []
    for g in grouped.values():
        r = rpc("drinks_ig_upsert_card", g) or {}
        signals[r["card_id"]] = int(r.get("new_examples") or 0)
        if r.get("created"):
            created.append({"card_id": r["card_id"], "merge_key": g["merge_key"], "kind": g["kind"], "state": "new", "first_seen_on": day,
                            "last_evaluated_on": None, "quiet_normal_days": 0, "increase_streak": 0, "audio_id": g["audio_id"]})
    return signals, created, capped


# ── 실행 ──

def _record_run(rpc: Rpc, source: str, day: date, t: Tally, *, excluded: Optional[int] = None, detail: Optional[dict] = None,
                status: Optional[str] = None) -> str:
    st = status or t.status
    rpc("drinks_ig_record_run", {"source": source, "observed_on": day.isoformat(), "status": st, "attempted": t.attempted,
                                 "succeeded": t.succeeded, "items": t.items, "failure_reasons": t.reasons,
                                 "excluded_no_views": excluded, "detail": detail or {}})
    return st


def run(rpc: Rpc, fetcher: Any, *, token: Optional[str], ig_user_id: Optional[str] = None, today: Optional[date] = None,
        now: Optional[datetime] = None) -> dict[str, Any]:
    """하루치 수집 → 실행 기록 → (정상 관측일이면) 카드 갱신. 건수 요약을 돌려준다(로그에도 건수와 사유 코드만)."""
    now = now or datetime.now(timezone.utc)
    today = today or today_local()
    ig = ig_user_id or config.DRINKS_IG_USER_ID
    day = today.isoformat()
    state = rpc("drinks_ig_worker_state", {"observed_on": day, "link_limit": config.DRINKS_IG_LINKS_PER_RUN}) or {}

    # 안 돌았던 날은 다음 실행이 not_run 으로 채운다. 이미 있는 기록은 DB 가 덮지 않는다.
    filled = missing_dates(state.get("last_run_on"), today)
    for d in filled:
        for src in DAILY_SOURCES:
            rpc("drinks_ig_record_run", {"source": src, "observed_on": d.isoformat(), "status": "not_run"})

    accounts: list[dict[str, Any]] = state.get("accounts") or []
    links: list[dict[str, Any]] = state.get("pending_links") or []
    out: dict[str, Any] = {"observed_on": day, "not_run_filled": len(filled), "normal_day": False, "cards_created": 0, "cards_capped": 0,
                           "lifecycle_applied": 0, "token_status": None, "token_days_left": None}

    graph = GraphClient(fetcher, token) if token else None
    info = graph.debug_token(now) if graph else TokenInfo("missing", error_code="token_missing")
    rpc("drinks_ig_record_token_check", {"observed_on": day, "status": info.status, "expires_at": info.expires_at,
                                         "data_access_expires_at": info.data_access_expires_at, "error_code": info.error_code})
    out["token_status"], out["token_days_left"] = info.status, info.days_left
    warn = token_warning(info)
    if warn:
        log.warning("drinks-ig: %s", warn)

    if graph is None or info.status == "expired":
        # 조용히 0건이 되지 않는다. 세 수집원 모두 failed + 사유. 카드는 건드리지 않는다(DB 도 거부한다).
        reason = info.error_code or "token_expired"
        log.error("drinks-ig: 토큰 문제(%s) — 수집하지 않습니다. 오늘은 실패로 기록하고 카드 상태는 멈춥니다", reason)
        t1 = Tally(attempted=len(config.DRINKS_IG_AUDIO_TYPES))
        t1.fail(reason, t1.attempted)
        t2 = Tally(attempted=len(accounts))
        t2.fail(reason, max(1, len(accounts)))
        t3 = Tally(attempted=len(links))
        t3.fail(reason, max(1, len(links)))
        out["t1"] = _record_run(rpc, "t1", today, t1, status="failed")
        out["t2"] = _record_run(rpc, "t2", today, t2, status="failed")
        out["t3"] = _record_run(rpc, "t3", today, t3, status="failed")
        return out

    # T1 ───
    audio, t1 = collect_audio(graph, ig)
    first_seen: dict[str, str] = state.get("audio_first_seen") or {}
    runs: list[dict[str, Any]] = list(state.get("runs") or [])
    ok_before = sorted({str(r["observed_on"])[:10] for r in runs
                        if r["source"] == "t1" and r["status"] == "ok" and str(r["observed_on"])[:10] < day})
    present: dict[str, set[str]] = {}
    for o in state.get("audio_recent") or []:
        present.setdefault(o["audio_id"], set()).add(str(o["observed_on"])[:10])
    t1_ok = t1.status == "ok"
    for a in audio:
        a["rising_reason"] = rising_audio_reason(today, first_seen.get(a["audio_id"]), ok_before, present.get(a["audio_id"], ())) if t1_ok else None
    if audio:
        rpc("drinks_ig_record_audio", {"observed_on": day, "items": audio})
    out["t1"] = _record_run(rpc, "t1", today, t1, detail={"rising": sum(1 for a in audio if a["rising_reason"])})

    # T2 ───
    results: dict[str, AccountResult] = {}
    if t1.token_dead:
        t2 = Tally(attempted=len(accounts))
        t2.fail("token_expired", max(1, len(accounts)))
        stats: dict[str, int] = {}
    else:
        results, t2, stats = collect_accounts(graph, ig, accounts, today, now, rpc)
    excluded = sum(1 for res in results.values() for r in res.reels if r.get("view_count") is None)
    detail: dict[str, Any] = dict(stats)
    if not accounts:
        detail["no_active_accounts"] = True
    out["t2"] = _record_run(rpc, "t2", today, t2, excluded=excluded, detail=detail)
    out["excluded_no_views"] = excluded

    # T3 ───
    resolved: list[dict[str, Any]] = []
    if t1.token_dead or t2.token_dead:
        t3 = Tally(attempted=len(links))
        if links:
            t3.fail("token_expired", len(links))
        # debug_token 은 통과했는데 수집 중 토큰이 죽었다 - 화면 경고가 사실대로 나가게 고쳐 적는다.
        rpc("drinks_ig_record_token_check", {"observed_on": day, "status": "expired", "expires_at": info.expires_at,
                                             "data_access_expires_at": info.data_access_expires_at, "error_code": "token_expired"})
        out["token_status"] = "expired"
    else:
        resolved, t3 = resolve_links(graph, ig, links, results, today, now, rpc)
    out["t3"] = _record_run(rpc, "t3", today, t3, excluded=sum(1 for r in resolved if r.get("view_count") is None))

    # 카드 ─── 정상 관측일에만. 다른 날은 관측만 남기고 카드·수명을 건드리지 않는다.
    normal = is_normal_day(t1.status, t2.attempted, t2.succeeded)
    out["normal_day"] = normal
    frozen = freeze_state([*(r for r in runs if str(r["observed_on"])[:10] != day),
                           {"source": "t1", "observed_on": day, "status": t1.status, "attempted": t1.attempted, "succeeded": t1.succeeded},
                           {"source": "t2", "observed_on": day, "status": t2.status, "attempted": t2.attempted, "succeeded": t2.succeeded}], today)
    out["missing_streak"], out["frozen"], out["last_normal_day"] = frozen.missing_streak, frozen.frozen, frozen.last_normal_day
    if frozen.frozen:
        log.error("drinks-ig: 관측 중단 — 정상 관측일이 %d일 끊겨 카드 상태를 고정합니다(마지막 정상일 %s)", frozen.missing_streak, frozen.last_normal_day)
    if normal:
        cards: list[dict[str, Any]] = state.get("cards") or []
        attached = set(state.get("attached_media") or [])
        challenges = [str(a["title"]) for a in audio if a["audio_type"] == "original_sound" and is_challenge_title(a.get("title"))]
        elements = [*link_elements([*(state.get("unattached_links") or []), *resolved], attached),
                    *reel_elements(results, attached, challenges), *audio_elements(audio)]
        signals, created, capped = sync_cards(rpc, elements, cards, today)
        out["cards_created"], out["cards_capped"] = len(created), capped
        by_audio = {a["audio_id"]: a for a in audio}
        batch = []
        for c in [*cards, *created]:
            a = by_audio.get(c.get("audio_id") or "")
            nxt = next_lifecycle(c, today=today, new_examples=max(signals.get(c["card_id"], 0), int(c.get("examples_today") or 0)),
                                 audio_in_list=a is not None, audio_three_days=bool(a and a.get("rising_reason") == "three_days"))
            if nxt is not None:
                batch.append(nxt)
        if batch:
            out["lifecycle_applied"] = int((rpc("drinks_ig_apply_lifecycle", {"observed_on": day, "cards": batch}) or {}).get("applied") or 0)
    return out


def exit_code(out: dict[str, Any]) -> int:
    """토큰 문제·수집 전체 실패는 워크플로를 빨갛게 만든다. 일부 실패는 기록으로 충분하다."""
    if out.get("token_status") in ("missing", "expired") or out.get("t1") == "failed" or out.get("t2") == "failed":
        return 1
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    from .drinks_collect import supabase_rpc

    fetcher = SafeFetcher([config.DRINKS_IG_GRAPH_HOST], interval_sec=config.DRINKS_IG_INTERVAL_SEC,
                          max_requests=config.DRINKS_IG_MAX_REQUESTS)
    try:
        out = run(supabase_rpc(), fetcher, token=os.getenv(config.DRINKS_IG_TOKEN_ENV) or None)
    except Exception as exc:  # noqa: BLE001 — 예외 문장·추적에 주소가 섞일 수 있어 종류만 남긴다
        log.error("drinks-ig: 중단 — %s (%s). 0063 마이그레이션 적용 여부를 확인하세요", type(exc).__name__, getattr(exc, "code", "-"))
        return 1
    finally:
        fetcher.close()
    log.info("drinks-ig: %s", json.dumps(out, ensure_ascii=False))
    return exit_code(out)


if __name__ == "__main__":
    sys.exit(main())
