"""주류 설명형 — 제작 큐 경로. 2026-11-02. docs/deviation-drinks-explainer-queue.md · 기획 v2 §3-3·§3-5·§3-9.

한 편은 제작 작업 세 종류로 나뉜다(drink_production_jobs.renderer). 사람 판정을 기다리는 동안 작업을 붙들고 있을 수 없어서다.

    explainer_plan    0원. TTS 실측 → 편집표 → 장면별 지시서(그림·움직임 문장, 시각 주장표, 길이, 금액). 사기 전 검사가 전부 여기 있다
    explainer_buy     돈. 슬롯 순서대로 시작 그림 + 클립 시도 → 자동 판정. 사람 선택이 필요한 자리에서 멈추고 작업을 닫는다
    explainer_render  0원. 선택된 클립만 잘라 잇는다(drinks_explainer.render_explainer) → 자동 검사 → 파일 묶음 → 사람 검수 대기

강제 조건:
  · 실제 공급자는 drinks_paid.LiveAdapter 뿐이고, 스위치 + 열린 결재가 없으면 가잡기 전에 멈춘다. 시험·리허설은 Deps.adapter 로 가짜를 넣는다.
  · explainer_render 는 어댑터를 받지 않는다 — 렌더 중에 살 길이 없다(E3). 클립 없음·깨짐·짧음이면 blocked_assets 로 멈추고 출력 파일이 없다(E4).
  · 옛 그림 나열식(drinks_render)을 부르지 않는다. 대체 그림·스틸 경로가 이 모듈에 없다.
  · 자동으로 다시 사지 않는다. 실패한 후보는 운영자가 [이어서 구매]를 눌러야 다음 시도를 연다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import config, drinks_develop as dd
from . import drinks_clay as clay
from . import drinks_explainer as dx
from . import drinks_paid as dpaid
from . import drinks_script_check as script_check
from .drinks_collect import DbError
from .drinks_render import draw_cover, sha256_file
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]
REF = re.compile(r"^\s*ref:(\d+)\s*$")


@dataclass
class Deps:
    """바꿔 끼울 수 있는 것. 비어 있으면 실제 공급자(스위치·결재 게이트)와 tts 인자대로의 TTS."""
    adapter: Any = None
    tts_fn: Optional[Callable[[str, str], None]] = None   # (문장, 저장 경로). 시험용


# ─────────────────────────────────────────────────────────────
# 장면별 지시서(순수) — 사기 전에 전부 재고, 어긋나면 한 푼도 쓰지 않는다
# ─────────────────────────────────────────────────────────────

def merge_visual_claims(scenes: list[dict[str, Any]], table: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """시각 주장표는 개발 요청 결과에 있다(0060 result.visual_claims — DB 검증기가 제작안에 보존하지 않는다).
    표가 없으면 멈춘다: 운영자가 제작안을 손으로 고친 버전에는 표가 없다(docs/deviation-drinks-explainer-stage1.md)."""
    if not table:
        raise dx.ExplainerStop("visual_claims_missing", "이 제작안에는 시각 주장표가 없습니다 — 소재 개발로 대본을 다시 만드세요(손으로 고친 버전에는 표가 없습니다)")
    by_scene = {int(r.get("scene") or 0): r for r in table}
    out = []
    for i, sc in enumerate(scenes, 1):
        row = by_scene.get(i)
        if not row:
            raise dx.ExplainerStop("visual_claims_missing", f"{i}번 장면의 시각 주장표가 없습니다")
        out.append({**sc, **{k: row.get(k) for k in dd.VISUAL_CLAIM_FIELDS}})
    return out


def choose_hook_scene(scenes: list[dict[str, Any]]) -> int:
    """훅 = 첫 도해(§3-6-2). 도해가 없으면 첫 장면."""
    for i, sc in enumerate(scenes, 1):
        if (sc.get("visual_role") or "reality") == "mechanism":
            return i
    return 1


def scene_boundary(scenes: list[dict[str, Any]], i: int) -> tuple[str, Optional[int]]:
    """들어오는 경계. 대본이 'ref:N' 으로 이어짐을 선언하면 match(그 슬롯이 선택돼야 시작 그림을 주문한다, §3-5).
    선언이 없으면 역할이 바뀔 때 cut_to_mechanism, 아니면 보통 컷(cut)."""
    if i == 1:
        return "loop", None
    sc, prev = scenes[i - 1], scenes[i - 2]
    kind, ref = dd.continuity_kind(sc.get("continuity"), i)
    if kind == "ref":
        if not 1 <= int(ref or 0) < i:
            raise dx.ExplainerStop("invalid_continuity", f"{i}번 장면이 이어 그릴 {ref}번은 앞 장면이 아닙니다")
        return "match", ref
    if (sc.get("visual_role") or "reality") != (prev.get("visual_role") or "reality"):
        return "cut_to_mechanism", None
    return "cut", None


def slot_key(plan_id: str, scene: int) -> str:
    return dx.slot_id(plan_id, scene)   # 장면당 슬롯 하나(§3-3)


def build_beats(scenes: list[dict[str, Any]], plan_id: str, tts_ms: dict[int, int], hook_scene: int,
                narration_paths: Optional[dict[int, str]] = None, boundaries: Optional[dict[int, str]] = None) -> list[dx.Beat]:
    """장면 → 비트. 첫 비트는 훅 자산의 뒤쪽 구간을 앞당겨 보여 주고(flash_forward) 첫 장면으로 넘어간다(§3-6-2 B1)."""
    n = len(scenes)
    beats: list[dx.Beat] = []
    for i, sc in enumerate(scenes, 1):
        asset = slot_key(plan_id, i)
        boundary = boundaries[i] if boundaries else scene_boundary(scenes, i)[0]
        tail = config.DRINKS_EXPLAINER_TAIL_MS if i == n else 0
        shots: tuple[dx.Shot, ...] = (dx.Shot(asset, boundary),)
        if i == 1 and hook_scene != 1:
            hook_use = int(tts_ms[hook_scene]) + (config.DRINKS_EXPLAINER_TAIL_MS if hook_scene == n else 0)
            start = max(0, hook_use - config.DRINKS_EXPLAINER_HOOK_END_GAP_MS - config.DRINKS_EXPLAINER_HOOK_RAW_MS)
            shots = (dx.Shot(slot_key(plan_id, hook_scene), "loop", raw_ms=config.DRINKS_EXPLAINER_HOOK_RAW_MS, src_start_ms=start), dx.Shot(asset, "flash_forward"))
        beats.append(dx.Beat(beat_id=f"B{i}", tts_ms=int(tts_ms[i]), shots=shots, narration=str(sc.get("narration") or ""), tail_ms=tail,
                             card_text=str(sc.get("overlays") or "").strip(), narration_path=(narration_paths or {}).get(i, "")))
    return beats


def pick_hook_text(topic: dict[str, Any], scenes: list[dict[str, Any]]) -> str:
    """상단 훅 자막은 한 줄이다(§3-8). 소재 질문이 안 들어가면 첫 장면 나레이션, 그것도 안 들어가면 멈춘다 — 자르지 않는다."""
    for text in (topic.get("question"), scenes[0].get("narration") if scenes else None):
        t = str(text or "").strip()
        if t and not dx.layout_caption("hook", t)["overflow"]:
            return t
    raise dx.ExplainerStop("hook_text_overflow", f"훅 자막이 한 줄에 들어가지 않습니다: {str(topic.get('question') or '')[:60]}")


def clip_sec_for(last_src_ms: int, provider: str) -> Optional[int]:
    """계획 규칙(§3-6-2): 쓰는 길이 ≤ 자산 길이 − 0.5초. 맞는 주문 길이가 없으면 None."""
    need = last_src_ms + config.DRINKS_EXPLAINER_PLAN_MARGIN_MS
    return next((s for s in config.DRINKS_EXPLAINER_CLIP_SEC_TIERS[provider] if s * 1000 >= need), None)


def visual_prompt_with_guard(sc: dict[str, Any]) -> str:
    """금지할 오해는 프롬프트 부정어 + 사람 검수 항목 둘 다로 쓴다(§3-4). [미검증] 한국어 문장을 그대로 넣었다 — 그림에 글자로 나오는지는 S2 에서 본다."""
    vp = str(sc.get("visual_prompt") or "").strip()
    bad = str(sc.get("forbidden_misreading") or "").strip()
    return f"{vp} Must not suggest: {bad}." if vp and bad else vp


def _stop_if(problems: list[dict[str, Any]]) -> None:
    if problems:
        raise dx.ExplainerStop("plan_not_buildable", "; ".join(f"{p['scene'] or '-'}번 {p['code']}" for p in problems)[:1500], problems=problems)


def plan_problems(job: dict[str, Any], scenes: list[dict[str, Any]], tts_ms: dict[int, int]) -> list[dict[str, Any]]:
    """대본·시각 주장표 코드 검사(0원) — 무료 경로와 달리 여기서는 막는다(buy_scene_images 와 같은 규칙). 클립·사진클레이 공용."""
    plan = job.get("plan") or {}
    problems: list[dict[str, Any]] = []

    def bad(code: str, message: str, scene: Optional[int] = None) -> None:
        problems.append({"code": code, "scene": scene, "message": message})

    rep = script_check.check(script_check.plan_spec(plan, job.get("claims") or [], sources=job.get("sources"), brief=job.get("brief")))
    for f in rep.blocks:
        bad(f.code, f.message, f.scene)
    for f in dd.visual_claim_checks({"scenes": scenes}, job.get("claims") or []):
        bad(f.code, f.message, f.scene)
    for i, sc in enumerate(scenes, 1):
        if not str(sc.get("visual_prompt") or "").strip():
            bad("visual_prompt_missing", "영어 그림 지시문이 없습니다", i)
        if not int(tts_ms.get(i) or 0):
            bad("narration_missing", "나레이션 길이를 재지 못했습니다", i)
    return problems


def build_directive(plan_id: str, job: dict[str, Any], visual_claims: Optional[list[dict[str, Any]]], tts_ms: dict[int, int], *, provider: str) -> dict[str, Any]:
    """장면별 지시서 — 운영자 결재 화면에 그대로 나가는 표이자 구매의 입력. 어긋나면 ExplainerStop(problems)."""
    topic = job.get("topic") or {}
    resolution = config.DRINKS_EXPLAINER_RESOLUTION
    scenes = merge_visual_claims((job.get("plan") or {}).get("scenes") or [], visual_claims)
    if not scenes:
        raise dx.ExplainerStop("plan_not_buildable", "장면이 없습니다")
    problems = plan_problems(job, scenes, tts_ms)
    _stop_if(problems)

    def bad(code: str, message: str, scene: Optional[int] = None) -> None:
        problems.append({"code": code, "scene": scene, "message": message})

    # 2. 편집표(실측 TTS 기준). 표가 안 맞으면 살 이유가 없다.
    hook_scene = choose_hook_scene(scenes)
    boundaries, refs = {}, {}
    for i in range(1, len(scenes) + 1):
        boundaries[i], refs[i] = scene_boundary(scenes, i)
    hook_text = pick_hook_text(topic, scenes)
    beats = build_beats(scenes, plan_id, tts_ms, hook_scene, boundaries=boundaries)
    roles = {slot_key(plan_id, i): sc.get("visual_role") or "reality" for i, sc in enumerate(scenes, 1)}
    tl = dx.build_timeline(beats, roles, hook_text=hook_text)
    lo, hi = config.DRINKS_EXPLAINER_FINAL_SEC
    if not lo <= tl.final_ms / 1000.0 <= hi:
        bad("duration_out_of_range", f"최종 {tl.final_ms / 1000.0:.1f}초 — 설명형은 {lo:g}~{hi:g}초입니다")
    for c in tl.cuts:
        for ly in c.subtitle_layers:
            if ly.overflow:
                bad("caption_overflow", f"{c.beat_id} 자막이 넘칩니다: {ly.text[:40]}")
    last_src: dict[str, int] = {}
    for c in tl.cuts:
        last_src[c.asset_id] = max(last_src.get(c.asset_id, 0), c.src_end_ms)
    min_src = dx.slot_min_src_ms(tl.cuts)

    # 3. 슬롯·금액
    slots: list[dict[str, Any]] = []
    images_usd = clips_usd = 0.0
    longest_clip = 0
    for i, sc in enumerate(scenes, 1):
        role = sc.get("visual_role") or "reality"
        sid = slot_key(plan_id, i)
        sec = clip_sec_for(last_src.get(sid, 0), provider)
        if sec is None:
            bad("scene_too_long", f"이 장면은 원본 {last_src.get(sid, 0) / 1000.0:.1f}초를 쓰는데 주문 길이 상한은 {max(config.DRINKS_EXPLAINER_CLIP_SEC_TIERS[provider])}초입니다 — 대본을 줄이세요", i)
            continue
        if not str(sc.get("motion_prompt") or "").strip():
            bad("motion_prompt_missing", "영어 움직임 지시문이 없습니다", i)
            continue
        ref = refs[i]
        guarded = dict(sc, visual_prompt=visual_prompt_with_guard(sc))
        img = dpaid.image_item(i, role, guarded["visual_prompt"], ref_item=f"A{ref}-last-frame" if ref else None, scene=guarded)
        candidates = config.DRINKS_EXPLAINER_HOOK_CANDIDATES if i == hook_scene else 1
        probe_item = dpaid.clip_item(i, role, str(sc["motion_prompt"]), img.item_key, None, clip_sec=sec, candidate_id=dx.candidate_id(sid, 1), provider=provider, resolution=resolution)
        images_usd += img.est_usd
        clips_usd += probe_item.est_usd * candidates
        longest_clip = max(longest_clip, sec)
        slots.append({"n": i, "scene": i, "slot_id": sid, "role": role, "narration": sc.get("narration"), "tts_ms": int(tts_ms[i]), "last_src_ms": last_src.get(sid, 0),
                      "min_src_ms": min_src[sid], "clip_sec": sec, "candidates_planned": candidates, "boundary_in": boundaries[i], "boundary_out": boundaries[i + 1] if i < len(scenes) else "loop",
                      "continuity_ref": ref, "visual_prompt": guarded["visual_prompt"], "image_prompt": img.prompt, "image_model": img.model, "image_item_key": img.item_key, "image_est_usd": img.est_usd,
                      "motion_prompt": sc["motion_prompt"], "clip_prompt": probe_item.prompt, "clip_model": probe_item.model, "clip_est_usd": probe_item.est_usd,
                      "claim_ids": list(sc.get("claim_ids") or []), "visual_claim_ko": sc.get("visual_claim_ko"), "allowed_simplification": sc.get("allowed_simplification"),
                      "forbidden_misreading": sc.get("forbidden_misreading"), "depiction_label": sc.get("depiction_label"), "overlays": sc.get("overlays") or None})
    _stop_if(problems)
    reserve = dx.clip_est_usd(provider, longest_clip, resolution) + config.DRINKS_EXPLAINER_PRICES["image"]["mechanism"]["usd"]   # §3-7 재시도 예비
    estimate = images_usd + clips_usd
    cap = math.ceil(round(estimate + reserve, 4) * 10) / 10
    return {"version": 1, "provider": provider, "resolution": resolution, "price_as_of": config.DRINKS_EXPLAINER_PRICES["as_of"], "hook_text": hook_text, "hook_scene": hook_scene,
            "playback_speed": tl.speed, "raw_ms": tl.raw_ms, "final_ms": tl.final_ms, "edit_cuts": len(tl.cuts), "slots": slots, "warnings": tl.warnings,
            "estimate": {"images_usd": round(images_usd, 4), "clips_usd": round(clips_usd, 4), "estimate_usd": round(estimate, 2), "reserve_usd": round(reserve, 4), "suggested_cap_usd": round(cap, 2)},
            "unverified": ["공급자 응답 모양", "시작 그림 첫 프레임 고정", "길이 지정", "청구 단위"]}


def build_clay_directive(plan_id: str, job: dict[str, Any], visual_claims: Optional[list[dict[str, Any]]], scene_sec: dict[int, float]) -> dict[str, Any]:
    """사진클레이 지시서(docs/deviation-drinks-explainer-clay.md). 대본 검사는 클립 경로와 같고, 클립 칸 대신 장면별 자막 줄·그림 한 장이다."""
    topic = job.get("topic") or {}
    scenes = merge_visual_claims((job.get("plan") or {}).get("scenes") or [], visual_claims)
    if not scenes:
        raise dx.ExplainerStop("plan_not_buildable", "장면이 없습니다")
    problems = plan_problems(job, scenes, {i: int(scene_sec.get(i, 0) * 1000) for i in range(1, len(scenes) + 1)})
    final_sec = sum(scene_sec.values())
    lo, hi = config.DRINKS_CLAY_FINAL_SEC
    if not lo <= final_sec <= hi:
        problems.append({"code": "duration_out_of_range", "scene": None, "message": f"최종 {final_sec:.1f}초 — 사진클레이는 {lo:g}~{hi:g}초입니다"})
    _stop_if(problems)
    slots, images_usd = clay.directive_slots(plan_id, scenes, scene_sec)
    reserve = config.DRINKS_CLAY_IMAGE_USD * 2   # 마음에 안 드는 그림 두 장을 다시 그릴 여유
    cap = math.ceil(round(images_usd + reserve, 4) * 10) / 10
    title = str(topic.get("title") or topic.get("question") or "").strip()
    final_ms = int(round(final_sec * 1000))
    return {"version": 1, "provider": config.DRINKS_CLAY_PROVIDER, "variant": "clay", "resolution": f"{clay.W}x{clay.H}", "price_as_of": config.DRINKS_EXPLAINER_PRICES["as_of"],
            "hook_text": title, "hook_scene": 1, "playback_speed": 1.0, "raw_ms": final_ms, "final_ms": final_ms,
            "edit_cuts": sum(len(s["lines"]) for s in slots), "slots": slots, "warnings": [],
            "voice": {"name": config.DRINKS_CLAY_TTS_VOICE, "rate": config.DRINKS_CLAY_TTS_RATE},
            "estimate": {"images_usd": images_usd, "clips_usd": 0.0, "estimate_usd": round(images_usd, 2), "reserve_usd": round(reserve, 4), "suggested_cap_usd": round(cap, 2)},
            "unverified": ["그림 속 째리 모양", "주인공 얼굴이 장면마다 같은지"]}


def directive_hash(directive: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(directive, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# TTS(무료)
# ─────────────────────────────────────────────────────────────

def _placeholder_tts(text: str, path: str) -> None:
    syl = len(re.sub(r"\s+", "", text)) or 1
    sec = max(1.0, syl / config.DRINKS_EXPLAINER_PLACEHOLDER_SYL_PER_SEC)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={sec:.3f}",
                    "-af", "volume=0.25", "-c:a", "pcm_s16le", path], check=True, capture_output=True)


def synth_narrations(scenes: list[dict[str, Any]], out_dir: str, tts: str, deps: Deps) -> dict[int, str]:
    os.makedirs(out_dir, exist_ok=True)
    out: dict[int, str] = {}
    for i, sc in enumerate(scenes, 1):
        text = str(sc.get("narration") or "").strip()
        if not text:
            raise dx.ExplainerStop("narration_missing", f"{i}번 장면에 나레이션이 없습니다")
        if deps.tts_fn is not None:
            p = os.path.join(out_dir, f"{i:02d}.wav")
            deps.tts_fn(text, p)
        elif tts == "edge":
            from .providers import tts as tts_provider

            p = os.path.join(out_dir, f"{i:02d}.m4a")
            tts_provider._edge_synthesize(text, p, config.EDGE_TTS_VOICE)
        elif tts == "placeholder":
            p = os.path.join(out_dir, f"{i:02d}.wav")
            _placeholder_tts(text, p)
        else:
            raise dx.ExplainerStop("paid_disabled", f"설명형은 무료 TTS 만 씁니다: {tts}")
        out[i] = p
    return out


# ─────────────────────────────────────────────────────────────
# 작업 세 종류
# ─────────────────────────────────────────────────────────────

class _Stop(Exception):
    """작업을 닫고 끝낸다. outcome=succeeded 면 정상 멈춤(사람 차례 등)."""

    def __init__(self, outcome: str, code: str, message: str, to_state: Optional[str] = None):
        super().__init__(f"{code}: {message}")
        self.outcome, self.code, self.message, self.to_state = outcome, code, message, to_state


def _context(job: dict[str, Any], rpc: Rpc) -> dict[str, Any]:
    return rpc("drinks_explainer_job_context", {"plan_revision_id": job["plan_revision_id"], "approval_id": job.get("spend_approval_id")}) or {}


def _lease(job: dict[str, Any]) -> dict[str, Any]:
    return {"job_id": job["job_id"], "lease_token": job["lease_token"]}


def _set_state(job: dict[str, Any], rpc: Rpc, to_state: str, code: Optional[str] = None, message: Optional[str] = None) -> None:
    rpc("drinks_explainer_episode_event", {**_lease(job), "to_state": to_state, "code": code, "message": message})


def _heartbeat(job: dict[str, Any], rpc: Rpc) -> None:
    hb = rpc("drinks_heartbeat_render", _lease(job)) or {}
    if hb.get("cancel_requested"):
        raise _Stop("failed", "canceled", "운영자가 취소했습니다")
    if hb.get("renderable") is False:
        raise _Stop("failed", "canceled_before_render", "제작안·근거가 지금은 유효하지 않습니다 — 더 진행하지 않습니다")


def _clay_scene_sec(scenes: list[dict[str, Any]], out_dir: str, deps: Deps) -> dict[int, float]:
    """사진클레이 길이 실측 — 조립과 같은 방식(장면 통째 TTS, 앞뒤 빈 소리 뺌, 장면 사이 숨)."""
    os.makedirs(out_dir, exist_ok=True)
    out: dict[int, float] = {}
    for i, sc in enumerate(scenes, 1):
        text = str(sc.get("narration") or "").strip()
        if not text:
            raise dx.ExplainerStop("narration_missing", f"{i}번 장면에 나레이션이 없습니다")
        p = os.path.join(out_dir, f"{i:02d}" + (".wav" if deps.tts_fn else ".mp3"))
        a0, a1 = clay.spoken_window(p, clay.speak(text, p, deps.tts_fn))
        out[i] = round(a1 - a0 + config.DRINKS_CLAY_SCENE_GAP_SEC, 3)
    return out


def _run_plan(job: dict[str, Any], rpc: Rpc, work: str, *, tts: str, deps: Deps) -> dict[str, Any]:
    ctx = _context(job, rpc)
    scenes = (job.get("plan") or {}).get("scenes") or []
    provider = (ctx.get("episode") or {}).get("provider") or config.DRINKS_EXPLAINER_DEFAULT_PROVIDER
    if provider == config.DRINKS_CLAY_PROVIDER:
        d = build_clay_directive(job["plan_revision_id"], job, ctx.get("visual_claims"), _clay_scene_sec(scenes, os.path.join(work, "narration"), deps))
        rpc("drinks_explainer_save_directive", {**_lease(job), "directive": d, "order_hash": directive_hash(d)})
        rpc("drinks_record_cost", {**_lease(job), "cost": {"kind": "tts", "provider": "test" if deps.tts_fn else "edge", "cost_usd": 0, "units": len(scenes), "note": "사진클레이 지시서용 길이 실측"}})
        return {"status_code": "directive_ready", "estimate": d["estimate"]}
    narr = synth_narrations(scenes, os.path.join(work, "narration"), tts, deps)
    tts_ms = {i: dx.media_duration_ms(p) for i, p in narr.items()}
    d = build_directive(job["plan_revision_id"], job, ctx.get("visual_claims"), tts_ms, provider=provider)
    rpc("drinks_explainer_save_directive", {**_lease(job), "directive": d, "order_hash": directive_hash(d)})
    rpc("drinks_record_cost", {**_lease(job), "cost": {"kind": "tts", "provider": "test" if deps.tts_fn else tts, "cost_usd": 0, "units": len(scenes), "note": "지시서용 길이 실측"}})
    return {"status_code": "directive_ready", "estimate": d["estimate"]}


def _cost(job: dict[str, Any], rpc: Rpc, kind: str, provider: str, model: str, usd: float, note: str) -> None:
    rpc("drinks_record_cost", {**_lease(job), "cost": {"kind": kind, "provider": provider, "model": model, "cost_usd": usd, "units": 1, "estimated": True, "note": note}})


def _buy_candidate(job: dict[str, Any], rpc: Rpc, storage: Any, item: dpaid.OrderItem, slot: dict[str, Any], start: str, work: str, adapter: Any) -> None:
    """시도 한 번 + 자동 판정. 실패는 예외로 올라가 작업을 닫는다 — 같은 작업 안에서 다시 사지 않는다."""
    b = dpaid.buy_clip_attempt(item, rpc=rpc, storage=storage, approval_id=job["spend_approval_id"], out_dir=os.path.join(work, "clips"), start_image=start,
                               adapter=adapter, lease=_lease(job))
    _cost(job, rpc, "video", item.provider, item.model, b.cost_usd, f"{item.position}번 장면 {item.candidate_id} — 청구서 대조 전")
    report = dx.check_candidate(b.path, int(slot["min_src_ms"]))
    rpc("drinks_explainer_verdict", {"candidate_id": item.candidate_id, "auto_verdict": "pass" if report["pass"] else "fail", "auto_report": report})


def _auto_check_stored(rpc: Rpc, storage: Any, cand: dict[str, Any], slot: dict[str, Any], work: str) -> None:
    """저장까지 됐는데 판정 전에 워커가 죽은 후보. 돈을 더 쓰지 않고 판정만 잇는다."""
    asset = cand.get("asset") or {}
    p = os.path.join(work, "recheck", re.sub(r"[^A-Za-z0-9_-]+", "_", cand["candidate_id"]) + ".mp4")
    storage.get(asset["storage_key"], p)
    report = dx.check_candidate(p, int(slot["min_src_ms"]))
    rpc("drinks_explainer_verdict", {"candidate_id": cand["candidate_id"], "auto_verdict": "pass" if report["pass"] else "fail", "auto_report": report})


def _run_buy_clay(job: dict[str, Any], rpc: Rpc, storage: Any, work: str, deps: Deps, ctx: dict[str, Any]) -> dict[str, Any]:
    """사진클레이 구매: 장면마다 그림 1장, 클립 없음. 1번은 째리 그림을, 나머지는 '1번 + 째리' 한 장을 참조로 그린다(공급자는 참조 1장만 받는다).
    다 사면 사람 선택 없이 assets_complete — 고를 후보가 없다. 사람은 완성 영상을 검수한다."""
    adapter = deps.adapter if deps.adapter is not None else clay.ClayAdapter()
    try:
        adapter.check_ready(ctx.get("approval"))   # ★ 스위치·결재 게이트. 가잡기보다 먼저다
    except dpaid.PaidError as exc:
        raise _Stop("failed", exc.code, exc.message) from exc
    ep = ctx.get("episode") or {}
    if ep.get("state") == "approved":
        _set_state(job, rpc, "buying")
    directive = ep.get("directive") or {}
    slots = sorted(directive.get("slots") or [], key=lambda s: int(s["n"]))
    if not slots:
        raise _Stop("failed", "directive_missing", "장면별 지시서가 없습니다")
    through, total = ep.get("buy_through_n"), len(slots)
    out_dir, ref_path, ref_id = os.path.join(work, "images"), clay.mascot_ref(os.path.join(work, "jjeri_ref.png")), clay.MASCOT_REF_ID
    for spec in slots:
        n = int(spec["n"])
        if through and n > int(through):
            return {"status_code": "scope_done", "through_n": through}
        _heartbeat(job, rpc)
        item = clay.image_item(n, total, str(spec["visual_prompt"] or ""), ref_id)
        if item.prompt != spec["image_prompt"]:
            raise _Stop("failed", "order_changed", f"{n}번 장면 그림 문장이 지시서와 다릅니다 — 지시서를 다시 만드세요")
        img = dpaid.buy(item, rpc=rpc, storage=storage, approval_id=job["spend_approval_id"], out_dir=out_dir, ref_path=ref_path, lease=_lease(job), generate=adapter.image)
        if not img.reused:
            _cost(job, rpc, "image", "gemini", item.model, img.cost_usd, f"{n}번 장면 클레이 그림 — 정가표")
        if n == 1:
            ref_path, ref_id = clay.reference_sheet(img.path, os.path.join(work, "ref_sheet.png")), sha256_file(img.path)
    _set_state(job, rpc, "assets_complete")
    return {"status_code": "assets_complete"}


def _run_buy(job: dict[str, Any], rpc: Rpc, storage: Any, work: str, deps: Deps) -> dict[str, Any]:
    ctx = _context(job, rpc)
    provider = (ctx.get("episode") or {}).get("provider")
    allowed = config.DRINKS_EXPLAINER_SEND_PROVIDERS
    if allowed and provider not in allowed:   # ★ 가잡기·호출 전. GitHub 작업기는 사진클레이만 산다
        raise _Stop("failed", "provider_not_on_this_worker", f"이 작업기는 {', '.join(allowed)} 만 삽니다({provider}) — 운영자 PC 워커에서 구매를 이어서 요청하세요")
    if provider == config.DRINKS_CLAY_PROVIDER:
        return _run_buy_clay(job, rpc, storage, work, deps, ctx)
    adapter = deps.adapter if deps.adapter is not None else dpaid.LiveAdapter((ctx.get("episode") or {}).get("provider"))
    try:
        adapter.check_ready(ctx.get("approval"))   # ★ 스위치·결재 게이트. 가잡기·시도 행보다 먼저다
    except dpaid.PaidError as exc:
        raise _Stop("failed", exc.code, exc.message) from exc
    ep = ctx.get("episode") or {}
    if ep.get("state") == "approved":
        _set_state(job, rpc, "buying")
    rpc("drinks_explainer_sweep_stale", {"older_than_sec": config.DRINKS_EXPLAINER_STALE_ATTEMPT_SEC})
    ctx = _context(job, rpc)
    directive = (ctx.get("episode") or {}).get("directive") or {}
    if not directive.get("slots"):
        raise _Stop("failed", "directive_missing", "장면별 지시서가 없습니다")
    if ctx.get("unknown_attempts"):
        raise _Stop("failed", "unknown_billed", "결과를 모르는 시도가 있습니다 — 운영자가 닫기 전에는 사지 않습니다", "unknown_billed")
    through = (ctx.get("episode") or {}).get("buy_through_n")
    provider = directive["provider"]
    runtime = {int(s["n"]): s for s in ctx.get("slots") or []}
    for spec in directive["slots"]:
        n = int(spec["n"])
        if through and n > int(through):
            return {"status_code": "scope_done", "through_n": through}
        rt = runtime.get(n) or {}
        if rt.get("status") == "no_pass":
            raise _Stop("failed", "no_pass", f"{n}번 슬롯의 후보가 모두 불합격입니다", "blocked_no_pass")
        if rt.get("status") == "selected":
            continue
        _heartbeat(job, rpc)
        ref = spec.get("continuity_ref")
        ref_path = None
        ref_sha = None
        if ref:
            if (runtime.get(int(ref)) or {}).get("status") != "selected":
                # 이어 그리기는 앞 슬롯의 **선택된** 클립 마지막 프레임으로 시작한다(§3-5). 사람 차례.
                return {"status_code": "awaiting_selection", "waiting_for_slot": ref, "next_slot": n}
            got = dpaid.fetch_selected(dx.slot_id(job["plan_revision_id"], int(ref)), rpc=rpc, storage=storage, out_dir=os.path.join(work, "refs"))
            ref_path = dx.last_frame(got.path, os.path.join(work, "refs", f"A{ref}_last.png"))
            ref_sha = sha256_file(ref_path)
        scene = dict((job.get("plan") or {}).get("scenes", [])[n - 1], visual_prompt=spec["visual_prompt"])
        img_item = dpaid.image_item(n, spec["role"], spec["visual_prompt"], ref_item=f"A{ref}-last-frame" if ref else None, ref_sha256=ref_sha, scene=scene)
        img = dpaid.buy(img_item, rpc=rpc, storage=storage, approval_id=job["spend_approval_id"], out_dir=os.path.join(work, "images"), ref_path=ref_path,
                        lease=_lease(job), generate=adapter.image)
        if not img.reused:
            _cost(job, rpc, "image", "gemini", img_item.model, img.cost_usd, f"{n}번 장면 시작 그림 — 정가표")
        start_sha = sha256_file(img.path)
        spec_h = dx.spec_hash(model=spec["clip_model"], prompt=spec["clip_prompt"], start_image_sha256=start_sha, clip_sec=int(spec["clip_sec"]), resolution=directive["resolution"])
        rpc("drinks_explainer_plan_slot", {"plan_revision_id": job["plan_revision_id"], "n": n, "role": spec["role"], "spec_hash": spec_h, "min_src_ms": spec["min_src_ms"],
                                           "candidates_planned": spec["candidates_planned"], "boundary_in": spec["boundary_in"], "boundary_out": spec["boundary_out"]})
        cands = {int(c["k"]): c for c in rt.get("candidates") or []}
        for k in range(1, int(spec["candidates_planned"]) + 1):
            cid = dx.candidate_id(spec["slot_id"], k)
            c = cands.get(k) or {"candidate_id": cid, "status": "pending"}
            if c.get("status") == "stored":
                if not c.get("auto_verdict"):
                    _auto_check_stored(rpc, storage, c, spec, work)
                continue
            if c.get("auto_verdict") == "fail":
                continue   # 자동 판정이 닫은 후보(시도 상한 소진 등). 다시 사지 않는다
            _heartbeat(job, rpc)
            item = dpaid.clip_item(n, spec["role"], str(spec["motion_prompt"]), img_item.item_key, start_sha, clip_sec=int(spec["clip_sec"]), candidate_id=cid, provider=provider, resolution=directive["resolution"])
            if item.prompt != spec["clip_prompt"]:
                raise _Stop("failed", "order_changed", f"{n}번 장면 움직임 문장이 지시서와 다릅니다 — 지시서를 다시 만드세요")
            try:
                _buy_candidate(job, rpc, storage, item, spec, img.path, work, adapter)
            except DbError as exc:
                if exc.code == "attempt_cap":
                    # 시도 상한을 다 쓴 후보는 더 살 수 없다. 자동 불합격으로 닫아 슬롯이 no_pass 로 갈 수 있게 한다.
                    rpc("drinks_explainer_verdict", {"candidate_id": cid, "auto_verdict": "fail", "auto_report": {"pass": False, "blocks": ["attempt_cap"]}})
                    continue
                raise
        fresh = _context(job, rpc)
        runtime = {int(s["n"]): s for s in fresh.get("slots") or []}
        if (runtime.get(n) or {}).get("status") == "no_pass":
            raise _Stop("failed", "no_pass", f"{n}번 슬롯의 후보가 모두 불합격입니다", "blocked_no_pass")
    return {"status_code": "awaiting_review"}


def _collect_selected(plan_id: str, directive: dict[str, Any], rpc: Rpc, storage: Any, out_dir: str) -> dict[str, dx.Asset]:
    """선택된 클립만 꺼낸다. 못 꺼낸 슬롯은 표에서 빠지고, 렌더의 강제 조건이 clip_missing 으로 멈춘다 — 사지 않고 대체하지 않는다."""
    assets: dict[str, dx.Asset] = {}
    for spec in directive["slots"]:
        sid = dx.slot_id(plan_id, int(spec["n"]))
        try:
            b = dpaid.fetch_selected(sid, rpc=rpc, storage=storage, out_dir=out_dir, check_hash=False)
        except dpaid.PaidError:
            continue
        except OSError as exc:
            log.warning("drinks: 설명형 클립 %s 를 꺼내지 못했습니다(%s)", sid, type(exc).__name__)
            continue
        assets[sid] = dx.Asset(asset_id=sid, path=b.path, sha256=b.sha256 or "", role=spec["role"], planned_ms=int(spec["clip_sec"]) * 1000)
    return assets


def _fetch_clay_images(directive: dict[str, Any], rpc: Rpc, storage: Any, out_dir: str) -> dict[int, str]:
    """산 그림을 저장소에서 꺼낸다(재구매 없음). 주문 해시는 구매 때와 같은 규칙으로 다시 계산한다 — 2번부터는 1번 그림 내용이 해시에 들어 있다."""
    os.makedirs(out_dir, exist_ok=True)
    slots = sorted(directive["slots"], key=lambda s: int(s["n"]))
    out: dict[int, str] = {}
    ref_id = clay.MASCOT_REF_ID
    for spec in slots:
        n = int(spec["n"])
        item = clay.image_item(n, len(slots), str(spec["visual_prompt"] or ""), ref_id)
        hit = rpc("drinks_find_generated", {"prompt_hashes": [item.prompt_hash]}) or []
        if not hit:
            raise _Stop("failed", "image_missing", f"{n}번 장면 그림을 찾지 못했습니다 — 구매를 이어서 요청하세요", "blocked_assets")
        p = os.path.join(out_dir, f"clay-{n:02d}.png")
        storage.get(hit[0]["storage_key"], p)
        if sha256_file(p) != hit[0]["sha256"]:
            raise _Stop("failed", "cache_corrupt", f"{n}번 장면 그림 파일이 기록과 다릅니다", "blocked_assets")
        out[n] = p
        if n == 1:
            ref_id = sha256_file(p)
    return out


def _run_render_clay(job: dict[str, Any], rpc: Rpc, storage: Any, work: str, ctx: dict[str, Any], directive: dict[str, Any], deps: Deps) -> dict[str, Any]:
    """사진클레이 조립(0원). ★ 사는 길이 없다 — 그림은 _fetch_clay_images 로 꺼내기만 한다."""
    from .drinks_produce import MIME_EXT
    from .drinks_render import _probe

    if (ctx.get("episode") or {}).get("state") != "rehearsal":
        _set_state(job, rpc, "rehearsal")
    pics = _fetch_clay_images(directive, rpc, storage, os.path.join(work, "images"))
    scenes = [clay.ClayScene(n=int(s["n"]), narration=str(s["narration"] or ""), lines=list(s["lines"]), picture=pics[int(s["n"])], mascot=bool(s.get("mascot_in_scene")))
              for s in sorted(directive["slots"], key=lambda s: int(s["n"]))]
    _heartbeat(job, rpc)
    out = os.path.join(work, "final.mp4")
    summary_render = clay.render(directive["hook_text"], scenes, out, os.path.join(work, "render"), deps.tts_fn)
    qa = clay.auto_qa(out, summary_render)
    if not qa["ok"]:
        raise _Stop("failed", "auto_qa_fail", "자동 검사 불합격: " + ", ".join(qa["blocks"])[:1500], "auto_qa_fail")
    _set_state(job, rpc, "rendered")
    probe = _probe(out)
    cover = os.path.join(work, "cover.jpg")
    draw_cover(job.get("topic") or {}, job.get("plan") or {}, cover)
    summary = {"format": "explainer", "variant": "clay", "auto_qa": {"state": "pass", "blocks": [], "warns": qa["warns"], "signals": summary_render},
               "warnings": qa["warns"], "tts": "test" if deps.tts_fn else "edge", "voice": directive.get("voice"),
               "visual_source": {"stand_in": [], "card_pages": [], "generated": sorted(pics)},
               "reel_spec": {"moov_first": dx.moov_before_mdat(out), "audio_sample_rate": probe.get("audio_sample_rate"), "video_codec": probe.get("video_codec"), "fps": probe.get("fps"), "cover_mime": "image/jpeg"},
               "probe": probe, "note": "자동 검사 통과는 '돌아간다'일 뿐이다 — 품질 판정은 사람이 한다"}
    files = [{"path": out, "role": "final_video", "position": 1, "mime": "video/mp4", "width": probe["width"], "height": probe["height"], "duration_ms": int(probe["duration_sec"] * 1000)},
             {"path": cover, "role": "cover", "position": 1, "mime": "image/jpeg", "width": 1080, "height": 1920}]
    registered = []
    for f in files:
        name = f"{f['role']}_{f['position']:02d}{MIME_EXT[f['mime']]}"
        stored = storage.put(f["path"], f"drinks/{job['job_id']}/{name}", f["mime"])
        reg = rpc("drinks_register_asset", {**_lease(job), "asset": {"storage_key": stored, "sha256": sha256_file(f["path"]), "mime": f["mime"], "bytes": os.path.getsize(f["path"]),
                                                                     "width": f.get("width"), "height": f.get("height"), "duration_ms": f.get("duration_ms"), "rights": "generated_paid",
                                                                     "provenance": {"renderer": config.DRINKS_CLAY_RENDERER_VERSION, "images": "generated_paid", "tts": summary["tts"]}}})
        registered.append({"asset_id": reg["asset_id"], "role": f["role"], "position": f["position"]})
    rpc("drinks_record_cost", {**_lease(job), "cost": {"kind": "render", "provider": "local_ffmpeg", "cost_usd": 0, "note": "사진클레이 조립 — 렌더 중 구매 0회"}})
    _set_state(job, rpc, "auto_qa_pass")
    return rpc("drinks_finish_render", {**_lease(job), "outcome": "succeeded", "assets": registered, "qa": summary})


def _run_render(job: dict[str, Any], rpc: Rpc, storage: Any, work: str, *, tts: str, deps: Deps) -> dict[str, Any]:
    """조립. ★ 이 함수에는 어댑터가 없다 — 렌더 중에 살 길이 코드에 없다(E3)."""
    from .drinks_produce import MIME_EXT

    plan_id = job["plan_revision_id"]
    ctx = _context(job, rpc)
    directive = (ctx.get("episode") or {}).get("directive") or {}
    if not directive.get("slots"):
        raise _Stop("failed", "directive_missing", "장면별 지시서가 없습니다")
    if directive.get("provider") == config.DRINKS_CLAY_PROVIDER:
        return _run_render_clay(job, rpc, storage, work, ctx, directive, deps)
    if (ctx.get("episode") or {}).get("state") != "rehearsal":
        _set_state(job, rpc, "rehearsal")
    assets = _collect_selected(plan_id, directive, rpc, storage, os.path.join(work, "selected"))
    scenes = (job.get("plan") or {}).get("scenes") or []
    narr = synth_narrations(scenes, os.path.join(work, "narration"), tts, deps)
    boundaries = {int(s["n"]): s["boundary_in"] for s in directive["slots"]}
    beats = build_beats(scenes, plan_id, {i: dx.media_duration_ms(p) for i, p in narr.items()}, int(directive["hook_scene"]), narration_paths=narr, boundaries=boundaries)
    _heartbeat(job, rpc)
    out = os.path.join(work, "final.mp4")
    rendered = dx.render_explainer(beats, assets, hook_text=directive["hook_text"], out_path=out, work_dir=os.path.join(work, "render"), plan_id=plan_id)
    qa = dx.run_auto_qa(rendered.out_path, rendered.manifest)
    if not qa.ok:
        raise _Stop("failed", "auto_qa_fail", "자동 검사 불합격: " + ", ".join(qa.blocks)[:1500], "auto_qa_fail")
    _set_state(job, rpc, "rendered")
    from .drinks_render import _probe

    cuts = [dx.EditCut(cut_id=c["cut_id"], beat_id=c["beat_id"], asset_id=c["asset_id"], src_start_ms=c["src_start_ms"], src_end_ms=c["src_end_ms"],
                       timeline_start_ms=c["timeline_start_ms"], timeline_end_ms=c["timeline_end_ms"], boundary=c["boundary"], zoom=c["zoom"]) for c in rendered.manifest["cuts"]]
    try:
        continuity = dx.boundary_metrics(cuts, assets, os.path.join(work, "boundaries"))
    except dx.ExplainerStop as exc:   # 기록용 숫자다. 못 재도 막지 않고 못 쟀다고 남긴다
        continuity = [{"error": exc.code}]
    probe = _probe(out)
    cover = os.path.join(work, "cover.jpg")
    draw_cover(job.get("topic") or {}, job.get("plan") or {}, cover)
    summary = {"format": "explainer", "auto_qa": {"state": qa.state, "blocks": qa.blocks, "warns": qa.warns, "signals": qa.signals}, "warnings": qa.warns,
               "continuity": continuity, "edit_cuts": len(rendered.manifest["cuts"]), "video_fallbacks": rendered.manifest["video_fallbacks"],
               "assets": rendered.manifest["assets"], "cuts": rendered.manifest["cuts"], "tts": "test" if deps.tts_fn else tts, "visual_source": {"stand_in": [], "card_pages": [], "generated": sorted(int(s["n"]) for s in directive["slots"])},
               "reel_spec": {"moov_first": dx.moov_before_mdat(out), "audio_sample_rate": probe.get("audio_sample_rate"), "video_codec": probe.get("video_codec"), "fps": probe.get("fps"), "cover_mime": "image/jpeg"},
               "probe": probe, "note": "자동 검사 통과는 '돌아간다'일 뿐이다 — 품질 판정은 사람이 한다(§3-8 B)"}
    files = [{"path": out, "role": "final_video", "position": 1, "mime": "video/mp4", "width": probe["width"], "height": probe["height"], "duration_ms": int(probe["duration_sec"] * 1000)},
             {"path": cover, "role": "cover", "position": 1, "mime": "image/jpeg", "width": 1080, "height": 1920}]
    registered = []
    for f in files:
        name = f"{f['role']}_{f['position']:02d}{MIME_EXT[f['mime']]}"
        stored = storage.put(f["path"], f"drinks/{job['job_id']}/{name}", f["mime"])
        reg = rpc("drinks_register_asset", {**_lease(job), "asset": {"storage_key": stored, "sha256": sha256_file(f["path"]), "mime": f["mime"], "bytes": os.path.getsize(f["path"]),
                                                                     "width": f.get("width"), "height": f.get("height"), "duration_ms": f.get("duration_ms"), "rights": "generated_paid",
                                                                     "provenance": {"renderer": config.DRINKS_EXPLAINER_RENDERER_VERSION, "images": "generated_paid", "tts": summary["tts"]}}})
        registered.append({"asset_id": reg["asset_id"], "role": f["role"], "position": f["position"]})
    rpc("drinks_record_cost", {**_lease(job), "cost": {"kind": "render", "provider": "local_ffmpeg", "cost_usd": 0, "note": "선택된 클립 조립 — 렌더 중 구매 0회"}})
    _set_state(job, rpc, "auto_qa_pass")
    return rpc("drinks_finish_render", {**_lease(job), "outcome": "succeeded", "assets": registered, "qa": summary})


def _finish(job: dict[str, Any], rpc: Rpc, outcome: str, code: Optional[str], message: Optional[str], to_state: Optional[str] = None, result: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return rpc("drinks_explainer_finish_job", {**_lease(job), "outcome": outcome, "error_code": code, "error_message": (message or "")[:1900] or None, "to_state": to_state, "result": result or {}})


BUDGET_CODES = {"budget_exceeded"}


def process_explainer_job(job: dict[str, Any], rpc: Rpc, storage: Any, *, tts: str = "edge", deps: Optional[Deps] = None) -> dict[str, Any]:
    deps = deps or Deps()
    renderer = job.get("renderer")
    work = tempfile.mkdtemp(prefix=f"drinks_ex_{str(job['job_id'])[:8]}_")
    try:
        try:
            _heartbeat(job, rpc)
            if renderer == "explainer_plan":
                return _finish(job, rpc, "succeeded", None, None, result=_run_plan(job, rpc, work, tts=tts, deps=deps))
            if renderer == "explainer_buy":
                return _finish(job, rpc, "succeeded", None, None, result=_run_buy(job, rpc, storage, work, deps))
            if renderer == "explainer_render":
                return _run_render(job, rpc, storage, work, tts=tts, deps=deps)
            raise _Stop("failed", "unknown_renderer", f"설명형 작업이 아닙니다: {renderer}")
        except _Stop as stop:
            return _finish(job, rpc, stop.outcome, stop.code, stop.message, stop.to_state)
        except dx.ExplainerStop as stop:
            # 렌더 강제 조건(blocked_assets) · 편집표·자동 검사 실패. 지시서 단계의 멈춤은 상태를 옮기지 않는다 — 아직 산 것이 없다.
            detail = stop.message + ("" if not stop.problems else " | " + json.dumps(stop.problems, ensure_ascii=False)[:1200])
            return _finish(job, rpc, "failed", stop.code, detail, stop.state if renderer == "explainer_render" else None)
        except dpaid.PaidError as exc:
            if exc.code == "unknown_billed":
                return _finish(job, rpc, "failed", exc.code, exc.message, "unknown_billed")
            return _finish(job, rpc, "failed", exc.code, exc.message)
        except DbError as exc:
            if exc.code == "lease_lost":
                log.warning("drinks: 설명형 작업 %s 임대를 잃어 결과를 저장하지 않습니다", job["job_id"])
                return {"status": "lease_lost"}
            if exc.code == "unknown_billed_open":
                return _finish(job, rpc, "failed", exc.code, exc.message, "unknown_billed")
            return _finish(job, rpc, "failed", exc.code, exc.message, "blocked_budget" if exc.code in BUDGET_CODES else None)
    except DbError as exc:
        log.warning("drinks: 설명형 작업 %s 를 닫지 못했습니다(%s)", job["job_id"], exc.code)
        return {"status": "lease_lost" if exc.code == "lease_lost" else "failed", "error_code": exc.code}
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 작업을 running 에 남기지 않는다
        log.exception("drinks: 설명형 작업 %s 예외", job["job_id"])
        try:
            return _finish(job, rpc, "failed", "worker_error", f"워커 예외: {type(exc).__name__}")
        except DbError:
            return {"status": "lease_lost"}
    finally:
        shutil.rmtree(work, ignore_errors=True)
