"""클립을 사기 전에 그림을 본다 (2026-09-27, 운영자 승인 "그림 먼저 검사하고 클립 사기").

무엇을 푸는가
------------
실사형 한 컷은 그림 한 장($0.04~0.13) 위에 클립($0.2~0.4)을 산다. 그림에 **글자가 박혔거나**
(flash 는 도해에 깨진 라벨을 그린다 — 2026-08-29 실측) **주인공이 없으면** 클립은 사도 못 쓴다.
지금까지는 그것을 편을 다 만든 뒤 사람이 보고 알았고, 다시 사는 비용은 클립 값이었다.
그림만 한 번 다시 그리는 편이 싸다.

무엇을 묻는가 — 좁게 고정한다(clip_candidates.review_tie 와 같은 규율)
  ① 그림 안에 글자·숫자·라벨이 그려져 있나 — 화풍 계약이 금지하고 카드가 대신 쓴다.
  ② 이 컷의 주인공(visual_prompt 첫 문장)이 한눈에 보이나.
  ③ 그림이 여러 칸(콜라주·분할)으로 쪼개졌나 — 2026-09-27 삼성전자 렌더 실측.
"어느 쪽이 예쁘냐"는 묻지 않는다 — 예쁨으로 고르면 우리가 아는 실패를 놓친다.

★ 판정 불가(키 없음·호출 실패·응답 모양 이상)는 **통과**다. 못 쟀다고 벌하지 않는다.
★ Jev 가 아니라 멀티모달 flash 다 — Jev 는 글만 본다.
"""

from __future__ import annotations

import re
from typing import Any

from . import config, continuity_qa

#: 재생성 뒤에도 실패한 컷이 남기는 저하 코드(sequence_render.degraded_summary 그릇).
DEGRADED_STILL_FAILED = "still_check_failed"

_SYSTEM = (
    "You check one generated still image before it is animated into a video clip. "
    "Answer only the three questions asked. Reply with JSON only."
)

_USER = (
    "INTENDED SUBJECT: {subject}\n\n"
    "1. text_in_image — Would a viewer watching this on a PHONE notice prominent lettering, "
    "numbers, a logo-like glyph or a label drawn on an object (a big sign, a caption, a chart "
    "label, large digits on a hull)? A page, card or screen that fills a large part of the frame "
    "with lines of lettering counts as true — fake writing is obvious on a phone. Answer false only "
    "for tiny print on small papers far away, rolled drawings and fine texture. IGNORE our own "
    "overlays: centered subtitle lines (white text with a dark outline) and small colored caption "
    "boxes or tags laid over the picture — judge only lettering that is part of the scene itself.\n"
    "2. subject_present — Is the main object of the INTENDED SUBJECT recognizably in the picture? "
    "Judge only whether that object is there and is the focus. Size, count, exact pose, "
    "lighting and small details do NOT matter.\n"
    "3. split_panels — Is the picture divided into two or more separate panels or tiles showing "
    "different scenes (a collage, a split-screen, stacked strips)? A single scene that merely "
    "contains a window, a screen or a doorway is NOT split.\n\n"
    'Reply exactly: {{"text_in_image": true|false, "subject_present": true|false, '
    '"split_panels": true|false, "reason": "<one short sentence>"}}'
)

_FIRST_SENTENCE = re.compile(r"^(.{20,240}?[.!?])(\s|$)")


def subject_of(cut: dict[str, Any]) -> str:
    """이 컷이 보여야 할 것 — 그림을 **실제로 시킨** visual_prompt 의 첫 문장.

    ★ staging_ko 를 쓰지 않는다(2026-09-27 실측): 연출 전체를 주면 판정관이 "크레인이 충분히
      크지 않다" 같은 세부로 떨어뜨렸다(10컷 중 7컷 불합격). 물어야 할 것은 "주인공이 있나"다.
    """
    vp = str(cut.get("visual_prompt") or "").strip()
    m = _FIRST_SENTENCE.match(vp)
    return (m.group(1) if m else vp[:240]).strip()


def applies(cut: dict[str, Any], header: dict[str, Any]) -> bool:
    """실사형·유료 그림·키 있음·주인공을 말할 수 있을 때만 본다."""
    return bool(config.STILL_CHECK_ENABLED
                and str(header.get("version_type") or "") == "photo"
                and continuity_qa.enabled()
                and subject_of(cut))


def judge(img_path: str, cut: dict[str, Any], asker=None) -> dict[str, Any]:
    """그림 → {measured, text_in_image, subject_present, reason}. 예외를 내지 않는다."""
    out: dict[str, Any] = {"measured": False, "text_in_image": None,
                           "subject_present": None, "split_panels": None, "reason": ""}
    ask = asker or continuity_qa.ask
    data = ask(_SYSTEM, _USER.format(subject=subject_of(cut)), [img_path])
    if not isinstance(data, dict):
        return out
    t, s = data.get("text_in_image"), data.get("subject_present")
    if not isinstance(t, bool) or not isinstance(s, bool):
        return out
    sp = data.get("split_panels")
    out.update(measured=True, text_in_image=t, subject_present=s,
               split_panels=sp if isinstance(sp, bool) else None,
               reason=str(data.get("reason") or ""))
    return out


def check(img_path: str, cut: dict[str, Any], asker=None) -> dict[str, Any]:
    """두 번 물어 **두 번 다 불합격일 때만** 불합격으로 본다(2026-09-27 실측).

    ★ 같은 그림에 같은 질문을 두 번 했더니 답이 갈린 컷이 있었다(10장 중 1장). 불합격 한 번이
      그림 재생성(돈)으로 이어지므로 흔들리는 판정으로 돈을 쓰지 않는다. 판정은 한 번에 약
      $0.0002 라 두 번 물어도 거의 공짜다. 첫 판정이 합격이면 두 번째는 묻지 않는다.
    """
    first = judge(img_path, cut, asker)
    if not failed(first):
        return first
    second = judge(img_path, cut, asker)
    if failed(second):
        return {**second, "votes": 2}
    return {**second, "votes": 1}


def failed(verdict: dict[str, Any] | None) -> bool:
    """글자가 박혔거나·주인공이 없거나·칸으로 쪼개졌다고 **판정된** 경우만 True. 판정 불가는 False.

    ★ split_panels(2026-09-27): 삼성전자 렌더에서 그림 10장 중 7장이 공장|사무실 콜라주였다.
      원인은 세계 문장(photo_world_multi_place)이지만, 그림 단계에서도 한 번 더 잡는다.
    """
    v = verdict or {}
    return bool(v.get("measured")) and (v.get("text_in_image") is True
                                        or v.get("subject_present") is False
                                        or v.get("split_panels") is True)


# ─── 렌더 직후 — 만들어진 **영상**의 프레임을 본다(2026-10-09 운영자 "렌더 직후 그림 검사 개선") ─────────────
#   그림 검사는 클립을 사기 **전** 그림만 봤다. 음파 완성본 컷 15~17 은 그림이 아니라 **영상이 만들어지며** 계획에서
#   벗어났다(사람 손등 상처 → 마네킹 손이 종이에 펜으로 쓰고, 종이에 가짜 글자). 그래서 stage 영상이 만들어진 직후
#   컷마다 그 컷 구간의 가운데 프레임 한 장을 같은 질문(주인공·글자·분할)으로 본다. 판정 한 번 ≈ $0.0002.
#   ★ 다시 사지 않는다(운영자: 비용 최소) — 실패 컷을 기록하고 렌더를 '사람 확인(degraded)'으로 돌린다.
CLIP_CHECK_FAILS: list[dict[str, Any]] = []


def check_clip_frames(video_path: str, plan: dict[str, Any], cuts: list[dict[str, Any]], work_dir: str,
                      asker=None) -> list[dict[str, Any]]:
    """stage 영상 → 컷 구간마다 가운데 프레임 판정. 실패만 돌려주고 CLIP_CHECK_FAILS 에도 쌓는다."""
    import os
    import subprocess
    out: list[dict[str, Any]] = []
    if not (config.CLIP_CHECK_ENABLED and (asker is not None or continuity_qa.enabled())):
        return out
    indexes = list(plan.get("indexes") or [])
    for k, (start, dur) in enumerate(plan.get("windows") or []):
        if k >= len(indexes) or indexes[k] >= len(cuts):
            continue
        cut = cuts[indexes[k]]
        if not subject_of(cut):
            continue
        frame = os.path.join(work_dir, f"clipcheck_{cut.get('cut_no')}.png")
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{float(start) + float(dur) / 2:.2f}",
                            "-i", video_path, "-frames:v", "1", frame], check=True, timeout=60)
        except Exception:  # noqa: BLE001 — 프레임을 못 뽑으면 판정 불가(통과)
            continue
        verdict = check(frame, cut, asker)
        if failed(verdict):
            row = {"cut_no": cut.get("cut_no"), "reason": verdict.get("reason", ""),
                   "text": verdict.get("text_in_image"), "subject": verdict.get("subject_present"),
                   "split": verdict.get("split_panels")}
            out.append(row)
            CLIP_CHECK_FAILS.append(row)
    return out
