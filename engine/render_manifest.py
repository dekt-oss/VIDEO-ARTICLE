"""컷별 렌더 manifest — 선언과 대조 (작업지시서 영상엔진품질 v3 §8-1).

무엇을 고치는가: 지금까지 **"이 컷에 무엇이 있어야 했는가"가 선언된 곳이 없었다.** 그려진
결과(`Placement` 목록)만 있고 기대치가 없으니, 요소 하나가 조용히 빠져도 아무도 모른다.
"이 화면은 왜 허전한가"를 물으면 답할 데이터가 없었다.

여기서 하는 일은 두 가지뿐이다:
  · declare()   — 그리기 **전**에 기대 레이어를 선언한다
  · reconcile() — 그린 **뒤**에 실제 placements 와 맞춰 본다

★ 순수 모듈이다: PIL·ffmpeg·네트워크를 모른다. board_layout.py 가 세운 분리 규약을 그대로
  따른다 — 그래야 단위 테스트가 렌더 없이 돈다.

★★ **기록 전용이다.** 이 모듈은 판정을 내리지 않고 예외도 던지지 않는다. 불일치가 있어도
   렌더는 계속된다. criticality → failed/degraded 승격(§8-2)과 상태 머신(§8-3)은 기록이
   쌓인 뒤 별개로 한다. cost.record·report_render 의 QA 호출이 세워 둔 규약과 같다 —
   관측을 켜다가 사고를 내지 않는다. 그래서 산출물에 policy="record_only" 를 박아 둔다.

★ 대조는 **마지막 프레임** placements 만 본다(render_board 가 프레임마다 재할당한다).
  "끝에 다 그려져 있는가"에는 옳지만, **중간에 나타났다 사라진 레이어는 못 본다.**
  단계 애니메이션의 tail 덕분에 마지막 프레임에서 전 단계가 완료돼 있다는 전제다.
"""

from __future__ import annotations

from typing import Any

from . import component_registry as cr
from . import config
from .board_layout import Placement, band_box

# 레이어 → 밴드. `board_render._draw_frame` 이 실제로 그리는 구조와 1:1 이다.
BAND_BY_LAYER: dict[str, str] = {
    "backdrop": "CORE",
    "title": "TITLE",
    "core": "CORE",
    "meta": "META",
    "sowhat": "SOWHAT",
    "source": "SOURCE",
}

# 컴포넌트가 없는 밴드 레이어의 criticality. 컴포넌트가 있는 레이어는 ComponentSpec 이 갖는다
# (§8-2 의 나머지 절반이 fallback_component 옆에 사는 것이 맞다).
# 지시서 기본값: 핵심 수치·차트·회사명·출처·자막=critical / 맥락·배지=important / 장식=decorative.
CRITICALITY_BY_LAYER: dict[str, str] = {
    "title": "critical",      # 자막·제목
    "sowhat": "important",    # 맥락 한 줄
    "backdrop": "decorative",
}

# so_what 을 전용 밴드에 그리는 보드. board_render.render_board 의 has_sowhat_band 와 같다.
SOWHAT_BAND_BOARDS: tuple[str, ...] = ("NUMBER_BOARD", "CHART_BOARD", "VALUATION_BOARD")

# ★ placements 로는 관측할 수 없는 레이어. 출처·면책은 보드가 아니라 ASS footer 로 나간다
#   (board_render 의 "SOURCE 밴드는 여기서 그리지 않는다" 주석). 지시서(§8-1)는 출처를
#   critical 로 선언하라고 하는데, 그대로 대조하면 **모든 컷이 결측**으로 잡힌다. 그래서
#   missing 과 다른 칸에 넣는다 — §8-2 승격 때 이걸 발견하면 승격을 통째로 되돌리게 된다.
UNOBSERVABLE_LAYERS: frozenset[str] = frozenset({"source"})


def _criticality(layer_id: str, component: str) -> str:
    if component:
        try:
            return cr.get_component(component).criticality
        except KeyError:
            pass
    return CRITICALITY_BY_LAYER.get(layer_id, "important")


def _bbox(layer_id: str) -> list[int]:
    """선언 박스. 좌표를 여기 적지 않고 밴드에서 해소한다(board_layout 과 같은 이유)."""
    b = band_box(BAND_BY_LAYER[layer_id])
    return [b.x1, b.y1, b.x2, b.y2]


def declare(board: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """그리기 전 선언. §8-1 의 expected_layers 스키마.

    ★ 컷 dict 이 아니라 **ctx**(render_board 가 만든 payload)를 받는다. 컷만 보고 선언하면
      틀린 결측이 나온다 — 예를 들어 TITLE 은 `ctx["title_text"]` 가 있을 때만 그려지고,
      그 값은 K10 중복 회피 로직이 비울 수도 있다. 선언과 그리기가 **같은 데이터**를 봐야
      manifest 가 거짓말을 하지 않는다.
    """
    pay = ctx.get("pay") or {}
    # ★ 라우팅은 render_board 가 §7-3 으로 이미 정해 ctx 에 실어 뒀다. 여기서 다시 풀면
    #   **선언과 그림이 갈린다** — 그 순간 manifest 는 대조가 아니라 거짓말이 된다.
    #   ctx 에 없으면(구 호출자·테스트) 보드 기준으로 되돌린다.
    core_component = str(ctx.get("core_component") or "")
    core_spec = (cr.get_component(core_component) if core_component
                 else cr.resolve_for_board(board, allow_draft=False))
    required = {
        "backdrop": True,
        "title": bool(ctx.get("title_text")),
        "core": True,
        "meta": bool(ctx.get("meta_kicker")),
        "sowhat": bool(pay.get("sowhat")) and board in SOWHAT_BAND_BOARDS,
        "source": True,
    }
    component = {
        "core": core_spec.component,
        "meta": cr.BAND_COMPONENTS.get("META", ""),
        "source": cr.BAND_COMPONENTS.get("SOURCE", ""),
    }

    layers: list[dict[str, Any]] = []
    for layer_id in BAND_BY_LAYER:
        comp = component.get(layer_id, "")
        fallback = ""
        if comp:
            try:
                fallback = cr.get_component(comp).fallback_component or ""
            except KeyError:
                fallback = ""
        layers.append({
            "layer_id": layer_id,
            "component": comp,
            "required": required[layer_id],
            "safe_zone": BAND_BY_LAYER[layer_id],
            "bbox": _bbox(layer_id),
            "criticality": _criticality(layer_id, comp),
            "fallback": fallback,
            "observable": layer_id not in UNOBSERVABLE_LAYERS,
        })
    return {"board": board, "expected_layers": layers}


def terminal_status(board_qa: list[dict[str, Any]] | None) -> tuple[str, list[str]]:
    """컷별 manifest 대조 결과 → 잡의 최종 상태 (§8-2·§8-3).

    지시서 §8-3: **done = critical QA 전부 PASS 일 때만.**
      · critical 누락  → failed
      · important 누락 → degraded (사람이 승인해야 발행 가능)
      · 그 외          → done

    ★ 이 판정이 성립하는 이유가 한 줄에 걸려 있다: `source` 레이어는 UNOBSERVABLE_LAYERS 라
      missing 에 안 들어간다. 출처는 보드가 아니라 ASS footer 로 나가서 placements 로는
      관측이 안 되기 때문인데, 그 제외가 없으면 **모든 컷이 critical 누락**이 되어 이 승격은
      첫날 전부 failed 를 만든다. UNOBSERVABLE_LAYERS 를 건드릴 때 여기를 같이 볼 것.

    ★ 반환하는 사유 문자열은 §8-2 가 요구한 기록이다(cut/layer/error_code). 잡의 error_log 로
      들어가 "몇 번 컷의 어느 레이어가 왜"를 남긴다.
    """
    critical: list[str] = []
    important: list[str] = []
    for cut in board_qa or []:
        man = cut.get("manifest") or {}
        cut_no = cut.get("cut_no")
        for miss in man.get("missing") or []:
            code = f"missing_{miss.get('criticality')}:{miss.get('layer_id')}#{cut_no}"
            if miss.get("criticality") == "critical":
                critical.append(code)
            elif miss.get("criticality") == "important":
                important.append(code)
        # ★ 레이아웃 판정 중 "사람이 보고 정할 것"(허전한 보드)도 여기로 온다. 렌더는 더 이상
        #   이걸로 잡을 죽이지 않으므로(config.LAYOUT_FAIL_REVIEWABLE), 이 줄이 없으면 빈
        #   보드가 done 으로 조용히 통과한다 — 승격 이전 상태로 되돌아가는 셈이다.
        for reason in cut.get("layout_fail") or []:
            if str(reason).startswith(config.LAYOUT_FAIL_REVIEWABLE):
                important.append(f"layout_review:{reason}#{cut_no}")
        # ★ Q3 애니메이션 계약(§9 · engine/animation_qa). 카운트업이 정지된 숫자로,
        #   막대가 안 자란 채로 나가는 것을 여기서 잡는다 — 계약값(min_change_ratio)은
        #   레지스트리에 있었는데 **읽는 곳이 없었다**(2026-09-03).
        #   critical 이 아니라 important 다: 화면은 그려져 있고 움직임만 없는 상태라
        #   사람이 보고 정하는 편이 낫다(core_underfilled 가 배운 것과 같은 처방 —
        #   이미 이미지·TTS·조립 비용을 다 쓴 뒤 산출물을 버리지 않는다).
        for reason in cut.get("animation_fail") or []:
            important.append(f"{reason}#{cut_no}")
    if critical:
        return "failed", critical + important
    if important:
        return "degraded", important
    return "done", []


def tag(placements: list[Placement] | None, layer_id: str,
        component: str = "") -> list[Placement]:
    """그려진 placements 에 레이어 정체를 찍는다. 반환은 같은 리스트(호출부에서 바로 += 한다).

    ★ 왜 Placement.kind 로 조인할 수 없나: kind 는 **모양** 어휘다(text|number|bar|…).
      TITLE·SOWHAT·숫자 라벨·킥커가 전부 `_draw_text_in` 을 거치는데 그 함수가 kind="text" 를
      하드코딩한다 — 원리적으로 구분이 안 된다. (kind, band) 조합도 부족하다: CORE 의 text 가
      number_count 의 라벨인지 폴백된 text_core 인지 갈라야 하는데, **그 구분이 바로 manifest
      의 존재 이유**(폴백 검출)다.
    ★ Placement.meta 는 선언만 돼 있고 아무도 안 쓰던 자리다. 여기 찍으면 Placement 생성자
      18곳을 한 줄도 안 건드린다 — 그래서 그림이 바뀌지 않고 골든 해시도 그대로다.
    """
    out = placements or []
    for p in out:
        p.meta["layer_id"] = layer_id
        if component:
            p.meta["component"] = component
    return out


def reconcile(manifest: dict[str, Any], placements: list[Placement],
              attempted_fallbacks: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """선언 ↔ 실제 대조. **절대 예외를 던지지 않고 판정도 바꾸지 않는다**(기록 전용).

    attempted_fallbacks: 그리기 중 폴백으로 **내려갔다는 사실**. placements 태그만으로는
    부족하다 — 폴백이 아무것도 못 그리면 찍을 placement 가 없어 "그냥 결측"으로 보인다.
    "폴백까지 갔는데도 비었다"와 "애초에 안 그렸다"는 원인이 다르고 처방도 다르다.
    """
    seen: dict[str, list[Placement]] = {}
    for p in placements:
        lid = str((p.meta or {}).get("layer_id") or "")
        if lid:
            seen.setdefault(lid, []).append(p)

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    fallbacks: list[dict[str, str]] = list(attempted_fallbacks or [])
    fell_back = {f["layer_id"] for f in fallbacks}
    unobservable: list[str] = []
    counts = {"critical": 0, "important": 0, "decorative": 0}

    for layer in manifest.get("expected_layers") or []:
        lid = layer["layer_id"]
        got = seen.get(lid) or []
        drawn = ""
        for p in got:
            drawn = str((p.meta or {}).get("component") or "") or drawn

        if not layer.get("observable", True):
            status = "unobservable"
            unobservable.append(lid)
        elif not layer["required"]:
            status = "not_required"
        elif not got:
            # 폴백까지 갔는데도 비었으면 그 사실을 status 로 구분한다 — 결측 원인이 다르다.
            status = "fallback_empty" if lid in fell_back else "missing"
            missing.append({"layer_id": lid, "criticality": layer["criticality"],
                            "status": status})
            if layer["criticality"] in counts:
                counts[layer["criticality"]] += 1
        elif layer["component"] and drawn and drawn != layer["component"]:
            status = "fallback"
            if lid not in fell_back:
                fallbacks.append({"layer_id": lid, "from": layer["component"], "to": drawn})
        else:
            status = "ok"

        rows.append({"layer_id": lid, "status": status,
                     "criticality": layer["criticality"],
                     "expected_component": layer["component"],
                     "drawn_component": drawn,
                     "placements": len(got)})

    declared = [l["layer_id"] for l in manifest.get("expected_layers") or []]
    return {
        "policy": "record_only",
        "layers": rows,
        "missing": missing,
        "fallback": fallbacks,
        "unobservable": unobservable,
        "untagged_placements": sum(1 for p in placements
                                   if not (p.meta or {}).get("layer_id")),
        "unexpected": sorted(set(seen) - set(declared)),
        "counts": counts,
    }
