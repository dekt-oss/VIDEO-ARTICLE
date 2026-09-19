"""이미지 Batch 오케스트레이션 (작업 A, 명세 §7) — Feature Flag(config.IMAGE_GENERATION_MODE=="batch").

★ 설계: render.py 의 Realtime 경로는 **전혀 수정하지 않는다.** `_gen_still` 은 이미 캐시 우선(§5.6
content_hash)이라, 이 모듈이 지시서 승인 직후 Batch 를 제출·폴링해 결과를 같은 render_assets 캐시에
미리 채워두면(pre-warm), 실제 렌더가 나중에 돌 때 `_gen_still` 이 캐시를 그대로 히트해 Batch 절감
(표준가의 50%)을 자동으로 본다. 렌더가 Batch 완료 전에 먼저 돌면 오늘처럼 Realtime+재시도+placeholder
폴백이 그대로 동작한다(전체 중단 없음, 회귀 없음) — Batch 는 "늦게 도착하면 이미 Realtime 이 채운 캐시를
덮어써 낭비"될 수 있는 최적화 레이어일 뿐, 필수 경로가 아니다(1인·배치 규모에 맞는 경량 트레이드오프).

★ **논문 라인 전용이다**(2026-09-19). `db.get_render_asset`·`image_batch_jobs` 를 직접 쓰는데
  두 표의 FK 가 논문 `directives` 하나뿐이라 리포트 지시서 id 를 넣으면 거부된다. 리포트에
  Batch 를 붙일 일이 생기면 `engine/asset_cache.py` 처럼 표를 가르는 자리를 먼저 만든다.

실행:
  python -m engine.image_batch <directive_id>   # 해당 지시서 Batch 제출
  python -m engine.image_batch                  # 대기 중 Batch 잡 폴링(1회)
"""

from __future__ import annotations

import base64
import sys
import tempfile
from typing import Any

from . import assemble, config, cost as cost_ledger, db, generation_spec
from . import render as render_mod
from .providers import image as image_provider
from .util import log


def _needs_still(cut: dict[str, Any], header: dict[str, Any]) -> bool:
    """render.py 의 분기와 동일 기준(드리프트 방지 위해 render_kind_for_scene 재사용):
    motion_source=video(하이브리드 첫 프레임) 이거나, Manim 클립 대상이 아닌 컷은 스틸이 필요하다."""
    if cut.get("motion_source") == "video":
        return True
    scene_kind = cut.get("scene_kind") or config.VERSION_DEFAULT_SCENE_KIND.get(
        header.get("version_type"), "")
    wants_clip = config.ANIMATION_ENGINE != "off" and \
        render_mod.render_kind_for_scene(scene_kind, header.get("version_type")) == "clip"
    return not wants_clip


def _cuts_needing_batch(directive_id: str, cuts: list[dict[str, Any]],
                        header: dict[str, Any]) -> list[dict[str, Any]]:
    """스틸이 필요하고 아직 캐시(READY)되지 않은 컷만 Batch 대상(§5.6 캐시 우선)."""
    out = []
    for c in cuts:
        if not _needs_still(c, header):
            continue
        cut_no = int(c.get("cut_no") or 0)
        existing = db.get_render_asset(directive_id, cut_no, "image")
        if assemble.cache_hit(existing, assemble.content_hash(c, header)):
            continue
        out.append(c)
    return out


def submit_for_directive(directive_id: str) -> list[str]:
    """지시서의 미캐시 스틸 컷을 **모델별로 나눠** Batch 제출. 반환: provider_job_id 목록.

    ★ 2026-08-29: 반환이 단수 → 목록으로 바뀌었다. Batch 엔드포인트가 모델별로 갈리므로
      한 지시서가 여러 잡을 낳는다(도해는 프리미엄, 실사는 기본). 예전처럼 하나로 묶으면
      전 컷이 한 모델로 생성된다 — 그게 역할별 상향이 Batch 에서 무효였던 이유다.
    """
    directive = db.get_directive(directive_id)
    if not directive:
        raise ValueError(f"directive 없음: {directive_id}")
    header = directive.get("header") or {}
    cuts = _cuts_needing_batch(directive_id, directive.get("cuts") or [], header)
    if not cuts:
        log.info("image_batch: directive=%s 대상 컷 없음(전부 캐시됨/Manim)", directive_id)
        return []

    grouped = image_provider.group_batch_requests(directive_id, cuts, header)
    job_ids: list[str] = []
    for model, requests in sorted(grouped.items()):
        # ★ 페이로드 해시에 모델을 섞는다 — 같은 컷을 다른 모델로 다시 제출하는 것은
        #   중복이 아니라 **다른 작업**이다. 모델을 빼면 모델 상향 후 재제출이 막힌다.
        payload_hash = image_provider.batch_payload_hash([{"model": model}, *requests])

        # §7.3: 동일 페이로드로 이미 SUBMITTED/RUNNING/SUCCEEDED 인 잡이 있으면 재사용(중복 제출 방지).
        existing = db.find_active_batch_job(directive_id, payload_hash)
        if existing:
            log.info("image_batch: directive=%s 기존 잡 재사용(중복 제출 방지) model=%s job=%s",
                     directive_id, model, existing.get("provider_job_id"))
            job_ids.append(str(existing.get("provider_job_id")))
            continue

        job_name = image_provider.submit_batch(
            requests, display_name=f"directive-{directive_id}-{model}", model=model)
        db.insert_image_batch_job({
            "directive_id": directive_id, "provider_job_id": job_name,
            "payload_hash": payload_hash, "status": "submitted", "request_count": len(requests),
        })
        log.info("image_batch: directive=%s 제출 완료 model=%s job=%s 컷=%d",
                 directive_id, model, job_name, len(requests))
        job_ids.append(job_name)
    return job_ids


def submit_for_approved(limit: int = 5) -> int:
    """자동 제출(cron 용): 최근 승인/렌더 흐름에 든 지시서 중 미캐시 컷이 있는 것에 Batch 를 건다.

    ★ Feature Flag 게이트: `IMAGE_GENERATION_MODE=="batch"` 이고 `IMAGE_PROVIDER=="gemini"` 일 때만
    실제로 동작(그 외엔 즉시 0, no-op). CLI 로 특정 directive_id 를 지정하는 `submit_for_directive` 는
    이 게이트를 타지 않는다(명시적 수동 호출은 의도된 예외 — 검증용 강제 실행).

    ★ 운용상 한계: 지시서 승인 직후 대시보드가 즉시 렌더를 트리거하므로(triggerRender), 방금 승인한
    지시서의 "첫 렌더"는 Batch 가 끝나기 전에 이미 Realtime 로 채워질 가능성이 높다(Batch 는 분~시간
    단위). 절감은 주로 **재렌더**(2번째 언어, 편집 후 재시도, 실패 재큐)에서 실현된다 — 그 시점엔
    첫 렌더가 이미 Batch 를 걸어뒀을 가능성이 있고, 캐시가 남아있으면 재사용된다.
    """
    if config.IMAGE_GENERATION_MODE != "batch" or config.IMAGE_PROVIDER != "gemini":
        return 0
    directives = db.list_recent_approved_directives(limit)
    n = 0
    for d in directives:
        try:
            if submit_for_directive(d["id"]):
                n += 1
        except Exception as exc:  # noqa: BLE001 — 한 지시서 제출 실패가 다른 지시서를 막지 않음
            log.warning("image_batch 자동 제출 실패 directive=%s: %s", d.get("id"), exc)
    return n


def _ingest_result(directive_id: str, cut: dict[str, Any], header: dict[str, Any], b64: str) -> None:
    """Batch 이미지 1건 → Storage 업로드 + render_assets 캐시 + 원장 기록(작업 C, generation_mode=batch)."""
    cut_no = int(cut.get("cut_no") or 0)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(base64.b64decode(b64))
        tmp_path = f.name
    try:
        dest = f"{directive_id}/assets/cut_{cut_no}.png"
        url = db.upload_render(tmp_path, dest, "image/png")
        db.upsert_render_asset({
            "directive_id": directive_id, "cut_no": cut_no, "asset_type": "image",
            "asset_url": url, "content_hash": assemble.content_hash(cut, header), "meta": {},
        })
        # Batch 성공 = 과금 확정(문서 §7.1) — 이 컷을 나중에 Realtime 이 먼저 채웠어도 이 Batch 호출
        # 자체는 실제 발생한 비용이라 원장엔 기록한다(경량 경로의 드문 레이스, 4.2/12.5 참조).
        # ★ 모델·단가는 generation_spec 에서 온다. 예전엔 config.IMAGE_MODEL 을 박아, 프리미엄
        #   모델로 만든 도해 컷이 원장에는 flash 단가로 남았다.
        spec = generation_spec.image_spec(cut, header, generation_mode="batch")
        cost_ledger.record(cost_ledger.build_attempt(
            asset_type="image", provider=spec.provider if spec.provider != "placeholder" else "gemini",
            model_id=spec.model, generation_mode="batch", unit_type=spec.unit_type,
            requested_units=1, directive_id=directive_id, cut_no=cut_no))
    finally:
        import os
        os.unlink(tmp_path)


def poll_once(limit: int | None = None) -> int:
    """대기 중(submitted/running) Batch 잡을 폴링. 완료분은 캐시에 적재. 반환: 처리한 잡 수."""
    jobs = db.claim_pending_batch_jobs(limit or config.BATCH_POLL_MAX_CHECKS_PER_RUN)
    if not jobs:
        log.info("image_batch_jobs: 대기 없음")
        return 0
    for job in jobs:
        job_id, directive_id, provider_job_id = job["id"], job["directive_id"], job["provider_job_id"]
        try:
            poll = image_provider.poll_batch(provider_job_id)
        except Exception as exc:  # noqa: BLE001 — 폴링 실패는 다음 폴에서 재시도(잡 상태 유지)
            log.warning("image_batch 폴링 실패 job=%s: %s", provider_job_id, exc)
            continue
        if not poll["done"]:
            db.update_image_batch_job(job_id, status="running")
            continue

        directive = db.get_directive(directive_id)
        header = (directive or {}).get("header") or {}
        cuts_by_key = {
            image_provider.build_batch_key(directive_id, int(c.get("cut_no") or 0)): c
            for c in (directive or {}).get("cuts") or []
        }
        try:
            results = image_provider.fetch_batch_results(poll)
        except Exception as exc:  # noqa: BLE001 — operation 레벨 에러 → 잡 실패 처리, 렌더는 Realtime 폴백
            log.error("image_batch 결과 파싱 실패 job=%s: %s", provider_job_id, exc)
            db.update_image_batch_job(job_id, status="failed", error=str(exc)[:500])
            continue

        succeeded, failed = 0, 0
        for key, (b64, err) in results.items():
            cut = cuts_by_key.get(key)
            if not cut:
                continue
            if b64:
                try:
                    _ingest_result(directive_id, cut, header, b64)
                    succeeded += 1
                except Exception as exc:  # noqa: BLE001 — 적재 실패는 그 컷만 미스(Realtime 폴백)
                    log.warning("image_batch 결과 적재 실패 key=%s: %s", key, exc)
                    failed += 1
            else:
                log.warning("image_batch 컷 실패 key=%s: %s", key, err)
                failed += 1
        db.update_image_batch_job(job_id, status="succeeded", succeeded_count=succeeded,
                                  failed_count=failed)
        log.info("image_batch 완료: job=%s 성공=%d 실패=%d(Realtime 폴백 대상)",
                 provider_job_id, succeeded, failed)
    return len(jobs)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            submit_for_directive(sys.argv[1])  # 명시 지정 — Feature Flag 게이트 없이 강제 실행(검증용)
        else:
            n = submit_for_approved()  # 자동 스캔(게이트 적용) — render 워커 cron 에 함께 호출
            log.info("image_batch: 자동 제출 %d건", n)
            poll_once()
    except Exception as exc:
        log.exception("image_batch 실패: %s", exc)
        sys.exit(1)
