"""engine.providers.image 순수 로직 테스트 (네트워크 없음).

_build_image_prompt 가 global_style 앵커 + visual_prompt + 9:16 규격을 합치는지만 검증한다.
실제 Gemini 호출은 라이브에서 확인.
"""

from engine.providers.image import _build_image_prompt


def test_prompt_combines_style_and_visual():
    p = _build_image_prompt(
        {"visual_prompt": "a robot fixing itself"},
        {"global_style": "flat webtoon style, bold outlines"},
    )
    assert "flat webtoon style" in p          # 화풍 앵커 먼저
    assert "a robot fixing itself" in p       # 컷 비주얼
    # ⑤ Burn-in 금지(§5.3) 강화: 텍스트뿐 아니라 수치·라벨도 차단(공유 에셋 언어 독립성).
    assert "9:16" in p
    assert "no text" in p and "no numbers" in p and "no labels" in p


def test_prompt_survives_empty_fields():
    p = _build_image_prompt({}, {})
    assert "9:16" in p and p.strip()          # 빈 입력에도 유효한 프롬프트

    p2 = _build_image_prompt({"visual_prompt": "x"}, None)
    assert "x" in p2 and "9:16" in p2
