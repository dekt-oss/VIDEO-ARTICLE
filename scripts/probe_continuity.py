"""Phase 0 — 시각 연속성 실측 프로브 (작업계획서_시각엔진_v3.md §6 Phase 0).

무엇을 재는가: v3 전체가 하나의 가정 위에 서 있다 —

    "이전 stage 의 화면을 참조로 주면, 같은 인물·같은 세계에서 **다음 상태**를 만들 수 있다."

이 가정이 실측된 적이 없다. 확인하지 않고 Sequence 스키마부터 만들면 정본 작업지시서
자신의 적대적 체크리스트("schema field 를 만들었지만 renderer 가 무시하고 있지 않은가")를
그대로 밟는다 — 필드만 있고 렌더가 못 하는 죽은 계약이 된다.

그래서 **프로덕션 코드를 건드리지 않고** 여기서 먼저 잰다. GO 가 나면 그때 배선한다.

재는 것(작업계획서 D4 = GO 기준):
  ① 연속 3 stage 에서 같은 인물·같은 세계로 인식되는가 (멀티모달 판정 + 콘택트시트)
  ② stage 당 이미지 비용이 현행 단가의 2배 이내인가
  ③ 글자 번인이 없는가

★ 이 스크립트는 프로덕션 경로가 아니다. engine/providers/image.py 는 텍스트 전용이라
  참조 이미지를 실을 수 없다 — 여기서는 요청 바디를 직접 만든다. 배선은 Phase 3 이다.

실행:
    IMAGE_PROVIDER=gemini python -m scripts.probe_continuity <출력디렉터리>
    (--no-video 로 Veo I2V 단계를 건너뛴다)
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
from typing import Any

import httpx

from engine import config
from engine.util import gemini_auth, log

# ── 실측 세계: 옥시토신 논문의 신뢰게임. 인물 2명·테이블·토큰이 persistent entity 다.
#    ★ 원문 근거를 넘는 것을 그리지 않는다(작업지시서 Paper §12) — 절차 상세·생리 경로는
#      쓰지 않고, "두 사람이 테이블에서 토큰을 주고받는다"는 초록이 말하는 범위 안이다.
WORLD = (
    "premium technical 3D render, clean realistic geometry, soft top-left studio lighting, "
    "35 degree isometric camera, neutral warm-grey background, restrained depth of field"
)
BASE_SCENE = (
    "two adult men sitting across a plain wooden table facing each other, "
    "the man on the left wears a grey sweater, the man on the right wears a navy shirt, "
    "a stack of ten identical small metallic discs sits on the table in front of the left man, "
    "the table is otherwise empty"
)

# 각 stage 는 **이전 화면을 참조로 받아** 상태만 바꾼다. 새 세계를 만들라고 하지 않는다.
STAGES: list[dict[str, str]] = [
    {
        "id": "S1",
        "operation": "TRANSFER",
        "change": "the left man pushes three of the metallic discs across the table "
                  "toward the right man; seven discs remain in front of the left man",
    },
    {
        "id": "S2",
        "operation": "ACCUMULATE",
        "change": "the three discs that were transferred have grown into a stack of nine "
                  "in front of the right man; the left man still has seven",
    },
    {
        "id": "S3",
        "operation": "TRANSFER",
        "change": "the right man pushes five discs back across the table toward the left man; "
                  "four discs remain in front of the right man",
    },
]

_REF_INSTRUCTION = (
    "Use the attached image as the exact starting frame. Keep the SAME two men "
    "(same faces, same clothing, same seating), the SAME table, the SAME camera angle, "
    "the SAME lighting and the SAME disc design. Do not redraw the scene from scratch. "
    "Change ONLY the following: "
)


def _post(model: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{config.GEMINI_BASE}/{model}:generateContent"
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
        resp = client.post(url, headers=gemini_auth(), json=body)
        resp.raise_for_status()
        return resp.json()


def _inline_image_b64(data: dict[str, Any]) -> str:
    for cand in (data.get("candidates") or []):
        for part in ((cand.get("content") or {}).get("parts") or []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return str(blob["data"])
    return ""


def _aspect_cfg() -> dict[str, Any]:
    """프로덕션과 같은 종횡비 파라미터를 쓴다 — 다르면 실측이 프로덕션을 대변하지 못한다."""
    from engine.providers.image import _aspect_generation_config

    return _aspect_generation_config()


def gen_image(prompt: str, out_path: str, model: str,
              ref_path: str | None = None) -> float:
    """텍스트(+참조 이미지) → 이미지. 반환: 근사 비용(USD)."""
    parts: list[dict[str, Any]] = []
    if ref_path:
        with open(ref_path, "rb") as f:
            parts.append({"inlineData": {"mimeType": "image/png",
                                         "data": base64.b64encode(f.read()).decode()}})
    parts.append({"text": prompt})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], **_aspect_cfg()},
    }
    b64 = _inline_image_b64(_post(model, body))
    if not b64:
        raise RuntimeError(f"이미지 응답에 inlineData 없음 (model={model})")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return float(config.PRICING.get(model, {}).get("image_standard",
                                                   config.GEMINI_IMAGE_COST_USD))


_JUDGE_PROMPT = """두 이미지를 비교한다. 첫 번째가 이전 단계, 두 번째가 다음 단계다.

의도한 변화: {change}

아래 JSON 만 출력한다(설명 금지).
{{
  "same_people": true/false,        // 같은 두 사람인가(얼굴·체형·옷)
  "same_world": true/false,         // 같은 테이블·같은 공간·같은 카메라 각도인가
  "same_style": true/false,         // 같은 조명·재질·화풍인가
  "intended_change_visible": true/false,  // 의도한 변화가 실제로 보이는가
  "observed_change": "<두 번째 이미지에서 실제로 달라진 것 한 문장>",
  "unintended_changes": ["<의도하지 않았는데 달라진 것>"],
  "text_burned_in": true/false,     // 그림 안에 글자·숫자·라벨이 그려졌는가
  "identity_score": 0-5             // 같은 개체로 보이는 정도(5=완전 동일)
}}"""


def judge(prev_path: str, next_path: str, change: str, model: str) -> dict[str, Any]:
    """멀티모달 판정(작업계획서 D2). 모델의 자기보고가 아니라 **결과 프레임**을 본다."""
    parts: list[dict[str, Any]] = []
    for p in (prev_path, next_path):
        with open(p, "rb") as f:
            parts.append({"inlineData": {"mimeType": "image/png",
                                         "data": base64.b64encode(f.read()).decode()}})
    parts.append({"text": _JUDGE_PROMPT.format(change=change)})
    data = _post(model, {"contents": [{"parts": parts}],
                         "generationConfig": {"responseMimeType": "application/json"}})
    for cand in (data.get("candidates") or []):
        for part in ((cand.get("content") or {}).get("parts") or []):
            if part.get("text"):
                try:
                    return json.loads(part["text"])
                except json.JSONDecodeError:
                    return {"parse_error": part["text"][:200]}
    return {"parse_error": "no text part"}


def size_of(path: str) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None


def main(argv: list[str]) -> int:
    out_dir = argv[0] if argv else "probe_out"
    want_video = "--no-video" not in argv
    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)

    img_model = config.image_model_for("MECHANISM")
    judge_model = os.getenv("PROBE_JUDGE_MODEL", "gemini-2.5-flash")
    report: dict[str, Any] = {"image_model": img_model, "judge_model": judge_model,
                              "stages": [], "cost_usd": 0.0}

    # ── Stage 0: canonical frame (텍스트만). 이후 stage 는 전부 이것에서 파생된다.
    base = os.path.join(out_dir, "S0.png")
    cost = gen_image(f"{WORLD}, {BASE_SCENE}, {config.BURN_IN_NEGATIVE_PROMPT}",
                     base, img_model)
    report["cost_usd"] += cost
    report["stages"].append({"id": "S0", "path": base, "size": size_of(base),
                             "cost_usd": round(cost, 4)})
    log.info("S0 canonical frame: %s %s", base, size_of(base))

    prev = base
    for st in STAGES:
        path = os.path.join(out_dir, f"{st['id']}.png")
        prompt = (f"{_REF_INSTRUCTION}{st['change']}. "
                  f"{WORLD}, {config.BURN_IN_NEGATIVE_PROMPT}")
        try:
            c = gen_image(prompt, path, img_model, ref_path=prev)
        except Exception as exc:  # noqa: BLE001 — 실패도 실측 결과다
            log.error("%s 생성 실패: %s", st["id"], exc)
            report["stages"].append({"id": st["id"], "error": str(exc)[:200]})
            break
        report["cost_usd"] += c
        v = judge(prev, path, st["change"], judge_model)
        report["stages"].append({
            "id": st["id"], "operation": st["operation"], "path": path,
            "size": size_of(path), "cost_usd": round(c, 4),
            "continuity_from": os.path.basename(prev), "judge": v,
        })
        log.info("%s [%s] identity=%s people=%s world=%s change_visible=%s text=%s",
                 st["id"], st["operation"], v.get("identity_score"),
                 v.get("same_people"), v.get("same_world"),
                 v.get("intended_change_visible"), v.get("text_burned_in"))
        prev = path

    # ── I2V: stage 전환을 영상으로 이을 수 있는가(있는 프로덕션 경로를 그대로 쓴다).
    if want_video and len(report["stages"]) >= 2:
        from engine.providers import video as video_provider
        clip = os.path.join(out_dir, "transition.mp4")
        cut = {"cut_no": 1, "visual_prompt": BASE_SCENE,
               "motion_prompt": "the left man slowly pushes three discs across the table",
               "motion_source": "video", "effects": []}
        try:
            _, vcost = video_provider.generate_clip(
                cut, {"version_type": "photo", "global_style": WORLD}, clip,
                duration=config.VEO_CLIP_SEC, start_image=base)
            report["cost_usd"] += vcost
            report["i2v"] = {"path": clip, "cost_usd": round(vcost, 4),
                             "bytes": os.path.getsize(clip)}
            log.info("I2V 전환 생성: %s ($%.3f)", clip, vcost)
        except Exception as exc:  # noqa: BLE001
            report["i2v"] = {"error": str(exc)[:200]}
            log.error("I2V 실패: %s", exc)

    report["cost_usd"] = round(report["cost_usd"], 4)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # ── GO/NO-GO (작업계획서 D4). 코드가 판정하고 근거를 남긴다.
    judged = [s for s in report["stages"] if s.get("judge")]
    ok_identity = [s for s in judged
                   if s["judge"].get("same_people") and s["judge"].get("same_world")
                   and int(s["judge"].get("identity_score") or 0) >= 4]
    ok_change = [s for s in judged if s["judge"].get("intended_change_visible")]
    burned = [s["id"] for s in judged if s["judge"].get("text_burned_in")]
    # ★ 비용 판정은 **이미지끼리** 비교한다(2026-08-29 1차 실행에서 틀렸던 지점).
    #   ① Veo 클립비를 stage 비용에 섞으면 안 된다 — I2V 는 지금도 쓰는 별개 항목이다.
    #   ② 기준은 flash 근사단가(GEMINI_IMAGE_COST_USD)가 아니라 **그 컷이 지금 쓰는 모델의
    #      단가**다. 도해 컷은 이미 gemini-3-pro-image 를 쓴다 — flash 와 비교하면
    #      "참조 조건 때문에 비싸졌다"가 아니라 "원래 비싼 모델"을 벌하는 것이 된다.
    img_cost = sum(float(s.get("cost_usd") or 0) for s in report["stages"])
    per_stage = img_cost / max(1, len(report["stages"]))
    baseline = float(config.PRICING.get(img_model, {}).get(
        "image_standard", config.GEMINI_IMAGE_COST_USD))
    budget = baseline * 2

    print("\n" + "=" * 62)
    print(f"stage 생성      : {len(report['stages'])}개 (S0 + 변이 {len(judged)})")
    print(f"identity 유지   : {len(ok_identity)}/{len(judged)}  (기준: 3연속)")
    print(f"의도 변화 관찰  : {len(ok_change)}/{len(judged)}")
    print(f"글자 번인       : {burned or '없음'}")
    print(f"stage 당 이미지 : ${per_stage:.4f}  (현행 {img_model} 단가 ${baseline:.4f} · 상한 ${budget:.4f})")
    print(f"이미지 합계     : ${img_cost:.4f}   I2V: ${float((report.get('i2v') or {}).get('cost_usd') or 0):.4f}")
    print(f"총 비용         : ${report['cost_usd']:.4f}")
    go = (len(ok_identity) >= 3 and len(ok_change) >= 3
          and not burned and per_stage <= budget)
    print(f"\n판정: {'GO' if go else 'NO-GO'}  — 근거는 report.json, 화면은 sheet.png")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
