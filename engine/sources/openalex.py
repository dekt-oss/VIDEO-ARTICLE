"""OpenAlex 수집 (명세 2-1).

인증 키 불필요. polite pool 을 위해 mailto 파라미터를 붙인다(리뷰 D1).
초록은 abstract_inverted_index(단어→위치 맵)로 오므로 평문 복원이 필요하다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .. import config
from ..attribution import strip_markup
from ..models import Paper
from ..util import http_get, log, normalize_doi


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """abstract_inverted_index → 평문(위치 순 단어 재배열)."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)


def _doi_external_id(work: dict[str, Any]) -> Optional[str]:
    doi = work.get("doi")
    if doi:
        return normalize_doi(doi)
    return None


def _venue(work: dict[str, Any]) -> Optional[str]:
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    return src.get("display_name")


def _authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    """저자 목록 + 각 저자의 대표 소속기관(첫 institution). 나레이션 구체화·출처 표기용."""
    out = []
    for a in work.get("authorships", []) or []:
        author = a.get("author") or {}
        insts = [i.get("display_name") for i in (a.get("institutions") or [])
                 if i.get("display_name")]
        out.append({
            "name": author.get("display_name"),
            "id": author.get("id"),
            "institution": insts[0] if insts else None,
        })
    return out


def _parse_date(s: str | None) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _source_id(work: dict[str, Any]) -> Optional[str]:
    """primary_location.source.id 를 'S...' 짧은 형태로(플래그십 판정용)."""
    loc = work.get("primary_location") or {}
    src = loc.get("source") or {}
    sid = src.get("id")
    return sid.rsplit("/", 1)[-1] if sid else None  # https://openalex.org/S.. → S..


_FLAGSHIP_IDS: set[str] = {
    s["source_id"] for s in config.FLAGSHIP_SOURCES if s.get("enabled")
}


def _build_paper(w: dict[str, Any]) -> Optional[Paper]:
    """OpenAlex work → Paper. DOI 없는 항목은 None(arXiv 가 따로 잡음)."""
    ext = _doi_external_id(w)
    if not ext:
        return None
    sid = _source_id(w)
    oa_id = (w.get("id") or "").rsplit("/", 1)[-1] or None
    return Paper(
        external_id=ext,
        source="openalex",
        title=strip_markup(w.get("title") or ""),  # OpenAlex 제목의 <i>..</i> 등 HTML 제거
        abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
        authors=_authors(w),
        venue=_venue(w),
        published_date=_parse_date(w.get("publication_date")),
        url=w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url"),
        doi=ext,
        work_type=w.get("type"),
        openalex_id=oa_id,
        source_id=sid,
        source_created_date=_parse_date(w.get("created_date")),
        is_flagship=bool(sid and sid in _FLAGSHIP_IDS),
    )


def _run_query(filters: list[str], sort: str, label: str, max_results: int | None = None) -> list[Paper]:
    """공통 커서 페이지네이션 수집(필터·정렬만 다름). select 로 필요한 필드만."""
    config.SECRETS.require("openalex_mailto")
    cap = max_results if max_results is not None else config.OPENALEX_MAX_RESULTS
    papers: list[Paper] = []
    cursor = "*"
    base_params: dict[str, Any] = {
        "filter": ",".join(filters),
        "per-page": config.OPENALEX_PER_PAGE,
        "select": config.OPENALEX_SELECT_FIELDS,
        "sort": sort,
        "mailto": config.SECRETS.openalex_mailto,
    }
    page = 0
    while cursor and len(papers) < cap:
        resp = http_get(config.OPENALEX_BASE, params=dict(base_params, cursor=cursor))
        data = resp.json()
        results = data.get("results", [])
        for w in results:
            p = _build_paper(w)
            if p is not None:
                papers.append(p)
        cursor = (data.get("meta") or {}).get("next_cursor")
        page += 1
        if not results:
            break
    log.info("OpenAlex[%s]: %d papers (%d pages)", label, len(papers), page)
    return papers


def collect(start: date, end: date) -> list[Paper]:
    """[start, end] 발행 범위의 works 를 수집(주 수집, 게재일 기준 — 즉시 색인되는 일반 논문)."""
    filters = [
        f"from_publication_date:{start.isoformat()}",
        f"to_publication_date:{end.isoformat()}",
        "has_abstract:true",
    ]
    if config.PEER_REVIEWED_ONLY:
        # 저널에 실린 일반 논문만(프리프린트 서버·데이터셋·세미나 항목 제외) = 동료 리뷰 근사.
        filters += ["type:article", "primary_location.source.type:journal"]
    return _run_query(filters, sort="publication_date:desc", label=f"main {start}~{end}")


def collect_flagship(pub_from: date) -> list[Paper]:
    """플래그십 저널을 게재일 넓은 롤링 창으로 수집(무료 티어).

    ★ 왜 created_date 가 아니라 publication_date 인가: OpenAlex 의 from_created_date 필터는 유료
      플랜 전용("Plan upgrade required")이라 무료 polite pool 로는 못 쓴다. 대신 "플래그십 6개
      source_id 로만 좁힌 넓은 게재일 창"을 매 실행 훑는다. 소스가 좁아 볼륨이 작으므로(주 수집의
      1000컷 손실 없음), 게재 당시 미색인이던 논문도 다음 실행(창이 넓어 여전히 포함)에서 반드시 잡힌다.
    type=article|review, paratext/retracted 제외. 멱등 upsert 라 매 실행 재수집해도 안전.
    """
    src_ids = "|".join(_FLAGSHIP_IDS)
    if not src_ids:
        return []
    types = "|".join(config.FLAGSHIP_ALLOWED_TYPES)
    filters = [
        f"primary_location.source.id:{src_ids}",
        f"from_publication_date:{pub_from.isoformat()}",
        f"type:{types}",
        "is_paratext:false",
        "is_retracted:false",
        "has_abstract:true",
    ]
    return _run_query(filters, sort="publication_date:desc",
                      label=f"flagship pub≥{pub_from}", max_results=config.FLAGSHIP_MAX_RESULTS)
