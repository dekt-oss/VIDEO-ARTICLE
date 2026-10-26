"""주류 공장 C단계 — 제작 워커(영상·카드뉴스). 2026-10-23. docs/deviation-drinks-production.md

    python -m engine.drinks_produce            # 대기 중인 제작 작업을 처리(대시보드 [렌더 요청])

규칙:
  · 작업은 DB 가 준다(drinks_start_render). 시작할 때 제작안·근거가 지금도 유효한지 DB 가 다시 잰다(무효면 취소).
  · 파일은 새 저장 위치에만 올린다(같은 위치 덮어쓰기 금지 — 재렌더는 새 묶음). 등록 때 sha256 을 남긴다.
  · 끝내기(drinks_finish_render)는 임대 토큰이 있어야 한다. 늦게 끝난 옛 워커의 결과는 저장되지 않는다.
  · 로컬 작업(renderer=local)은 유료 호출 0: 무료 TTS(edge)·로컬 장면 카드·ffmpeg 만. 비용 원장에는 0 원 기록을 남긴다.
  · 유료 작업(renderer=paid, 0054)은 장면 그림만 결재 안에서 산다(engine/drinks_paid.py — 그림마다 DB 가 상한을 잰다).
    음성·조립은 그대로 무료. 장면에 영어 그림 지시문이 없으면 아무것도 사기 전에 실패한다.
    ★ GitHub Actions 의 drinks-produce.yml 에는 그림 생성 키가 없다 — 거기서 집은 유료 작업은 가잡기 전에 api_key_missing 으로 멈춘다.
  · 저장: DRINKS_STORAGE=supabase → 비공개 버킷 'drinks' 의 drinks/{job}/… (논문·리포트 GC 가 걷지 않는 접두어)
          DRINKS_STORAGE=local(기본) → DRINKS_LOCAL_STORAGE_DIR 아래 같은 경로(검증용, 대시보드 미리보기는 안 됨)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from typing import Any, Callable, Optional

from . import config
from .drinks_collect import DbError, supabase_rpc
from .drinks_render import RenderError, render_video, sha256_file
from .util import log

Rpc = Callable[[str, dict[str, Any]], Any]

BUCKET = "drinks"


class Storage:
    """저장소. put 은 새 위치에만 쓴다 — 이미 있으면 내용이 같을 때만 통과(덮어쓰기 금지)."""

    def __init__(self, mode: Optional[str] = None, root: Optional[str] = None):
        self.mode = mode or os.getenv("DRINKS_STORAGE", "local")
        self.root = root or os.getenv("DRINKS_LOCAL_STORAGE_DIR") or os.path.join(tempfile.gettempdir(), "drinks_storage")

    def put(self, path: str, key: str, mime: str) -> str:
        assert key.startswith("drinks/"), key
        if self.mode == "local":
            dest = os.path.join(self.root, key.replace("/", os.sep))
            if os.path.exists(dest):
                if sha256_file(dest) != sha256_file(path):
                    raise RenderError("storage_conflict", f"이미 다른 내용이 있는 위치입니다: {key}")
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(path, dest)
            return f"local:{key}"
        if self.mode == "supabase":
            from . import db

            with open(path, "rb") as f:
                # upsert 하지 않는다 — 같은 위치에 이미 있으면 실패한다(불변).
                db.client().storage.from_(BUCKET).upload(key, f.read(), {"content-type": mime, "upsert": "false"})
            return key
        raise RenderError("storage_mode", f"알 수 없는 저장 방식: {self.mode}")

    def get(self, key: str, dest: str) -> None:
        """저장된 파일을 작업 폴더로 꺼낸다(산 그림 재사용)."""
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        if key.startswith("local:"):
            shutil.copyfile(os.path.join(self.root, key[len("local:"):].replace("/", os.sep)), dest)
            return
        if self.mode == "supabase":
            from . import db

            with open(dest, "wb") as f:
                f.write(db.client().storage.from_(BUCKET).download(key))
            return
        raise RenderError("storage_mode", f"이 저장 방식으로는 {key} 를 꺼낼 수 없습니다")


def buy_scene_images(job: dict[str, Any], rpc: Rpc, storage: Storage, work: str) -> tuple[dict[int, str], list[dict[str, Any]]]:
    """유료 작업: 장면마다 그림을 결재 안에서 산다(이미 산 것은 다시 쓴다). 정리 카드 장면은 사지 않는다.

    장면에 영어 그림 지시문(visual_prompt)이 없으면 **아무것도 사기 전에** 멈춘다 — 반쯤 산 채로 실패하지 않게."""
    from .drinks_paid import PaidError, build_image_items, buy

    from . import drinks_script_check as script_check

    lease = {"job_id": job["job_id"], "lease_token": job["lease_token"]}
    scenes = (job.get("plan") or {}).get("scenes") or []
    # 대본·화면 계획 코드 검사(0원) — 원문에 없는 숫자·양·권고, 근거 없는 사실 장면이 있으면 아무것도 사지 않는다.
    rep = script_check.check(script_check.plan_spec(job.get("plan") or {}, job.get("claims") or [],
                                                    sources=job.get("sources"), brief=job.get("brief")))
    if not rep.ok:
        raise RenderError("script_check_failed", "대본 검사에서 막혔습니다(사기 전): " +
                          "; ".join(f"{f.scene or '-'}번 {f.code}" for f in rep.blocks)[:1500])
    try:
        items = build_image_items(scenes)   # 지시문이 빠진 장면이 있으면 여기서(아무것도 사기 전에) 멈춘다
    except PaidError as exc:
        raise RenderError(exc.code, exc.message) from exc
    images: dict[int, str] = {}
    paths: dict[str, str] = {}
    costs: list[dict[str, Any]] = []
    for it in items:
        rpc("drinks_heartbeat_render", lease)
        try:
            b = buy(it, rpc=rpc, storage=storage, approval_id=job["spend_approval_id"], out_dir=os.path.join(work, "bought"),
                    ref_path=paths.get(it.ref_item) if it.ref_item else None, lease=lease)
        except PaidError as exc:
            raise RenderError(exc.code, exc.message) from exc
        images[it.position] = b.path
        paths[it.item_key] = b.path
        costs.append({"kind": "image", "provider": "gemini", "model": it.model, "units": 1, "cost_usd": b.cost_usd,
                      "estimated": not b.reused,
                      "note": f"{it.position}번 장면 " + ("— 이미 산 그림 재사용(0원)" if b.reused else "— 정가표 금액(청구서 대조 전)")})
    return images, costs


def process_job(job: dict[str, Any], rpc: Rpc, storage: Storage, *, tts: str = "edge") -> dict[str, Any]:
    lease = {"job_id": job["job_id"], "lease_token": job["lease_token"]}
    work = tempfile.mkdtemp(prefix=f"drinks_{job['job_id'][:8]}_")
    try:
        hb = rpc("drinks_heartbeat_render", lease) or {}
        if hb.get("cancel_requested") or hb.get("renderable") is False:
            return rpc("drinks_finish_render", {**lease, "outcome": "failed", "error_code": "canceled_before_render",
                                                "error_message": "렌더 전에 취소됐거나 근거가 무효가 됐습니다"})
        if job["format"] == "video":
            images: dict[int, str] = {}
            paid_costs: list[dict[str, Any]] = []
            if job.get("renderer") == "paid":
                images, paid_costs = buy_scene_images(job, rpc, storage, work)
            rendered = render_video(job, work, tts=tts, images=images)
            rendered.costs = paid_costs + rendered.costs
        else:
            from .drinks_cards import render_carousel   # 카드뉴스 렌더(정적 이미지)

            rendered = render_carousel(job, os.path.join(work, "pages"))
        rpc("drinks_heartbeat_render", lease)
        assets = []
        for f in rendered.files:
            ext = ".mp4" if f["mime"] == "video/mp4" else ".png"
            name = f"{f['role']}_{f['position']:02d}{ext}"
            key = f"drinks/{job['job_id']}/{name}"   # 작업마다 새 폴더 — 옛 묶음 파일을 덮지 않는다
            # ★ 올린 뒤 등록한다. 등록 직전에 임대를 잃으면 비공개 버킷에 DB 행 없는 파일이 남는다(고아) —
            #   덮어쓰지 않는 새 위치라 다른 묶음을 해치지 않고, 정리 규칙이 생기면 그때 회수한다(docs).
            stored = storage.put(f["path"], key, f["mime"])
            reg = rpc("drinks_register_asset", {**lease, "asset": {
                "storage_key": stored, "sha256": sha256_file(f["path"]), "mime": f["mime"], "bytes": os.path.getsize(f["path"]),
                "width": f.get("width"), "height": f.get("height"), "duration_ms": f.get("duration_ms"),
                "rights": "generated_paid" if rendered.qa.get("generated_scenes") else "generated_local",
                "provenance": {"renderer": job.get("renderer_version"),
                               "images": "generated_paid" if rendered.qa.get("generated_scenes") else "local_stand_in_cards",
                               "spend_approval_id": job.get("spend_approval_id"),
                               "tts": tts if job["format"] == "video" else None, "brand": rendered.qa.get("brand")}}})
            assets.append({"asset_id": reg["asset_id"], "role": f["role"], "position": f["position"]})
        for c in rendered.costs:
            rpc("drinks_record_cost", {**lease, "cost": c})
        return rpc("drinks_finish_render", {**lease, "outcome": "succeeded", "assets": assets, "qa": rendered.qa})
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 제작 작업 %s 임대를 잃어 결과를 저장하지 않습니다", job["job_id"])
            return {"status": "lease_lost"}
        # 묶음 규칙 위반 등 DB 가 거부한 것도 작업을 '렌더 중'에 남기지 않고 실패로 닫는다(검토 지적).
        try:
            return rpc("drinks_finish_render", {**lease, "outcome": "failed", "error_code": exc.code, "error_message": exc.message})
        except DbError:
            return {"status": "lease_lost"}
    except RenderError as exc:
        return rpc("drinks_finish_render", {**lease, "outcome": "failed", "error_code": exc.code, "error_message": exc.message})
    except Exception as exc:  # noqa: BLE001 — 어떤 예외도 작업을 running 에 남기지 않는다
        log.exception("drinks: 제작 작업 %s 예외", job["job_id"])
        try:
            return rpc("drinks_finish_render", {**lease, "outcome": "failed", "error_code": "worker_error",
                                                "error_message": f"워커 예외: {type(exc).__name__}"})
        except DbError:
            return {"status": "lease_lost"}
    finally:
        shutil.rmtree(work, ignore_errors=True)   # 이 작업의 임시 폴더만 지운다(저장소 파일은 건드리지 않는다)


def run_queue(rpc: Rpc, storage: Storage, *, worker_id: str, tts: str = "edge", max_jobs: int = 5) -> list[dict[str, Any]]:
    out = []
    for _ in range(max_jobs):
        got = rpc("drinks_start_render", {"worker_id": worker_id}) or {}
        job = got.get("job")
        if not job:
            break
        log.info("drinks: 제작 %s 시작 (%s, %s)", job["job_id"], job["format"], job["topic"].get("title"))
        res = process_job(job, rpc, storage, tts=tts)
        log.info("drinks: 제작 %s → %s", job["job_id"], (res or {}).get("status"))
        out.append({"job_id": job["job_id"], **(res or {})})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="주류 공장 제작 워커")
    ap.add_argument("--tts", default=os.getenv("DRINKS_TTS", "edge"), choices=["edge", "placeholder"])
    args = ap.parse_args(argv)
    res = run_queue(supabase_rpc(), Storage(), worker_id=config.WORKER_ID, tts=args.tts)
    bad = [r for r in res if r.get("status") in ("failed", "lease_lost")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
