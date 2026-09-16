"""단계별 소요시간 계측 (작업지시서 영상엔진품질 v3 §10 관측성).

무엇이 없었나: §10 이 "stage metric(job당): parse/extract/draft/directive/asset/render/qa ms"
를 요구하는데, 저장소 전체에 **타이머가 한 개도 없었다**(`stage_ms|elapsed_ms|duration_ms`
grep 0건). 렌더가 8분 걸려도 그 8분이 어디서 갔는지 아무도 몰랐다 — 에셋 생성인지, TTS 인지,
조립인지. 느려졌을 때 어디를 볼지 정할 근거가 없다는 뜻이다.

★ §10 의 나머지 항목(토큰·image_calls·retry·cost_total)은 이미 `generation_attempts`
  원장이 호출 1건 = 1행으로 담고 있다(engine/cost.py). 여기서 다시 세지 않는다 — 같은 수를
  두 곳에서 세면 반드시 갈린다.

★ 저장 위치는 잡의 `qa` jsonb 다(마이그레이션 없음). `qa["board"]`·`qa["cut_map"]` 이
  이미 같은 방식으로 들어가 있어 그 관례를 따른다.

순수 모듈 — 시계 외에는 아무것도 만지지 않는다. DB·네트워크 없음.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any, Iterator

# §10 이 열거한 단계 이름. 오타로 새 키가 생기면 집계가 조용히 갈리므로 어휘를 고정한다.
STAGES: tuple[str, ...] = (
    "parse", "extract", "draft", "directive", "asset", "tts", "assemble", "render", "qa", "upload",
)

# ★ **다른 단계 안에서 재는** 단계. 합계에서 빼지 않으면 이중 계상된다.
#   실측 사고(2026-08-03, 리뷰 지적): TTS 는 `_gen_cut_assets` 안에서 재는데 그 함수 전체가
#   이미 `asset` 블록 안에 있다. 그래서 asset_ms 에 TTS 시간이 포함돼 있는데 total_ms 가
#   tts_ms 를 또 더했다 — 아래 total_ms 의 "겹치는 단계가 없다"는 가정을 이 파일 자신이
#   깨고 있었다. 중첩은 없애는 게 아니라(둘 다 알고 싶다) **선언**해서 합계에서 뺀다.
NESTED_STAGES: frozenset[str] = frozenset({"tts"})


@contextlib.contextmanager
def stage(out: dict[str, Any] | None, name: str) -> Iterator[None]:
    """`with stage(m, "asset"):` — 블록의 소요시간을 out[name+"_ms"] 에 정수 ms 로 남긴다.

    ★ 예외가 나도 기록한다(finally). 오히려 실패한 잡의 소요시간이 더 궁금하다 — "어디까지
      가다가 죽었나"가 원인 추적의 출발점이다.
    ★ out 이 None 이면 아무것도 하지 않는다. 계측 배선이 안 된 호출자를 막지 않기 위해서다 —
      관측을 켜다가 파이프라인을 죽이는 것이 이 저장소가 겪은 사고다(report_render 의 run_qa).
    """
    if name not in STAGES:
        raise ValueError(f"알 수 없는 단계: {name} (STAGES 에 먼저 추가한다)")
    t0 = time.monotonic()
    try:
        yield
    finally:
        if out is not None:
            out[f"{name}_ms"] = int((time.monotonic() - t0) * 1000)


def _stage_items(metrics: dict[str, Any]) -> list[tuple[str, int]]:
    """(단계이름, ms) 목록. total_ms 자신과 비-숫자는 뺀다."""
    return [(k[:-3], int(v)) for k, v in (metrics or {}).items()
            if k.endswith("_ms") and k != "total_ms" and isinstance(v, (int, float))]


def total_ms(metrics: dict[str, Any]) -> int:
    """계측된 단계들의 합(ms). **중첩 단계는 뺀다** — 그러지 않으면 이중 계상이다.

    예: asset 100ms 안에 tts 40ms 가 들어 있으면 합은 100 이지 140 이 아니다.
    """
    return sum(ms for name, ms in _stage_items(metrics) if name not in NESTED_STAGES)


def summarize(metrics: dict[str, Any]) -> str:
    """로그 한 줄용. 느린 단계부터 적는다 — 눈이 먼저 가야 할 곳이 앞에 있어야 한다.

    중첩 단계는 `tts=1200ms(asset 내부)` 처럼 표시한다. 표시가 없으면 로그를 읽는 사람이
    합계와 항목이 안 맞는 것을 보고 계측이 틀렸다고 생각한다.
    """
    items = _stage_items(metrics)
    if not items:
        return "(계측 없음)"
    items.sort(key=lambda kv: kv[1], reverse=True)
    return " ".join(f"{name}={ms}ms" + ("(내부)" if name in NESTED_STAGES else "")
                    for name, ms in items)
