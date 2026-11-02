"""주류 공장 — 유료 그림·영상 사기(결재 안에서만). 2026-10-24. docs/deviation-drinks-paid-pilot.md

흐름(항목 하나 = 그림 1장 또는 움직이는 장면 1개):
  1. 재사용 목록(drink_generated_assets)에 같은 프롬프트 해시가 있으면 그 파일을 쓴다 — 0원, 다시 사지 않는다.
  2. 없으면 결재에 가잡기(drinks_hold_spend). DB 가 결재 행을 잠그고 상한을 넘으면 거절한다 — 여기서 멈춘다.
  3. 엔진 공급자를 그 호출 하나 동안만 유료로 켜고 부른다(끝나면 되돌린다). 실패하면 가잡기를 해제한다(청구 없음).
  4. 성공하면 확정(정가표 금액 — 공급자 청구서와 대조 전이라 '추정'으로 표시)하고, 파일을 저장소에 올려 재사용 목록에 등록한다.

★ 프롬프트는 엔진의 실사형 그림 경로(`providers.image._build_image_prompt`)가 만든다 — 운영자가 2026-09-08 확정한
  무광 CG 화풍(VISUAL_ROLE_STYLE)과 글자 금지(BURN_IN_NEGATIVE_PROMPT)를 그대로 탄다. 주문서에 찍히는 문장이
  공급자에 실제로 가는 문장과 같다(같은 함수 한 번).
★ 주류만의 소품 규칙(상표 없는 병·빈 라벨)은 장면 지시문 끝에 붙인다(config.DRINKS_PRODUCT_CLAUSE).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Optional

from . import config

Rpc = Callable[[str, dict[str, Any]], Any]

# 제작안 화면 역할 → 엔진 그림 역할(모델·화풍 선택). 정리 카드는 사지 않는다(로컬로 그린다).
ENGINE_ROLE = {"mechanism": "MECHANISM", "reality": "REALITY", "other": "REALITY"}
HEADER = {"version_type": "photo", "aspect_ratio": "9:16", "global_style": config.PHOTO_GLOBAL_STYLE}


class PaidError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass
class OrderItem:
    item_key: str
    position: int                 # 제작안 장면 번호
    role: str                     # 제작안 화면 역할(reality·mechanism)
    kind: str                     # image | video
    model: str
    est_usd: float
    prompt: str                   # 공급자에 실제로 가는 문장
    prompt_hash: str
    ref_item: Optional[str] = None    # 이어 그릴 앞 그림(같은 세계) / 움직일 시작 그림
    clip_sec: int = 0
    cut: dict[str, Any] = field(default_factory=dict)
    candidate_id: Optional[str] = None   # 설명형 후보(§3-3). 있으면 해시·항목 키에 들어가 후보 1·2가 한 파일로 합쳐지지 않는다


def image_price(role: str) -> float:
    return config.DRINKS_PAID_PRICES["image_mechanism" if role == "mechanism" else "image_reality"]


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def image_item(position: int, role: str, visual_prompt: str, *, ref_item: Optional[str] = None,
               ref_sha256: Optional[str] = None, scene: Optional[dict[str, Any]] = None) -> OrderItem:
    """그림 1장 주문 항목. 참조 그림이 있으면 그 내용(sha256)까지 해시에 넣는다 — 앞 그림이 바뀌면 다른 그림이다.

    scene 을 주면 엔진 컷으로 바꿔(drinks_screen) 엔진 자동 보정과 **도해 구조(mechanism)** 를 그대로 싣는다 —
    엔진 그림 프롬프트가 부품·강조 부분을 읽어 "A, B, C 가 한 장면에 다 보이고 X 가 설명 대상" 을 붙인다."""
    from .providers import image as image_provider

    if role not in ENGINE_ROLE:
        raise PaidError("invalid_order", f"{position}번 장면은 그림을 사지 않는 역할입니다({role})")
    vp = visual_prompt.strip()
    if not vp:
        raise PaidError("visual_prompt_missing", f"{position}번 장면에 영어 그림 지시문(visual_prompt)이 없습니다")
    if scene is not None:
        from .drinks_screen import engine_cut_for_image

        cut = engine_cut_for_image(dict(scene, visual_prompt=f"{vp}, {config.DRINKS_PRODUCT_CLAUSE}"), position)
    else:
        cut = {"cut_no": position, "visual_role": ENGINE_ROLE[role], "visual_prompt": f"{vp}, {config.DRINKS_PRODUCT_CLAUSE}"}
    model = config.image_model_for(cut["visual_role"])
    prompt = image_provider._build_image_prompt(cut, HEADER, referenced=bool(ref_item))
    price = float(config.PRICING.get(model, {}).get("image_standard", 0)) or image_price(role)
    key = f"scene-{position:02d}-{role}"
    return OrderItem(item_key=key, position=position, role=role, kind="image", model=model, est_usd=price, prompt=prompt,
                     prompt_hash=_hash({"kind": "image", "model": model, "prompt": prompt, "ref": ref_sha256,
                                        "aspect": config.ASPECT_RATIO}),
                     ref_item=ref_item, cut=cut)


_REF = re.compile(r"^\s*ref:(\d+)\s*$")


def build_image_items(scenes: list[dict[str, Any]], positions: Optional[list[int]] = None) -> list[OrderItem]:
    """제작안 장면 → 그림 주문 항목(시험 스크립트와 워커가 같은 함수를 쓴다 — 같은 장면은 같은 해시라 다시 사지 않는다).

    continuity 가 'ref:N' 이면 N번 장면 그림을 이어 그린다(같은 세계). N 은 앞 장면이어야 하고 함께 주문돼야 한다."""
    want = set(positions) if positions else None
    by_pos: dict[int, OrderItem] = {}
    out: list[OrderItem] = []
    for i, sc in enumerate(scenes, 1):
        role = sc.get("visual_role") or "reality"
        if role == "text_card" or (want is not None and i not in want):
            continue
        m = _REF.match(sc.get("continuity") or "")
        ref = int(m.group(1)) if m else None
        if ref is not None and (ref >= i or ref not in by_pos):
            raise PaidError("invalid_order", f"{i}번 장면이 이어 그릴 {ref}번 그림이 앞에서 함께 주문되지 않았습니다")
        it = image_item(i, role, sc.get("visual_prompt") or "",
                        ref_item=by_pos[ref].item_key if ref else None, ref_sha256=by_pos[ref].prompt_hash if ref else None,
                        scene=sc)
        by_pos[i] = it
        out.append(it)
    return out


def clip_item(position: int, role: str, motion_prompt: str, start_item: str, start_sha256: Optional[str] = None,
              *, clip_sec: Optional[int] = None, candidate_id: Optional[str] = None) -> OrderItem:
    """움직이는 장면 1개(시작 그림 + 움직임 지시문 → Veo).

    candidate_id 를 주면 설명형 후보다(기획 v2 §3-3): 항목 키 = 후보 id(0054 의 '항목당 시도' 상한이 후보마다 걸린다), 해시에 후보 id 가 들어간다.
    주지 않으면 해시·항목 키가 종전과 **글자까지 같다** — 이미 산 시험 클립의 재사용이 끊기지 않는다."""
    from .providers import video as video_provider

    sec = int(clip_sec or config.DRINKS_PILOT_CLIP_SEC)
    if sec not in config.VEO_CLIP_SEC_TIERS:
        raise PaidError("invalid_order", f"영상 길이는 {config.VEO_CLIP_SEC_TIERS} 중 하나입니다")
    cut = {"cut_no": position, "visual_role": ENGINE_ROLE.get(role, "REALITY"), "motion_prompt": motion_prompt.strip()}
    prompt = video_provider.build_motion_prompt(cut, HEADER)
    model = config.VEO_MODEL
    per_sec = float(config.PRICING.get(model, {}).get("video_720p_per_sec", config.DRINKS_PAID_PRICES["video_per_sec"]))
    payload: dict[str, Any] = {"kind": "video", "model": model, "prompt": prompt, "start": start_sha256, "sec": sec}
    if candidate_id:
        payload["candidate_id"] = candidate_id
    return OrderItem(item_key=candidate_id or f"scene-{position:02d}-clip{sec}", position=position, role=role, kind="video", model=model,
                     est_usd=round(per_sec * sec, 4), prompt=prompt, prompt_hash=_hash(payload),
                     ref_item=start_item, clip_sec=sec, cut=cut, candidate_id=candidate_id)


def order_hash(items: list[OrderItem]) -> str:
    """주문서 해시 — 결재에 같이 남긴다(보여드린 주문서와 산 것이 같은지 나중에 대조)."""
    # prompt_hash 에 이어 그릴·움직일 시작 그림이 들어 있다 — 시작 그림이 바뀌면 주문서도 달라진다.
    return _hash({"items": [{"key": i.item_key, "model": i.model, "prompt": i.prompt, "est": i.est_usd, "hash": i.prompt_hash}
                            for i in items]})


@contextmanager
def _paid_provider(kind: str) -> Iterator[None]:
    """그 호출 하나 동안만 공급자를 유료로 켠다. 끝나면(실패해도) 무료로 되돌린다."""
    prev = (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER)
    try:
        if kind == "image":
            config.IMAGE_PROVIDER = "gemini"
        else:
            config.VIDEO_PROVIDER = "veo"
        yield
    finally:
        config.IMAGE_PROVIDER, config.VIDEO_PROVIDER = prev


@dataclass
class Bought:
    item_key: str
    path: str
    cost_usd: float
    reused: bool
    asset_id: Optional[str]
    hold_id: Optional[str]
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None     # 영상: ffprobe 실측(E5)
    frames: Optional[int] = None


def _copy_from_storage(storage: Any, key: str, dest: str) -> None:
    storage.get(key, dest)


def _measure_clip(path: str) -> dict[str, Any]:
    """E5(기획 v2 §3-1): 받은 영상 파일을 실제로 잰다. 요청 길이를 적지 않는다."""
    from .drinks_explainer import probe_clip

    probe = probe_clip(path)
    if not probe["ok"] or not probe["has_video"] or probe["still"] or not probe["duration_ms"]:
        raise PaidError("clip_corrupt", f"받은 영상 파일을 재지 못했습니다: {str(probe['error'])[:200]}")
    return probe


def fetch_selected(slot: str, *, rpc: Rpc, storage: Any, out_dir: str) -> Bought:
    """설명형 재사용(§3-3): 다시 쓰는 것은 **이 슬롯에서 이미 선택된 자산**뿐이다(재렌더·언어 추가). 선택이 없으면 사지 않고 멈춘다."""
    from .drinks_render import sha256_file

    row = rpc("drinks_explainer_selected_asset", {"slot_id": slot}) or {}
    if not row.get("storage_key"):
        raise PaidError("no_selected_asset", f"이 슬롯에 선택된 자산이 없습니다: {slot}")
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", slot)
    out = os.path.join(out_dir, f"{safe}.mp4")
    _copy_from_storage(storage, row["storage_key"], out)
    if sha256_file(out) != row["sha256"]:
        raise PaidError("cache_corrupt", f"저장된 파일 내용이 기록과 다릅니다: {row['storage_key']}")
    return Bought(slot, out, 0.0, True, row.get("asset_id"), None, width=row.get("width"), height=row.get("height"), duration_ms=row.get("duration_ms"))


def buy(item: OrderItem, *, rpc: Rpc, storage: Any, approval_id: str, out_dir: str,
        ref_path: Optional[str] = None, lease: Optional[dict[str, Any]] = None,
        generate: Optional[Callable[[OrderItem, str, Optional[str]], float]] = None) -> Bought:
    """항목 하나를 산다(또는 이미 산 것을 다시 쓴다). generate 는 테스트용 주입 — 기본은 엔진 공급자."""
    from .drinks_render import sha256_file

    os.makedirs(out_dir, exist_ok=True)
    ext = ".png" if item.kind == "image" else ".mp4"
    # 후보 id 에는 ':'·'#' 가 있다(윈도우 파일 이름에 못 쓴다). 기존 항목 키(scene-01-reality)는 글자가 그대로다.
    out = os.path.join(out_dir, f"{re.sub(r'[^A-Za-z0-9_-]+', '_', item.item_key)}{ext}")
    # 후보를 채울 때는 캐시를 보지 않는다(§3-3) — 다시 쓰는 길은 fetch_selected 하나다.
    hit = [] if item.candidate_id else (rpc("drinks_find_generated", {"prompt_hashes": [item.prompt_hash]}) or [])
    if hit:
        _copy_from_storage(storage, hit[0]["storage_key"], out)
        if sha256_file(out) != hit[0]["sha256"]:
            raise PaidError("cache_corrupt", f"저장된 파일 내용이 기록과 다릅니다: {hit[0]['storage_key']}")
        return Bought(item.item_key, out, 0.0, True, hit[0]["asset_id"], None)
    if not config.SECRETS.gemini_api_key:
        # 가잡기 전에 멈춘다 — 키 없이 가잡으면 결재 금액만 묶인다.
        raise PaidError("api_key_missing", "GEMINI_API_KEY 가 없습니다 — 유료 생성을 시작하지 않았습니다")
    hold = rpc("drinks_hold_spend", {"approval_id": approval_id, "item_key": item.item_key, "kind": item.kind,
                                     "provider": "gemini" if item.kind == "image" else "veo", "model": item.model,
                                     "est_usd": item.est_usd, "note": f"{item.position}번 장면", **(lease or {})})
    hold_id = hold["hold_id"]
    try:
        cost = (generate or _generate)(item, out, ref_path)
    except Exception as exc:
        billed = getattr(exc, "clip_sec", None)
        if billed:   # Veo 가 만들고 받기만 실패 — 청구됐을 가능성이 높다(엔진 VeoBilledRejection)
            rpc("drinks_settle_spend", {"hold_id": hold_id, "outcome": "settled", "actual_usd": item.est_usd,
                                        "note": f"생성 완료 후 받기 실패(청구 유력): {type(exc).__name__}"})
        else:
            rpc("drinks_settle_spend", {"hold_id": hold_id, "outcome": "released", "note": f"생성 실패(청구 없음): {type(exc).__name__}"})
        raise
    rpc("drinks_settle_spend", {"hold_id": hold_id, "outcome": "settled", "actual_usd": round(float(cost), 4),
                                "note": "정가표 금액(공급자 청구서 대조 전)"})
    size = None
    clip_probe: Optional[dict[str, Any]] = None
    if item.kind == "image":
        from .providers.image import measure_aspect

        size = measure_aspect(out)
    else:
        # 돈은 위에서 이미 확정됐다. 파일이 재지지 않으면 등록하지 않는다 — 깨진 클립이 재사용 목록에 들어가면 안 된다.
        clip_probe = _measure_clip(out)
        size = (clip_probe["width"], clip_probe["height"])
    key = f"drinks/generated/{item.prompt_hash[:2]}/{item.prompt_hash}{ext}"
    stored = storage.put(out, key, "image/png" if item.kind == "image" else "video/mp4")
    reg = rpc("drinks_register_generated", {"hold_id": hold_id, "prompt_hash": item.prompt_hash, "asset": {
        "storage_key": stored, "sha256": sha256_file(out), "mime": "image/png" if item.kind == "image" else "video/mp4",
        "bytes": os.path.getsize(out), "width": size[0] if size else None, "height": size[1] if size else None,
        "duration_ms": clip_probe["duration_ms"] if clip_probe else None,
        "provenance": {"provider": "gemini" if item.kind == "image" else "veo", "model": item.model, "item_key": item.item_key,
                       "prompt_hash": item.prompt_hash, "approval_id": approval_id, "ref_item": item.ref_item,
                       **({"requested_ms": item.clip_sec * 1000, "measured_frames": clip_probe["frames"], "measured_fps": clip_probe["fps"]} if clip_probe else {}),
                       **({"candidate_id": item.candidate_id} if item.candidate_id else {})}}})
    return Bought(item.item_key, out, float(cost), False, reg["asset_id"], hold_id,
                  width=size[0] if size else None, height=size[1] if size else None,
                  duration_ms=clip_probe["duration_ms"] if clip_probe else None, frames=clip_probe["frames"] if clip_probe else None)


def _generate(item: OrderItem, out: str, ref_path: Optional[str]) -> float:
    if item.kind == "image":
        from .providers import image as image_provider

        with _paid_provider("image"):
            _, cost = image_provider.generate_image(item.cut, HEADER, out, model=item.model, ref_path=ref_path)
        return cost
    from .providers import video as video_provider

    if not ref_path:
        raise PaidError("invalid_order", "움직이는 장면에는 시작 그림이 필요합니다")
    spec = SimpleNamespace(clip_sec=item.clip_sec, model=item.model, unit_price_usd=item.est_usd / item.clip_sec)
    with _paid_provider("video"):
        _, cost = video_provider.generate_clip(item.cut, HEADER, out, item.clip_sec, start_image=ref_path, spec=spec)
    return cost
