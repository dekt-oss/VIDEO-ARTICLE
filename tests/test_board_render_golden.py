"""보드 렌더 **화면 불변** 대조 (작업지시서 영상엔진품질 v3 P2).

무엇을 지키는가: P2 는 시각 레이어를 리팩터한다 — 토큰을 한 곳으로 모으고(P2-b),
드로잉을 컴포넌트 경계로 감싸고(P2-c), `_draw_frame` 의 보드 이름 if 분기를 레지스트리
조회로 바꾼다(P2-e). **이 셋은 전부 "나오는 화면이 오늘과 같아야" 한다**(운영자 결정).

"같다"를 주장이 아니라 검사로 만든다 — 보드 11종을 실제로 렌더해 프레임 PNG 의 해시를
고정값과 대조한다. 리팩터가 픽셀을 한 점이라도 바꾸면 여기서 먼저 깨진다.

★ 왜 해시인가: placements 나 core_fill 같은 파생값만 보면 "색이 바뀌었는데 배치는 같은"
  변경을 통과시킨다. 화면 불변을 주장하려면 화면을 봐야 한다.

★★ 이 대조는 **리눅스에서만 성립한다.** 기준값은 CI(ubuntu) 에서 만든 것이고,
  윈도우 Pillow 휠에는 텍스트 셰이퍼 raqm/harfbuzz 가 없어(실측: features.check("raqm")
  → False) 같은 폰트·같은 코드로도 글자 배치가 리눅스와 미세하게 어긋난다.
  그래서 윈도우에서는 **대조를 하지 않고 건너뛴다.** 여기서 빨간 것을 보고 기준값을
  갱신하면 CI 가 그날로 빨개지고 이 검사는 무의미해진다.

  실측 근거(2026-09-17, docs/실측_골든해시_환경의존_2026-09-17.md):
    · 기준값을 만든 그 시점의 트리(68b4f1f1, 2026-08-20)를 그대로 꺼내 윈도우에서
      돌려도 **자기 기준값과 어긋난다** → 코드 드리프트가 아니다.
    · Pillow 11.3 과 12.3 이 서로 **완전히 같은 해시**를 냈다 → Pillow 버전도 아니다.
    · 남는 차이가 셰이퍼다. golden-refresh.yml 머리말이 처음부터 그렇게 적어 뒀다.

★ 폰트가 없으면 대조를 못 한다. 다만 **기준 환경에서는 그것을 skip 으로 넘기지 않는다** —
  폰트는 assets/fonts/ 에 커밋돼 있어서 없다는 것은 체크아웃이 깨졌다는 뜻이고, 그때
  조용히 건너뛰면 대조가 통째로 사라져도 CI 는 초록이다(아래 전용 검사가 그것을 막는다).

기준값 갱신: 화면을 **의도적으로** 바꿨을 때만, **워크플로로** 한다 —
    Actions → golden-refresh → Run workflow (무엇을 바꿨는지 적는다)
  로컬에서 `tests/make_golden.py` 를 직접 돌리지 말 것(그 스크립트가 막는다).
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

from engine import board_render
from engine import visual_contract as vc

GOLDEN = Path(__file__).parent / "golden" / "board_render_hashes.json"

# 기준값을 만드는 환경. 여기서만 대조가 성립한다(파일 머리말 참조).
#   ★ sys.platform 으로 가른다 — raqm 유무로 가르면 "기준 환경에도 raqm 이 있는가"를
#     확인하지 않은 채 CI 를 조용히 skip 으로 보낼 수 있다. 플랫폼은 확실하다.
BASELINE_PLATFORM = "linux"

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


def test_fonts_are_present_on_the_baseline_platform():
    """기준 환경에서 폰트가 없으면 **실패**한다 — 건너뛰지 않는다.

    폰트는 assets/fonts/ 에 커밋돼 있으므로 기준 환경에서 없다는 것은 체크아웃이 깨졌다는
    뜻이다. 종전엔 그 상황도 skip 이라, 화면 대조가 통째로 사라져도 CI 는 초록이었다.
    tests.yml 의 skip 가드는 **건수만** 보고 이름을 안 보기 때문에 거기서도 안 잡힌다.
    """
    if sys.platform != BASELINE_PLATFORM:
        pytest.skip(f"기준 환경({BASELINE_PLATFORM})이 아니다 — 여기서 잴 일이 아니다")
    assert _fonts_available(), (
        "기준 환경에 렌더 폰트가 없다. assets/fonts/ 는 저장소에 커밋돼 있으므로 "
        "체크아웃·경로가 깨진 것이다. 이대로 두면 화면 불변 대조가 통째로 건너뛰어진다.")


@pytest.mark.skipif(
    sys.platform != BASELINE_PLATFORM,
    reason=(f"기준값은 {BASELINE_PLATFORM}(CI)에서 만든다 — 여기선 텍스트 셰이퍼가 달라 "
            "해시가 반드시 어긋난다. 판정은 CI 가 한다. 기준값을 갱신하지 말 것."))
@pytest.mark.skipif(
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
            "\n의도한 변경이면 Actions → golden-refresh 워크플로로 기준값을 다시 만든다"
            "(무엇을 왜 바꿨는지 입력값으로 남는다). 손으로 JSON 을 고치거나 로컬에서 "
            "make_golden.py 를 돌리지 말 것 — 환경이 달라 CI 가 빨개진다.")


def test_golden_covers_every_board():
    """보드를 새로 추가하고 기준값을 안 넣으면 그 보드는 검사를 안 받는다."""
    if not GOLDEN.exists():
        pytest.skip("기준값 없음")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(expected) == set(BOARDS)
