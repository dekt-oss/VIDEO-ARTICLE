"""종횡비 파라미터 실측 (docs/수정명세서_웹툰버전_v1.md §4 DoD ①).

1차 샘플에서 생성 이미지 8장이 전부 1024×1024 로 나왔다. 프롬프트의 "vertical 9:16" 은 무시되고,
종횡비는 **요청 파라미터**로 보내야 한다. 그런데 그 필드 경로가 공식 문서에서 두 가지로 나온다:

    generationConfig.imageConfig.aspectRatio          (SDK ImageConfig 의 REST 직렬화)
    generationConfig.responseFormat.image.aspectRatio (현행 image-generation 문서의 curl 예시)

추측해서 박지 않는다. 이 스크립트가 **두 형태를 실제로 호출해 보고 산출물 크기를 잰다.**
통과한 형태를 `IMAGE_ASPECT_CONFIG_SHAPE` 기본값으로 확정하면 된다.

실행(GEMINI_API_KEY 필요 — 개발 샌드박스에는 없다. Actions 러너에서 돌린다):

    python -m scripts.verify_image_aspect

이미지 1~3장 생성 비용이 든다(장당 약 $0.04). 그래서 형태를 순서대로 시도하고 **먼저 통과하면
거기서 멈춘다.**
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import config  # noqa: E402
from engine.providers import image as image_provider  # noqa: E402

# 화풍이 아니라 종횡비만 보는 것이므로 프롬프트는 단순할수록 좋다.
PROBE_CUT = {"cut_no": 1, "visual_prompt": "a single red sphere on a dark background"}
PROBE_HEADER = {"version_type": "webtoon", "global_style": "korean webtoon illustration"}


def _try_shape(shape: str | None) -> tuple[bool, str]:
    """한 가지 필드 형태로 1장 생성하고 크기를 잰다. 반환: (9:16 인가, 사람이 읽을 결과)."""
    prev_shape, prev_on = config.IMAGE_ASPECT_CONFIG_SHAPE, config.IMAGE_ASPECT_RATIO_PARAM
    config.IMAGE_ASPECT_RATIO_PARAM = shape is not None
    if shape is not None:
        config.IMAGE_ASPECT_CONFIG_SHAPE = shape
    label = shape or "(파라미터 없음 — 대조군)"
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            out = fh.name
        image_provider.generate_image(PROBE_CUT, PROBE_HEADER, out)
    except Exception as exc:  # noqa: BLE001 — 400(미지의 필드)도 결과의 일부다
        return False, f"{label}: 호출 실패 — {type(exc).__name__}: {str(exc)[:200]}"
    finally:
        config.IMAGE_ASPECT_CONFIG_SHAPE, config.IMAGE_ASPECT_RATIO_PARAM = prev_shape, prev_on

    size = image_provider.measure_aspect(out)
    if size is None:
        return False, f"{label}: 산출물 크기를 못 읽음 ({out})"
    ok = image_provider.is_portrait_916(*size)
    return ok, f"{label}: {size[0]}×{size[1]} → {'9:16 확보' if ok else '9:16 아님'} ({out})"


def main() -> int:
    if config.IMAGE_PROVIDER != "gemini":
        print(f"IMAGE_PROVIDER={config.IMAGE_PROVIDER} — placeholder 로는 아무것도 증명할 수 없다.")
        print("IMAGE_PROVIDER=gemini 와 GEMINI_API_KEY 를 설정하고 다시 실행하라.")
        return 2

    print(f"모델: {config.IMAGE_MODEL} · 목표 종횡비: {config.ASPECT_RATIO}")
    winner: str | None = None
    for shape in config.IMAGE_ASPECT_CONFIG_SHAPES:
        ok, msg = _try_shape(shape)
        print(f"  {msg}")
        if ok:
            winner = shape
            break

    if winner:
        print(f"\n✅ 통과한 형태: {winner}")
        print(f"   engine/config.py 의 IMAGE_ASPECT_CONFIG_SHAPE 기본값을 '{winner}' 로 확정하라"
              f" (현재 기본값: '{config.IMAGE_ASPECT_CONFIG_SHAPE}').")
        return 0

    print("\n❌ 두 형태 모두 9:16 을 못 만들었다.")
    print("   IMAGE_ASPECT_RATIO_PARAM=false 로 되돌리고, 위 실패 메시지를 근거로")
    print("   docs/deviation-webtoon-b1-removal.md 의 종횡비 항목을 갱신하라.")
    print("   ★ 9:16 이 확보되기 전에는 webtoon 을 운영에 쓰지 않는다(지시서 v2 절대규칙 4).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
