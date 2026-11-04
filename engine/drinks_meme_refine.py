"""밈 틀 정밀화 — [쓰자] 카드의 릴스(≤3)를 Apify 로 받아 비트 수·컷 길이·반전 시점·자막 자리·화면 종류·동기화 등급을 잰다. 2026-11-02.
docs/deviation-drinks-stage3-4.md · 총괄 계획 §3(결정 1) · 기획 v2 §6-1·§6-5·§6-7 · 검토 §8.

    python -m engine.drinks_meme_refine            # 큐만 보여 준다. 돈이 드는 호출은 하지 않는다
    python -m engine.drinks_meme_refine --yes      # 실제 실행(Apify + 영상 분석 모델). GitHub 워크플로 drinks-apify.yml 이 이렇게 부른다
    python -m engine.drinks_meme_refine --fake     # 가짜 응답으로 끝까지(0원). 산출물 docs/preview-<날짜>/meme-refine/

지키는 것:
  · 돈은 DB 가 센다. 요청(drink_apify_requests)은 [쓰자] 클릭이 만들고, 실행 상한 $0.02·월 상한 $3 을 넘으면 요청 자체가 안 생긴다(0070).
    워커는 Apify 실행에 maxTotalChargeUsd 를 상한으로 걸고, 끝난 뒤 실제 금액을 적는다. 모르면 상한을 적는다.
  · 남의 영상은 **분석 뒤 즉시 지운다.** 실행마다 새 임시 폴더, finally 에서 삭제, 시작 때 24시간 넘은 임시 폴더 청소(§6-7).
    우리 저장소(Supabase Storage)에는 넣지 않는다 — 이 파일에는 Storage 가 없고(tests 가 감시), DB 에는 메타만 간다(영상 주소가 있으면 DB 가 거부).
  · 입력은 공식 API 가 이미 고른 릴스 주소만(DB 가 준다). 계정 전체를 다시 사지 않는다.
  · 토큰은 Authorization 헤더로만. 값은 로그·출력·DB 어디에도 남기지 않는다.
  · 컷 길이·비트 수는 ffmpeg 장면 전환 감지(0원·결정적)로 재고, 모델에는 영상을 봐야 아는 나머지(반전 시점·첫 1.5초·동기화·화면 종류·자막 자리)만 묻는다.
    모델 답은 코드가 걸러 **영상 근거 칸 다섯 개와 구조·표지 글자만** 카드로 간다. 그 밖의 칸은 버린다(§6-5 "근거 없는 필드 생성률 0%").
  · 분석 모델은 상수 하나(DRINKS_APIFY_ANALYSIS_MODEL). 60초·20MB 넘는 영상은 분석하지 않고 ffmpeg 측정만 남긴다.
★ 결과는 참고 자료다. 사실 근거가 아니다(총괄 §3). 카드가 정밀 틀이 되면 밈 제작(engine/drinks_meme.py)이 이어진다 — 그 경로는 리허설과 같다.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from . import config
from .drinks_collect import DbError
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]

TMP_PREFIX = "drinks_apify_"
VIDEO_FIELDS = ("beat_count", "cut_lengths", "twist_at", "first_1_5s", "music_sync")
MODEL_FIELDS = ("twist_at", "first_1_5s", "music_sync", "structure", "cover_text", "frame", "text_position", "sync_grade")
STRUCTURES = ("pov", "before_after", "twist", "list", "reaction")
FRAMES = ("top_text", "full_title", "no_text")
TEXT_POSITIONS = ("top", "center", "bottom", "none")
# 결과 행에 남기는 칸(검토 §8). 주소·바이트는 여기 없다.
RESULT_KEYS = ("input_url", "status", "duration_sec", "play_count", "audio_id", "uses_original_audio", "posted_at", "has_video")
_MEDIA_URL = re.compile(r"(cdninstagram|fbcdn|videoUrl|video_url|audioUrl|audio_url|download_url)", re.I)


class RefineStop(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


# ─────────────────────────────────────────────────────────────
# 계획·견적 (순수)
# ─────────────────────────────────────────────────────────────

def plan_inputs(job: dict[str, Any]) -> list[str]:
    """보낼 릴스 주소. DB 가 조회수 순으로 고른 것을 상한 안에서 그대로 쓴다. 인스타 주소가 아니면 버린다."""
    out: list[str] = []
    for r in job.get("reels") or []:
        u = str((r or {}).get("permalink") or "").strip()
        if re.match(r"^https://(www\.)?instagram\.com/", u) and u not in out:
            out.append(u)
    return out[: config.DRINKS_APIFY_MAX_REELS_PER_RUN]


def estimate_usd(n_reels: int, *, analyze: bool = True) -> float:
    """실행 예상액: 행 수 × 단가 + 시작 + 분석. 오류 행도 청구되므로 보낸 수로 센다."""
    apify = n_reels * config.DRINKS_APIFY_REEL_USD + config.DRINKS_APIFY_START_USD
    return round(apify + (n_reels * config.DRINKS_APIFY_ANALYSIS_EST_USD if analyze else 0.0), 4)


def apify_input(urls: list[str]) -> dict[str, Any]:
    """Actor 입력. 공유 수·받아쓰기·영상 저장(추가 과금)은 전부 끈다(검토 §1)."""
    return {"directUrls": urls, "resultsLimit": len(urls), "includeSharesCount": False, "includeTranscript": False, "downloadVideos": False}


def split_budget(cap_usd: float, n_reels: int) -> dict[str, float]:
    """실행 상한을 Apify 몫과 분석 몫으로 나눈다(리뷰 R2). 분석 몫 = 영상 수 × 분석 1편 예상액. 내림으로 자른다(상한을 넘지 않게)."""
    per = float(config.DRINKS_APIFY_ANALYSIS_EST_USD)
    reserve = round(n_reels * per, 4)
    apify = max(0.0, math.floor((cap_usd - reserve) * 10000) / 10000)
    return {"cap_usd": round(cap_usd, 4), "apify_cap_usd": apify, "analysis_reserve_usd": reserve, "per_analysis_usd": per}


def run_cap_check(job: dict[str, Any], n_reels: int) -> None:
    cap = float(job.get("cap_usd") or 0)
    est = estimate_usd(n_reels)
    if est > cap:
        raise RefineStop("run_cap_exceeded", f"예상액 ${est:.4f} 가 실행 상한 ${cap:.2f} 를 넘습니다 — 릴스 수를 줄이세요")


# ─────────────────────────────────────────────────────────────
# Apify 결과 → 메타 행 (순수)
# ─────────────────────────────────────────────────────────────

def classify_row(item: dict[str, Any]) -> str:
    err = str(item.get("error") or item.get("errorDescription") or "").lower()
    if not err and (item.get("videoDuration") is not None or item.get("videoUrl")):
        return "ok"
    if "age" in err and "restrict" in err:
        return "age_restricted"
    if "not_found" in err or "not found" in err or "404" in err:
        return "not_found"
    if "restricted" in err or "private" in err:
        return "restricted_other"
    return "failed"


def result_rows(items: list[dict[str, Any]], inputs: list[str]) -> list[dict[str, Any]]:
    """저장용 메타 행. 영상·음성 주소는 여기서 떨어진다. 보낸 주소마다 한 행 — 응답에 없으면 failed."""
    by_url: dict[str, dict[str, Any]] = {}
    for it in items or []:
        u = str(it.get("inputUrl") or it.get("url") or "")
        key = _canon(u)
        by_url.setdefault(key, it)
    rows = []
    for u in inputs:
        it = by_url.get(_canon(u))
        if it is None:
            rows.append({"input_url": u, "status": "failed", "duration_sec": None, "play_count": None, "audio_id": None,
                         "uses_original_audio": None, "posted_at": None, "has_video": False})
            continue
        music = it.get("musicInfo") or {}
        dur = it.get("videoDuration")
        rows.append({
            "input_url": u, "status": classify_row(it),
            "duration_sec": round(float(dur), 2) if isinstance(dur, (int, float)) else None,
            "play_count": it.get("videoPlayCount") if isinstance(it.get("videoPlayCount"), int) else None,
            "audio_id": str(music.get("audio_id")) if music.get("audio_id") else None,
            "uses_original_audio": music.get("uses_original_audio") if isinstance(music.get("uses_original_audio"), bool) else None,
            "posted_at": it.get("timestamp") if isinstance(it.get("timestamp"), str) else None,
            "has_video": bool(it.get("videoUrl")),
        })
    return rows


def _canon(u: str) -> str:
    return re.sub(r"[?#].*$", "", str(u or "").strip().rstrip("/").replace("www.", "").replace("/reels/", "/reel/").lower())


def assert_no_media_url(payload: Any) -> None:
    """DB 로 가는 것에 주소가 섞였으면 보내지 않는다(DB 도 거부하지만 먼저 멈춘다)."""
    if _MEDIA_URL.search(json.dumps(payload, ensure_ascii=False)):
        raise RefineStop("media_url_rejected", "영상·음성 주소가 저장 데이터에 섞였습니다 — 보내지 않습니다")


# ─────────────────────────────────────────────────────────────
# ffmpeg 측정 (0원, 결정적)
# ─────────────────────────────────────────────────────────────

def ffprobe_duration(path: str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RefineStop("probe_failed", f"ffprobe 실패: {(p.stderr or '')[-200:]}")
    return float((p.stdout or "0").strip() or 0)


def scene_cut_times(path: str, *, threshold: Optional[float] = None) -> list[float]:
    """장면 전환 시각(초). ffmpeg select=gt(scene,t) + showinfo 의 pts_time 을 읽는다."""
    th = config.DRINKS_APIFY_SCENE_THRESHOLD if threshold is None else threshold
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vf", f"select='gt(scene,{th})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, encoding="utf-8", errors="replace")
    times = [float(m.group(1)) for m in re.finditer(r"pts_time:\s*([0-9.]+)", p.stderr or "")]
    return sorted(set(round(t, 2) for t in times if t > 0.2))


def cut_lengths_from(duration: float, cuts: list[float]) -> list[float]:
    """전환 시각 → 컷 길이(초). 0.5초보다 짧은 조각은 앞 컷에 붙인다(깜빡임을 비트로 세지 않게)."""
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    out: list[float] = []
    for a, b in zip(bounds, bounds[1:]):
        seg = round(b - a, 1)
        if out and seg < 0.5:
            out[-1] = round(out[-1] + seg, 1)
        else:
            out.append(seg)
    return [x for x in out if x > 0]


def measure_video(path: str) -> dict[str, Any]:
    dur = ffprobe_duration(path)
    cuts = scene_cut_times(path)
    lens = cut_lengths_from(dur, cuts)
    return {"duration_sec": round(dur, 2), "cut_times": cuts, "cut_lengths": lens, "beat_count": len(lens), "bytes": os.path.getsize(path)}


# ─────────────────────────────────────────────────────────────
# 영상 분석 모델 — 영상을 봐야 아는 칸만 묻고, 답은 코드가 걸러 쓴다
# ─────────────────────────────────────────────────────────────

ANALYSIS_SYSTEM = (
    "너는 인스타 릴스의 **형식**만 보는 분석기다. 내용의 사실·주장은 보지 않는다. JSON 만 낸다.\n"
    "보이는 것만 적는다. 안 보이면 null. 추측하지 않는다.\n"
    "형식: {\"frame\": \"top_text|full_title|no_text\", \"text_position\": \"top|center|bottom|none\", \"cover_text\": \"첫 화면에 보이는 글자 그대로 또는 null\", "
    "\"first_1_5s\": \"첫 1.5초에 화면에서 일어나는 일 한 문장\", \"twist_at_sec\": 반전·결정적 순간의 초 또는 null, "
    "\"structure\": \"pov|before_after|twist|list|reaction|null\", \"music_sync\": \"required|free|unknown\" — 글·장면 전환이 소리의 박자·가사 지점에 맞춰져 있으면 required, "
    "분위기 소리라 어디서 시작해도 되면 free, 소리가 없거나 판단 못 하면 unknown, \"notes\": \"한 줄\"}"
)


def analysis_prompt(duration: float, cut_lengths: list[float]) -> str:
    return (f"영상 길이 {duration:.1f}초. 코드가 잰 장면 전환으로 나눈 컷 길이(초): {cut_lengths}.\n"
            "이 영상의 형식을 위 JSON 으로 적어라. 글자는 보이는 그대로, 시각은 초 단위 숫자로.")


def gemini_video_json(path: str, *, model: str, system: str, user: str, max_tokens: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Gemini REST, 영상 바이트 직접 전송(inline_data, 20MB 이하). 돌려주는 것: (JSON 답, usageMetadata)."""
    from . import llm
    from .util import gemini_auth

    config.SECRETS.require("gemini_api_key")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": "video/mp4", "data": data}}, {"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens, "temperature": 0.2,
                             "mediaResolution": "MEDIA_RESOLUTION_LOW"},
    }
    url = f"{config.GEMINI_BASE}/{model}:generateContent"
    with httpx.Client(timeout=config.LLM_HTTP_TIMEOUT_SEC) as client:
        resp = client.post(url, headers=gemini_auth(), json=body)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RefineStop("analysis_unavailable", f"분석 모델 {resp.status_code} — 오늘은 다시 시도하지 않습니다(§6-7)")
        resp.raise_for_status()
        out = resp.json()
    usage = out.get("usageMetadata") or {}
    text = "".join(p.get("text", "") for p in ((out.get("candidates") or [{}])[0].get("content") or {}).get("parts", []))
    return llm.salvage_json(text), usage


def analysis_usd(model: str, usage: dict[str, Any]) -> float:
    from .drinks_develop import usage_usd

    return usage_usd(model, usage)   # Gemini usageMetadata 키(promptTokenCount·candidatesTokenCount·thoughtsTokenCount)를 그대로 읽는다


def fields_from_analysis(measured: dict[str, Any], ans: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """카드 칸(근거 video). 컷 길이·비트 수는 ffmpeg(확신 high), 모델 답은 걸러서(확신 low). 모델이 안 본 것은 칸을 만들지 않는다(= null)."""
    out = [
        {"field": "beat_count", "value": str(measured["beat_count"]), "evidence": "video", "confidence": "high"},
        {"field": "cut_lengths", "value": ",".join(f"{x:g}" for x in measured["cut_lengths"]), "evidence": "video", "confidence": "high"},
    ]
    a = ans if isinstance(ans, dict) else {}
    twist = a.get("twist_at_sec")
    if isinstance(twist, (int, float)) and not isinstance(twist, bool) and 0 <= float(twist) <= measured["duration_sec"]:
        out.append({"field": "twist_at", "value": f"{float(twist):g}초", "evidence": "video", "confidence": "low"})
    first = str(a.get("first_1_5s") or "").strip()
    if first and not _MEDIA_URL.search(first):
        out.append({"field": "first_1_5s", "value": first[:300], "evidence": "video", "confidence": "low"})
    sync = str(a.get("music_sync") or "").strip().lower()
    if sync in ("required", "free"):
        out.append({"field": "music_sync", "value": "박자에 맞춰야 함(필수)" if sync == "required" else "박자 무관(분위기)", "evidence": "video", "confidence": "low"})
    st = str(a.get("structure") or "").strip().lower()
    if st in STRUCTURES:
        out.append({"field": "structure", "value": st, "evidence": "video", "confidence": "low"})
    cover = str(a.get("cover_text") or "").strip()
    if cover and not _MEDIA_URL.search(cover):
        out.append({"field": "cover_text", "value": cover[:300], "evidence": "video", "confidence": "low"})
    return out


def frame_summary(ans: Optional[dict[str, Any]]) -> dict[str, Any]:
    """카드 칸이 아닌 틀 정보(화면 종류·자막 자리) — 요청의 analysis 칸에만 남는다. 허용 어휘 밖은 버린다."""
    a = ans if isinstance(ans, dict) else {}
    fr, tp = str(a.get("frame") or "").lower(), str(a.get("text_position") or "").lower()
    return {"frame": fr if fr in FRAMES else None, "text_position": tp if tp in TEXT_POSITIONS else None,
            "notes": str(a.get("notes") or "")[:300] or None}


# ─────────────────────────────────────────────────────────────
# 파일 수명 (§6-7) — 받은 영상은 분석 뒤 지운다
# ─────────────────────────────────────────────────────────────

def sweep_old_tmp(root: Optional[str] = None, *, hours: Optional[int] = None, now: Optional[float] = None) -> list[str]:
    """시작 때 오래된 임시 폴더를 먼저 지운다(지난 실행이 지우지 못한 것)."""
    base = Path(root or tempfile.gettempdir())
    limit = (hours if hours is not None else config.DRINKS_APIFY_TMP_SWEEP_HOURS) * 3600
    t = now if now is not None else time.time()
    gone = []
    for p in base.glob(f"{TMP_PREFIX}*"):
        try:
            if p.is_dir() and t - p.stat().st_mtime > limit:
                shutil.rmtree(p, ignore_errors=True)
                gone.append(str(p))
        except OSError:
            continue
    return gone


class BorrowedVideos:
    """남의 영상이 머무는 임시 폴더. 나갈 때 지운다. 지우기에 실패하면 로그에 남기고 다음 실행의 sweep 이 지운다."""

    def __init__(self, root: Optional[str] = None):
        self.root = root
        self.path: Optional[str] = None
        self.deleted = False

    def __enter__(self) -> "BorrowedVideos":
        self.path = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=self.root)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self.path and os.path.isdir(self.path):
            shutil.rmtree(self.path, ignore_errors=True)
            self.deleted = not os.path.isdir(self.path)
            if not self.deleted:
                log.warning("drinks: 빌린 영상 폴더를 지우지 못했습니다 — 다음 실행의 청소가 지웁니다")
        else:
            self.deleted = True


# ─────────────────────────────────────────────────────────────
# 공급자 — Apify (실제) / 가짜
# ─────────────────────────────────────────────────────────────

@dataclass
class ApifyResult:
    items: list[dict[str, Any]]
    run_id: Optional[str]
    usage_usd: Optional[float]      # None = 못 읽음 → 상한으로 적는다


class ApifyClient:
    """최소 REST. 토큰은 헤더로만, 로그 없음. 실행마다 maxTotalChargeUsd 를 건다."""

    def __init__(self, token: str, *, actor: Optional[str] = None, host: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        if not token:
            raise RefineStop("token_missing", f"{config.DRINKS_APIFY_TOKEN_ENV} 가 없어 Apify 를 부를 수 없습니다")
        self._headers = {"Authorization": f"Bearer {token}"}
        self.actor = actor or config.DRINKS_APIFY_REEL_ACTOR
        self.base = f"https://{host or config.DRINKS_APIFY_HOST}/v2"
        self._client = httpx.Client(timeout=httpx.Timeout(config.DRINKS_APIFY_RUN_TIMEOUT_SEC + 30, connect=20), transport=transport, trust_env=False)

    def run_reels(self, urls: list[str], *, cap_usd: float) -> ApifyResult:
        params = {"maxTotalChargeUsd": f"{cap_usd:.4f}", "timeout": str(config.DRINKS_APIFY_RUN_TIMEOUT_SEC), "memory": "1024"}
        resp = self._client.post(f"{self.base}/acts/{self.actor}/run-sync-get-dataset-items", params=params, headers=self._headers, json=apify_input(urls))
        if resp.status_code >= 400:
            raise RefineStop("apify_error", f"Apify {resp.status_code}")   # 본문에 주소·토큰이 섞일 수 있어 적지 않는다
        items = resp.json()
        run_id = resp.headers.get("x-apify-run-id") or None
        usage = None
        if run_id:
            r2 = self._client.get(f"{self.base}/actor-runs/{run_id}", headers=self._headers)
            if r2.status_code < 400:
                data = (r2.json() or {}).get("data") or {}
                u = data.get("usageTotalUsd")
                usage = float(u) if isinstance(u, (int, float)) else None
        return ApifyResult(items=items if isinstance(items, list) else [], run_id=run_id, usage_usd=usage)

    def download(self, url: str, dest: str, *, max_bytes: int) -> int:
        """서명 달린 임시 영상 주소 → 임시 파일. 상한을 넘으면 끊고 받은 것을 지운다."""
        n = 0
        with self._client.stream("GET", url) as r:
            if r.status_code >= 400:
                raise RefineStop("download_failed", f"영상 받기 실패({r.status_code})")
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    n += len(chunk)
                    if n > max_bytes:
                        f.close()
                        os.remove(dest)
                        raise RefineStop("video_too_large", f"영상이 {max_bytes // (1024 * 1024)}MB 를 넘어 분석하지 않습니다")
                    f.write(chunk)
        return n

    def close(self) -> None:
        self._client.close()


@dataclass
class FakeApify:
    """시험·리허설용. 네트워크 0. items 는 Apify 모양 그대로(videoUrl 은 로컬 파일 경로를 가리킨다)."""
    items: list[dict[str, Any]]
    run_id: str = "fake-run"
    usage_usd: Optional[float] = 0.0088
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run_reels(self, urls: list[str], *, cap_usd: float) -> ApifyResult:
        self.calls.append({"urls": list(urls), "cap_usd": cap_usd})
        return ApifyResult(items=self.items, run_id=self.run_id, usage_usd=self.usage_usd)

    def download(self, url: str, dest: str, *, max_bytes: int) -> int:
        shutil.copyfile(url, dest)
        return os.path.getsize(dest)

    def close(self) -> None:
        return None


Analyzer = Callable[[str, float, list[float]], tuple[Optional[dict[str, Any]], Optional[float]]]   # 금액 None = 모름


def gemini_analyzer(path: str, duration: float, cut_lengths: list[float]) -> tuple[Optional[dict[str, Any]], float]:
    model = config.DRINKS_APIFY_ANALYSIS_MODEL
    ans, usage = gemini_video_json(path, model=model, system=ANALYSIS_SYSTEM, user=analysis_prompt(duration, cut_lengths),
                                   max_tokens=config.DRINKS_APIFY_ANALYSIS_MAX_OUT_TOKENS)
    # 리뷰 R2: 사용량이 안 왔으면 0원이 아니라 "모름"(None)이다 — refine 이 분석 예약액으로 적는다.
    return ans, (analysis_usd(model, usage) if usage else None)


def no_analyzer(_path: str, _duration: float, _cuts: list[float]) -> tuple[Optional[dict[str, Any]], float]:
    return None, 0.0


# ─────────────────────────────────────────────────────────────
# 한 요청 처리
# ─────────────────────────────────────────────────────────────

@dataclass
class RefineOutcome:
    outcome: str                       # done · partial · failed · stopped
    results: list[dict[str, Any]]
    analysis: dict[str, Any]
    fields: list[dict[str, Any]]
    actual_usd: Optional[float]
    run_id: Optional[str]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    deleted: bool = True


def pick_fields(per_video: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """릴스 여러 개 중 카드 칸으로 올릴 것: 분석이 된 것 중 재생 수가 가장 큰 것(없으면 첫 것)."""
    done = [v for v in per_video if v.get("fields")]
    if not done:
        return []
    best = max(done, key=lambda v: (v.get("analyzed") is True, v.get("play_count") or 0))
    return best["fields"]


def refine(job: dict[str, Any], *, provider: Any, analyzer: Analyzer, tmp_root: Optional[str] = None) -> RefineOutcome:
    inputs = plan_inputs(job)
    if not inputs:
        return RefineOutcome("stopped", [], {}, [], 0.0, None, "no_reels", "보낼 릴스 주소가 없습니다")
    try:
        run_cap_check(job, len(inputs))
    except RefineStop as exc:
        return RefineOutcome("stopped", [], {}, [], 0.0, None, exc.code, exc.message)
    sweep_old_tmp(tmp_root)
    # 리뷰 R2(2026-11-04): 실행 상한 하나를 수집과 분석에 **먼저 나눈다**. 예전엔 Apify 에 상한 전체를 주고 분석비를 그 위에 얹어
    # $0.020 + $0.003 = $0.023 이 done 으로 끝났다. 분석 예약액 = 영상 수 × 분석 예상액, Apify 상한 = 나머지.
    cap = float(job["cap_usd"])
    budget = split_budget(cap, len(inputs))
    try:
        res = provider.run_reels(inputs, cap_usd=budget["apify_cap_usd"])
    except RefineStop as exc:
        return RefineOutcome("failed", [], {}, [], None, None, exc.code, exc.message)
    rows = result_rows(res.items, inputs)
    # 사용액을 못 읽으면 예상액이 아니라 **Apify 상한**으로 적는다(작게 적지 않는다).
    spent = res.usage_usd if res.usage_usd is not None else budget["apify_cap_usd"]
    paid_stop: Optional[str] = None     # 한 번 결과를 모르는 분석이 나오면 그 뒤 유료 분석은 하지 않는다
    per_video: list[dict[str, Any]] = []
    by_url = {_canon(str(it.get("inputUrl") or it.get("url") or "")): it for it in res.items}
    with BorrowedVideos(tmp_root) as box:
        for i, row in enumerate(rows):
            entry: dict[str, Any] = {"input_url": row["input_url"], "status": row["status"], "play_count": row["play_count"], "analyzed": False}
            it = by_url.get(_canon(row["input_url"])) or {}
            vurl = it.get("videoUrl")
            if row["status"] != "ok" or not vurl:
                entry["skip"] = "no_video"
                per_video.append(entry)
                continue
            dest = os.path.join(box.path or ".", f"reel{i}.mp4")
            try:
                provider.download(str(vurl), dest, max_bytes=config.DRINKS_APIFY_ANALYSIS_MAX_BYTES)
                m = measure_video(dest)
                entry["measured"] = {k: m[k] for k in ("duration_sec", "cut_lengths", "beat_count")}
                ans: Optional[dict[str, Any]] = None
                reserve = budget["per_analysis_usd"]
                if not (m["duration_sec"] <= config.DRINKS_APIFY_ANALYSIS_MAX_SEC and m["bytes"] <= config.DRINKS_APIFY_ANALYSIS_MAX_BYTES):
                    entry["skip"] = "too_long_or_large"
                elif paid_stop:
                    entry["skip"] = paid_stop
                elif analyzer is not no_analyzer and cap - spent < reserve - 1e-9:
                    # 호출 **전에** 남은 예산을 본다 — 분석 1편 예약액이 안 남았으면 부르지 않는다.
                    entry["skip"] = paid_stop = "budget_exhausted"
                else:
                    try:
                        ans, usd = analyzer(dest, m["duration_sec"], m["cut_lengths"])
                    except Exception as exc:  # noqa: BLE001 — 보낸 뒤 실패는 청구됐을 수 있다. 예약액으로 적고 더 부르지 않는다
                        spent += reserve
                        entry["skip"] = paid_stop = "analysis_unknown"
                        entry["error"] = getattr(exc, "message", type(exc).__name__)[:200]
                    else:
                        spent += reserve if usd is None else usd
                        if usd is None:
                            entry["usage_unknown"] = True
                        entry["analyzed"] = ans is not None
                        entry["frame"] = frame_summary(ans)
                entry["fields"] = fields_from_analysis(m, ans)
            except RefineStop as exc:
                entry["skip"] = exc.code
                entry["error"] = exc.message
            finally:
                if os.path.exists(dest):
                    os.remove(dest)      # 영상 하나 잴 때마다 바로 지운다(검토 §6 시험 2 와 같다)
            per_video.append(entry)
    fields = pick_fields(per_video)
    analysis = {"per_video": per_video, "picked_from": next((v["input_url"] for v in per_video if v.get("fields") is fields), None) if fields else None,
                "deleted": box.deleted, "analyzer": "model" if any(v.get("analyzed") for v in per_video) else "ffmpeg_only",
                "budget": {**budget, "spent_usd": round(spent, 4)}}
    if spent > cap + 1e-9:
        # 이미 나간 돈은 숨기지 않는다 — 그대로 기록하고 경고한다(상한은 호출 전에 걸었다).
        analysis["over_cap_usd"] = round(spent - cap, 4)
        log.warning("drinks: 정밀화 %s 가 실행 상한 $%.4f 를 $%.4f 넘었습니다(공급자 보고액 기준)", job.get("request_id"), cap, spent - cap)
    payload = {"results": rows, "analysis": analysis, "fields": fields}
    try:
        assert_no_media_url(payload)
    except RefineStop as exc:
        return RefineOutcome("failed", [], {}, [], round(spent, 4), res.run_id, exc.code, exc.message, deleted=box.deleted)
    ok = sum(1 for r in rows if r["status"] == "ok")
    outcome = "done" if ok == len(rows) and fields else "partial" if fields else "failed"
    code = None if outcome != "failed" else ("age_restricted" if any(r["status"] == "age_restricted" for r in rows) else "no_video")
    return RefineOutcome(outcome, rows, analysis, fields, round(spent, 4), res.run_id, code,
                         None if code is None else "분석할 영상을 하나도 받지 못했습니다(연령 제한·없음) — 돈은 나갔습니다", deleted=box.deleted)


def process_job(job: dict[str, Any], rpc: Rpc, *, provider: Any, analyzer: Analyzer, tmp_root: Optional[str] = None) -> dict[str, Any]:
    lease = {"request_id": job["request_id"], "lease_token": job["lease_token"]}
    try:
        out = refine(job, provider=provider, analyzer=analyzer, tmp_root=tmp_root)
        payload = {**lease, "outcome": out.outcome, "results": out.results, "analysis": out.analysis, "fields": out.fields,
                   "actual_usd": out.actual_usd, "run_id": out.run_id, "input_count": len(plan_inputs(job)),
                   "error_code": out.error_code, "error_message": out.error_message}
        return rpc("drinks_apify_finish", payload)
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 정밀화 %s 임대를 잃어 결과를 저장하지 않습니다", job["request_id"])
            return {"status": "lease_lost"}
        raise
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 요청을 running 에 남기지 않는다(금액은 상한으로 적힌다)
        log.exception("drinks: 정밀화 %s 예외", job["request_id"])
        return rpc("drinks_apify_finish", {**lease, "outcome": "failed", "error_code": getattr(exc, "code", "worker_error"),
                                           "error_message": getattr(exc, "message", f"워커 예외: {type(exc).__name__}")})


def run_queue(rpc: Rpc, *, worker_id: str, provider: Any, analyzer: Analyzer, max_jobs: int = 5, tmp_root: Optional[str] = None) -> list[dict[str, Any]]:
    out = []
    for _ in range(max_jobs):
        got = rpc("drinks_apify_claim", {"worker_id": worker_id, "kind": "meme_refine"}) or {}
        job = got.get("job")
        if not job:
            break
        log.info("drinks: 정밀화 %s 시작(릴스 %d개, 상한 $%.2f)", job["request_id"], len(plan_inputs(job)), float(job["cap_usd"]))
        res = process_job(job, rpc, provider=provider, analyzer=analyzer, tmp_root=tmp_root)
        log.info("drinks: 정밀화 %s → %s", job["request_id"], (res or {}).get("status"))
        out.append({"request_id": job["request_id"], **(res or {})})
    return out


# ─────────────────────────────────────────────────────────────
# 명령줄
# ─────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="밈 틀 정밀화 워커(Apify + 영상 분석). --yes 없이는 실제 호출을 하지 않는다")
    ap.add_argument("--yes", action="store_true", help="실제 Apify·분석 모델 호출(돈이 든다 — 클릭 승인분만, 월 $3 안)")
    ap.add_argument("--fake", action="store_true", help="가짜 응답으로 끝까지(0원, DB 없음). 산출물 docs/preview-<날짜>/meme-refine/")
    ap.add_argument("--max", type=int, default=5)
    args = ap.parse_args(argv)
    if args.fake:
        from scripts.meme_refine_rehearsal import main as rehearsal

        return rehearsal([])
    from .drinks_collect import supabase_rpc

    if not args.yes:
        # 점유(claim)도 하지 않는다 — 점유하면 요청이 running 이 되고, 끝내지 못하면 상한이 실제 금액으로 적힌다.
        print("실제 호출은 --yes 가 필요합니다. 큐에 든 요청과 이달 누적액은 밈 보드 화면(T4 줄·[쓰자] 옆)에서 봅니다. 돈은 나가지 않았습니다.")
        return 0
    rpc = supabase_rpc()
    token = os.getenv(config.DRINKS_APIFY_TOKEN_ENV, "")
    provider = ApifyClient(token)
    try:
        res = run_queue(rpc, worker_id=config.WORKER_ID, provider=provider, analyzer=gemini_analyzer, max_jobs=args.max)
    finally:
        provider.close()
    return 1 if any(r.get("status") in ("failed", "lease_lost") for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
