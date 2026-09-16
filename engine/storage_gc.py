"""저장소 자동 정리 — 렌더 산출물이 무한히 쌓이는 것을 막는다 (2026-08-24 신설).

왜 생겼나
---------
2026-08-24, Supabase Storage 가 무료 한도 1GB 를 넘겨(1.53GB) **조직 전체가 정지**됐다.
대시보드·API 가 전부 402 를 뱉었고, 같은 조직의 다른 프로젝트까지 함께 멈췄다.

원인은 용량이 아니라 **지우는 장치가 없었다는 것**이다:
  · ⑥ 화면의 "버리기"는 `render_jobs.deleted_at` 만 찍고 **파일은 그대로 뒀다**.
  · 유튜브 업로드가 끝나도 컷별 캐시(스틸·클립)가 영원히 남았다.
  · 편당 15~30MB 씩 2026-07-08 부터 한 번도 줄지 않고 쌓였다.

그래서 "쌓이면 지운다"를 코드로 만든다. 사람이 기억해야 하는 일로 두지 않는다.

무엇을 지우나 (안전한 것만)
---------------------------
① 휴지통 잡의 파일          — 운영자가 이미 버렸다.
② 업로드된 **잡**의 최종 mp4 — 유튜브에 있으니 중복. 잡 단위로 본다(같은 편이라도
                              KO 만 올렸으면 EN 은 남긴다).
③ 살아있는 잡이 **전부** 업로드된 편의 컷별 캐시(스틸·클립)
                            — 재렌더 비용을 아끼려는 캐시인데, 이미 나간 편은 재렌더하지 않는다.

④ **묵은** 컷 캐시(기본 14일)       — 캐시는 재생성할 수 있다. 2주면 캐시로서 값을 잃는다.
⑤ **묵은** 미발행 최종 mp4(기본 30일) — 한 달이 지나도록 안 올렸으면 운영자가 접은 편이다.

무엇을 남기나
-------------
· **최근** 미업로드 편의 최종 mp4 — 아직 사람이 확인할 결과물이다.
· 판정에 필요한 정보가 없는 것(연결된 잡을 못 찾는 고아 경로)도 남긴다 — 모르면 지우지 않는다.

★ ④⑤ 는 왜 생겼나 (2026-08-28)
   원래 규칙 "미업로드 최종 영상은 절대 안 지운다"에 **기한이 없었다.** 그래서 영원히 올릴 일
   없는 편의 파일이 무한히 남았다 — 실측: 7월 개발기의 실험 렌더 **532MB** 가 6주 뒤에도
   그대로였다(폐기된 `hybrid`·`image_sequence`·`animation` 버전). 그것만으로 무료 한도의
   절반을 먹었다. "안 지운다"는 안전 규칙이 동시에 **무한 누적 규칙**이었던 것이다.
   그래서 안전은 유지하되 기한을 둔다 — 기한 안에서는 여전히 절대 안 지운다.

쓰는 법
-------
    python -m engine.storage_gc              # 드라이런 — 무엇을 지울지만 보여준다
    python -m engine.storage_gc --apply      # 실제 삭제(정상 Storage API 사용 → 고아 안 생김)

`engine/publish.py` 가 유튜브 업로드에 성공하면 그 편만 대상으로 자동 호출한다.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger("engine")

#: `{directive_id}/{render_job_id}_{lang}.mp4` 또는 `{directive_id}/{uuid}.mp4` 가 최종 산출물.
#: 그 외 mp4 는 컷별 클립, 나머지는 컷별 스틸(둘 다 재생성 캐시).
_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


@dataclass(frozen=True)
class Obj:
    """저장소 오브젝트 한 개(판정에 필요한 것만)."""

    path: str
    size: int
    #: 파일이 만들어진 지 며칠 됐나. 기한 규칙(④⑤)의 판정 기준이다.
    #: 기본 0 이면 "방금 만든 것"으로 보므로, 나이를 모르면 아무것도 안 지운다(안전측).
    age_days: float = 0.0


@dataclass(frozen=True)
class JobState:
    """렌더 잡 하나의 상태. 판정에 필요한 것만 추린 것."""

    job_id: str
    directive_id: str
    trashed: bool
    uploaded: bool
    #: 휴지통에 들어간 지 며칠 됐나. ⑥ 의 "버리기"는 **복원 가능한** 소프트 삭제라
    #: 바로 파일을 지우면 [복원]이 껍데기가 된다. 보관 기간이 지난 것만 회수한다.
    trashed_days: float = 0.0


@dataclass(frozen=True)
class Doomed:
    path: str
    size: int
    reason: str


def classify(path: str) -> str:
    """경로 → 'final' | 'clip' | 'still'."""
    import re

    if re.search(rf"_(?:ko|en)\.mp4$", path) or re.search(rf"/{_UUID}\.mp4$", path):
        return "final"
    return "clip" if path.endswith(".mp4") else "still"


def job_id_of(path: str) -> str:
    """최종 산출물 경로에서 렌더 잡 id 를 뽑는다. 없으면 빈 문자열."""
    import re

    m = re.search(rf"({_UUID})(?:_(?:ko|en))?\.mp4$", path)
    return m.group(1) if m else ""


def directive_of(path: str) -> str:
    """`report/{dir}/…` 와 `{dir}/…` 둘 다에서 지시서 id 를 뽑는다."""
    parts = path.split("/")
    if not parts:
        return ""
    return parts[1] if parts[0] == "report" and len(parts) > 1 else parts[0]


def plan(objects: list[Obj], jobs: list[JobState],
         trash_retention_days: float = 7.0,
         cache_retention_days: float = 14.0,
         unpublished_retention_days: float = 30.0) -> list[Doomed]:
    """지울 것을 고른다. **순수 함수** — 네트워크·DB 를 모른다(테스트: tests/test_storage_gc.py).

    모르는 것은 지우지 않는다: 연결된 잡을 하나도 못 찾은 경로는 남긴다.
    나이를 모르는 것(`age_days=0`)도 기한 규칙에 안 걸린다 — 둘 다 안전측이다.

    기한 셋이 각각 다른 위험을 막는다:
      · `trash_retention_days`   버린 뒤 ⑥ 에서 [복원]할 수 있어야 하는 기간
      · `cache_retention_days`   컷 캐시는 재생성 가능 — 2주면 캐시로서 값을 잃는다
      · `unpublished_retention_days`
            한 달이 지나도록 안 올린 편은 운영자가 접은 것으로 본다. 이 기한이 없으면
            저장소가 무한히 쌓인다(§ 모듈 docstring 의 532MB 실측).
    """
    alive: dict[str, int] = {}
    alive_up: dict[str, int] = {}
    #: 이 편의 휴지통 잡들이 전부 보관 기간을 넘겼는가
    trash_ripe: dict[str, bool] = {}
    uploaded_jobs: set[str] = set()
    known: set[str] = set()
    for j in jobs:
        known.add(j.directive_id)
        alive.setdefault(j.directive_id, 0)
        alive_up.setdefault(j.directive_id, 0)
        if j.uploaded:
            uploaded_jobs.add(j.job_id)
        if not j.trashed:
            alive[j.directive_id] += 1
            if j.uploaded:
                alive_up[j.directive_id] += 1
        else:
            ripe = j.trashed_days >= trash_retention_days
            trash_ripe[j.directive_id] = trash_ripe.get(j.directive_id, True) and ripe

    out: list[Doomed] = []
    for o in objects:
        d = directive_of(o.path)
        if d not in known:
            continue  # 판정 근거 없음 → 남긴다
        kind = classify(o.path)
        if alive[d] == 0:
            if not trash_ripe.get(d, False):
                continue  # 아직 복원할 수 있는 기간 — 남긴다
            out.append(Doomed(o.path, o.size, f"휴지통 잡({trash_retention_days:.0f}일 경과)"))
        elif kind == "final" and job_id_of(o.path) in uploaded_jobs:
            out.append(Doomed(o.path, o.size, "업로드된 최종 mp4"))
        elif kind != "final" and alive[d] == alive_up[d]:
            out.append(Doomed(o.path, o.size, "업로드 완료 편의 컷 캐시"))
        elif kind != "final" and o.age_days >= cache_retention_days:
            out.append(Doomed(o.path, o.size, f"묵은 컷 캐시({cache_retention_days:.0f}일 경과)"))
        elif kind == "final" and o.age_days >= unpublished_retention_days:
            out.append(Doomed(o.path, o.size, f"미발행 최종 mp4({unpublished_retention_days:.0f}일 경과)"))
    return out


# ─────────────────────────────────────────────────────────────
# 실제 실행 (DB·Storage 접근)
# ─────────────────────────────────────────────────────────────
BUCKET = "renders"


def _retention() -> tuple[float, float, float]:
    """config 의 보관 기한 3종. `plan()` 을 순수하게 두려고 여기서만 config 를 읽는다."""
    from . import config

    return (float(config.STORAGE_TRASH_RETENTION_DAYS),
            float(config.STORAGE_CACHE_RETENTION_DAYS),
            float(config.STORAGE_UNPUBLISHED_RETENTION_DAYS))


#: 한 번의 list() 응답 상한. Supabase 기본값은 100 이라 명시하지 않으면 조용히 잘린다.
_LIST_LIMIT = 1000
#: 폭주 방지(경로가 예상 밖으로 깊을 때).
_MAX_DEPTH = 4


def _age_days(entry: dict, now: datetime) -> float:
    """storage list 응답의 생성시각 → 며칠 됐나. 못 읽으면 0(=방금 만든 것, 안 지움)."""
    raw = entry.get("created_at") or (entry.get("metadata") or {}).get("lastModified")
    if not raw:
        return 0.0
    try:
        at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - at).total_seconds() / 86400)


def _walk(supa, path: str, out: list[Obj], now: datetime | None = None,
          depth: int = 0) -> None:
    """폴더를 재귀로 훑어 파일만 모은다.

    ★ 왜 재귀인가(2026-08-28 실측): 컷 캐시는 최상위가 아니라 **`{지시서}/assets/cut_N.png`**
      하위 폴더에 있다. 최상위만 보면 그 폴더는 `metadata` 가 없는 "폴더 항목" 하나로 보이고,
      크기가 0 으로 잡힌다 — 실제로 드라이런이 캐시 21개를 `0 MB` 로 보고했다.
      즉 **재귀하지 않으면 지워야 할 것을 못 찾고, 크기 집계도 거짓말을 한다.**
    """
    now = now or datetime.now(timezone.utc)
    if depth > _MAX_DEPTH:
        log.warning("storage 경로가 너무 깊다 — 중단: %s", path)
        return
    try:
        entries = supa.storage.from_(BUCKET).list(path, {"limit": _LIST_LIMIT}) or []
    except Exception as exc:  # noqa: BLE001 — 없는 폴더는 건너뛴다
        log.debug("storage list 실패(%s): %s", path, exc)
        return
    for e in entries:
        nm = e.get("name") or ""
        if not nm:
            continue
        child = f"{path}/{nm}"
        meta = e.get("metadata")
        if meta:  # 파일
            out.append(Obj(child, int(meta.get("size") or 0), _age_days(e, now)))
        else:  # 하위 폴더 — 들어간다
            _walk(supa, child, out, now, depth + 1)


def _load(supa) -> tuple[list[Obj], list[JobState]]:
    objects: list[Obj] = []
    jobs: list[JobState] = []

    now = datetime.now(timezone.utc)

    def collect(table: str, up_table: str, prefix: str = "") -> None:
        rows = supa.table(table).select("id, directive_id, deleted_at").execute().data or []
        ups = (supa.table(up_table).select("render_job_id, status, youtube_url")
               .eq("status", "done").execute().data or [])
        done = {u["render_job_id"] for u in ups if (u.get("youtube_url") or "").strip()}
        for r in rows:
            days = 0.0
            if r.get("deleted_at"):
                try:
                    at = datetime.fromisoformat(str(r["deleted_at"]).replace("Z", "+00:00"))
                    days = (now - at).total_seconds() / 86400
                except ValueError:
                    days = 0.0  # 못 읽으면 방금 버린 것으로 본다(안전측 — 안 지운다)
            jobs.append(JobState(
                job_id=str(r["id"]),
                directive_id=str(r["directive_id"]),
                trashed=r.get("deleted_at") is not None,
                uploaded=r["id"] in done,
                trashed_days=days,
            ))
        folders = {str(r["directive_id"]) for r in rows}
        for d in sorted(folders):
            _walk(supa, f"{prefix}{d}", objects, now)

    collect("render_jobs", "upload_requests")
    collect("report_render_jobs", "report_upload_requests", prefix="report/")
    return objects, jobs


def walk_all(supa, prefix: str = "") -> list[Obj]:
    """버킷 전체(또는 prefix 아래)의 파일을 모은다. 용량 집계용 공개 진입점.

    ★ `_load` 와 다르다: `_load` 는 **판정에 필요한 폴더만** 훑는다(렌더 잡이 있는
      지시서 폴더). 용량은 그것으로 못 센다 — 잡이 사라진 고아 폴더도 용량은 먹는다.
      2026-08-24 정지 사고 때 한도를 넘긴 것에는 그런 파일도 섞여 있었다.
    """
    objects: list[Obj] = []
    _walk(supa, prefix, objects)
    return objects


def sweep(apply: bool = False, supa=None) -> int:
    """전체 훑어 지운다. 반환: 회수한 바이트."""
    from .db import client

    supa = supa or client()
    objects, jobs = _load(supa)
    doomed = plan(objects, jobs, *_retention())
    total = sum(d.size for d in doomed)

    by_reason: dict[str, list[int]] = {}
    for d in doomed:
        by_reason.setdefault(d.reason, []).append(d.size)
    for reason, sizes in sorted(by_reason.items(), key=lambda kv: -sum(kv[1])):
        log.info("  %-22s %4d개 %8.0f MB", reason, len(sizes), sum(sizes) / 1024 / 1024)
    log.info("  %-22s %4d개 %8.0f MB", "합계", len(doomed), total / 1024 / 1024)

    if not apply:
        log.info("드라이런 — 실제로 지우려면 --apply")
        return total

    paths = [d.path for d in doomed]
    for i in range(0, len(paths), 50):
        supa.storage.from_(BUCKET).remove(paths[i:i + 50])
        log.info("  삭제 %d/%d", min(i + 50, len(paths)), len(paths))
    return total


def purge_after_upload(directive_id: str, supa=None, report: bool = False) -> int:
    """업로드 직후 그 편만 정리한다. `engine/publish.py` 가 부른다.

    실패해도 **업로드를 되돌리지 않는다** — 정리는 부수 작업이고, 못 지웠으면 다음 sweep 이 잡는다.
    """
    from .db import client

    try:
        supa = supa or client()
        objects, jobs = _load(supa)
        prefix = f"report/{directive_id}" if report else directive_id
        doomed = [d for d in plan(objects, jobs, *_retention())
                  if d.path.startswith(prefix + "/")]
        if not doomed:
            return 0
        supa.storage.from_(BUCKET).remove([d.path for d in doomed])
        freed = sum(d.size for d in doomed)
        log.info("업로드 후 정리: %s — %d개 · %.0f MB 회수", directive_id, len(doomed), freed / 1024 / 1024)
        return freed
    except Exception as exc:  # noqa: BLE001
        log.warning("업로드 후 정리 실패(무시, 다음 sweep 이 처리): %s", exc)
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sweep(apply="--apply" in sys.argv)
