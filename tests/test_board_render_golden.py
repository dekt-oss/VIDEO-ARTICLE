"""보드 렌더 **화면 불변** 대조 (작업지시서 영상엔진품질 v3 P2).

무엇을 지키는가: P2 는 시각 레이어를 리팩터한다 — 토큰을 한 곳으로 모으고(P2-b),
드로잉을 컴포넌트 경계로 감싸고(P2-c), `_draw_frame` 의 보드 이름 if 분기를 레지스트리
조회로 바꾼다(P2-e). **이 셋은 전부 "나오는 화면이 오늘과 같아야" 한다**(운영자 결정).

"같다"를 주장이 아니라 검사로 만든다 — 보드 11종을 실제로 렌더해 프레임 PNG 의 해시를
고정값과 대조한다. 리팩터가 픽셀을 한 점이라도 바꾸면 여기서 먼저 깨진다.

★ 왜 해시인가: placements 나 core_fill 같은 파생값만 보면 "색이 바뀌었는데 배치는 같은"
  변경을 통과시킨다. 화면 불변을 주장하려면 화면을 봐야 한다.

★ 폰트가 없는 환경에서는 건너뛴다 — visual_contract 가 FontContractError 를 던진다.
  (렌더 실패를 조용히 폴백하지 않는 것이 이 저장소의 자세라 예외가 그대로 올라온다.)

기준값 갱신: 화면을 **의도적으로** 바꿨을 때만
    python3 -m pytest tests/test_board_render_golden.py --update-golden
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from engine import board_render
from engine import visual_contract as vc

GOLDEN = Path(__file__).parent / "golden" / "board_render_hashes.json"

# 렌더 입력. 보드마다 필요한 필드가 달라 한 벌로 다 채우고 보드만 바꾼다
# (board_payload 가 자기 보드에 필요한 것만 꺼내 쓴다).
HEADER = {
    "version_type": "explainer",
    "aspect_ratio": "9:16",
    "hook_ko": "코스피, 하루 만에 18% 급등의 진실",
    "broker": "대신증권",
    "explainer": {
        "profile": "EVENT",
        "source_mode": "PARTIAL_REPORT",
        "report_claim_summary": {
            "speaker": "대신증권",
            "statement": "빅테크의 설비 투자가 막바지에 이르렀다는 인식이 확산됐습니다.",
        },
        "watchpoint": {"text": "빅테크 CapEx 계획을 주목해야 합니다.", "metric": "CapEx"},
        "number_claims": [
            {"claim_no": 1, "value": "18.50", "unit": "%", "label": "코스피 일일 상승률",
             "comparison_basis": "당일 종가", "comparison_value": "6,628.20pt",
             "why_significant": "이례적인 일일 급등", "big_number_ok": True},
            {"claim_no": 2, "value": "7.6", "unit": "조원", "label": "외국인 순매수",
             "comparison_basis": "당일 집계", "comparison_value": "기관 1.1조원",
             "why_significant": "지수 상승을 견인", "big_number_ok": True},
        ],
    },
}

# 보드 11종 — config.EXPLAINER_BOARD_SCENE_KIND 의 키와 같다.
BOARDS = (
    "HOOK_BOARD", "CLAIM_BOARD", "NUMBER_BOARD", "CHART_BOARD", "EVIDENCE_BOARD",
    "REPORT_REASON_BOARD", "MECHANISM_BOARD", "VALUATION_BOARD", "COMPARISON_BOARD",
    "WATCHPOINT_BOARD", "CONTEXT_BOARD",
)


def _cut(board: str) -> dict:
    return {
        "cut_no": 1,
        "board": board,
        "narration_ko": "외국인 순매수가 7.6조원 유입되며 지수가 급등했습니다.",
        "so_what_ko": "전체 시장 상승을 주도한 핵심 수급 주체입니다.",
        # ★ 복수형이다. `number_claim_ref`(단수)로 적으면 board_payload 가 조용히 못 찾아
        #   NUMBER_BOARD 가 숫자 없이 렌더된다(core_fill 0.0) — 기준값이 숫자 경로를 아예
        #   안 태우게 된다. 처음에 그렇게 적어서 잡았다.
        "number_claim_refs": [1, 2],
        "duration_sec": 4,
    }


def _hash_board(board: str, out_dir: str) -> dict:
    """보드 1종을 렌더해 요약 지문을 낸다. 프레임 수가 많아 전 프레임 대신 첫/중/끝만 센다."""
    res = board_render.render_board(
        _cut(board), HEADER, None, out_dir, idx=BOARDS.index(board),
        total_sec=2.0, lang="ko", bg_image=None,
    )
    paths = res.frame_paths
    assert paths, f"{board}: 프레임이 0장"
    picks = [paths[0], paths[len(paths) // 2], paths[-1]]
    digest = hashlib.sha256()
    for p in picks:
        digest.update(Path(p).read_bytes())
    return {
        "frames": len(paths),
        "sha256": digest.hexdigest(),
        # 해시가 깨졌을 때 "무엇이" 달라졌는지 보이게 파생값도 남긴다.
        "core_fill": round(res.core_fill, 4),
        "placements": len(res.placements),
    }


def _render_all() -> dict:
    out: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as d:
        for board in BOARDS:
            out[board] = _hash_board(board, d)
    return out


def _fonts_available() -> bool:
    try:
        vc.preflight_fonts()
    except Exception:                        # noqa: BLE001 — 폰트 없음 = 이 검사를 못 함
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _fonts_available(), reason="렌더 폰트 없음 — 화면 불변 대조를 못 한다")


def test_board_render_is_pixel_stable():
    """P2 리팩터가 화면을 바꾸지 않았는가. 이것이 P2-b·P2-c·P2-e 의 합격기준이다."""
    if not GOLDEN.exists():
        pytest.skip(f"기준값 없음 — 먼저 생성: python3 {Path(__file__).parent}/make_golden.py")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = _render_all()

    changed = [b for b in BOARDS if expected.get(b, {}).get("sha256") != actual[b]["sha256"]]
    if changed:
        detail = "\n".join(
            f"  {b}: 기대 {expected.get(b, {})} / 실제 {actual[b]}" for b in changed)
        pytest.fail(
            "보드 렌더 화면이 바뀌었다(P2 는 화면 불변이 합격기준):\n" + detail +
            "\n의도한 변경이면 tests/golden/board_render_hashes.json 을 갱신하고 "
            "커밋 메시지에 무엇이 왜 바뀌는지 적어라.")


def test_golden_covers_every_board():
    """보드를 새로 추가하고 기준값을 안 넣으면 그 보드는 검사를 안 받는다."""
    if not GOLDEN.exists():
        pytest.skip("기준값 없음")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(expected) == set(BOARDS)
