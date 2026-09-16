"""대본 정본 — 지문(해시)과 씬 동기화 (2026-08-20, PR #94 후속 리뷰 P1-1·P1-2).

무엇을 고치는가: **한 편에 대본이 두 벌 있었다.**

  · `report_drafts.script_md` — ④ 화면에서 운영자가 실제로 고치는 것
  · `report_drafts.scenes`    — 씬별 나레이션·근거. ④ 는 **읽기만** 한다

그런데 ⑤ 지시서 생성기는 둘을 **동시에** LLM 입력으로 넣었다. 운영자가 대본에서 지운 문장이
씬에는 남아 있으면, 서로 충돌하는 두 원고가 한 프롬프트에 들어간다 — 지운 문장이 영상에 다시
등장할 수 있다. 재검사도 같은 문제를 겪었다: 저장된 옛 씬으로 근거·밀도를 다시 계산했다.

여기서 하는 일은 둘뿐이다(순수 함수 — DB·네트워크·LLM 을 모른다).

  · fingerprint()  — 대본의 지문. "이 판정은 어느 대본에 대한 것인가"를 붙들어 둔다
  · sync_scenes()  — 편집된 대본으로 씬의 나레이션을 갱신한다

★ 씬을 다시 만들 수 있는 이유: `script_md` 는 **빈 줄로 나뉜 문단이 곧 씬 하나**다(실측 —
  씬 7개짜리 초안의 script_md 가 문단 7개 + 면책 1줄이었다). 그래서 LLM 없이 자리로 맞출 수 있다.
  역할(scene_role)·근거(source_facts)·길이(duration_sec)는 씬에 그대로 남긴다 — 운영자가 고친
  것은 문장이지 근거 배정이 아니다.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import config

# 문단 구분: 빈 줄 하나 이상.
_PARA_SPLIT = re.compile(r"\n\s*\n")

# ★ 씬 머리글 줄. `script_md` 형식은 **고정이 아니다** — 프롬프트가 "전체 대본 마크다운"만
#   요구해서, 어떤 초안은 문단만 있고 어떤 초안은 `**씬1 (후크)**` 머리글이 붙는다(둘 다 실측).
#   머리글을 걸러내지 않으면 씬 동기화가 나레이션을 "**씬1 (후크)** 로봇 회사 하나가…" 로
#   덮어써서 **TTS 가 별표와 '씬일'을 소리 내 읽는다.** 실제로 그 직전까지 갔다.
_SCENE_HEADING = re.compile(r"^[*#\s]*씬\s*\d+[^\n]*$")


def _strip_headings(block: str) -> str:
    """한 문단에서 씬 머리글 줄만 걷어낸다. 본문 줄은 건드리지 않는다."""
    body = [ln for ln in block.splitlines() if not _SCENE_HEADING.match(ln.strip())]
    return " ".join(" ".join(body).split())


def fingerprint(script_md: str | None) -> str:
    """대본의 지문. 같은 글이면 같은 값, 한 글자만 달라도 다른 값.

    ★ 웹(Next)에서도 같은 값을 계산해 비교한다 — 알고리즘이 갈리면 "검증 이후 수정됨" 판정이
      항상 참이 되어 경고가 늑대소년이 된다. 파리티는 tests/test_script_revision.py 가 지킨다.
      계약: sha256(대본 원문 utf-8) 의 앞 16글자.
    """
    text = (script_md or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def is_disclaimer(paragraph: str) -> bool:
    """면책 문단인가. 면책은 씬이 아니라 화면 하단 고정 자막으로 나간다(§5-2)."""
    p = (paragraph or "").strip()
    if not p:
        return False
    return any(m in p for m in config.COMPLIANCE_DISCLAIMER_MARKERS)


def script_paragraphs(script_md: str | None) -> list[str]:
    """대본 → 씬이 될 문단 목록(면책 제외). 빈 문단은 버린다."""
    raw = _PARA_SPLIT.split((script_md or "").strip())
    out: list[str] = []
    for p in raw:
        text = _strip_headings(p)           # 씬 머리글 제거 + 줄바꿈·중복 공백 정리
        if text and not is_disclaimer(text):
            out.append(text)
    return out


def sync_scenes(scenes: list[dict[str, Any]] | None,
                script_md: str | None) -> list[dict[str, Any]]:
    """편집된 대본으로 씬의 나레이션을 갱신한다. 근거·역할·길이는 보존.

    ★ 문단 수가 씬 수와 다를 수 있다(운영자가 문단을 쪼개거나 합친다).
      · 문단이 더 많으면 → 남는 문단을 **새 씬**으로 만든다. 근거는 비운다.
        비워 두는 것이 맞다: 그 문장은 아직 어떤 Fact 에도 매이지 않았고, 근거 게이트가
        그것을 빨간 깃발로 잡아 주는 것이 이 파이프라인의 자세다. 앞 씬의 근거를 물려주면
        **검증되지 않은 문장이 검증된 것처럼** 보인다.
      · 문단이 더 적으면 → 남는 씬은 버린다(운영자가 지운 문장이다).
    ★ 원본 리스트를 건드리지 않는다(순수).
    """
    paras = script_paragraphs(script_md)
    src = list(scenes or [])
    if not paras:
        # 대본이 비었으면 판단할 근거가 없다 — 있는 씬을 그대로 둔다(파괴하지 않는다).
        return [dict(s) for s in src]

    out: list[dict[str, Any]] = []
    for i, para in enumerate(paras):
        if i < len(src):
            scene = dict(src[i])
            scene["narration_ko"] = para
        else:
            scene = {
                "scene": i + 1,
                "title": "",
                "narration_ko": para,
                "narration_en": "",
                "duration_sec": 0,
                "scene_role": "",
                "source_facts": [],      # ★ 물려주지 않는다(위 주석)
                "image_prompt": "",
                "image_prompt_ko": "",
                "video_prompt": "",
                "video_prompt_ko": "",
            }
        scene["scene"] = i + 1
        out.append(scene)
    return out


def scenes_match_script(scenes: list[dict[str, Any]] | None,
                        script_md: str | None) -> bool:
    """씬의 나레이션이 지금 대본과 일치하는가. ⑤ 입력에 씬을 실을지 판단한다.

    어긋나면 씬은 **옛 원고**다 — 지시서 프롬프트에 실으면 지운 문장이 되살아난다.
    """
    paras = script_paragraphs(script_md)
    narr = [" ".join(str(s.get("narration_ko") or "").split()) for s in (scenes or [])]
    return paras == narr
