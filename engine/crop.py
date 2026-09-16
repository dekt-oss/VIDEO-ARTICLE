"""크롭 파생 · 톤 그레이딩 (docs/수정명세서_웹툰버전_v1.md §3).

카메라 이동(zoom_in / zoom_out / return)을 **이미지 생성이 아니라 크롭**으로 만든다.
이미지 모델은 "같은 대상을 더 가까이"를 지키지 못해 컷마다 다른 물체·다른 스케일을 그린다 —
1차 샘플에서 운석이 흑요석 → 크리스탈 바위 → 거대 암석으로 변한 것이 그 증거다. 크롭은
같은 픽셀에서 잘라내므로 연속성이 100% 보장되고, 생성 호출이 0이라 비용도 0이다.

★ 모듈 구조 규칙: 순수 함수(`crop_box`·`grade_params`)는 PIL 을 모른다. PIL 은 `derive_image`
  안에서만 **지연 import** 한다. Pillow 가 없는 환경(수집·채점 잡)에서 이 모듈을 import 해도
  깨지지 않아야 하고, 크롭 수학은 그런 환경에서도 테스트가 돌아야 하기 때문이다.
★ 지시서는 픽셀이 아니라 **비율**(cx·cy·scale)만 싣는다. 원본 해상도가 바뀌어도(1024×1024
  레거시 자산 → 9:16 신규 자산) 저장된 지시서가 낡지 않는다.
"""

from __future__ import annotations

from typing import Any

from . import config


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def target_aspect() -> float:
    """출력 종횡비(가로/세로). 렌더 해상도에서 유도 — 상수를 두 벌로 만들지 않는다."""
    return config.RENDER_WIDTH / config.RENDER_HEIGHT


def crop_box(width: int, height: int, cx: float, cy: float,
             scale: float) -> tuple[int, int, int, int]:
    """원본 크기와 크롭 비율 → 픽셀 박스 (left, top, right, bottom).

    2단계로 계산한다.

    ⓐ **원본에서 가장 큰 중앙 9:16 부분 사각형을 먼저 잡는다.** 레거시 자산은 1024×1024 라
      바로 1080×1920 으로 리사이즈하면 가로로 찌그러진다. 원본이 이미 9:16 이면 이 단계는
      무연산이다(종횡비 파라미터가 붙은 뒤의 정상 경로).

    ⓑ 그 사각형 안에서 `1/scale` 크기의 박스를 `(cx, cy)` 중심에 놓는다. 박스는 9:16 비율을
      유지하므로 리사이즈에서 다시 찌그러지지 않는다. 박스가 경계를 넘으면 **밀어 넣는다 —
      줄이지 않는다.** 줄이면 지시서가 요청한 배율이 조용히 바뀌어 "2.2배 확대"가 1.7배가 된다.
    """
    width = max(int(width), 1)
    height = max(int(height), 1)
    aspect = target_aspect()

    # ⓐ 중앙 9:16 부분 사각형
    if width / height > aspect:          # 원본이 더 넓다 → 좌우를 깎는다
        rw = max(int(round(height * aspect)), 1)
        rh = height
    else:                                 # 원본이 더 높다(또는 같다) → 위아래를 깎는다
        rw = width
        rh = max(int(round(width / aspect)), 1)
    rx = (width - rw) // 2
    ry = (height - rh) // 2

    # ⓑ 그 안에서 1/scale 박스
    s = _clamp(float(scale), config.CROP_MIN_SCALE, config.CROP_MAX_SCALE)
    bw = max(int(round(rw / s)), config.CROP_MIN_BOX_PX)
    bh = max(int(round(rh / s)), config.CROP_MIN_BOX_PX)
    bw, bh = min(bw, rw), min(bh, rh)

    cxr = _clamp(float(cx), 0.0, 1.0)
    cyr = _clamp(float(cy), 0.0, 1.0)
    left = int(round(rx + cxr * rw - bw / 2))
    top = int(round(ry + cyr * rh - bh / 2))
    # 경계 밖이면 밀어 넣는다(크기 보존).
    left = int(_clamp(left, rx, rx + rw - bw))
    top = int(_clamp(top, ry, ry + rh - bh))
    return left, top, left + bw, top + bh


def grade_params(name: str | None) -> tuple[tuple[int, int, int], float] | None:
    """톤 그레이딩 이름 → (블렌드 RGB, 알파). 미지정·미지의 이름이면 None(무연산)."""
    key = str(name or "").strip().lower()
    if not key or key == config.DEFAULT_TONE_GRADE:
        return None
    return config.TONE_GRADES.get(key)


def has_work(crop: dict[str, Any] | None, tone_grade: str | None) -> bool:
    """실제로 픽셀을 건드릴 일이 있는가. 없으면 호출측이 그냥 파일을 복사한다."""
    if grade_params(tone_grade) is not None:
        return True
    if not isinstance(crop, dict):
        return False
    try:
        return float(crop.get("scale") or config.CROP_MIN_SCALE) > config.CROP_MIN_SCALE
    except (TypeError, ValueError):
        return False


def derive_image(base_path: str, out_path: str, crop: dict[str, Any] | None,
                 tone_grade: str | None) -> None:
    """기준 스틸 → 크롭·리사이즈·그레이딩된 컷 스틸. 생성 API 호출 0.

    ★ PIL 은 여기서만 import 한다(모듈 최상단 규칙 참조).
    ★ 예외를 삼키지 않는다 — 호출측(`render._reuse_base_image`)이 잡아서 '평범한 복사'로
      강등한다. 크롭이 깨졌다고 **유료 생성으로 떨어지면 안 된다**는 것이 이 기능의 안전 속성이다.
    """
    from PIL import Image  # noqa: PLC0415 — 지연 import (Pillow 없는 환경 보호)

    with Image.open(base_path) as src:
        img = src.convert("RGB")
        if isinstance(crop, dict):
            box = crop_box(
                img.width, img.height,
                float(crop.get("cx", config.CROP_DEFAULT_CENTER)),
                float(crop.get("cy", config.CROP_DEFAULT_CENTER)),
                float(crop.get("scale", config.CROP_MIN_SCALE)),
            )
            img = img.crop(box)
        if (img.width, img.height) != (config.RENDER_WIDTH, config.RENDER_HEIGHT):
            img = img.resize((config.RENDER_WIDTH, config.RENDER_HEIGHT), Image.LANCZOS)
        grade = grade_params(tone_grade)
        if grade is not None:
            rgb, alpha = grade
            img = Image.blend(img, Image.new("RGB", img.size, rgb), alpha)
        img.save(out_path, "PNG")


def mean_abs_delta(path_a: str, path_b: str) -> float:
    """두 이미지의 평균 절대 픽셀 차(0~255). 같은 그림이면 0.0.

    ★ 왜 필요한가(2026-08-29 실측): 재사용 컷이 크롭도 톤도 없으면 렌더가 기준 스틸을
      `shutil.copyfile` 했다. 그 결과 컷5와 컷6이 **바이트까지 동일한 파일**로 나갔고,
      시청자에게는 영상이 멈춘 것으로 보였다. 지시서는 "상태가 바뀐다"고 선언했지만
      화면은 그대로였다 — 이 저장소의 자세대로, 그 선언이 참인지는 **코드가 판정한다.**

    ★ 순수 비교다. 크기가 다르면 작은 쪽에 맞춰 리사이즈해서 본다(크롭 파생 비교용).
    ★ 읽기에 실패하면 -1.0 을 돌려 "판정 못 함"을 알린다 — 판정 실패가 차단으로 이어지면
      렌더가 이미지 하나 못 읽었다고 통째로 멈춘다.
    """
    from PIL import Image, ImageChops, ImageStat  # noqa: PLC0415 — 지연 import

    try:
        with Image.open(path_a) as ia, Image.open(path_b) as ib:
            a = ia.convert("RGB")
            b = ib.convert("RGB")
            if a.size != b.size:
                size = (min(a.width, b.width), min(a.height, b.height))
                a = a.resize(size, Image.LANCZOS)
                b = b.resize(size, Image.LANCZOS)
            stat = ImageStat.Stat(ImageChops.difference(a, b))
    except Exception:  # noqa: BLE001 — 판정 실패는 차단이 아니다
        return -1.0
    return round(sum(stat.mean) / len(stat.mean), 4)
