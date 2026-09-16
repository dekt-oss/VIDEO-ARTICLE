"""저장소 정리 — 완성·발행이 끝난 렌더 산출물을 지운다 (2026-08-21 신설).

왜 필요한가
-----------
Supabase Storage 가 무료 한도(1GB)를 넘겼다(실측 1.53GB). 전부 렌더 산출물이고,
**지우는 장치가 아예 없었다** — ⑥ 화면의 "버리기"는 `render_jobs.deleted_at` 만 찍고
파일은 그대로 둔다. 영상 한 편당 15~30MB 씩 쌓이므로 일회성 청소로는 몇 주 뒤 같은 상황이 된다.

무엇을 지우나 (안전한 것만)
---------------------------
① 휴지통 잡의 파일        — 운영자가 이미 버린 것.
② 업로드된 편의 최종 mp4  — 유튜브에 있으므로 중복. **잡 단위로** 판정한다(같은 편의
                            KO 는 올렸고 EN 은 안 올렸으면 EN 은 남긴다).
③ 업로드 완료된 편의 컷별 캐시(스틸·클립) — 재렌더 비용을 아끼려고 두는 것인데, 이미
                            유튜브로 나간 편은 재렌더할 일이 없다.

무엇을 남기나
-------------
· 미업로드 편의 모든 파일(최종 mp4 + 캐시) — 아직 사람이 볼 것이 남았다.
· 리포트 라인(`report/…`) 전체 — 발행 경로가 달라 따로 판단한다.
· 살아 있는 잡이 하나라도 미업로드면 그 편의 캐시는 남긴다.

사용법
------
    python -m scripts.storage_cleanup            # 드라이런(기본) — 무엇을 지울지만 보여준다
    python -m scripts.storage_cleanup --apply    # 실제 삭제

★ 삭제는 되돌릴 수 없다. 반드시 드라이런으로 먼저 확인한다.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

from engine import config  # noqa: F401  (.env 로드 부수효과)
from engine.db import client

BUCKET = "renders"
# 최종 산출물 파일명: `{directive_id}/{render_job_id}_{lang}.mp4` 또는 `{directive_id}/{uuid}.mp4`
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
FINAL_RE = re.compile(rf"^({UUID})_(?:ko|en)\.mp4$|^({UUID})\.mp4$")


def _size(entry: dict) -> int:
    meta = entry.get("metadata") or {}
    try:
        return int(meta.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def collect() -> tuple[list[tuple[str, int, str]], dict[str, int]]:
    """(지울 파일, 사유, 크기) 목록과 남길 것의 요약을 만든다."""
    supa = client()

    # ── 잡 상태: 디렉티브별 살아있는 잡 수 / 업로드된 잡 id ──
    jobs = supa.table("render_jobs").select("id, directive_id, deleted_at").execute().data or []
    ups = (supa.table("upload_requests")
           .select("render_job_id, status, youtube_url").eq("status", "done").execute().data or [])
    uploaded_jobs = {u["render_job_id"] for u in ups if (u.get("youtube_url") or "").strip()}

    alive: dict[str, int] = defaultdict(int)
    alive_uploaded: dict[str, int] = defaultdict(int)
    known_dirs: set[str] = set()
    for j in jobs:
        d = str(j["directive_id"])
        known_dirs.add(d)
        if j.get("deleted_at") is None:
            alive[d] += 1
            if j["id"] in uploaded_jobs:
                alive_uploaded[d] += 1

    delete: list[tuple[str, int, str]] = []
    keep: dict[str, int] = defaultdict(int)

    for folder in sorted(known_dirs):
        try:
            entries = supa.storage.from_(BUCKET).list(folder) or []
        except Exception as exc:  # noqa: BLE001 — 폴더가 없으면 건너뛴다
            print(f"  ! {folder} 목록 실패: {exc}", file=sys.stderr)
            continue
        for e in entries:
            name = e.get("name") or ""
            if not name:
                continue
            path = f"{folder}/{name}"
            sz = _size(e)
            m = FINAL_RE.match(name)
            is_final = bool(m)
            job_id = (m.group(1) or m.group(2)) if m else None

            if alive.get(folder, 0) == 0:
                delete.append((path, sz, "휴지통 잡"))
            elif is_final and job_id in uploaded_jobs:
                delete.append((path, sz, "업로드된 최종 mp4"))
            elif not is_final and alive.get(folder, 0) == alive_uploaded.get(folder, 0):
                delete.append((path, sz, "업로드 완료 편의 컷 캐시"))
            else:
                keep["보관(미업로드 등)"] += sz
    return delete, keep


def main() -> None:
    apply = "--apply" in sys.argv
    delete, keep = collect()

    by_reason: dict[str, list[int]] = defaultdict(list)
    for _p, sz, reason in delete:
        by_reason[reason].append(sz)

    mb = lambda b: f"{b / 1024 / 1024:,.0f} MB"  # noqa: E731
    print("\n=== 삭제 대상 ===")
    for reason, sizes in sorted(by_reason.items(), key=lambda kv: -sum(kv[1])):
        print(f"  {reason:24s} {len(sizes):4d}개  {mb(sum(sizes)):>10s}")
    total = sum(sz for _p, sz, _r in delete)
    print(f"  {'합계':24s} {len(delete):4d}개  {mb(total):>10s}")
    print("\n=== 남기는 것 ===")
    for k, v in keep.items():
        print(f"  {k:24s}        {mb(v):>10s}")
    print("  리포트 라인(report/…)            (이 스크립트 대상 아님)")

    if not apply:
        print("\n드라이런입니다. 실제로 지우려면 --apply 를 붙이세요.")
        return

    supa = client()
    paths = [p for p, _s, _r in delete]
    done = 0
    for i in range(0, len(paths), 50):  # 배치 삭제(한 번에 너무 많이 보내지 않는다)
        batch = paths[i:i + 50]
        supa.storage.from_(BUCKET).remove(batch)
        done += len(batch)
        print(f"  삭제 {done}/{len(paths)}")
    print(f"\n삭제 완료: {done}개 · {mb(total)}")


if __name__ == "__main__":
    main()
