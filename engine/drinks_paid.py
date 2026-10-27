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
    aspect: str = ""              # 그림 종횡비. 비어 있으면 엔진 전역(config.ASPECT_RATIO, 영상 9:16) — 카드뉴스는 "4:5"
    cut: dict[str, Any] = field(default_factory=dict)


def _image_hash(model: str, prompt: str, ref_sha256: Optional[str], aspect: str) -> str:
    return _hash({"kind": "image", "model": model, "prompt": prompt, "ref": ref_sha256, "aspect": aspect})


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
                     prompt_hash=_image_hash(model, prompt, ref_sha256, config.ASPECT_RATIO),   # 영상 항목 해시는 예전 그대로
                     ref_item=ref_item, cut=cut)


def card_image_item(position: int, image_prompt: str) -> OrderItem:
    """카드뉴스 배경 사진 1장(4:5). 시제품(gen.cjs)과 같은 문장 — 장면 지시문 + 공통 꼬리(config.DRINKS_CARD_IMAGE_STYLE).

    엔진의 영상용 프롬프트 조립(9:16·3D 도해 화풍)을 타지 않는다: cut["raw_prompt"] 가 그대로 공급자에 간다.
    역할은 실사(reality) 단가. 종횡비는 주문 항목의 속성이라 해시에 들어간다(같은 문장도 4:5 와 9:16 은 다른 그림)."""
    ip = (image_prompt or "").strip()
    if not ip:
        raise PaidError("visual_prompt_missing", f"{position}쪽에 영어 그림 지시문(image_prompt)이 없습니다")
    prompt = f"{ip} {config.DRINKS_CARD_IMAGE_STYLE}"
    model = config.image_model_for("REALITY")
    price = float(config.PRICING.get(model, {}).get("image_standard", 0)) or image_price("reality")
    return OrderItem(item_key=f"page-{position:02d}-photo", position=position, role="reality", kind="image", model=model,
                     est_usd=price, prompt=prompt, prompt_hash=_image_hash(model, prompt, None, config.DRINKS_CARD_ASPECT),
                     cut={"cut_no": position, "visual_role": "REALITY", "raw_prompt": prompt}, aspect=config.DRINKS_CARD_ASPECT)


def build_card_image_items(pages: list[dict[str, Any]]) -> list[OrderItem]:
    """카드 제작안 쪽 → 그림 주문 항목. image_prompt 가 있는 쪽만 산다(출처 장·그림 없는 쪽은 로컬로 그린다).

    사진형인데 살 그림이 하나도 없으면 아무것도 사기 전에 멈춘다(결재만 묶이지 않게)."""
    items = [card_image_item(int(pg["position"]), pg["image_prompt"]) for pg in sorted(pages, key=lambda p: int(p["position"]))
             if pg.get("role") != "source" and str(pg.get("image_prompt") or "").strip()]
    if not items:
        raise PaidError("visual_prompt_missing", "그림 지시문(image_prompt)이 있는 쪽이 없습니다")
    return items


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
              *, clip_sec: Optional[int] = None) -> OrderItem:
    """움직이는 장면 1개(시작 그림 + 움직임 지시문 → Veo)."""
    from .providers import video as video_provider

    sec = int(clip_sec or config.DRINKS_PILOT_CLIP_SEC)
    if sec not in config.VEO_CLIP_SEC_TIERS:
        raise PaidError("invalid_order", f"영상 길이는 {config.VEO_CLIP_SEC_TIERS} 중 하나입니다")
    cut = {"cut_no": position, "visual_role": ENGINE_ROLE.get(role, "REALITY"), "motion_prompt": motion_prompt.strip()}
    prompt = video_provider.build_motion_prompt(cut, HEADER)
    model = config.VEO_MODEL
    per_sec = float(config.PRICING.get(model, {}).get("video_720p_per_sec", config.DRINKS_PAID_PRICES["video_per_sec"]))
    return OrderItem(item_key=f"scene-{position:02d}-clip{sec}", position=position, role=role, kind="video", model=model,
                     est_usd=round(per_sec * sec, 4), prompt=prompt,
                     prompt_hash=_hash({"kind": "video", "model": model, "prompt": prompt, "start": start_sha256, "sec": sec}),
                     ref_item=start_item, clip_sec=sec, cut=cut)


def order_hash(items: list[OrderItem]) -> str:
    """주문서 해시 — 결재에 같이 남긴다(보여드린 주문서와 산 것이 같은지 나중에 대조)."""
    # prompt_hash 에 이어 그릴·움직일 시작 그림이 들어 있다 — 시작 그림이 바뀌면 주문서도 달라진다.
    return _hash({"items": [{"key": i.item_key, "model": i.model, "prompt": i.prompt, "est": i.est_usd, "hash": i.prompt_hash}
                            for i in items]})


@contextmanager
def _paid_provider(kind: str, aspect: str = "") -> Iterator[None]:
    """그 호출 하나 동안만 공급자를 유료로 켠다(aspect 를 주면 종횡비도). 끝나면(실패해도) 되돌린다."""
    prev = (config.IMAGE_PROVIDER, config.VIDEO_PROVIDER, config.ASPECT_RATIO)
    try:
        if kind == "image":
            config.IMAGE_PROVIDER = "gemini"
        else:
            config.VIDEO_PROVIDER = "veo"
        if aspect:
            config.ASPECT_RATIO = aspect
        yield
    finally:
        config.IMAGE_PROVIDER, config.VIDEO_PROVIDER, config.ASPECT_RATIO = prev


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


def _copy_from_storage(storage: Any, key: str, dest: str) -> None:
    storage.get(key, dest)


def buy(item: OrderItem, *, rpc: Rpc, storage: Any, approval_id: str, out_dir: str,
        ref_path: Optional[str] = None, lease: Optional[dict[str, Any]] = None,
        generate: Optional[Callable[[OrderItem, str, Optional[str]], float]] = None) -> Bought:
    """항목 하나를 산다(또는 이미 산 것을 다시 쓴다). generate 는 테스트용 주입 — 기본은 엔진 공급자."""
    from .drinks_render import sha256_file

    os.makedirs(out_dir, exist_ok=True)
    ext = ".png" if item.kind == "image" else ".mp4"
    out = os.path.join(out_dir, f"{item.item_key}{ext}")
    hit = rpc("drinks_find_generated", {"prompt_hashes": [item.prompt_hash]}) or []
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
    if item.kind == "image":
        from .providers.image import measure_aspect

        size = measure_aspect(out)
    key = f"drinks/generated/{item.prompt_hash[:2]}/{item.prompt_hash}{ext}"
    stored = storage.put(out, key, "image/png" if item.kind == "image" else "video/mp4")
    reg = rpc("drinks_register_generated", {"hold_id": hold_id, "prompt_hash": item.prompt_hash, "asset": {
        "storage_key": stored, "sha256": sha256_file(out), "mime": "image/png" if item.kind == "image" else "video/mp4",
        "bytes": os.path.getsize(out), "width": size[0] if size else None, "height": size[1] if size else None,
        "duration_ms": item.clip_sec * 1000 if item.kind == "video" else None,
        "provenance": {"provider": "gemini" if item.kind == "image" else "veo", "model": item.model, "item_key": item.item_key,
                       "prompt_hash": item.prompt_hash, "approval_id": approval_id, "ref_item": item.ref_item}}})
    return Bought(item.item_key, out, float(cost), False, reg["asset_id"], hold_id,
                  width=size[0] if size else None, height=size[1] if size else None)


def _generate(item: OrderItem, out: str, ref_path: Optional[str]) -> float:
    if item.kind == "image":
        from .providers import image as image_provider

        with _paid_provider("image", item.aspect):
            _, cost = image_provider.generate_image(item.cut, HEADER, out, model=item.model, ref_path=ref_path)
        return cost
    from .providers import video as video_provider

    if not ref_path:
        raise PaidError("invalid_order", "움직이는 장면에는 시작 그림이 필요합니다")
    spec = SimpleNamespace(clip_sec=item.clip_sec, model=item.model, unit_price_usd=item.est_usd / item.clip_sec)
    with _paid_provider("video"):
        _, cost = video_provider.generate_clip(item.cut, HEADER, out, item.clip_sec, start_image=ref_path, spec=spec)
    return cost
