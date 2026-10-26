"""자막 큐 생성 (P-V1, M-V5) — SRT 텍스트를 만들어 libass 로 번인한다.

두 경로:
- 단어 타임스탬프(Edge TTS WordBoundary) → 정밀 싱크 자막(merge_word_cues).
- 타임스탬프가 없으면(placeholder 등) 컷 단위 자막(cues_from_cuts) — 컷 길이만큼 나레이션 표시.

순수 로직(네트워크/ffmpeg 없음) — 단위 테스트 대상. 실제 번인은 engine/assemble.py.
"""

from __future__ import annotations

import re
from typing import Any

from . import config

Cue = tuple[float, float, str]  # (start_sec, end_sec, text)


def srt_timestamp(sec: float) -> str:
    """초 → SRT 타임스탬프 'HH:MM:SS,mmm'."""
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[Cue]) -> str:
    """(start,end,text) 목록 → SRT 문서. 빈 텍스트 큐는 건너뛴다."""
    blocks: list[str] = []
    idx = 1
    for start, end, text in cues:
        text = (text or "").strip()
        if not text or end <= start:
            continue
        blocks.append(f"{idx}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}")
        idx += 1
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def ass_timestamp(sec: float) -> str:
    """초 → ASS 타임스탬프 'H:MM:SS.cc'(센티초)."""
    if sec < 0:
        sec = 0.0
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def platform_margin_v(platform: str | None) -> int:
    """②플랫폼별 자막 앵커(높이%)를 하단 MarginV(px)로 변환.

    앵커%는 화면 상단 기준 자막 높이 → 하단 여백 = height * (1 - anchor). 마스터는 TikTok(가장
    빡빡). 미지 플랫폼/None 이면 DEFAULT_PLATFORM. 앵커표에 없으면 SUBTITLE_SAFE_BOTTOM 폴백.
    """
    h = config.RENDER_HEIGHT
    key = (platform or config.DEFAULT_PLATFORM).strip().lower()
    anchor = config.PLATFORM_CAPTION_ANCHOR_PCT.get(key)
    if anchor is None:
        return int(h * config.SUBTITLE_SAFE_BOTTOM)
    return int(round(h * (1.0 - anchor)))


def build_ass(cues: list[Cue], *, header_title: str = "", header_hook: str = "",
              total_sec: float = 0.0, lang: str | None = None,
              platform: str | None = None, footer_text: str = "",
              overlays: list[tuple[float, float, str, str]] | None = None,
              caption_margin_v: int | None = None,
              footer_margin_v: int | None = None,
              footer_from: float = 0.0) -> str:
    """(start,end,text) 목록 → ASS 문서.

    ★ PlayResX/Y 를 렌더 해상도로 명시한다. 그래야 폰트 크기·MarginV 가 실제 픽셀 단위로
    동작한다(SRT+force_style 은 libass 기본 PlayResY=288 좌표계라 마진/크기가 어긋난다).
    스타일: 하단 중앙(Alignment=2, Default) + 상단 고정 헤더(Alignment=8, Header).
    header_title(시리즈 제목)·header_hook(논문 후킹)가 있으면 [0, total_sec] 전 구간 상단 표시.

    lang: ⑤언어별 자막 폰트(CAPTION_FONT). None 이면 기존 SUBTITLE_FONT_NAME(=ko).
    platform: ②플랫폼별 자막 앵커. None 이면 기존 SUBTITLE_SAFE_BOTTOM 위치(하위호환).
    overlays: 【§11】 근거 오버레이 `(start, end, text, style)` 목록. 자막(하단)·헤더(상단)와
      겹치지 않는 중상단에 놓인다. **값이 있을 때만 스타일을 정의**하므로 오버레이 없는 기존
      출력은 바이트 단위로 불변이다(Footer 와 같은 패턴).
    """
    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    font_name = config.CAPTION_FONT.get(lang, config.SUBTITLE_FONT_NAME) if lang \
        else config.SUBTITLE_FONT_NAME
    # 자막·제목 세로 위치: center_band 면 "바 안"(하단 바 자막·상단 바 제목), 아니면 플랫폼 앵커/세이프존.
    if config.LAYOUT_MODE == "center_band":
        margin_v = config.LETTERBOX_CAPTION_MARGIN_V
        margin_top = config.LETTERBOX_HEADER_MARGIN_V
    elif platform:
        margin_v = platform_margin_v(platform)
        margin_top = int(h * config.SUBTITLE_SAFE_TOP)
    else:
        margin_v = int(h * config.SUBTITLE_SAFE_BOTTOM)
        margin_top = int(h * config.SUBTITLE_SAFE_TOP)
    # ★ 설명판형(full_bleed)은 자막·출처 바를 §20-3 밴드 안으로 올려야 한다 — 기본 앵커로 두면
    #   자막이 CORE 를 침범하고 출처 바가 DEAD_BOTTOM(플랫폼 UI 구역)에 놓인다.
    #   None 이면 위 계산 그대로 → **논문 출력 바이트 불변**(Footer·overlay 스타일과 같은 패턴).
    if caption_margin_v is not None:
        margin_v = int(caption_margin_v)
    # 하단 고정 자막(리포트 면책/출처). footer_text 있을 때만 스타일 정의 → 논문 출력 바이트 불변.
    footer = (footer_text or "").strip().replace("\n", " ")
    footer_style = (
        # ★ 반투명 상자(BorderStyle=3, 상자색 = OutlineColour — 키워드 카드와 같은 문법). full_bleed 에서는
        #   바탕 검은 띠가 없어 밝은 그림 위 옅은 글씨가 안 읽혔다(2026-09-28 미리보기 실측).
        f"Style: Footer,{font_name},{config.FOOTER_FONT_SIZE},{config.FOOTER_COLOR_ASS},"
        f"{config.FOOTER_BOX_ASS},&H64000000,1,0,3,8,0,2,40,40,"
        f"{config.FOOTER_MARGIN_V if footer_margin_v is None else int(footer_margin_v)}\n"
    ) if footer else ""
    # 【§11】 근거 오버레이 스타일. Alignment=2(하단 중앙 기준) + 큰 MarginV 로 중상단에 띄운다.
    # ★ 오버레이가 있을 때만 정의 → 기존 출력 바이트 불변(Footer 패턴 계승).
    ov = [o for o in (overlays or []) if str(o[2]).strip()]
    overlay_styles = (
        f"Style: Evidence,{font_name},{config.OVERLAY_FONT_SIZE},{config.OVERLAY_COLOR_ASS},"
        f"&H00000000,&H64000000,1,0,1,3,0,2,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_MARGIN_V}\n"
        f"Style: NumberPunch,{font_name},{config.OVERLAY_NUMBER_FONT_SIZE},{config.OVERLAY_COLOR_ASS},"
        f"&H00000000,&H64000000,1,0,1,4,0,2,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_MARGIN_V}\n"
        f"Style: Caveat,{font_name},{config.OVERLAY_FONT_SIZE},{config.OVERLAY_CAVEAT_COLOR_ASS},"
        f"&H00000000,&H64000000,0,0,1,2,0,2,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_MARGIN_V}\n"
        # ★ 2026-09-18 기전 교육력(연구 T3). 범례는 좌하단(Alignment=1) — 근거 카드·자막과
        #   자리를 나눈다. 분할 화면 캡션은 상단 기준(Alignment=8)으로 위 캡션은 헤더 아래,
        #   아래 캡션은 분할선 바로 아래. 견본 색은 텍스트 안의 인라인 오버라이드가 정한다.
        f"Style: Legend,{font_name},{config.OVERLAY_LEGEND_FONT_SIZE},{config.LEGEND_COLORS_ASS['white']},"
        f"&H00000000,&H64000000,1,0,1,3,0,1,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_LEGEND_MARGIN_V}\n"
        f"Style: LabelTop,{font_name},{config.OVERLAY_LABEL_FONT_SIZE},{config.LEGEND_COLORS_ASS['white']},"
        f"&H00000000,&H64000000,1,0,1,3,0,8,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_LABEL_TOP_MARGIN_V}\n"
        f"Style: LabelBottom,{font_name},{config.OVERLAY_LABEL_FONT_SIZE},{config.LEGEND_COLORS_ASS['white']},"
        f"&H00000000,&H64000000,1,0,1,3,0,8,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_LABEL_BOTTOM_MARGIN_V}\n"
        # ★ 키워드 카드(2026-09-18): 불투명 박스(BorderStyle=3) + 좌상단(Alignment=7).
        #   참고 영상이 모든 컷에 쓰는 문법이다 — 낱말 하나로 화면 속 물체에 이름을 단다.
        # ★ 2026-09-28 풀이 카드: 좌상단(7) → **위 가운데(8)**. 용어+풀이 두 줄이라 가운데가 잘 읽히고,
        #   상단 고정 줄이 꺼져 있으면(SCREEN_HEADER_ENABLED) 헤더 자리만큼 위로 올린다.
        f"Style: Keyword,{font_name},{config.OVERLAY_KEYWORD_FONT_SIZE},{config.OVERLAY_KEYWORD_COLOR_ASS},"
        f"{config.OVERLAY_KEYWORD_BOX_ASS},&H00000000,1,0,3,6,0,8,{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_SIDE_MARGIN_PX},"
        f"{config.OVERLAY_KEYWORD_MARGIN_V if config.SCREEN_HEADER_ENABLED else int(h * config.SUBTITLE_SAFE_TOP)}\n"
        # ★ 지시 화살표: 글자가 아니라 ASS 도형이다. 자리는 문자열이 \pos 로 직접 지정하므로
        #   여기 마진은 안 쓰인다. 외곽선 0 — 도형에 테두리가 생기면 촉이 뭉툼해진다.
        f"Style: Pointer,{font_name},20,{config.OVERLAY_POINTER_COLOR_ASS},"
        f"&H00000000,&H64000000,0,0,1,0,0,7,0,0,0\n"
        # ★ 화면 숫자 카드(2026-10-05, V2): 키워드 카드와 같은 반투명 상자, 화면 가운데 위쪽(근거 카드 자리).
        f"Style: ScreenFact,{font_name},{config.OVERLAY_SCREEN_FACT_FONT_SIZE},{config.OVERLAY_KEYWORD_COLOR_ASS},"
        f"{config.OVERLAY_KEYWORD_BOX_ASS},&H00000000,1,0,3,8,0,2,{config.OVERLAY_SIDE_MARGIN_PX},"
        f"{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_MARGIN_V}\n"
        # ★ S5(2026-10-05): 전망·추정·가설 숫자 카드 — 같은 자리·크기, **상자 없이** 흰 글자 + 검은 외곽선
        #   (BorderStyle=1). ASS 는 점선 테두리를 못 그려서 "상자 있음 = 실적·관측 / 상자 없음 + 강조색
        #   이름표 = 전망·추정"으로 구분한다. 외곽선을 강조색으로 했더니 같은 색 이름표가 뭉개져 안 읽혔다(실측).
        f"Style: ScreenFactEstimate,{font_name},{config.OVERLAY_SCREEN_FACT_FONT_SIZE},{config.OVERLAY_KEYWORD_COLOR_ASS},"
        f"&H00000000,&H64000000,1,0,1,4,0,2,{config.OVERLAY_SIDE_MARGIN_PX},"
        f"{config.OVERLAY_SIDE_MARGIN_PX},{config.OVERLAY_MARGIN_V}\n"
        # ★ S4(2026-10-05): 장면 동작 층(드러내기 막·흐름 화살표). 도형이 \pos 로 자리를 직접 정한다.
        f"Style: StageMotion,{font_name},20,{config.OVERLAY_ANNOTATION_COLOR_ASS},"
        f"&H00000000,&H64000000,0,0,1,0,0,7,0,0,0\n"
    ) if ov else ""
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
        "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        # 본문 자막: 굵게(Bold=1) + 두꺼운 외곽선(Outline=5) — 눈에 잘 띄게. 하단 중앙(Alignment=2).
        f"Style: Default,{font_name},{config.SUBTITLE_FONT_SIZE},"
        f"&H00FFFFFF,&H00000000,&H64000000,1,0,1,5,0,2,60,60,{margin_v}\n"
        f"Style: Header,{font_name},{config.HEADER_TITLE_SIZE},"
        f"&H00FFFFFF,&H00000000,&H64000000,1,0,1,4,0,8,60,60,{margin_top}\n"
        f"{footer_style}{overlay_styles}\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines: list[str] = []
    # 상단 고정 헤더: 시리즈 제목(굵게) + 후킹(작게 다음 줄). 전 구간 표시.
    # ★ 2026-09-28 벤치마크 3번: 기본으로 끈다(SCREEN_HEADER_ENABLED). 벤치마크에는 고정 줄이 없고,
    #   첫 컷이 질문 한마디(HOOK_CUT_RULE)라 훅이 화면에 두 번 뜰 이유도 없다.
    show_header = config.SCREEN_HEADER_ENABLED
    title = (header_title or "").strip().replace("\n", " ") if show_header else ""
    hook = (header_hook or "").strip().replace("\n", " ") if show_header else ""
    if title or hook:
        end_t = total_sec if total_sec and total_sec > 0 else _cues_end(cues)
        if end_t > 0:
            parts = []
            if title:
                parts.append(title)  # 제목: Header 스타일(흰색·굵게·큰 폰트)
            if hook:
                # 부제(후킹): 노랑 강조 + 굵게 — 제목(흰색)과 대비로 특징있게, 눈에 잘 띄게.
                parts.append(
                    f"{{\\fs{config.HEADER_HOOK_SIZE}\\b1\\c{config.HEADER_HOOK_COLOR_ASS}}}{hook}"
                )
            text = "\\N".join(parts)
            lines.append(
                f"Dialogue: 0,{ass_timestamp(0.0)},{ass_timestamp(end_t)},Header,,0,0,0,,{text}"
            )
    # 하단 고정 면책/출처 자막. footer_text 있을 때만. footer_from 부터 끝까지(기본 0 = 전 구간).
    #   ★ 2026-09-28: 리포트는 마지막 컷에서만 띄운다(report_render._footer_start).
    if footer:
        f_end = total_sec if total_sec and total_sec > 0 else _cues_end(cues)
        f_start = min(max(0.0, float(footer_from or 0.0)), f_end)
        if f_end > f_start:
            lines.append(
                f"Dialogue: 0,{ass_timestamp(f_start)},{ass_timestamp(f_end)},Footer,,0,0,0,,{footer}"
            )
    # ★ S4 장면 동작 층(드러내기 막 등)은 **자막보다 아래**(Layer 0, 자막보다 먼저)에 깐다 —
    #   막이 걷히는 0.9초 동안 나레이션 자막이 어두워지면 안 된다.
    for start, end, text, style in ov:
        if style != "StageMotion" or end <= start:
            continue
        lines.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},{style},,0,0,0,,{str(text).strip()}"
        )
    ov = [c for c in ov if c[3] != "StageMotion"]
    for start, end, text in cues:
        text = (text or "").strip().replace("\n", "\\N")
        if not text or end <= start:
            continue
        lines.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Default,,0,0,0,,{text}"
        )
    # 【§11】 근거 오버레이 — Layer=1 로 자막 위에 얹는다(겹칠 때 근거가 가려지지 않게).
    for start, end, text, style in ov:
        text = str(text).strip().replace("\n", "\\N")
        if end <= start:
            continue
        lines.append(
            f"Dialogue: 1,{ass_timestamp(start)},{ass_timestamp(end)},{style},,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + ("\n" if lines else "")


def _cues_end(cues: list[Cue]) -> float:
    """자막 큐의 마지막 종료 시각(헤더 표시 구간 폴백)."""
    return max((float(e) for _s, e, _t in cues), default=0.0)


def cues_from_cuts(durations: list[float], texts: list[str]) -> list[Cue]:
    """컷 단위 자막: 각 컷 나레이션을 그 컷 구간 동안 표시(누적 타임라인)."""
    cues: list[Cue] = []
    t = 0.0
    for dur, text in zip(durations, texts):
        d = max(0.0, float(dur))
        cues.append((t, t + d, text))
        t += d
    return cues


def merge_word_cues(words: list[dict[str, Any]], offset: float = 0.0,
                    max_chars: int | None = None) -> list[Cue]:
    """단어 타임스탬프[{text,start,end}] → 한 줄 max_chars 이하로 묶은 자막 큐.

    offset: 이 컷의 전역 시작 시각. 각 단어 start/end 는 컷 로컬 기준.
    """
    limit = max_chars or config.SUBTITLE_MAX_CHARS
    cues: list[Cue] = []
    line = ""
    line_start: float | None = None
    line_end = 0.0
    for w in words:
        wt = str(w.get("text") or "")
        ws = offset + float(w.get("start") or 0.0)
        we = offset + float(w.get("end") or ws)
        candidate = (line + " " + wt).strip() if line else wt
        if line and len(candidate) > limit:
            cues.append((line_start or 0.0, line_end, line))
            line, line_start = wt, ws
            line_end = we
        else:
            line = candidate
            if line_start is None:
                line_start = ws
            line_end = we
    if line:
        cues.append((line_start or 0.0, line_end, line))
    return cues


def _chunk_chars(text: str) -> int:
    """가독 요구시간 R 계산용 글자수(공백 제외 — CJK/라틴 공통 근사)."""
    return len(text.replace(" ", ""))


def clamp_overlaps(cues: list[Cue]) -> list[Cue]:
    """겹치는 자막 큐 제거 — 각 큐의 끝을 다음 큐 시작으로 클램프(한 시점에 자막 1개).

    컷 경계에서 tail_hold 가 다음 컷 자막 시작을 침범해 두 자막이 위·아래로 겹쳐 보이던 문제를
    막는다. 시작 시각 순 정렬 후 e = min(e, 다음 시작). 빈 텍스트/역전 큐는 버린다.
    """
    ordered = sorted((c for c in cues if (c[2] or "").strip()), key=lambda c: (c[0], c[1]))
    out: list[Cue] = []
    for i, (s, e, t) in enumerate(ordered):
        if i + 1 < len(ordered):
            e = min(e, ordered[i + 1][0])
        if e > s:
            out.append((s, e, t))
    return out


def _split_word_events(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """성긴 워드 이벤트(공백 다수 포함 = 한 이벤트가 여러 어절)를 어절 단위로 재분할.

    한국어 edge-tts WordBoundary 는 종종 어절이 아니라 구/문장 단위로 성기게 온다. 그대로 두면
    chunk_by_rate 가 "한 청크=한 이벤트"로 문장을 통째로 표시한다. 각 이벤트를 공백 기준 어절로
    쪼개고 시간은 글자수 비례로 배분해 잘게 싱크한다(빈/단일 어절 이벤트는 그대로).
    """
    out: list[dict[str, Any]] = []
    for w in words:
        text = str(w.get("text") or "")
        s = float(w.get("start") or 0.0)
        e = float(w.get("end") or s)
        toks = text.split()
        if len(toks) <= 1:
            out.append({"text": text, "start": s, "end": e})
            continue
        dur = max(0.0, e - s)
        total = sum(len(t) for t in toks) or 1
        cur = s
        for t in toks:
            nxt = cur + dur * (len(t) / total)
            out.append({"text": t, "start": cur, "end": nxt})
            cur = nxt
    return out


# ── 뜻 단위 끊기(한국어) ── config.CAPTION_PHRASE_BREAKS 가 켜졌을 때만. 규칙은 config 주석.
_HARD_END = re.compile(r"[.?!…。]$")
_SOFT_END = re.compile(r"[,，·]$")
# 꾸미는 말: 뒤 어절과 떨어지면 안 된다.
_DETERMINERS = {"그", "이", "저", "이런", "그런", "저런", "모든", "한", "두", "세", "네", "몇", "각", "어느", "무슨", "어떤",
                "아무", "딱", "꼭", "좀", "더", "안", "못", "잘", "다", "또", "약", "총", "첫", "새", "옛", "온", "여러", "같은"}
# 어절 끝이 이 조사·어미면 뒤에서 끊기 좋다(뜻 덩어리가 닫힌다).
_CLOSERS = ("에서는", "으로는", "에게는", "까지는", "부터는", "에서", "으로", "에게", "까지", "부터", "처럼", "보다", "하고", "이고",
            "지만", "는데", "은데", "니까", "려면", "도록", "면서", "거든요", "는데요", "어요", "아요", "해요", "에요", "예요", "죠", "요",
            "이나", "이든", "라도", "든", "나",
            "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "도", "만", "고", "면", "서", "게", "다", "랑")
_PARTICLE_N = ("은", "는", "을", "를", "인")   # 받침 ㄴ·ㄹ 로 끝나도 조사인 것(관형형으로 보지 않는다)
# '-다는·-라는·-하는…' 은 '는'으로 끝나도 조사가 아니라 뒤 명사를 꾸민다(마신다는 사람들, 과이아콜이라는 분자).
_ADNOMINAL = ("다는", "라는", "하는", "되는", "있는", "없는", "이라는", "란")
# '-은'으로 끝나 조사와 헷갈리는 흔한 꾸밈말(형용사 관형형). 목록 밖은 조사로 본다(틀려도 한 줄 더 길어질 뿐이다).
_ADJ_N = {"작은", "좋은", "많은", "높은", "낮은", "같은", "짧은", "깊은", "얕은", "옅은", "짙은", "적은", "넓은", "좁은", "검은",
          "붉은", "밝은", "맑은", "묽은", "늙은", "젊은", "얇은", "굵은", "곧은", "괜찮은"}
# 앞말에 붙어야 뜻이 서는 의존 명사(쓸 수, 고를 때, 먹을 것 …) — 이 앞에서 끊지 않는다.
#   정확한 꼴만 본다 — 접두 비교를 하면 '적힌'·'수입'·'때문' 같은 다른 말까지 걸린다.
_BOUND_NOUNS = {b + p for b in ("수", "때", "것", "줄", "적", "뿐", "듯", "만큼", "정도", "채", "척", "편")
                for p in ("", "이", "가", "은", "는", "을", "를", "도", "만", "에")} | {"땐", "건", "걸", "게"} \
    | {"거", "거예요", "거죠", "거든요", "거야", "거래요"}   # 입말 '거'(마신다는 거, 아세요?·탄 거예요)
# 받침 ㄴ 으로 끝나지만 꾸밈말이 아닌 흔한 명사(담기 전·마신 뒤 …). 뒤 말과 떨어져도 된다.
_N_NOUNS = {"전", "후", "뒤", "중", "속", "밖", "간", "년", "원", "분", "산", "손", "돈", "판", "편", "문",
            "사실", "물", "술", "말", "일", "날", "길", "얼굴", "마을", "기술", "원료"}
_TIME_NOUNS = {"전", "후", "뒤", "중"}   # '담기 전 / 물을…' — 때를 나타내는 말 뒤는 끊어도 자연스럽다
_NUM_UNIT = re.compile(r"^\d[\d,.]*(%|도|ml|ML|mL|L|년|원|개|번|분|초|배|잔|병)$")   # 40도·30ml — '도'는 조사가 아니다


def _bare(tok: str) -> str:
    return re.sub(r"[\"'“”‘’()\[\]{}<>「」『』]+", "", tok).rstrip(".,?!…·，。")


def _is_modifier(tok: str) -> bool:
    """뒤 어절을 꾸미는 말인가 — 관형사, '-의', 관형형 어미(받침 ㄴ·ㄹ: 된·한·할·갈 …)."""
    b = _bare(tok)
    if not b or _SOFT_END.search(tok) or _HARD_END.search(tok):
        return False
    if b in _DETERMINERS or b in _ADJ_N or b.endswith("의") or (len(b) >= 3 and b.endswith(_ADNOMINAL)):
        return True
    last = b[-1]
    # 조사·어미로 끝나면(신청하면·지역에서·술은 …) 받침이 ㄴ·ㄹ 이어도 꾸미는 말이 아니다
    if (not ("가" <= last <= "힣") or (len(b) >= 2 and b.endswith(_CLOSERS)) or b in _PARTICLE_N or b in _BOUND_NOUNS
            or b in _N_NOUNS):
        return False   # 건(것은)·땐(때는)도 받침 ㄴ 이지만 뜻이 닫히는 자리다
    jong = (ord(last) - 0xAC00) % 28
    return jong in (4, 8)   # ㄴ, ㄹ (한 글자도 — 쓸·할·갈. 받침 ㄴ·ㄹ 명사가 뒤에 붙는 것은 복합어라 괜찮다)


def _break_score(tok: str, nxt: str | None = None) -> float:
    """이 어절 뒤에서 끊을 때의 보너스(클수록 좋다). 음수면 끊으면 안 되는 자리."""
    if _HARD_END.search(tok):
        return 6.0
    if nxt is not None and _bare(nxt) in _BOUND_NOUNS:
        return -8.0
    if _SOFT_END.search(tok):
        return 4.0
    if _bare(tok) in ("수", "것", "줄", "적", "뿐"):
        return -6.0   # '쓸 수 / 있어요' — 의존 명사 뒤 서술어와도 떨어지지 않게
    if _bare(tok) in ("건", "걸", "땐", "때는"):
        return 2.0
    if _bare(tok) in _TIME_NOUNS:
        return 1.0
    if _NUM_UNIT.match(_bare(tok)):
        return -3.0   # 숫자+단위는 뒤 말과 한 덩어리('40도 정도로', '30ml 한 잔에')
    if _is_modifier(tok):
        return -8.0
    # 조사·어미 없이 끝나는 말(지역·사케 …)은 뒤 말과 한 덩어리일 때가 많다 — 끊기를 꺼린다.
    return 2.0 if _bare(tok).endswith(_CLOSERS) else -3.0


def phrase_groups(text: str) -> list[str]:
    """한 컷 나레이션을 자막 줄로 나눈다(동적 계획 — 길이 목표 + 끊는 자리 점수). 원문 어절 순서·글자는 그대로다."""
    return [g for g, _, _ in _phrase_groups(text)]


def _phrase_groups(text: str) -> list[tuple[str, bool, float]]:
    """(줄, 문장이 이 줄에서 끝나는가, 이 줄 뒤 끊김의 세기). 짧은 줄을 합칠 때 문장 경계를 넘지 않고 약한 끊김 쪽을 지운다."""
    toks = str(text or "").split()
    if not toks:
        return []
    ideal, mx, mt = config.CAPTION_PHRASE_IDEAL_CHARS, config.CAPTION_PHRASE_MAX_CHARS, config.CAPTION_PHRASE_MAX_TOKENS
    n = len(toks)
    best = [0.0] + [float("inf")] * n
    back = [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(max(0, j - mt), j):
            chunk = toks[i:j]
            if any(_HARD_END.search(t) for t in chunk[:-1]):
                continue   # 문장 끝을 넘어 묶지 않는다
            chars = sum(len(_bare(t)) for t in chunk)
            cost = ((chars - ideal) / 3.0) ** 2
            cost += 5.0 * sum(1 for t in chunk[:-1] if _SOFT_END.search(t))   # 쉼표를 줄 가운데 두지 않는다
            if chars > mx and len(chunk) > 1:
                cost += 40.0
            cost -= _break_score(chunk[-1], toks[j]) if j < n else 6.0
            if best[i] + cost < best[j]:
                best[j], back[j] = best[i] + cost, i
    out, j = [], n
    while j > 0:
        i = back[j]
        out.append((" ".join(toks[i:j]), bool(_HARD_END.search(toks[j - 1])) or j == n,
                    _break_score(toks[j - 1], toks[j]) if j < n else 6.0))
        j = i
    # 줄 끝 쉼표·마침표는 보이지 않게(물음표는 둔다)
    return [(re.sub(r"[,，.。]+$", "", g), end, sc) for g, end, sc in reversed(out)]


def chunk_text_by_phrase(text: str, start: float, end: float) -> list[Cue]:
    """뜻 단위 줄로 나누고, 나레이션 구간을 글자 수 비례로 이어 붙여 배분한다(빈틈·겹침 없음).

    너무 짧게 뜨는 줄(하드 플로어 미만)은 이웃과 합치되 **문장 경계를 넘지 않고**, 둘 중 **약한 끊김**을 지운다
    ("안 돼요."가 다음 문장과 붙거나, 쉼표 뒤 "와인과"가 앞 줄로 넘어가 "와인과 증류주"가 갈리지 않게).
    한 문장짜리 짧은 줄은 그대로 둔다."""
    groups = _phrase_groups(text)
    if not groups:
        return []
    dur = max(0.0, float(end) - float(start))
    total = sum(_chunk_chars(g) for g, _, _ in groups) or 1
    rows: list[list] = []   # [start, end, text, ends_sentence, break_after]
    cur = float(start)
    for g, ends, sc in groups:
        nxt = cur + dur * (_chunk_chars(g) / total)
        rows.append([cur, nxt, g, ends, sc])
        cur = nxt
    floor = config.CAPTION_MIN_DISPLAY_FLOOR_SEC
    i = 0
    while i < len(rows):
        s, e, t, ends, sc = rows[i]
        if e - s >= floor or len(rows) == 1:
            i += 1
            continue
        prev_ok = i > 0 and not rows[i - 1][3]        # 앞 줄이 문장 끝이 아니면 앞과 합칠 수 있다
        next_ok = i + 1 < len(rows) and not ends      # 이 줄이 문장 끝이 아니면 뒤와 합칠 수 있다
        if prev_ok and (not next_ok or rows[i - 1][4] < sc):   # 앞 끊김이 더 약하면 앞과
            p = rows[i - 1]
            rows[i - 1] = [p[0], e, f"{p[2]} {t}", ends, sc]
            del rows[i]
            i -= 1
        elif next_ok:
            nx = rows[i + 1]
            rows[i + 1] = [s, nx[1], f"{t} {nx[2]}", nx[3], nx[4]]
            del rows[i]
        else:
            i += 1   # 짧은 한 문장("안 돼요.") — 그대로 둔다
    return [(s, e, t) for s, e, t, _, _ in rows]


def chunk_text_by_rate(text: str, start: float, end: float, lang: str = "ko") -> list[Cue]:
    """워드 타임스탬프가 없을 때(placeholder/실패) 컷 나레이션을 어절로 쪼개 시간 비례 배분 후 청킹.

    → 컷 통짜 자막(문장 전체 한 화면) 대신 ①레이트 기반 청크로 나눠 표시한다.
    ★ 한국어이고 config.CAPTION_PHRASE_BREAKS 가 켜져 있으면 뜻 단위로 끊는다(chunk_text_by_phrase).
    """
    if lang == "ko" and config.CAPTION_PHRASE_BREAKS:
        return chunk_text_by_phrase(text, start, end)
    toks = str(text or "").split()
    if not toks:
        return []
    dur = max(0.0, float(end) - float(start))
    total = sum(len(t) for t in toks) or 1
    synth: list[dict[str, Any]] = []
    cur = float(start)
    for t in toks:
        nxt = cur + dur * (len(t) / total)
        synth.append({"text": t, "start": cur, "end": nxt})
        cur = nxt
    return chunk_by_rate(synth, lang=lang, offset=0.0)


def chunk_by_rate(words: list[dict[str, Any]], lang: str = "ko",
                  offset: float = 0.0) -> list[Cue]:
    """①레이트 기반 자막 청킹 + Fallback 트리(DV7, docs/규격서_숏폼_v2.md §1.2).

    오디오 싱크 불가침 — 오디오를 지연시키지 않는다. 최소 노출은 "청크 크기"로 조절한다.
    words: [{text,start,end}](컷 로컬 초). 반환: 전역 시간(offset 반영) 자막 큐.

    그룹핑 규칙(Fallback 3 = 빠른 발화면 어절 수 축소):
      - 청크에 단어를 붙이되, 토큰이 CHUNK_MAX 에 도달하면 닫는다.
      - 이미 CHUNK_FAST 이상인데 자연 표시창 W 가 가독요구 R 보다 짧으면(=읽을 시간 부족)
        더 붙이지 않고 닫는다 → 빠른 구간은 자동으로 3–4어절로 쪼개진다.
    표시창(Fallback 1·2): t_end = 마지막 단어 끝 + tail_hold(다음 청크까지 침묵으로만, 최대 0.5s).
    하드 플로어(Fallback 4): 표시 < MIN_DISPLAY_FLOOR 면 인접 청크와 병합(발화 유지, 표시만 합침).
    """
    if not words:
        return []
    words = _split_word_events(words)  # 성긴 워드 이벤트를 어절 단위로 재분할(한국어 대응)
    target_cps = config.CAPTION_TARGET_CPS.get(lang, config.CAPTION_TARGET_CPS["ko"])
    max_tokens = config.CAPTION_CHUNK_MAX.get(lang, config.CAPTION_CHUNK_MAX["ko"])
    fast_tokens = config.CAPTION_CHUNK_FAST.get(lang, config.CAPTION_CHUNK_FAST["ko"])
    tail_max = config.CAPTION_TAIL_HOLD_MAX_SEC
    floor = config.CAPTION_MIN_DISPLAY_FLOOR_SEC

    # ── 1) 그룹핑 → 청크(단어 리스트) 목록.
    groups: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        cur.append(w)
        text = " ".join(str(x.get("text") or "") for x in cur).strip()
        t_start = float(cur[0].get("start") or 0.0)
        t_end = float(cur[-1].get("end") or t_start)
        window = max(0.0, t_end - t_start)
        required = _chunk_chars(text) / target_cps if target_cps > 0 else 0.0
        if len(cur) >= max_tokens or (len(cur) >= fast_tokens and window < required):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    # ── 2) 표시창 산출(+ tail_hold 를 다음 청크까지의 침묵에만 부여).
    cues: list[Cue] = []
    for i, g in enumerate(groups):
        text = " ".join(str(x.get("text") or "") for x in g).strip()
        start = offset + float(g[0].get("start") or 0.0)
        end = offset + float(g[-1].get("end") or start)
        if i + 1 < len(groups):
            next_start = offset + float(groups[i + 1][0].get("start") or end)
            gap = max(0.0, next_start - end)
            end += min(gap, tail_max)
        else:
            end += tail_max
        cues.append((start, end, text))

    # ── 3) 하드 플로어 병합: 너무 짧은 표시는 인접 큐로 흡수(발화는 그대로).
    merged: list[Cue] = []
    for start, end, text in cues:
        if end - start < floor and merged:
            ps, _pe, pt = merged[-1]
            merged[-1] = (ps, end, (pt + " " + text).strip())
        else:
            merged.append((start, end, text))
    # 첫 큐가 플로어 미만이고 뒤 큐가 있으면 앞으로 흡수(표시만 연장).
    if len(merged) >= 2 and merged[0][1] - merged[0][0] < floor:
        s0, _e0, t0 = merged[0]
        s1, e1, t1 = merged[1]
        merged[0:2] = [(s0, e1, (t0 + " " + t1).strip())]
    return merged
