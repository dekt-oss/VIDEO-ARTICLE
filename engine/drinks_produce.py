"""주류 공장 C단계 — 제작 워커(영상·카드뉴스). 2026-10-23. docs/deviation-drinks-production.md

    python -m engine.drinks_produce            # 대기 중인 제작 작업을 처리(대시보드 [렌더 요청])

규칙:
  · 작업은 DB 가 준다(drinks_start_render). 시작할 때 제작안·근거가 지금도 유효한지 DB 가 다시 잰다(무효면 취소).
  · 파일은 새 저장 위치에만 올린다(같은 위치 덮어쓰기 금지 — 재렌더는 새 묶음). 등록 때 sha256 을 남긴다.
  · 끝내기(drinks_finish_render)는 임대 토큰이 있어야 한다. 늦게 끝난 옛 워커의 결과는 저장되지 않는다.
  · 유료 호출 0: 무료 TTS(edge)·로컬 장면 카드·ffmpeg 만. 비용 원장에는 0 원 기록을 남긴다(공급자·모델별).
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


def process_job(job: dict[str, Any], rpc: Rpc, storage: Storage, *, tts: str = "edge") -> dict[str, Any]:
    lease = {"job_id": job["job_id"], "lease_token": job["lease_token"]}
    work = tempfile.mkdtemp(prefix=f"drinks_{job['job_id'][:8]}_")
    try:
        hb = rpc("drinks_heartbeat_render", lease) or {}
        if hb.get("cancel_requested") or hb.get("renderable") is False:
            return rpc("drinks_finish_render", {**lease, "outcome": "failed", "error_code": "canceled_before_render",
                                                "error_message": "렌더 전에 취소됐거나 근거가 무효가 됐습니다"})
        if job["format"] == "video":
            rendered = render_video(job, work, tts=tts)
        else:
            from .drinks_cards import render_carousel   # 카드뉴스 렌더(정적 이미지)

            rendered = render_carousel(job, os.path.join(work, "pages"))
        rpc("drinks_heartbeat_render", lease)
        assets = []
        for f in rendered.files:
            ext = ".mp4" if f["mime"] == "video/mp4" else ".png"
            name = f"{f['role']}_{f['position']:02d}{ext}"
            key = f"drinks/{job['job_id']}/{name}"   # 작업마다 새 폴더 — 옛 묶음 파일을 덮지 않는다
            stored = storage.put(f["path"], key, f["mime"])
            reg = rpc("drinks_register_asset", {**lease, "asset": {
                "storage_key": stored, "sha256": sha256_file(f["path"]), "mime": f["mime"], "bytes": os.path.getsize(f["path"]),
                "width": f.get("width"), "height": f.get("height"), "duration_ms": f.get("duration_ms"), "rights": "generated_local",
                "provenance": {"renderer": job.get("renderer_version"), "images": "local_stand_in_cards",
                               "tts": tts if job["format"] == "video" else None, "brand": rendered.qa.get("brand")}}})
            assets.append({"asset_id": reg["asset_id"], "role": f["role"], "position": f["position"]})
        for c in rendered.costs:
            rpc("drinks_record_cost", {**lease, "cost": c})
        return rpc("drinks_finish_render", {**lease, "outcome": "succeeded", "assets": assets, "qa": rendered.qa})
    except DbError as exc:
        if exc.code == "lease_lost":
            log.warning("drinks: 제작 작업 %s 임대를 잃어 결과를 저장하지 않습니다", job["job_id"])
            return {"status": "lease_lost"}
        raise
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
