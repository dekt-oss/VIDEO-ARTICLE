"""설명형 2단계 스크립트(S0.5·S2·S3)가 함께 쓰는 것 — 결재 문장·금액 표·안전 장치. 2026-11-02. docs/deviation-drinks-explainer-stage2.md

규칙(세 스크립트 공통):
  · 기본은 **0원 dry-run** 이다. 모델·공급자·운영 DB 쓰기는 `--yes` 가 있어야 하고, 그 전에 결재 문장과 상한을 화면에 찍고 되묻는다.
  · 상한은 config.DRINKS_EXPLAINER_STAGE_CAPS_USD 에서만 읽는다. 계산한 예상액이 상한을 넘으면 `--yes` 가 있어도 멈춘다.
  · 영상 구매(S2·S3)는 그 위에 DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED 가 켜져 있어야 한다 — 운영자 PC 에서 한 회만 켠다. 코드가 켜지 않는다.
  · 비밀값(키·토큰)은 찍지도 저장하지도 않는다.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from engine.util import today_local

ROOT = Path(__file__).resolve().parents[1]


class StageStop(Exception):
    """스크립트를 멈춘다. 돈이 나가기 전의 멈춤이다."""


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def preview_dir(name: str) -> Path:
    out = ROOT / "docs" / f"preview-{today_local().isoformat()}" / name
    out.mkdir(parents=True, exist_ok=True)
    return out


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def cap_for(stage: str) -> float:
    return float(config.DRINKS_EXPLAINER_STAGE_CAPS_USD[stage])


def approval_sentence(stage_label: str, *, purpose: str, cap_usd: float, estimate_usd: float, scope: str) -> str:
    """운영자가 그대로 읽고 승인하는 한 문장. DB 의 approver_words 칸에 **운영자가 친 말**이 들어가고, 이 문장은 제안이다."""
    return (f"[{stage_label}] {purpose} — {scope}. 예상 ${estimate_usd:.2f}, 상한 ${cap_usd:.2f}. "
            f"상한을 넘으면 자동으로 멈추고 추가 구매는 없다. 승인 문장을 `--approve \"…\"` 로 적어 실행한다.")


def ceil_cents(x: float) -> float:
    return math.ceil(round(x, 6) * 100) / 100


# ─────────────────────────────────────────────────────────────
# 지시서 표 — S2·S3 가 돈을 쓰기 전에 화면에 찍는 것
# ─────────────────────────────────────────────────────────────

def slot_rows(directive: dict[str, Any], through_n: Optional[int] = None) -> list[dict[str, Any]]:
    rows = []
    for s in directive.get("slots") or []:
        n = int(s["n"])
        if through_n and n > through_n:
            continue
        cands = int(s.get("candidates_planned") or 1)
        rows.append({"n": n, "role": s["role"], "boundary_in": s["boundary_in"], "clip_sec": int(s["clip_sec"]), "candidates": cands,
                     "image_usd": float(s["image_est_usd"]), "clips_usd": float(s["clip_est_usd"]) * cands, "narration": str(s.get("narration") or "")[:40],
                     "visual_claim_ko": str(s.get("visual_claim_ko") or "")[:60]})
    return rows


def rows_total(rows: list[dict[str, Any]]) -> float:
    return sum(r["image_usd"] + r["clips_usd"] for r in rows)


def format_table(rows: list[dict[str, Any]], *, title: str) -> str:
    lines = [title, f"{'슬롯':>3} {'역할':<9} {'경계':<16} {'길이':>4} {'후보':>2} {'그림$':>6} {'클립$':>6}  나레이션 / 시각 주장"]
    for r in rows:
        lines.append(f"{r['n']:>3} {r['role']:<9} {r['boundary_in']:<16} {r['clip_sec']:>3}s {r['candidates']:>2} {r['image_usd']:>6.3f} {r['clips_usd']:>6.3f}  {r['narration']} / {r['visual_claim_ko']}")
    lines.append(f"합계 ${rows_total(rows):.3f}")
    return "\n".join(lines)


def s2_scope(directive: dict[str, Any]) -> dict[str, Any]:
    """S2 = 1번 슬롯 … 훅 슬롯(후보 2)까지만 산다(§3-10). 상한은 config, 예상은 지시서 금액 + 가장 긴 클립 재시도 1회."""
    hook = int(directive["hook_scene"])
    rows = slot_rows(directive, through_n=hook)
    longest = max((r["clip_sec"] for r in rows), default=0)
    provider, res = directive["provider"], directive.get("resolution") or config.DRINKS_EXPLAINER_RESOLUTION
    from engine import drinks_explainer as dx

    reserve = dx.clip_est_usd(provider, longest, res) * config.DRINKS_EXPLAINER_S2_EXTRA_CLIP_RETRY if longest else 0.0
    estimate = rows_total(rows)
    cap = cap_for("s2")
    # §3-10: 예상 약 $2.2 에 상한 $2.6 — 상한은 문서가 정했고, 예상이 상한 안이어야 산다. 남는 폭(headroom)이 재시도 1회를 얼마나 덮는지는 따로 보인다.
    headroom = round(cap - estimate, 4)
    return {"through_n": hook, "rows": rows, "estimate_usd": round(estimate, 4), "retry_reserve_usd": round(reserve, 4), "headroom_usd": headroom,
            "retry_covered": headroom >= reserve, "cap_usd": cap, "fits": ceil_cents(estimate) <= cap, "slots": [r["n"] for r in rows]}


def s3_scope(directive: dict[str, Any], *, s2_spent_usd: float, selected_slots: tuple[int, ...] = ()) -> dict[str, Any]:
    """S3 = 편 전체. 상한 = $8.90 − S2 사용액(§3-10). 이미 선택된 슬롯(S2 자산)은 다시 사지 않으므로 예상에서 뺀다."""
    rows = [r for r in slot_rows(directive) if r["n"] not in set(selected_slots)]
    estimate = rows_total(rows)
    reserve = float(directive.get("estimate", {}).get("reserve_usd") or 0.0)
    cap = ceil_cents(cap_for("s3") - float(s2_spent_usd))
    headroom = round(cap - estimate, 4)
    return {"rows": rows, "estimate_usd": round(estimate, 4), "retry_reserve_usd": round(reserve, 4), "headroom_usd": headroom, "retry_covered": headroom >= reserve,
            "cap_usd": cap, "s2_spent_usd": round(float(s2_spent_usd), 4), "fits": ceil_cents(estimate) <= cap and cap > 0, "skipped_slots": sorted(set(selected_slots))}


# ─────────────────────────────────────────────────────────────
# 실행 전 게이트
# ─────────────────────────────────────────────────────────────

def require_yes(args: Any, what: str) -> None:
    if not getattr(args, "yes", False):
        raise StageStop(f"{what} 는 `--yes` 가 있어야 합니다(지금은 0원 dry-run). 위 결재 문장을 확인한 뒤 `--yes --approve \"승인 문장\"` 으로 다시 실행하세요.")
    if not str(getattr(args, "approve", "") or "").strip():
        raise StageStop("결재 문장(`--approve \"…\"`)이 없습니다 — 운영자가 승인한 말을 그대로 적습니다(DB approver_words).")


def require_db_env() -> None:
    if not (config.SECRETS.supabase_url and config.SECRETS.supabase_service_key):
        raise StageStop("SUPABASE_URL·SUPABASE_SERVICE_KEY 가 없습니다 — 운영 DB 에 쓰는 단계는 운영자 PC 에서만 돕니다.")


def require_provider_switch() -> None:
    if not config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED:
        raise StageStop("실호출 스위치가 꺼져 있습니다 — 운영자 PC 에서 이 한 회만 `DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED=1` 로 켭니다. 코드는 켜지 않습니다.")
    if not config.SECRETS.gemini_api_key:
        raise StageStop("GEMINI_API_KEY 가 없습니다.")


def require_migration(rpc: Any, fn: str, probe: dict[str, Any]) -> None:
    """운영 DB 에 그 함수가 있는지 — 없으면 0067 등 미적용이다. 쓰기 없는 호출로만 잰다."""
    from engine.drinks_collect import DbError

    try:
        rpc(fn, probe)
    except DbError:
        return   # 함수는 있고 입력만 거부했다
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "PGRST202" in msg or "Could not find the function" in msg or "does not exist" in msg:
            raise StageStop(f"운영 DB 에 {fn} 이 없습니다 — 마이그레이션이 적용되지 않았습니다(별도 결재 뒤 적용).") from exc
        raise


def env_summary() -> dict[str, Any]:
    """무엇이 켜져 있나 — 값은 절대 찍지 않는다."""
    return {"supabase": bool(config.SECRETS.supabase_url and config.SECRETS.supabase_service_key), "gemini_key": bool(config.SECRETS.gemini_api_key),
            "provider_send_enabled": bool(config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED), "preflight_enabled": bool(config.DRINKS_EXPLAINER_OMNI_PREFLIGHT_ENABLED),
            "default_provider": config.DRINKS_EXPLAINER_DEFAULT_PROVIDER, "worker_id": os.getenv("WORKER_ID", "local")}
