"""같은 아티클이 번호만 바꿔 다시 들어오는 것을 막는 열쇠(순수 함수).

★ 왜 따로 있나(2026-11-23 실측). 수집 단계의 중복 제거는 **그 회차 안에서만** 비교했다.
  DB 에 이미 있는 글과는 비교하지 않아서, 같은 글이 다른 날 다른 external_id 로 오면 새 글이 됐다.
    · 리포트: 같은 텔레그램 메시지가 다음 날 새 신호 번호로 다시 수집(신한 엔비디아 11/20·11/21),
              같은 리포트를 포털 두 곳(한경·네이버)에서 받아 두 건(삼성전기 11/21 후보 2건)
    · 논문:   arXiv 사전공개본과 몇 달 뒤 학술지 정식본(제목 같음, external_id 다름)
  리포트는 수집(새 글 거르기 — drop_known)과 배치(group_ids) 두 곳에서, 논문은 **배치에서만** 쓴다
  (수집 때 빼면 후보 창 밖의 사전공개본 때문에 한 번도 안 보인 정식본이 사라진다).

★ 같은 글 판정 = 열쇠가 같고, 제목이 서로 포함 관계이고, 본문(리포트)이 거의 통째로 같다(same_article).
  - 리포트 열쇠는 요약 앞부분이다. 제목은 포털마다 표기가 달라서('삼성전기(009150) …' vs
    '[삼성전기] …') 열쇠로 못 쓰고, 연재물은 제목이 같아도 내용이 다르다('Daily Market Digest').
  - 그런데 연재물은 요약 머리말도 같을 수 있다('Japan Weekly(10월 2주차)' vs '(10월 3주차)').
    그래서 제목 포함 관계를 한 번 더 본다 — 주차·날짜가 다르면 다른 글이다.
  - 제목까지 같은 연재물('Market Weekly Check ME up!' 10/17·11/14)은 머리말 뒤 본문이 다르다.
    진짜 재게시는 본문이 98% 이상 같았다(실측 65묶음) — 그래서 본문 일치율도 본다.

★ 함정 — 상투 문구. KB "장마감코멘트" 는 날마다 다른 글인데 요약이 똑같은 면책 문구로 시작한다.
  ① 면책 문구 문장을 빼고 열쇠를 만들고 ② 그래도 한 열쇠를 너무 많은 글이 나눠 가지면
  (DEDUP_BOILERPLATE_GROUP 이상) 상투 문구로 보고 판정에 쓰지 않는다 — 진짜 중복은 2~4건이다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Iterable

from . import config

_KEEP_RE = re.compile(r"[\W_]+")   # 모든 언어의 글자·숫자는 남긴다(τ·μ 가 다른 논문을 같게 보지 않게)
_SENT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")
_URL_RE = re.compile(r"https?://\S+")
_STOCK_CODE_RE = re.compile(r"\d{6}")


def _norm(text: str) -> str:
    """소문자 + 글자·숫자만(공백·기호·이모지 제거). 그리스 문자 등 비영문 글자는 남긴다."""
    return _KEEP_RE.sub("", (text or "").lower())


def paper_key(title: str | None) -> str | None:
    """논문 열쇠 = 정규화 제목. 짧은 제목('New Products' 같은 잡지 꼭지)은 열쇠 없음."""
    key = _norm(title or "")
    return key if len(key) >= config.PAPER_DEDUP_MIN_TITLE_CHARS else None


def _strip_boilerplate(text: str) -> str:
    """링크와, 면책·고지 문구가 든 문장을 뺀다."""
    markers = config.REPORT_DEDUP_BOILERPLATE_MARKERS
    kept = [s for s in _SENT_RE.split(_URL_RE.sub(" ", text or ""))
            if not any(m in s for m in markers)]
    return " ".join(kept)


def report_body(summary: str | None) -> str:
    """비교용 본문 = 링크·면책 문구를 뺀 요약의 정규화 글자."""
    return _norm(_strip_boilerplate(summary or ""))


def report_key(title: str | None, summary: str | None) -> str | None:
    """리포트 열쇠(묶음 후보) = 본문 앞부분. 본문이 너무 짧으면 열쇠 없음."""
    body = report_body(summary)
    if len(body) < config.REPORT_DEDUP_MIN_CHARS:
        return None
    return body[: config.REPORT_DEDUP_KEY_CHARS]


def _shared_ratio(a: str, b: str) -> float:
    """앞에서부터 같은 글자 수 / 긴 쪽 길이."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n / max(len(a), len(b), 1)


def same_article(title_a: str | None, title_b: str | None,
                 body_a: str | None = None, body_b: str | None = None) -> bool:
    """열쇠가 같은 두 글이 정말 같은 글인가.

    ① 제목이 서로 포함 관계(종목코드 6자리는 표기 차이라 뺀다, 한쪽이 비면 통과)
    ② 본문이 둘 다 있으면 앞에서부터 REPORT_DEDUP_MIN_SHARED 이상 같다.
    """
    a = _norm(_STOCK_CODE_RE.sub("", title_a or ""))
    b = _norm(_STOCK_CODE_RE.sub("", title_b or ""))
    if a and b and not (a in b or b in a):
        return False
    if body_a and body_b:
        return _shared_ratio(body_a, body_b) >= config.REPORT_DEDUP_MIN_SHARED
    return True


def boilerplate_keys(pairs: Iterable[tuple[str, str | None]]) -> set[str]:
    """너무 많은 **서로 다른 글**이 나눠 가진 열쇠 = 상투 문구. 판정에서 뺀다.

    pairs = [(external_id 또는 id, 열쇠)]. 같은 글을 다시 수집한 행은 한 번만 센다 —
    행 수로 세면 이미 쌓인 중복 쌍이 재수집될 때 문턱을 넘어 거르기가 꺼진다(리뷰 지적).
    """
    owners: dict[str, set[str]] = defaultdict(set)
    for ext, key in pairs:
        if key:
            owners[key].add(ext)
    return {k for k, s in owners.items() if len(s) >= config.DEDUP_BOILERPLATE_GROUP}


def drop_known(
    items: list[Any],
    ext_of: Callable[[Any], str],
    key_of: Callable[[Any], str | None],
    title_of: Callable[[Any], str | None],
    existing: list[tuple[str, str | None, str | None, str | None]],
    body_of: Callable[[Any], str | None] = lambda _: None,
) -> tuple[list[Any], list[tuple[str, str]]]:
    """이미 있는 글(다른 external_id)과 같은 글인 새 글을 뺀다. 이번 회차 안의 겹침도 뺀다.

    existing: [(external_id, 열쇠, 제목, 본문)] — 비교 대상 기존 글(본문은 리포트만, 논문은 None).
    같은 external_id 의 재수집(갱신)은 빼지 않는다 — upsert 가 갱신으로 처리한다.
    반환: (남은 것, [(뺀 external_id, 같은 글로 본 external_id)]).
    """
    ignore = boilerplate_keys([(e[0], e[1]) for e in existing]
                              + [(ext_of(it), key_of(it)) for it in items])
    seen: dict[str, list[tuple[str, str | None, str | None]]] = defaultdict(list)
    for ext, key, title, body in existing:
        if key and key not in ignore:
            seen[key].append((ext, title, body))
    stored = {e[0] for e in existing}
    kept: list[Any] = []
    dropped: list[tuple[str, str]] = []
    for it in items:
        ext, key, title, body = ext_of(it), key_of(it), title_of(it), body_of(it)
        if ext in stored:          # 이미 저장된 글의 재수집 = 갱신. 빼지 않는다.
            kept.append(it)
            continue
        if key and key not in ignore:
            twin = next((e for e, t, b in seen[key]
                         if e != ext and same_article(title, t, body, b)), None)
            if twin:
                dropped.append((ext, twin))
                continue
            seen[key].append((ext, title, body))
        kept.append(it)
    return kept, dropped


def group_ids(records: list[tuple[str, str | None, str | None, str | None]]) -> dict[str, str]:
    """[(id, 열쇠, 제목, 본문)] → id 별 '같은 글 묶음' 대표 id. 열쇠 없는 글은 자기 자신이 대표.

    배치가 쓴다: 같은 묶음은 후보에 한 번만, 지난 후보와 같은 묶음이면 다시 안 올린다.
    """
    ignore = boilerplate_keys((r[0], r[1]) for r in records)
    # 열쇠 → [(대표 id, 제목, 본문)]
    buckets: dict[str, list[tuple[str, str | None, str | None]]] = defaultdict(list)
    out: dict[str, str] = {}
    for rid, key, title, body in records:
        rep = rid
        if key and key not in ignore:
            rep = next((r for r, t, b in buckets[key] if same_article(title, t, body, b)), rid)
            buckets[key].append((rep, title, body))
        out[rid] = rep
    return out


def report_records(rows: list[dict[str, Any]], id_field: str = "id") -> list[tuple[str, str | None, str | None, str | None]]:
    """reports 행 → [(id, 열쇠, 제목, 본문)]."""
    return [(r[id_field], report_key(r.get("title"), r.get("summary")), r.get("title"),
             report_body(r.get("summary"))) for r in rows]


def paper_records(rows: list[dict[str, Any]], id_field: str = "id") -> list[tuple[str, str | None, str | None, str | None]]:
    """papers 행 → [(id, 열쇠, 제목, None)] — 논문은 제목이 곧 열쇠라 본문 비교가 없다."""
    return [(r[id_field], paper_key(r.get("title")), r.get("title"), None) for r in rows]
