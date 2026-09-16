"""수집 누락 진단 (수집지시서 v2 §2) — 누락 DOI 를 OpenAlex 에 직접 질의해 원인을 못 박는다.

"등록 지연이 원인"을 단정하지 않고, 실제 lookup 으로 확정한다:
- created_date > publication_date 크게 → "등록 지연" 확정(created_date 워터마크가 해결).
- primary_location.source.id 가 플래그십 목록에 없음 → "저널 매핑 오류" 확정(config 보강 필요).
- type 이 article|review 아님 → "유형 필터 탈락" 확정.

실행: ``python -m engine.diagnose 10.1126/science.aea9708 [<doi> ...]``
"""

from __future__ import annotations

import sys
from typing import Any

from . import config
from .sources.openalex import _FLAGSHIP_IDS, _source_id
from .util import http_get, log, normalize_doi


def lookup_doi(doi: str) -> dict[str, Any]:
    """단일 DOI 를 OpenAlex 에 질의해 진단 필드를 dict 로. 순수 판정은 classify()."""
    norm = normalize_doi(doi)
    url = f"https://api.openalex.org/works/doi:{norm}"
    params = {"select": config.OPENALEX_SELECT_FIELDS, "mailto": config.SECRETS.openalex_mailto}
    try:
        resp = http_get(url, params=params)
        w = resp.json()
    except Exception as exc:  # noqa: BLE001 — 조회 자체 실패도 진단 결과
        return {"doi_normalized": norm, "lookup_status": f"error: {str(exc)[:120]}"}
    sid = _source_id(w)
    return {
        "doi_normalized": norm,
        "openalex_work_id": (w.get("id") or "").rsplit("/", 1)[-1] or None,
        "openalex_source_id": sid,
        "source_name": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "created_date": w.get("created_date"),
        "publication_date": w.get("publication_date"),
        "updated_date": w.get("updated_date"),
        "type": w.get("type"),
        "in_flagship_config": bool(sid and sid in _FLAGSHIP_IDS),
        "lookup_status": "found" if w.get("id") else "not_found",
    }


def classify(rec: dict[str, Any]) -> str:
    """진단 필드 → 원인 라벨(순수 함수). 여러 원인 가능하나 가장 유력한 하나."""
    if rec.get("lookup_status", "").startswith("error"):
        return "lookup_error(OpenAlex 조회 실패)"
    if rec.get("lookup_status") == "not_found":
        return "not_in_openalex(OpenAlex 미색인 — 소스 자체 부재)"
    created, pub = rec.get("created_date"), rec.get("publication_date")
    if created and pub and str(created) > str(pub):
        return f"index_lag(등록 지연: created {created} > pub {pub}) — 플래그십 넓은 게재일 롤링 창이 다음 실행에서 잡음"
    if not rec.get("in_flagship_config"):
        return f"source_mapping(플래그십 config 미등록 source_id={rec.get('openalex_source_id')})"
    if rec.get("type") not in config.FLAGSHIP_ALLOWED_TYPES:
        return f"type_filter(유형 {rec.get('type')} 이 허용목록 밖)"
    return "no_obvious_cause(색인·매핑·유형 정상 — 페이지네이션/upsert 등 추가 점검)"


def run(dois: list[str]) -> list[dict[str, Any]]:
    config.SECRETS.require("openalex_mailto")
    out: list[dict[str, Any]] = []
    for doi in dois:
        rec = lookup_doi(doi)
        rec["diagnosis"] = classify(rec)
        log.info("진단 %s → %s | %s", rec["doi_normalized"], rec["lookup_status"], rec["diagnosis"])
        out.append(rec)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: python -m engine.diagnose <doi> [<doi> ...]")
        raise SystemExit(2)
    for r in run(args):
        print(r["doi_normalized"], "→", r["diagnosis"])
