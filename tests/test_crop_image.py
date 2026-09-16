"""크롭 파생의 실제 픽셀 결과 (engine/crop.derive_image).

★ Pillow 가 없는 환경(수집·채점 잡)에서는 파일 전체가 skip 된다 — 저장소 기본 pytest 가
  "순수 로직 테스트"라는 규약을 지키기 위해서다. 렌더 러너에는 Pillow 가 있어 실제로 돈다.
"""

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from engine import config, crop  # noqa: E402


def _make_base(path, size=(1080, 1920)):
    """왼쪽 위는 빨강, 오른쪽 아래는 파랑인 원본. 크롭 위치를 색으로 확인할 수 있다."""
    img = Image.new("RGB", size, (255, 0, 0))
    img.paste((0, 0, 255), (size[0] // 2, size[1] // 2, size[0], size[1]))
    img.save(path, "PNG")
    return str(path)


def test_derive_outputs_render_resolution(tmp_path):
    base = _make_base(tmp_path / "base.png")
    out = str(tmp_path / "out.png")
    crop.derive_image(base, out, {"cx": 0.5, "cy": 0.42, "scale": 2.2}, "none")
    with Image.open(out) as img:
        assert img.size == (config.RENDER_WIDTH, config.RENDER_HEIGHT)


def test_derive_from_square_source_is_not_squashed(tmp_path):
    # 레거시 1024×1024 자산도 세로 규격으로 나와야 하고, 종횡비 왜곡이 없어야 한다.
    base = _make_base(tmp_path / "sq.png", size=(1024, 1024))
    out = str(tmp_path / "out.png")
    crop.derive_image(base, out, {"cx": 0.5, "cy": 0.5, "scale": 1.0}, "none")
    with Image.open(out) as img:
        assert img.size == (config.RENDER_WIDTH, config.RENDER_HEIGHT)


def test_crop_actually_selects_the_requested_region(tmp_path):
    """왼쪽 위를 확대하면 화면이 빨강만, 오른쪽 아래를 확대하면 파랑만이어야 한다.

    이게 "크롭이 실제로 일어났는가"를 색으로 증명한다 — 크기만 보면 단순 리사이즈와 구별되지 않는다.
    """
    base = _make_base(tmp_path / "base.png")
    top_left = str(tmp_path / "tl.png")
    bottom_right = str(tmp_path / "br.png")
    crop.derive_image(base, top_left, {"cx": 0.0, "cy": 0.0, "scale": 2.5}, "none")
    crop.derive_image(base, bottom_right, {"cx": 1.0, "cy": 1.0, "scale": 2.5}, "none")

    with Image.open(top_left) as img:
        assert img.getpixel((img.width // 2, img.height // 2)) == (255, 0, 0)
    with Image.open(bottom_right) as img:
        assert img.getpixel((img.width // 2, img.height // 2)) == (0, 0, 255)


def test_tone_grade_shifts_color_toward_the_grade(tmp_path):
    base = _make_base(tmp_path / "base.png")
    plain = str(tmp_path / "plain.png")
    graded = str(tmp_path / "graded.png")
    crop.derive_image(base, plain, None, "none")
    crop.derive_image(base, graded, None, "cool")

    with Image.open(plain) as p, Image.open(graded) as g:
        px, gx = p.getpixel((10, 10)), g.getpixel((10, 10))
    assert px != gx
    assert gx[2] > px[2]          # cool 은 파랑을 올린다
    assert gx[0] < px[0]          # 그리고 빨강을 내린다


def test_unknown_tone_grade_is_a_noop(tmp_path):
    base = _make_base(tmp_path / "base.png")
    plain = str(tmp_path / "plain.png")
    weird = str(tmp_path / "weird.png")
    crop.derive_image(base, plain, None, "none")
    crop.derive_image(base, weird, None, "magenta")
    with Image.open(plain) as p, Image.open(weird) as w:
        assert p.getpixel((10, 10)) == w.getpixel((10, 10))
