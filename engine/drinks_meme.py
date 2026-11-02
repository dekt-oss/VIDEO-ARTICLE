"""주류 공장 밈형 제작 엔진 — 틀 → 글 → 렌더(로컬, 0원). 2026-11-02. docs/deviation-drinks-meme-engine.md

    python -m engine.drinks_meme            # 승인된 제작안을 로컬로 렌더한다(유료 호출 0)
    python -m engine.drinks_meme --text     # 글 초안 요청을 처리한다(LLM. 결재 안에서만, 없으면 부르지 않는다)

틀(총괄 계획 §4-3): ① top_text = 검은 바탕 위쪽 글 한 줄 + 가운데 가로 장면 ② full_title = 세로 꽉 찬 장면 + 크고 굵은 제목.
글은 코드가 그린다(ASS). 장면은 코드가 만드는 움직이는 배경이 기본이고, 우리가 산 짧은 반응 장면을 넣을 자리가 있다(유료, 이번엔 경로만).

★ 남의 영상·장면을 쓰지 않고 저장하지 않는다. 이 파일에는 내려받는 코드가 없고(tests 가 감시), 장면 칸은 우리 권리의 파일만 받는다.
★ 박자 맞춤(sync_required)은 자동 게시 대상이 아니다 — publish_gate 가 manual_audio 로 보내고, DB 도 그 상태 말고는 못 가게 막는다(0066).
  운영자가 앱에서 음원을 붙이도록 안내(manual_audio_guide)만 만든다. Audio API 에는 시작 위치 칸이 없다(기획 v2 §7-2).
★ 안전 검사는 낱말 규칙이다. 돌려 말한 농담의 뜻은 못 본다 — 그것은 사람이 승인 때 본다.
★ 정보가 들어간 밈은 근거 규칙을 탄다. 승인된 근거의 원문 인용이 없으면 멈춘다. 숫자·양·권고는 drinks_script_check 의 규칙을 그대로 쓴다.
★ 게시 워커(drinks_publish)와는 아직 연결돼 있지 않다. 게시 대기(publish_waiting)까지가 이 파일의 끝이다. 연결할 때 assert_auto_publishable 을 거쳐야 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import assemble, config, subtitles
from . import drinks_script_check as script_check
from .drinks_collect import DbError, supabase_rpc
from .drinks_explainer import ExplainerStop, _ass_color, _ass_text, _detect_freeze
from .drinks_ig_trends import hook_similarity
from .drinks_produce import Storage
from .drinks_render import BRAND, FONT_DIR, _mean_volume_db, _probe, missing_glyphs, moov_before_mdat, reel_spec_warnings, sha256_file
from .drinks_script_check import Finding, Report
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
LEASE_MIME_EXT = {"final_video": ("video/mp4", ".mp4"), "cover": ("image/jpeg", ".jpg"), "guide": ("text/plain", ".txt")}


class MemeStop(Exception):
    """멈춘다. 조용히 넘어가지 않는다 — code·message 가 화면까지 간다."""

    def __init__(self, code: str, message: str, *, findings: Optional[list[Finding]] = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.findings = code, message, findings or []


# ─────────────────────────────────────────────────────────────
# 제작안 모양
# ─────────────────────────────────────────────────────────────

def auto_beat_ms(text: str) -> int:
    """글 읽는 시간으로 비트 길이를 정한다(운영자가 안 정했을 때)."""
    return min(config.DRINKS_MEME_BEAT_MAX_MS, max(config.DRINKS_MEME_BEAT_FLOOR_MS, len(str(text or "")) * config.DRINKS_MEME_BEAT_MS_PER_CHAR))


def card_requires_sync(card: Optional[dict[str, Any]]) -> bool:
    value = str((((card or {}).get("fields") or {}).get("music_sync") or {}).get("value") or "")
    return bool(re.search(config.DRINKS_MEME_SYNC_REQUIRED_PATTERN, value, re.I))


def card_beat_ms(card: Optional[dict[str, Any]]) -> list[int]:
    """카드의 '컷 길이' 칸(영상·운영자 근거) → 비트 ms. 숫자가 아니면 빈 목록. 컷 길이 뜻이 칸마다 달라 초 단위 숫자 목록만 읽는다."""
    raw = str((((card or {}).get("fields") or {}).get("cut_lengths") or {}).get("value") or "")
    if not re.fullmatch(r"\s*[0-9]+(\.[0-9]+)?(\s*[,/·]\s*[0-9]+(\.[0-9]+)?)*\s*", raw):
        return []
    return [int(round(float(x) * 1000)) for x in re.split(r"[,/·]", raw)]


def build_spec(*, frame: str, top_line: str, beats: list[dict[str, Any]], caption: str = "", palette: str = "amber",
               sync_grade: str = "sync_free", audio: Optional[dict[str, Any]] = None, contains_info: bool = False,
               claim_ids: Optional[list[str]] = None, scene: Optional[dict[str, Any]] = None, title_keyword: str = "") -> dict[str, Any]:
    """제작안(spec) 한 벌. 비트에 ms 가 없으면 글 길이로 채운다."""
    timed = [{"text": str(b.get("text") or "").strip(), "keyword": str(b.get("keyword") or "").strip(),
              "ms": int(b["ms"]) if b.get("ms") else auto_beat_ms(str(b.get("text") or ""))} for b in beats]
    return {"frame": frame, "top_line": str(top_line or "").strip(), "title_keyword": str(title_keyword or "").strip(),
            "beats": timed, "caption": str(caption or "").strip(),
            "scene": scene or {"source": "text_bg", "palette": palette},
            "sync_grade": sync_grade, "audio": audio or {"mode": "ambient_local"},
            "contains_info": bool(contains_info), "claim_ids": [str(c) for c in (claim_ids or [])]}


def total_ms(spec: dict[str, Any]) -> int:
    return sum(int(b.get("ms") or 0) for b in spec.get("beats") or [])


def screen_texts(spec: dict[str, Any]) -> list[str]:
    """화면에 나가는 글 전부."""
    return [str(spec.get("top_line") or "")] + [str(b.get("text") or "") for b in spec.get("beats") or []]


def validate_spec(spec: dict[str, Any]) -> list[Finding]:
    """모양 검사(순수). SQL drinks_meme_blockers 와 같은 규칙이다."""
    out: list[Finding] = []

    def bad(code: str, msg: str) -> None:
        out.append(Finding(code, None, msg))

    if spec.get("frame") not in config.DRINKS_MEME_FRAMES:
        bad("meme_invalid", "화면 틀은 top_text·full_title 중 하나입니다")
    top = str(spec.get("top_line") or "").strip()
    if not top or len(top) > config.DRINKS_MEME_TEXT_MAX_CHARS:
        bad("meme_invalid", f"윗줄·제목은 1~{config.DRINKS_MEME_TEXT_MAX_CHARS}자입니다")
    beats = spec.get("beats") or []
    if not 1 <= len(beats) <= config.DRINKS_MEME_MAX_BEATS:
        bad("meme_invalid", f"비트는 1~{config.DRINKS_MEME_MAX_BEATS}개입니다")
    for b in beats:
        t = str(b.get("text") or "").strip()
        if not t or len(t) > config.DRINKS_MEME_TEXT_MAX_CHARS:
            bad("meme_invalid", f"비트 글은 1~{config.DRINKS_MEME_TEXT_MAX_CHARS}자입니다")
        ms = b.get("ms")
        if isinstance(ms, bool) or not isinstance(ms, int) or not config.DRINKS_MEME_BEAT_MIN_MS <= ms <= config.DRINKS_MEME_BEAT_MAX_MS:
            bad("meme_invalid", "비트 길이가 범위 밖입니다")
    sec = total_ms(spec) / 1000.0
    if not config.DRINKS_MEME_MIN_SEC <= sec <= config.DRINKS_MEME_MAX_SEC:
        bad("meme_duration", f"길이는 {config.DRINKS_MEME_MIN_SEC:g}~{config.DRINKS_MEME_MAX_SEC:g}초입니다(지금 {sec:g}초)")
    grade, audio = spec.get("sync_grade"), spec.get("audio") or {}
    mode = audio.get("mode")
    if grade not in config.DRINKS_MEME_SYNC_GRADES or mode not in config.DRINKS_MEME_AUDIO_MODES:
        bad("meme_invalid", "소리 등급·음원 방식이 없습니다")
    if grade == "sync_required" and (mode != "app_manual" or not str(audio.get("title") or "").strip() or audio.get("start_hint_sec") is None):
        bad("meme_sync_blocked", "박자 맞춤은 앱에서 붙일 음원 이름과 시작 지점(초)이 있어야 합니다")
    if grade == "sync_free" and mode == "app_manual":
        bad("meme_invalid", "앱에서 붙이는 음원은 박자 맞춤 등급에서만 씁니다")
    if mode == "ig_audio" and not str(audio.get("audio_id") or "").strip():
        bad("meme_invalid", "인스타 음원을 쓰려면 음원 ID 가 있어야 합니다")
    scene = spec.get("scene") or {}
    if scene.get("source") not in ("text_bg", "bought_reaction"):
        bad("meme_invalid", "장면은 글+배경 또는 우리가 산 반응 장면입니다")
    elif scene.get("source") == "text_bg" and scene.get("palette") not in config.DRINKS_MEME_PALETTES:
        bad("meme_invalid", "배경 색 이름이 없습니다")
    elif scene.get("source") == "bought_reaction" and not scene.get("asset_id"):
        bad("meme_invalid", "반응 장면을 쓰려면 산 파일이 있어야 합니다")
    return out


# ─────────────────────────────────────────────────────────────
# 안전 검사 · 근거 규칙
# ─────────────────────────────────────────────────────────────

def _joined(spec: dict[str, Any]) -> str:
    return "\n".join(screen_texts(spec) + [str(spec.get("caption") or "")])


def looks_informational(spec: dict[str, Any]) -> bool:
    return bool(re.search(config.DRINKS_MEME_INFO_PATTERN, _joined(spec), re.I))


def check_safety(spec: dict[str, Any], *, claims: Optional[list[dict[str, Any]]] = None, sources: Optional[list[dict[str, Any]]] = None,
                 card: Optional[dict[str, Any]] = None, hooks: Optional[list[str]] = None) -> Report:
    """제작안 검사(0원). blocks 가 하나라도 있으면 제작하지 않는다. claims = 승인된 근거 묶음의 주장들."""
    rep = Report()
    rep.blocks.extend(validate_spec(spec))
    text = _joined(spec)
    for code, label, pattern in config.DRINKS_MEME_UNSAFE_RULES:
        m = re.search(pattern, text, re.I)
        if m:
            rep.blocks.append(Finding(code, None, f"{label} — '{m.group(0)}' 는 쓰지 않습니다"))
    if re.search(config.DRINKS_MEME_FOREIGN_MEDIA_PATTERN, json.dumps(spec, ensure_ascii=False), re.I):
        rep.blocks.append(Finding("meme_foreign_media", None, "제작안에 남의 영상·게시물 주소가 들어 있습니다"))
    if spec.get("sync_grade") == "sync_free" and card_requires_sync(card):
        rep.blocks.append(Finding("meme_sync_blocked", None, "이 카드는 박자에 맞춰야 성립한다고 적혀 있습니다 — 박자 맞춤으로 두거나 카드 칸을 고치세요"))
    for hook in hooks or []:
        for t in screen_texts(spec):
            if hook_similarity(t, hook) >= config.DRINKS_MEME_COPY_SIMILAR_MAX:
                rep.blocks.append(Finding("meme_copied_text", None, f"원본 릴스의 글과 거의 같습니다: {t[:40]}"))
                break
    _check_evidence(spec, rep, claims or [], sources or [])
    scene = spec.get("scene") or {}
    if scene.get("source") == "bought_reaction" and "AI 생성" not in str(spec.get("caption") or ""):
        rep.blocks.append(Finding("meme_ai_label_missing", None, "산 장면을 쓰면 캡션에 'AI 생성 영상' 한 줄을 넣습니다(기획 v2 §3-4)"))
    return rep


def _check_evidence(spec: dict[str, Any], rep: Report, claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    """정보 밈의 근거 규칙 + 캡션 규칙. 농담도 캡션은 같은 검사를 받는다(게시 워커가 게시 직전에 같은 검사로 멈춘다)."""
    declared = bool(spec.get("contains_info"))
    if looks_informational(spec) and not declared:
        rep.blocks.append(Finding("meme_info_undeclared", None, "정보로 읽히는 말이 있습니다 — '정보 포함'으로 표시하고 근거를 붙이거나 말을 바꾸세요"))
    cids = [str(c) for c in spec.get("claim_ids") or []]
    known = {str(c.get("claim_id")): c for c in claims if isinstance(c, dict)}
    usable: list[dict[str, Any]] = []
    if declared:
        if not cids:
            rep.blocks.append(Finding("meme_evidence_missing", None, "정보가 들어간 밈인데 근거가 없습니다 — 멈춥니다"))
        for c in cids:
            if c not in known:
                rep.blocks.append(Finding("meme_evidence_missing", None, f"승인된 근거에 없는 주장입니다: {c}"))
            elif script_check._is_derived(known[c]):
                rep.blocks.append(Finding("derived_claim_cited", None, f"원문 인용이 아닌 근거입니다: {c}"))
            else:
                usable.append(known[c])
        for t in screen_texts(spec):
            for f in script_check.check_caption(t, usable, sources=sources).blocks:
                rep.blocks.append(Finding(f.code, None, f"화면 글: {f.message}"))
    # 농담의 캡션은 근거가 없으므로 숫자·양·권고가 있으면 막힌다. 정보 밈은 자기 근거 안에서만 말한다.
    rep.blocks.extend(script_check.check_caption(str(spec.get("caption") or ""), usable, sources=sources).blocks)


# ─────────────────────────────────────────────────────────────
# 소리 등급 → 게시 문
# ─────────────────────────────────────────────────────────────

def publish_gate(spec: dict[str, Any]) -> dict[str, Any]:
    """제작이 끝난 뒤 어디로 가나. 박자 맞춤은 자동 게시 대기열로 못 간다."""
    if spec.get("sync_grade") == "sync_free" and (spec.get("audio") or {}).get("mode") != "app_manual":
        return {"auto_publish": True, "next_status": "publish_waiting", "code": None, "reason": None}
    return {"auto_publish": False, "next_status": "manual_audio", "code": "sync_required",
            "reason": "박자에 맞춰야 하는 밈이라 자동 게시하지 않습니다. 앱에서 음원을 붙여 올리세요."}


def assert_auto_publishable(spec: dict[str, Any]) -> None:
    """★ 자동 게시로 넘기는 코드는 반드시 이것을 먼저 부른다(tests/test_drinks_meme.py 가 감시)."""
    gate = publish_gate(spec)
    if not gate["auto_publish"]:
        raise MemeStop(gate["code"], gate["reason"])


def manual_audio_guide(spec: dict[str, Any], caption: Optional[str] = None) -> str:
    """운영자가 앱에서 음원을 붙이는 안내. 지어낸 값 없이 제작안에 적힌 것만 옮긴다."""
    a = spec.get("audio") or {}
    t, lines = 0, []
    for i, b in enumerate(spec.get("beats") or [], 1):
        lines.append(f"  {t / 1000:.1f}초  {i}번 글: {b.get('text')}")
        t += int(b.get("ms") or 0)
    who = f" ({a.get('artist')})" if a.get("artist") else ""
    return "\n".join([
        "이 영상은 박자에 맞춰야 하는 밈이라 자동으로 올리지 않습니다. 소리 없는 영상으로 만들었습니다.",
        "",
        "1. 이 영상을 휴대폰으로 옮겨 인스타 앱의 릴스 만들기에 올립니다.",
        f"2. 음원에서 '{a.get('title')}'{who} 를 찾습니다." + (f" 음원 ID: {a.get('audio_id')}" if a.get("audio_id") else ""),
        f"3. 음원을 {a.get('start_hint_sec')}초 지점부터 시작합니다.",
        "4. 아래 글이 바뀌는 시각이 박자에 맞는지 귀로 확인합니다. 안 맞으면 시작 지점을 옮깁니다.",
        *lines,
        "5. 영상 소리는 0 으로 둡니다(이 영상에는 무음만 들어 있습니다).",
        "6. 캡션을 붙여 넣고 게시합니다.",
        f"   {caption if caption is not None else spec.get('caption')}",
        "7. 게시한 릴스 주소를 밈 보드에 등록합니다.",
    ])


# ─────────────────────────────────────────────────────────────
# 반응 장면 — 우리가 산 파일만. 이번에는 사지 않는다
# ─────────────────────────────────────────────────────────────

@dataclass
class SceneAsset:
    """장면 칸에 넣는 파일. rights·provenance 가 우리 것이어야 받는다."""
    path: str
    sha256: str
    rights: str
    provenance: dict[str, Any] = field(default_factory=dict)


def validate_scene_asset(asset: SceneAsset) -> None:
    if asset.rights not in config.DRINKS_MEME_SCENE_RIGHTS:
        raise MemeStop("meme_foreign_media", f"권리가 확인되지 않은 파일은 장면으로 쓰지 않습니다({asset.rights})")
    if re.search(config.DRINKS_MEME_FOREIGN_MEDIA_PATTERN, json.dumps(asset.provenance, ensure_ascii=False), re.I):
        raise MemeStop("meme_foreign_media", "남의 게시물에서 온 파일은 장면으로 쓰지 않습니다")
    if not os.path.isfile(asset.path):
        raise MemeStop("scene_missing", "장면 파일이 없습니다")
    if sha256_file(asset.path) != asset.sha256:
        raise MemeStop("scene_corrupt", "장면 파일의 해시가 등록값과 다릅니다")


def reaction_quote() -> dict[str, Any]:
    """반응 장면 1개 견적(기획 v2 §5). 계획값이지 실측이 아니다."""
    clip = round(config.DRINKS_MEME_REACTION_CLIP_SEC * config.DRINKS_MEME_REACTION_CLIP_USD_PER_SEC, 4)
    return {"clip_sec": config.DRINKS_MEME_REACTION_CLIP_SEC, "clip_usd": clip, "image_usd": config.DRINKS_MEME_REACTION_IMAGE_USD,
            "total_usd": round(clip + config.DRINKS_MEME_REACTION_IMAGE_USD, 4)}


def buy_reaction_scene(prompt: str, *, approval_id: Optional[str] = None, buyer: Optional[Callable[..., SceneAsset]] = None) -> SceneAsset:
    """우리 반응 장면을 사는 자리. ★ 지금은 꺼져 있다 — 공급자 연결(buyer)이 없고, 스위치는 코드를 바꿔야 켜진다.

    켤 때: 결재(0054 drink_spend_approvals) 안에서 사는 buyer 를 넘긴다. 글자 없는 장면이어야 하고, 산 파일은 그대로 scene 칸으로 간다."""
    if not config.DRINKS_MEME_REACTION_PAID_ENABLED or buyer is None:
        raise MemeStop("paid_disabled", "반응 장면 구매는 결재 전이라 꺼져 있습니다(약 $%.2f). 글+배경으로 만드세요" % reaction_quote()["total_usd"])
    if not approval_id:
        raise MemeStop("approval_missing", "결재 없이 반응 장면을 사지 않습니다")
    return buyer(prompt, approval_id=approval_id, quote=reaction_quote())


# ─────────────────────────────────────────────────────────────
# 글 배치
# ─────────────────────────────────────────────────────────────

def _font(size: int):
    from PIL import ImageFont

    return ImageFont.truetype(os.path.join(FONT_DIR, config.DRINKS_MEME_FONT_FILE), size)


def _pack(groups: list[str], font, width: int, max_lines: int) -> Optional[list[str]]:
    """뜻 단위 덩어리를 줄로 묶는다. 덩어리 안에서는 끊지 않는다 — 못 넣으면 None(글자 크기를 줄여 다시 본다)."""
    if any(font.getlength(g) > width for g in groups) and max_lines == 1:
        return None
    lines: list[str] = []
    if len(groups) <= max_lines:
        lines = list(groups)
    else:
        cur = ""
        for g in groups:
            cand = f"{cur} {g}".strip()
            if cur and font.getlength(cand) > width:
                lines.append(cur)
                cur = g
            else:
                cur = cand
        if cur:
            lines.append(cur)
    if len(lines) > max_lines or any(font.getlength(ln) > width for ln in lines):
        return None
    return lines


def layout_text(text: str, rule: dict[str, Any], *, center_x: int, y: int, anchor: int) -> dict[str, Any]:
    """줄과 글자 크기를 정하고 그림 위 상자를 계산한다. 못 넣으면 자르지 않고 overflow 로 표시한다."""
    width = config.RENDER_WIDTH - 2 * config.DRINKS_MEME_TEXT_SIDE_PX
    raw = str(text or "")
    groups = [g.strip() for g in raw.split("\n") if g.strip()] if "\n" in raw else subtitles.phrase_groups(raw)
    if rule["max_lines"] == 1:
        groups = [" ".join(groups)]
    groups = groups or [raw]
    lines, size, font = None, rule["size"], None
    for size in range(rule["size"], rule["min_size"] - 1, -2):
        font = _font(size)
        lines = _pack(groups, font, width, rule["max_lines"])
        if lines is not None:
            break
    overflow = lines is None
    lines = lines or groups
    ascent, descent = font.getmetrics()
    h = (ascent + descent) * len(lines)
    w = int(max(font.getlength(ln) for ln in lines))
    y0 = y - h if anchor == 2 else (y - h // 2 if anchor == 5 else y)
    return {"lines": lines, "size": size, "overflow": overflow, "anchor": anchor, "pos": (center_x, y),
            "box": [center_x - w // 2, y0, center_x + w // 2, y0 + h]}


def scene_rect(frame: str) -> tuple[int, int, int, int]:
    """장면 자리(x, y, w, h)."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    if frame == "top_text":
        sh = config.DRINKS_MEME_LANDSCAPE_H
        return (0, (h - sh) // 2, w, sh)
    return (0, 0, w, h)


def build_layers(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """화면 글 층. 시각은 ms. 윗줄·제목은 내내 있고, 비트 글은 차례로 바뀐다(마지막 비트는 끝까지)."""
    frame = spec["frame"]
    end = total_ms(spec)
    accent = spec.get("title_keyword") or ""
    cx = config.RENDER_WIDTH // 2
    rect = scene_rect(frame)
    layers: list[dict[str, Any]] = []
    if frame == "top_text":
        top = layout_text(spec["top_line"], config.DRINKS_MEME_TOP_LINE, center_x=cx, y=rect[1] - 36, anchor=2)
        beat_rule, beat_y, beat_anchor = config.DRINKS_MEME_BEAT_TOP, rect[1] + rect[3] // 2, 5
    else:
        top = layout_text(spec["top_line"], config.DRINKS_MEME_TITLE, center_x=cx, y=config.DRINKS_MEME_TITLE["y"], anchor=8)
        beat_rule, beat_y, beat_anchor = config.DRINKS_MEME_BEAT_FULL, config.DRINKS_MEME_BEAT_FULL["y"], 8
    layers.append({"kind": "top", "text": spec["top_line"], "start_ms": 0, "end_ms": end, "keyword": accent, "pop": False, **top})
    t = 0
    for b in spec["beats"]:
        ly = layout_text(b["text"], beat_rule, center_x=cx, y=beat_y, anchor=beat_anchor)
        layers.append({"kind": "beat", "text": b["text"], "start_ms": t, "end_ms": t + int(b["ms"]), "keyword": b.get("keyword") or "", "pop": True, **ly})
        t += int(b["ms"])
    return layers


def _ass_lines(ly: dict[str, Any], accent_color: str) -> str:
    parts = []
    for ln in ly["lines"]:
        s = _ass_text(ln)
        kw = _ass_text(ly.get("keyword") or "")
        if kw and kw in s:
            s = s.replace(kw, f"{{\\c{accent_color}}}{kw}{{\\c&HFFFFFF&}}", 1)
        parts.append(s)
    pop = "\\fscx86\\fscy86\\t(0,110,\\fscx100\\fscy100)" if ly.get("pop") else ""
    return f"{{\\an{ly['anchor']}\\pos({ly['pos'][0]},{ly['pos'][1]})\\fs{ly['size']}{pop}}}" + "\\N".join(parts)


def build_ass(spec: dict[str, Any], layers: list[dict[str, Any]]) -> str:
    """줄바꿈은 위에서 정했으므로 자동 줄바꿈을 끈다(WrapStyle 2) — 계산한 상자와 그림이 같아야 안전 영역 검사가 뜻이 있다."""
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    accent = _ass_color(config.DRINKS_MEME_ACCENT[spec["frame"]])
    name = config.DRINKS_MEME_FONT_NAME
    head = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {w}\nPlayResY: {h}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
            f"Style: Meme,{name},64,&H00FFFFFF,&H00000000,&H64000000,0,0,1,5,0,2,0,0,0\n"
            f"Style: Brand,{name},30,&H00A0B8C8,&H00000000,&H64000000,0,0,1,2,0,2,0,0,0\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    rows = [f"Dialogue: 1,{subtitles.ass_timestamp(ly['start_ms'] / 1000.0)},{subtitles.ass_timestamp(ly['end_ms'] / 1000.0)},Meme,,0,0,0,,{_ass_lines(ly, accent)}"
            for ly in layers]
    end = subtitles.ass_timestamp(total_ms(spec) / 1000.0)
    brand_y = config.RENDER_HEIGHT - config.DRINKS_EXPLAINER_SAFE_BOTTOM_PX
    label = BRAND["name"] + ("  ·  AI 생성 장면" if (spec.get("scene") or {}).get("source") == "bought_reaction" else "")
    rows.append(f"Dialogue: 0,{subtitles.ass_timestamp(0.0)},{end},Brand,,0,0,0,,{{\\an2\\pos({config.RENDER_WIDTH // 2},{brand_y})}}{_ass_text(label)}")
    return head + "\n".join(rows) + "\n"


# ─────────────────────────────────────────────────────────────
# 렌더 (로컬 ffmpeg, 0원)
# ─────────────────────────────────────────────────────────────

def _run(argv: list[str], *, cwd: Optional[str] = None) -> None:
    proc = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", cwd=cwd)
    if proc.returncode != 0:
        raise MemeStop("render_failed", f"ffmpeg 실패({proc.returncode}): {(proc.stderr or '')[-400:]}")


def ambient_expr(palette: str) -> str:
    """코드로 합성한 분위기 음원 — 박자가 없는 낮은 화음. 남의 음악을 쓰지 않으므로 권리 문제가 없다. ★ 듣기 좋은지는 귀로 판정한 적 없다."""
    f1, f2, f3 = config.DRINKS_MEME_AMBIENT_CHORDS.get(palette, config.DRINKS_MEME_AMBIENT_CHORDS["amber"])
    return (f"0.20*sin(2*PI*{f1}*t)*(0.7+0.3*sin(2*PI*0.21*t))"
            f"+0.14*sin(2*PI*{f2}*t)*(0.7+0.3*sin(2*PI*0.13*t))"
            f"+0.10*sin(2*PI*{f3}*t)*(0.7+0.3*sin(2*PI*0.08*t))")


def build_render_argv(spec: dict[str, Any], *, ass_name: str, out_name: str, scene_name: Optional[str] = None) -> list[str]:
    """작업 폴더에서 실행하는 상대 경로 전용 명령(한글 경로의 글꼴을 필터가 열면 ffmpeg 가 죽는다 — drinks_explainer.prepare_burn_dir)."""
    w, h, fps = config.RENDER_WIDTH, config.RENDER_HEIGHT, config.RENDER_FPS
    dur = total_ms(spec) / 1000.0
    frame = spec["frame"]
    x, y, sw, sh = scene_rect(frame)
    scene = spec.get("scene") or {}
    palette = scene.get("palette") or "amber"
    c0, c1 = config.DRINKS_MEME_PALETTES.get(palette, config.DRINKS_MEME_PALETTES["amber"])
    grad = (f"gradients=s={sw}x{sh}:r={fps}:d={dur:.3f}:c0={c0}:c1={c1}:n=2:speed={config.DRINKS_MEME_BG_SPEED}"
            f":x0=0:y0=0:x1={sw}:y1={sh}")
    graph = (f"color=c=black:s={w}x{h}:r={fps}:d={dur:.3f}[base];{grad}[sc];[base][sc]overlay={x}:{y}[v0]" if frame == "top_text"
             else f"{grad}[v0]")
    inputs: list[str] = []
    last = "v0"
    if scene_name:
        # 반응 장면은 지정한 비트부터 재생하고, 끝나면 배경으로 돌아간다. 늘이거나 멈춰 세우지 않는다(사진+움직임 금지 규칙).
        inputs += ["-i", scene_name]
        beat = int(scene.get("beat") or 0)
        start = sum(int(b["ms"]) for b in spec["beats"][:beat]) / 1000.0
        graph += (f";[0:v]fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},setpts=PTS-STARTPTS+{start:.3f}/TB[react]"
                  f";[v0][react]overlay={x}:{y}:eof_action=pass[v1]")
        last = "v1"
    graph += f";[{last}]ass=filename='{assemble.filter_path(ass_name)}':fontsdir=fonts,format=yuv420p[vout]"
    mode = (spec.get("audio") or {}).get("mode")
    audio_src = (f"aevalsrc='{ambient_expr(palette)}':s=48000:d={dur:.3f}" if mode == "ambient_local"
                 else f"anullsrc=r=48000:cl=mono:d={dur:.3f}")
    inputs += ["-f", "lavfi", "-i", audio_src]
    audio_index = 1 if scene_name else 0
    af = ["-af", f"lowpass=f=1200,afade=t=in:d=0.6,afade=t=out:st={max(0.0, dur - 0.8):.3f}:d=0.8"] if mode == "ambient_local" else []
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", graph,
            "-map", "[vout]", "-map", f"{audio_index}:a", *af, "-t", f"{dur:.3f}", "-r", str(fps),
            "-c:v", "libx264", "-preset", config.DRINKS_MEME_X264_PRESET, "-crf", str(config.DRINKS_MEME_X264_CRF), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-movflags", "+faststart", out_name]


def _text_box_problems(layers: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    for ly in layers:
        if ly["overflow"]:
            out.append("text_overflow")
        x0, y0, x1, y1 = ly["box"]
        if x0 < 0 or y0 < 0 or x1 > w - config.DRINKS_EXPLAINER_SAFE_RIGHT_PX or y1 > h - config.DRINKS_EXPLAINER_SAFE_BOTTOM_PX:
            out.append("text_out_of_safe_area")
    return sorted(set(out))


def glyph_problems(spec: dict[str, Any]) -> list[str]:
    font = _font(64)
    return sorted({ch for t in screen_texts(spec) for ch in missing_glyphs(font, t)})


def evaluate_qa(spec: dict[str, Any], layers: list[dict[str, Any]], probe: dict[str, Any], *, file_bytes: int, moov_first: bool,
                cover_mime: str, cover_bytes: int, mean_db: Optional[float], freeze: list[Any]) -> dict[str, Any]:
    """자동 검사(순수). blocks 가 있으면 게시 대기로 못 간다. 통과해도 '돌아간다'일 뿐 품질 합격이 아니다(G3)."""
    blocks: list[str] = []
    warns: list[str] = []
    if (probe.get("width"), probe.get("height")) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
        blocks.append("not_vertical_1080x1920")
    dur = float(probe.get("duration_sec") or 0)
    if not config.DRINKS_MEME_MIN_SEC - 0.1 <= dur <= config.DRINKS_MEME_MAX_SEC + 0.1:
        blocks.append("duration_out_of_range")
    blocks.extend(reel_spec_warnings(probe, file_bytes, moov_first, cover_mime, cover_bytes))
    blocks.extend(_text_box_problems(layers))
    if (spec.get("audio") or {}).get("mode") == "ambient_local" and (mean_db is None or mean_db < -60):
        blocks.append("ambient_silent")
    if freeze:
        warns.append("frozen_span")
    return {"ok": not blocks, "blocks": sorted(set(blocks)), "warnings": warns, "probe": probe, "mean_volume_db": mean_db, "freeze": freeze,
            "moov_first": moov_first, "layers": [{k: ly[k] for k in ("kind", "text", "start_ms", "end_ms", "size", "box", "lines")} for ly in layers]}


@dataclass
class MemeOutput:
    status: str                 # publish_waiting · manual_audio · stopped
    gate: dict[str, Any]
    safety: dict[str, Any]
    qa: dict[str, Any] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)
    guide: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def render_meme(spec: dict[str, Any], work_dir: str, *, scene_asset: Optional[SceneAsset] = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """제작안 → final.mp4 + cover.jpg. 돈·네트워크 0. 유료 공급자를 부르는 경로가 없다."""
    os.makedirs(work_dir, exist_ok=True)
    fonts = os.path.join(work_dir, "fonts")
    os.makedirs(fonts, exist_ok=True)
    shutil.copyfile(os.path.join(FONT_DIR, config.DRINKS_MEME_FONT_FILE), os.path.join(fonts, config.DRINKS_MEME_FONT_FILE))
    missing = glyph_problems(spec)
    if missing:
        raise MemeStop("glyph_missing", f"글꼴에 없는 글자가 있습니다: {' '.join(missing)}")
    layers = build_layers(spec)
    problems = _text_box_problems(layers)
    if "text_overflow" in problems:
        raise MemeStop("text_overflow", "글이 길어 화면 틀에 안 들어갑니다 — 줄이세요")
    with open(os.path.join(work_dir, "meme.ass"), "w", encoding="utf-8") as f:
        f.write(build_ass(spec, layers))
    scene_name = None
    if (spec.get("scene") or {}).get("source") == "bought_reaction":
        if scene_asset is None:
            raise MemeStop("scene_missing", "반응 장면 파일이 없습니다")
        validate_scene_asset(scene_asset)
        scene_name = "scene_input.mp4"
        shutil.copyfile(scene_asset.path, os.path.join(work_dir, scene_name))
    _run(build_render_argv(spec, ass_name="meme.ass", out_name="final.mp4", scene_name=scene_name), cwd=work_dir)
    out = os.path.join(work_dir, "final.mp4")
    cover = os.path.join(work_dir, "cover.jpg")
    first_mid = int(spec["beats"][0]["ms"]) / 2000.0
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{first_mid:.3f}", "-i", "final.mp4", "-frames:v", "1", "-q:v", "3", "cover.jpg"], cwd=work_dir)
    probe = _probe(out)
    try:
        freeze = [[round(s, 3), round(d, 3)] for s, d in _detect_freeze(out, config.DRINKS_MEME_FREEZE_MIN_SEC)]
    except ExplainerStop:
        freeze = []
    qa = evaluate_qa(spec, layers, probe, file_bytes=os.path.getsize(out), moov_first=moov_before_mdat(out), cover_mime="image/jpeg",
                     cover_bytes=os.path.getsize(cover), mean_db=_mean_volume_db(out), freeze=freeze)
    files = [{"path": out, "role": "final_video", "mime": "video/mp4", "width": probe["width"], "height": probe["height"],
              "duration_ms": int(probe["duration_sec"] * 1000), "sha256": sha256_file(out), "bytes": os.path.getsize(out)},
             {"path": cover, "role": "cover", "mime": "image/jpeg", "width": 1080, "height": 1920, "sha256": sha256_file(cover), "bytes": os.path.getsize(cover)}]
    return files, qa


def produce(spec: dict[str, Any], work_dir: str, *, claims: Optional[list[dict[str, Any]]] = None, sources: Optional[list[dict[str, Any]]] = None,
            card: Optional[dict[str, Any]] = None, hooks: Optional[list[str]] = None, scene_asset: Optional[SceneAsset] = None) -> MemeOutput:
    """검사 → 렌더 → 자동 검사 → 게시 문. 막히면 멈추고 이유를 돌려준다. 게시 호출은 어디에도 없다."""
    rep = check_safety(spec, claims=claims, sources=sources, card=card, hooks=hooks)
    gate = publish_gate(spec)
    if not rep.ok:
        return MemeOutput("stopped", gate, rep.as_dict(), error_code=rep.blocks[0].code, error_message="; ".join(f"{f.code}: {f.message}" for f in rep.blocks)[:1500])
    try:
        files, qa = render_meme(spec, work_dir, scene_asset=scene_asset)
    except MemeStop as exc:
        return MemeOutput("stopped", gate, rep.as_dict(), error_code=exc.code, error_message=exc.message)
    if not qa["ok"]:
        return MemeOutput("stopped", gate, rep.as_dict(), qa=qa, error_code="auto_qa_failed", error_message="자동 검사 실패: " + ", ".join(qa["blocks"]))
    guide = None
    if not gate["auto_publish"]:
        guide = manual_audio_guide(spec)
        path = os.path.join(work_dir, "guide.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(guide + "\n")
        files.append({"path": path, "role": "guide", "mime": "text/plain", "sha256": sha256_file(path), "bytes": os.path.getsize(path)})
    return MemeOutput(gate["next_status"], gate, rep.as_dict(), qa=qa, files=files, guide=guide)


# ─────────────────────────────────────────────────────────────
# 글 초안 (LLM) — 코드 경로만. 결재가 없으면 부르지 않는다
# ─────────────────────────────────────────────────────────────

TEXT_SYSTEM = """너는 술 이야기 인스타 계정 '술째리고'의 짧은 밈 글을 쓴다. JSON 으로만 답한다.
형식: {"top_line": "화면 위쪽 글", "beats": [{"text": "차례로 바뀌는 글", "keyword": "강조할 낱말(그 글 안에 있는 말)"}], "caption": "캡션 한두 줄"}
규칙:
- 친구한테 말하듯 쉬운 구어체. 비트는 2~4개, 비트 하나는 뜻 하나, 18자 안쪽.
- 틀만 빌린다. 원본 릴스의 글을 그대로 옮기지 않는다.
- 농담이다. 사실·숫자·효능·법령·연구를 말하지 않는다. 없는 사실을 지어내지 않는다.
- 술을 권하지 않는다. 많이 마시는 것, 취한 것, 필름 끊긴 것을 자랑하지 않는다. 미성년·학교·교복·운전·임신을 소재로 삼지 않는다.
- 캡션에 숫자와 "~해 보세요" 같은 권고를 쓰지 않는다."""


def text_prompt(card: dict[str, Any], topic: Optional[dict[str, Any]], feedback: Optional[list[str]] = None) -> str:
    """LLM 입력은 카드의 글 칸·소재 문장뿐이다. 영상·주소는 넘기지 않는다."""
    fields = (card or {}).get("fields") or {}
    parts = [f"밈 이름: {(card or {}).get('name') or ''}", f"구조: {(card or {}).get('structure') or (fields.get('structure') or {}).get('value') or '미상'}"]
    for k, label in (("cover_text", "원본 표지 글(베끼지 말 것)"), ("caption_hook", "원본 캡션 첫 문장(베끼지 말 것)"), ("twist_at", "반전 시점")):
        if (fields.get(k) or {}).get("value"):
            parts.append(f"{label}: {fields[k]['value']}")
    if topic:
        parts.append(f"소재: {topic.get('title') or ''} / {topic.get('question') or ''}")
    if feedback:
        parts.append("지난 글이 막힌 이유(고쳐서 다시 쓴다): " + "; ".join(feedback))
    return "\n".join(parts)


def llm_write_text(system: str, user: str) -> dict[str, Any]:
    from . import llm

    llm.set_text_purpose("drinks_meme_text")
    return llm.call_json(model=config.DRINKS_MEME_TEXT_MODEL, system=system, user=user, max_tokens=config.DRINKS_MEME_TEXT_MAX_OUT_TOKENS)


def spec_from_llm(out: dict[str, Any], *, frame: str, palette: str = "amber", card: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """모델 답 → 제작안. 글 칸만 받는다. 소리는 기본값(분위기 음원)이고, 카드가 박자 맞춤이면 멈추도록 등급을 그대로 맞춘다."""
    raw = out.get("beats") if isinstance(out, dict) else None
    if not isinstance(raw, list) or not raw:
        raise MemeStop("llm_bad_output", "모델 답에 비트가 없습니다")
    beats = [{"text": str(b.get("text") or ""), "keyword": str(b.get("keyword") or "")} for b in raw if isinstance(b, dict)]
    sync = "sync_required" if card_requires_sync(card) else "sync_free"
    audio = {"mode": "app_manual", "title": str((card or {}).get("name") or ""), "audio_id": (card or {}).get("audio_id")} if sync == "sync_required" else {"mode": "ambient_local"}
    spec = build_spec(frame=frame, top_line=str(out.get("top_line") or ""), beats=beats, caption=str(out.get("caption") or ""), palette=palette,
                      sync_grade=sync, audio=audio)
    wanted = card_beat_ms(card)
    if len(wanted) == len(spec["beats"]):   # 정밀 틀의 컷 길이가 있으면 그대로 쓴다
        for b, ms in zip(spec["beats"], wanted):
            b["ms"] = ms
    return fit_duration(spec)


def fit_duration(spec: dict[str, Any]) -> dict[str, Any]:
    """비트 길이를 비율대로 늘이거나 줄여 6~15초 안에 넣는다(글 길이로 정한 값일 때만 쓴다). 나머지 ms 는 마지막 비트가 받는다."""
    total = total_ms(spec)
    lo, hi = int(config.DRINKS_MEME_MIN_SEC * 1000), int(config.DRINKS_MEME_MAX_SEC * 1000)
    target = lo if total < lo else hi if total > hi else total
    if total <= 0 or target == total:
        return spec
    beats = spec["beats"]
    for b in beats:
        b["ms"] = int(b["ms"] * target / total)
    beats[-1]["ms"] += target - total_ms(spec)
    return spec


def write_text(job: dict[str, Any], rpc: Rpc, *, call: Callable[[str, str], dict[str, Any]] = llm_write_text) -> dict[str, Any]:
    """글 초안 한 건. 호출마다 결재 안에서 먼저 가잡고(0066 drinks_meme_hold) 실제 금액으로 확정한다. 막히면 한 번만 다시 쓴다."""
    from .drinks_develop import capture_usage, estimate_usd

    lease = {"draft_id": job["draft_id"], "lease_token": job["lease_token"]}
    card, topic = job.get("card") or {}, job.get("topic")
    hooks = [str(((card.get("fields") or {}).get(k) or {}).get("value") or "") for k in ("cover_text", "caption_hook")]
    hooks = [h for h in hooks if h]
    feedback: Optional[list[str]] = None
    spec: Optional[dict[str, Any]] = None
    rep = Report()
    for _ in range(2):
        user = text_prompt(card, topic, feedback)
        est = estimate_usd(config.DRINKS_MEME_TEXT_MODEL, len(TEXT_SYSTEM) + len(user), config.DRINKS_MEME_TEXT_MAX_OUT_TOKENS)
        hold = rpc("drinks_meme_hold", {**lease, "est_usd": est, "model": config.DRINKS_MEME_TEXT_MODEL})
        try:
            with capture_usage() as box:
                out = call(TEXT_SYSTEM, user)
        except Exception:
            rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "released", "note": "호출 실패"})
            raise
        rpc("drinks_develop_settle", {"hold_id": hold["hold_id"], "outcome": "settled", "actual_usd": round(box.usd, 6)})
        spec = spec_from_llm(out, frame=job.get("frame") or "top_text", card=card)
        rep = check_safety(spec, card=card, hooks=hooks)
        if rep.ok:
            break
        feedback = [f"{f.code}: {f.message}" for f in rep.blocks]
    if not rep.ok:
        return rpc("drinks_meme_finish_text", {**lease, "outcome": "stopped", "error_code": rep.blocks[0].code,
                                               "error_message": "; ".join(f"{f.code}: {f.message}" for f in rep.blocks)[:1500]})
    return rpc("drinks_meme_finish_text", {**lease, "outcome": "ok", "spec": spec})


# ─────────────────────────────────────────────────────────────
# 워커 — 승인된 제작안만. 사람 승인을 대신하지 않는다
# ─────────────────────────────────────────────────────────────

def process_render_job(job: dict[str, Any], rpc: Rpc, storage: Storage) -> dict[str, Any]:
    lease = {"draft_id": job["draft_id"], "lease_token": job["lease_token"]}
    spec = job["spec"]
    work = tempfile.mkdtemp(prefix=f"drinks_meme_{str(job['draft_id'])[:8]}_")
    try:
        asset = None
        s = job.get("scene_asset")
        if s:
            local = os.path.join(work, "scene_in.mp4")
            storage.get(s["storage_key"], local)
            asset = SceneAsset(path=local, sha256=s["sha256"], rights=s["rights"], provenance=s.get("provenance") or {})
        res = produce(spec, os.path.join(work, "out"), claims=job.get("claims"), sources=job.get("sources"), card=job.get("card"),
                      hooks=job.get("hooks"), scene_asset=asset)
        if res.status == "stopped":
            return rpc("drinks_meme_finish", {**lease, "outcome": "stopped", "error_code": res.error_code, "error_message": res.error_message,
                                              "safety": res.safety, "qa": _qa_for_db(res.qa)})
        # 작업마다 새 위치 — 옛 파일을 덮지 않는다(Storage.put 은 덮어쓰기를 거부한다).
        prefix = f"drinks/memes/{job['draft_id']}/{str(job['lease_token'])[:8]}"
        out_files = []
        for f in res.files:
            mime, ext = LEASE_MIME_EXT[f["role"]]
            key = storage.put(f["path"], f"{prefix}/{f['role']}{ext}", mime)
            out_files.append({"role": f["role"], "storage_key": key, "sha256": f["sha256"], "bytes": f["bytes"], "mime": mime,
                              "width": f.get("width"), "height": f.get("height"), "duration_ms": f.get("duration_ms")})
        # 어디로 갈지는 DB 가 sync_grade 로 정한다. 워커가 고르지 않는다.
        return rpc("drinks_meme_finish", {**lease, "outcome": "rendered", "files": out_files, "safety": res.safety, "qa": _qa_for_db(res.qa), "guide": res.guide})
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 밈 %s 임대를 잃어 결과를 저장하지 않습니다", job["draft_id"])
            return {"status": "lease_lost"}
        raise
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 제작안을 rendering 에 남기지 않는다
        log.exception("drinks: 밈 %s 예외", job["draft_id"])
        return rpc("drinks_meme_finish", {**lease, "outcome": "failed", "error_code": getattr(exc, "code", "worker_error"),
                                          "error_message": getattr(exc, "message", f"워커 예외: {type(exc).__name__}")})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _qa_for_db(qa: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (qa or {}).items() if k != "layers"}


def run_queue(rpc: Rpc, storage: Storage, *, worker_id: str, kind: str = "render", max_jobs: int = 5,
              call: Callable[[str, str], dict[str, Any]] = llm_write_text) -> list[dict[str, Any]]:
    out = []
    for _ in range(max_jobs):
        got = rpc("drinks_meme_claim", {"worker_id": worker_id, "kind": kind}) or {}
        job = got.get("job")
        if not job:
            break
        log.info("drinks: 밈 %s 시작(%s)", job["draft_id"], kind)
        if kind == "text":
            try:
                res = write_text(job, rpc, call=call)
            except Exception as exc:  # noqa: BLE001
                log.warning("drinks: 밈 글 초안 %s 실패(%s)", job["draft_id"], type(exc).__name__)
                res = rpc("drinks_meme_finish_text", {"draft_id": job["draft_id"], "lease_token": job["lease_token"], "outcome": "failed",
                                                      "error_code": getattr(exc, "code", "llm_failed"), "error_message": f"글 초안 실패: {type(exc).__name__}"})
        else:
            res = process_render_job(job, rpc, storage)
        log.info("drinks: 밈 %s → %s", job["draft_id"], (res or {}).get("status"))
        out.append({"draft_id": job["draft_id"], **(res or {})})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 공장 밈 제작 워커")
    ap.add_argument("--text", action="store_true", help="글 초안 요청 처리(LLM, 결재 안에서만)")
    args = ap.parse_args(argv)
    res = run_queue(supabase_rpc(), Storage(), worker_id=config.WORKER_ID, kind="text" if args.text else "render")
    return 1 if any(r.get("status") in ("failed", "lease_lost") for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
