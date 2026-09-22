"""테스트 공용 픽스처.

★ 왜 생겼나 (2026-08-03, CI 첫 실행에서 드러난 것):
   `primary_filter` 를 부르는 테스트 2건이 **로컬에서만 초록**이었다. 이 샌드박스에는
   `langdetect` 가 설치돼 있지 않아 `pipeline._detect` 가 None 이고, 그래서 언어 게이트가
   통째로 건너뛰어진다. CI 러너에는 설치되므로 게이트가 살아나고, 테스트가 쓰던 채움
   문자열("aaaa…"·"bbbb…")이 영/한이 아닌 것으로 판정돼 **전부 걸러졌다** — 두 테스트가
   빈 목록을 받고 실패했다.

   즉 문제는 테스트가 틀린 것이 아니라 **환경에 따라 다른 코드를 돌고 있었다**는 것이다.
   실제 초록처럼 보이는 영문을 쓰는 것으로도 넘길 수는 있지만, 그러면 판정이 langdetect 의
   확률적 결과에 얹히고 검사 대상(컷오프·정렬)과 무관한 이유로 깨질 수 있다. 그래서
   **탐지기를 고정한다** — 언어 게이트 자체는 아래 전용 테스트가 따로 덮는다.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def stub_lang_detect(monkeypatch):
    """언어 탐지기를 '항상 en' 으로 고정한다(langdetect 설치 여부와 무관).

    컷오프·정렬을 보는 테스트가 언어 판정에 흔들리지 않게 하는 용도다. 게이트가 실제로
    거르는지는 tests/test_logic.py 의 언어 게이트 테스트가 본다.
    """
    from engine import pipeline

    monkeypatch.setattr(pipeline, "_detect", lambda _text: "en")
    return "en"


@pytest.fixture(autouse=True)
def _no_ledger_writes_from_tests(monkeypatch):
    """★ 테스트가 **운영 비용 원장에 쓰지 못하게** 막는다 (2026-08-29 실측 사고).

    무슨 일이 있었나: `pytest tests/test_shared_assets.py` 한 번에 운영 DB 의
    `generation_attempts` 가 519 → 528 행으로 늘었다. 테스트는 이미지 생성 함수를 가짜로
    바꾸지만 **비용 기록은 안 막아서**, 실제 API 호출이 없었는데도 $0.039 짜리 행이 쌓였다.

    그 결과 운영자가 "왜 이렇게 돈을 썼냐"고 물었을 때 원장이 **거짓말을 했다**:
        원장 528행 중 468행($18.34)이 테스트가 쓴 것이고, 진짜 생성은 60행($2.79)뿐이었다.
    비용 원장의 존재 이유는 "얼마 썼는지 답하는 것"인데, 오염된 원장은 그 반대를 한다.

    ★ autouse 다 — 개별 테스트가 기억해서 막는 방식은 언젠가 빠뜨린다. 실제로 몇몇
      테스트만 monkeypatch 하고 있었고, 새로 쓴 픽스처가 그걸 빠뜨려 사고가 났다.
    ★ 막는 것은 **DB 쓰기**이지 `cost.record` 자체가 아니다. record 를 통째로 갈아 끼우면
      그 함수의 동작(실패를 삼켜 렌더를 막지 않는다)을 검사하는 테스트가 가짜를 보게 된다 —
      실제로 그렇게 만들었다가 test_ledger_failure_does_not_block_render 가 깨졌다.
      가장 바깥이 아니라 **가장 안쪽**을 막는 것이 관측을 덜 망가뜨린다.
    ★ 이 함수 자체를 검사하는 테스트는 `db.real_insert_generation_attempt` 로 원본을 되찾을
      수 있다(그 테스트는 자기 클라이언트를 스텁하므로 네트워크로 나가지 않는다).
    """
    from engine import db

    def _blocked(_row):
        raise AssertionError(
            "테스트가 운영 비용 원장에 쓰려고 했다 — conftest 가 막았다. "
            "이 함수 자체를 검사하려면 db.real_insert_generation_attempt 를 쓰라.")

    monkeypatch.setattr(db, "real_insert_generation_attempt",
                        db.insert_generation_attempt, raising=False)
    monkeypatch.setattr(db, "insert_generation_attempt", _blocked)


@pytest.fixture(autouse=True)
def _no_live_judge_calls_from_tests(monkeypatch):
    """★ 테스트가 **판정 모델(Jev)을 실제로 부르지 못하게** 막는다 (2026-09-22).

    무슨 일이 있었나: 운영자가 Jev 를 켜라고 해서 `.env` 에 `JEV_ENABLED=1` 을 넣었다.
    `config` 가 `.env` 를 읽으므로 **그 순간 테스트 스위트가 라이브 API 를 때리기
    시작했다** — 실제로 `tests/test_jev_only_relaxes.py` 두 건이 깨지면서 드러났고,
    비용 원장에 쓰려다 위 가드에 걸린 경고가 로그에 남았다.

    위 원장 사고와 **같은 종류**다: 운영 설정이 테스트 결과를 바꾸면 테스트는
    "코드가 맞나"가 아니라 "오늘 .env 가 어떤가"를 재게 된다. 게다가 느리고 돈이 든다.

    ★ 막는 것은 `decide.enabled()` 다 — config 값이 아니라 **문**이다. 그래야
      `config.JEV_ENABLED` 를 읽는 테스트(기본값 검사)는 그대로 살아 있고,
      켜진 상태를 보고 싶은 테스트는 `decide.enabled` 를 스스로 덮어써서 볼 수 있다.
    """
    from engine import decide

    monkeypatch.setattr(decide, "enabled", lambda: False)
