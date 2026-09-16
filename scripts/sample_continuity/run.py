"""컷 유기성 샘플 1편 제작 — 일회성 검증 스크립트 (지시서 §4).

목적: 화성 논문 1편으로 "컷 전환에 이유가 있는" 버전을 만들어 기존 버전과 눈으로 비교한다.

★ 프로덕션 무변경. engine/ 은 읽기·호출만 하고 수정하지 않는다. DB 쓰기 없음.
★ 레퍼런스 이미지 입력이 지원되지 않아(근거: PATHS.md) 지시서 §6 의 **프롬프트 접두사 고정**
  방식으로 진행한다. STYLE_PREFIX 를 header.global_style 에 넣으면 기존
  engine/providers/image.py:_build_image_prompt 가 "접두사, 장면묘사, 9:16, burn-in negative"
  형태로 조립해 준다 — 새 API 코드를 짤 필요가 없다.

실행:
    python -m scripts.sample_continuity.run --step refs    # 레퍼런스 2장(눈으로 확인용)
    python -m scripts.sample_continuity.run --step cuts    # 컷 스틸 8장
    python -m scripts.sample_continuity.run --step video   # Veo 클립 + TTS + 자막 + 조립
    python -m scripts.sample_continuity.run --step all
    python -m scripts.sample_continuity.run --step before --before-url <기존 mp4 URL>

각 단계는 산출 파일이 이미 있으면 건너뛴다(재실행 시 재과금 방지).
호출·비용은 log.json 에 기록한다(기존 generation_attempts 원장 패턴을 로컬 파일로 옮긴 것).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from engine import config  # noqa: E402
from engine.providers import image as image_provider  # noqa: E402

REF_DIR = HERE / "ref"
CUT_DIR = HERE / "cuts"
BEFORE_DIR = HERE / "before"
AFTER_DIR = HERE / "after"
WORK_DIR = HERE / "work"
LOG_PATH = HERE / "log.json"
DIRECTIVE_PATH = HERE / "directive_v2.json"

# ── 지시서 §6: 레퍼런스 미지원 → 접두사 고정 ──
# episode_world.style_note + persistent_object 를 영문 한 덩어리로 굳힌 것. 매 컷 프롬프트 앞에 붙는다.
STYLE_PREFIX = (
    "Dark space background, deep red Martian tones, single strong side light, "
    "realistic illustration, cinematic, 9:16 vertical. "
    "Recurring object: a dark reddish-brown angular meteorite fragment, fist-sized."
)

REF_PROMPTS = {
    "style_ref": (
        "Dark space background, deep red Martian tones, single strong side light, "
        "realistic illustration, cinematic, 9:16 vertical composition. "
        "A reference frame establishing color palette and lighting direction."
    ),
    "object_ref": (
        "A single dark reddish-brown Martian meteorite fragment, angular broken surface, "
        "fist-sized, isolated on plain dark background, single side light, "
        "realistic illustration, 9:16 vertical."
    ),
}

# transition == "return" 인 컷은 원래 앞 컷 이미지를 구도 참조로 넘겨야 한다(§3-3). 접두사 방식에는
# 이미지 입력이 없으므로 구도를 **문장으로** 고정한다. 레퍼런스 방식보다 약한 대체다.
RETURN_COMPOSITION_NOTE = (
    "Reproduce the exact same camera angle, framing, and subject placement as the earlier shot "
    "described here: "
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(entry: dict[str, Any]) -> None:
    """로컬 원장에 한 줄 추가. DB 에는 쓰지 않는다."""
    rows: list[dict[str, Any]] = []
    if LOG_PATH.exists():
        rows = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    rows.append({"ts": _now(), **entry})
    LOG_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_spec() -> dict[str, Any]:
    return json.loads(DIRECTIVE_PATH.read_text(encoding="utf-8"))


def _scene_prompt(cut: dict[str, Any], spec_cuts: list[dict[str, Any]]) -> str:
    """컷 → 이미지 프롬프트 본문(장면 묘사만). 세계 묘사는 STYLE_PREFIX 가 담당한다."""
    body = str(cut.get("change_en") or cut.get("change") or "").strip()
    if cut.get("transition") == "return" and cut.get("transition_from"):
        src = next((c for c in spec_cuts if c["cut_no"] == cut["transition_from"]), None)
        if src:
            body = f"{RETURN_COMPOSITION_NOTE}{src.get('change_en') or ''} Now: {body}"
    return body


def _gen_one(name: str, prompt: str, out_path: Path, cut_no: int = 0) -> float:
    """이미지 1장 생성. 이미 있으면 건너뛴다. 반환: 비용."""
    if out_path.exists():
        print(f"  건너뜀(이미 있음): {out_path.name}")
        return 0.0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cut = {"cut_no": cut_no, "visual_prompt": prompt}
    header = {"global_style": ""}   # 접두사는 prompt 안에 이미 들어 있다
    _, cost = image_provider.generate_image(cut, header, str(out_path))
    print(f"  생성: {out_path.name}  (${cost:.4f})")
    _log({"step": "image", "target": name, "provider": config.IMAGE_PROVIDER,
          "model": config.IMAGE_MODEL, "cost_usd": cost, "prompt": prompt})
    return cost


# ── 단계 1: 레퍼런스 2장 ──
def step_refs() -> float:
    """§3-2. 접두사 방식에서는 입력으로 쓰이지 않지만, 세계관 톤을 눈으로 먼저 확인하는 게이트로 남긴다.

    여기서 색·조명이 의도와 다르면 STYLE_PREFIX 를 고치고 다시 돌린다. 컷 8장을 뽑기 전에 잡는다.
    """
    print("[refs] 레퍼런스 2장 생성 (톤 확인용 — 접두사 방식이라 입력으로는 안 쓰임)")
    total = 0.0
    for name, prompt in REF_PROMPTS.items():
        total += _gen_one(name, prompt, REF_DIR / f"{name}.png")
    print(f"[refs] 완료. 비용 ${total:.4f}")
    print(f"[refs] ★ {REF_DIR} 의 2장을 눈으로 확인한 뒤 --step cuts 로 넘어가라.")
    return total


# ── 단계 2: 컷 스틸 8장 ──
def step_cuts() -> float:
    print("[cuts] 컷 스틸 8장 생성 (접두사 고정 + 장면 묘사)")
    spec = _load_spec()
    cuts = spec["cuts"]
    total = 0.0
    for cut in cuts:
        n = int(cut["cut_no"])
        prompt = f"{STYLE_PREFIX} Scene: {_scene_prompt(cut, cuts)}"
        total += _gen_one(f"cut_{n:02d}", prompt, CUT_DIR / f"cut_{n:02d}.png", cut_no=n)
    print(f"[cuts] 완료. 비용 ${total:.4f}")
    return total


# ── 단계 3: 클립 + 조립 ──
def _install_pregenerated_shim() -> None:
    """--step cuts 로 이미 만든 스틸을 렌더가 재생성하지 않도록 provider 를 감싼다.

    ★ engine 파일은 건드리지 않는다. 런타임에 모듈 속성만 교체하는 샘플 전용 shim 이다.
      이게 없으면 render 가 같은 프롬프트로 8장을 다시 만들어 이미지 비용이 두 배가 되고,
      무엇보다 --step cuts 에서 눈으로 확인한 그림과 다른 그림이 영상에 들어간다.
    """
    real = image_provider.generate_image

    def shim(cut: dict[str, Any], header: dict[str, Any], out_path: str):
        n = int(cut.get("cut_no") or 0)
        src = CUT_DIR / f"cut_{n:02d}.png"
        if src.exists():
            shutil.copyfile(src, out_path)
            print(f"  스틸 재사용: cut_{n:02d}.png (생성 호출 0)")
            return out_path, 0.0
        return real(cut, header, out_path)

    image_provider.generate_image = shim


def build_engine_directive() -> dict[str, Any]:
    """샘플 스펙 → engine 이 아는 지시서 dict.

    ★ 나레이션·스틸/영상 구분은 기존 버전 그대로다(단일 변수 원칙). 컷 화면 시간은 엔진이
      TTS 실측 길이로 정하는데, 나레이션이 동일하므로 기존 버전과 같은 길이가 나온다.
    """
    spec = _load_spec()
    cuts = []
    for c in spec["cuts"]:
        cuts.append({
            "cut_no": int(c["cut_no"]),
            "scene_kind": "comic_panel",          # 기존 화성 버전과 동일
            "visual_type": "image",
            "estimated_sec": int(c["duration_sec"]),
            "visual_prompt": _scene_prompt(c, spec["cuts"]),
            "motion_source": c["motion_source"],
            "motion_prompt": c.get("change_en") or "",
            "effects": ["ken_burns_zoom_in"] if c["motion_source"] == "still" else [],
            "narration_ko": c["narration_ko"],
            "source_facts": ["what_found[0]"],    # 로컬 렌더는 검증하지 않지만 스키마상 채운다
        })
    return {
        "version_type": "comic",
        "header": {
            "version_type": "comic",
            "aspect_ratio": "9:16",
            "global_style": STYLE_PREFIX,
            "hook_ko": spec["cuts"][0]["narration_ko"],
            "total_estimated_sec": sum(c["duration_sec"] for c in spec["cuts"]),
        },
        "cuts": cuts,
    }


def step_video() -> str:
    out = AFTER_DIR / "sample.mp4"
    if out.exists():
        print(f"[video] 건너뜀(이미 있음): {out}")
        return str(out)
    missing = [n for n in range(1, 9) if not (CUT_DIR / f"cut_{n:02d}.png").exists()]
    if missing:
        raise SystemExit(f"[video] 중단 — 컷 스틸이 없다: {missing}. 먼저 --step cuts 를 돌려라.")

    print("[video] Veo 클립 + TTS + 자막 + 조립 (기존 엔진 함수 그대로 호출)")
    _install_pregenerated_shim()
    from engine import render as engine_render   # shim 설치 후 import

    AFTER_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    directive = build_engine_directive()
    engine_render.render_directive_local(directive, str(out), work_dir=str(WORK_DIR), lang="ko")
    _log({"step": "video", "target": "after/sample.mp4",
          "video_provider": config.VIDEO_PROVIDER, "tts_provider": config.TTS_PROVIDER,
          "video_cuts": [c["cut_no"] for c in directive["cuts"]
                         if c["motion_source"] == "video"]})
    print(f"[video] 완료: {out}")
    return str(out)


# ── 비교 대상 확보 ──
def step_before(url: str | None) -> None:
    """기존 버전 mp4 를 before/ 에 내려받는다(§2, 비교용).

    ★ Supabase 조회로 논문을 찾아내는 대신 URL 을 직접 받는다 — 스키마를 추측하지 않기 위해서다.
      대시보드 ⑥ 화면에서 기존 화성 편의 mp4 링크를 복사해 --before-url 로 넘겨라.
    """
    dest = BEFORE_DIR / "before.mp4"
    if dest.exists():
        print(f"[before] 건너뜀(이미 있음): {dest}")
        return
    if not url:
        print("[before] URL 미지정 — 건너뜀. 비교하려면 --before-url 로 기존 mp4 링크를 넘겨라.")
        return
    import httpx
    BEFORE_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    print(f"[before] 저장: {dest} ({dest.stat().st_size} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description="컷 유기성 샘플 1편 제작(일회성)")
    ap.add_argument("--step", required=True,
                    choices=["refs", "cuts", "video", "before", "all"])
    ap.add_argument("--before-url", default=os.environ.get("BEFORE_URL") or None)
    args = ap.parse_args()

    print(f"provider: image={config.IMAGE_PROVIDER} video={config.VIDEO_PROVIDER} "
          f"tts={config.TTS_PROVIDER}")
    if config.IMAGE_PROVIDER == "placeholder" and args.step in ("refs", "cuts", "all"):
        print("⚠ IMAGE_PROVIDER=placeholder — 단색 PNG 만 나온다. 판정에 쓸 수 없다.")

    if args.step in ("refs", "all"):
        step_refs()
    if args.step in ("cuts", "all"):
        step_cuts()
    if args.step in ("before", "all"):
        step_before(args.before_url)
    if args.step in ("video", "all"):
        step_video()


if __name__ == "__main__":
    main()
