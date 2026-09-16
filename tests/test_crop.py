"""크롭 수학 (engine/crop.py) — 순수. PIL 없이 돈다.

여기서 잡으려는 것은 "그럴듯한데 1px 씩 틀린 크롭"이다. 반올림이 어긋나면 컷 2→3 확대에서
피사체가 미묘하게 밀려 보이고, 그건 육안 판정 전까지 드러나지 않는다. 그래서 정확한 정수로 단언한다.
"""

from engine import config, crop


def test_scale_1_returns_full_916_rect_for_916_source():
    # 이미 9:16 인 원본에 배율 1 → 원본 전체. 잘라낼 것이 없다.
    assert crop.crop_box(1080, 1920, 0.5, 0.5, 1.0) == (0, 0, 1080, 1920)


def test_scale_2_is_centered_quarter_area():
    # 2배 확대 = 가로·세로 각각 절반. 1080/2=540, 1920/2=960, 중앙 정렬.
    assert crop.crop_box(1080, 1920, 0.5, 0.5, 2.0) == (270, 480, 810, 1440)


def test_off_center_box_slides_in_bounds_keeping_size():
    # 오른쪽 끝을 중심으로 잡으면 박스가 이미지 밖으로 나간다 → 밀어 넣되 크기는 보존해야 한다.
    # (줄이면 지시서가 요청한 배율이 조용히 바뀐다.)
    left, top, right, bottom = crop.crop_box(1080, 1920, 0.98, 0.02, 2.0)
    assert (right - left, bottom - top) == (540, 960)
    assert left >= 0 and top >= 0
    assert right <= 1080 and bottom <= 1920
    assert right == 1080          # 오른쪽 경계에 붙는다
    assert top == 0               # 위쪽 경계에 붙는다


def test_square_source_yields_916_box_not_squashed():
    # 레거시 1024×1024 자산: 바로 1080×1920 으로 리사이즈하면 가로로 찌그러진다.
    # 정사각형은 9:16 보다 **넓으므로** 좌우를 깎아야 한다(위아래가 아니다).
    left, top, right, bottom = crop.crop_box(1024, 1024, 0.5, 0.5, 1.0)
    w, h = right - left, bottom - top
    assert h == 1024                                   # 세로는 그대로
    assert w == 576                                    # 1024 × 9/16
    assert abs(w / h - crop.target_aspect()) < 0.01    # 반환 박스가 9:16
    assert left > 0 and right < 1024                   # 좌우를 깎았다


def test_scale_is_clamped_to_config_max():
    # 정규화가 1차 방어선이지만, 저장된 옛 지시서가 상한 밖 값을 들고 올 수 있다.
    over = crop.crop_box(1080, 1920, 0.5, 0.5, 99.0)
    at_max = crop.crop_box(1080, 1920, 0.5, 0.5, config.CROP_MAX_SCALE)
    assert over == at_max


def test_center_ratio_is_clamped():
    assert crop.crop_box(1080, 1920, -3.0, 5.0, 2.0) == crop.crop_box(1080, 1920, 0.0, 1.0, 2.0)


def test_grade_params_unknown_name_is_none():
    assert crop.grade_params("magenta") is None
    assert crop.grade_params("") is None
    assert crop.grade_params(None) is None
    assert crop.grade_params(config.DEFAULT_TONE_GRADE) is None


def test_grade_params_known_name_returns_rgb_and_alpha():
    rgb, alpha = crop.grade_params("warm")
    assert len(rgb) == 3
    assert 0.0 < alpha < 1.0


def test_has_work_is_false_for_neutral_cut():
    # 크롭도 그레이딩도 없으면 렌더는 그냥 파일을 복사한다(오늘 동작 유지).
    assert crop.has_work(None, None) is False
    assert crop.has_work({"cx": 0.5, "cy": 0.5, "scale": 1.0}, "none") is False


def test_has_work_is_true_when_zoomed_or_graded():
    assert crop.has_work({"cx": 0.5, "cy": 0.5, "scale": 2.0}, "none") is True
    assert crop.has_work(None, "red") is True
