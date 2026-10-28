"""주류 유료 생성 시험(단계별 결재). 2026-10-24. docs/deviation-drinks-paid-pilot.md

    python -m scripts.drinks_pilot order   docs/drinks-pilot/gi-sake-v1.json --stage 1 --out <폴더>    # 주문서(0원)
    python -m scripts.drinks_pilot buy     docs/drinks-pilot/gi-sake-v1.json --stage 1 --out <폴더> --approval <결재 id>
    python -m scripts.drinks_pilot preview docs/drinks-pilot/gi-sake-v1.json --stage 1 --out <폴더>    # 미리보기(0원)

규칙:
  · order 는 돈을 쓰지 않는다. 공급자에 실제로 갈 문장 전문과 금액을 주문서(order-stageN.md/json)로 남긴다.
  · buy 는 결재가 있어야 한다. 결재에 남긴 주문서 해시가 지금 주문서와 다르면 사지 않는다(보여드린 것과 다른 것을 사지 않게).
    상한·중복 구매·재시도 횟수는 DB(0054 drinks_hold_spend)가 막는다. 이미 산 것은 다시 쓴다(0원).
  · preview 는 산 그림을 다시 쓰고 조립·음성(무료)만 한다. 사지 않은 장면이 있으면 멈춘다.
  · DB 는 SUPABASE_URL·SUPABASE_SERVICE_KEY 가 가리키는 곳(0054 적용 필요). 파일은 <폴더>/storage 아래에 둔다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from engine import config
from engine.drinks_paid import OrderItem, PaidError, build_image_items, buy, clip_item, order_hash


def load_spec(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def stage_items(spec: dict[str, Any], stage: str) -> list[OrderItem]:
    st = spec["stages"][stage]
    scenes = spec["scenes"]
    if st.get("images"):
        return build_image_items(scenes, st["images"])
    items = []
    for c in st.get("clips") or []:
        pos = int(c["scene"])
        start = build_image_items(scenes, _with_refs(scenes, pos))[-1]
        sc = scenes[pos - 1]
        if not (sc.get("motion_prompt") or "").strip():
            raise PaidError("motion_prompt_missing", f"{pos}번 장면에 움직임 지시문이 없습니다")
        items.append(clip_item(pos, sc.get("visual_role") or "reality", sc["motion_prompt"], start.item_key, start.prompt_hash,
                               clip_sec=int(c.get("sec") or config.DRINKS_PILOT_CLIP_SEC)))
    return items


def _with_refs(scenes: list[dict[str, Any]], pos: int) -> list[int]:
    """이 장면 그림과, 이어 그리기로 그 앞에 필요한 장면들."""
    need = [pos]
    cont = (scenes[pos - 1].get("continuity") or "").strip()
    while cont.startswith("ref:"):
        pos = int(cont[4:])
        need.insert(0, pos)
        cont = (scenes[pos - 1].get("continuity") or "").strip()
    return need


def script_gate(spec: dict[str, Any]) -> Any:
    """대본·화면 계획 코드 검사(0원). 막힘이 하나라도 있으면 주문서도 만들지 않고 사지도 않는다."""
    from engine import drinks_script_check as sc

    rep = sc.check(spec)
    print("대본 검사: " + sc.summary_ko(rep))
    if not rep.ok:
        raise PaidError("script_check_failed", "대본 검사에서 막힌 문장이 있습니다 — 고친 뒤 다시 주문하세요: " + ", ".join(rep.codes()))
    return rep


def write_order(spec: dict[str, Any], stage: str, out: str) -> dict[str, Any]:
    rep = script_gate(spec)
    items = stage_items(spec, stage)
    total = round(sum(i.est_usd for i in items), 4)
    h = order_hash(items)
    cap = float(spec["stages"][stage]["cap_usd"])
    if total > cap:
        raise PaidError("over_cap", f"예상 ${total:.3f} 가 이 단계 결재 상한 ${cap:.2f} 를 넘습니다")
    data = {"pilot_id": spec["pilot_id"], "stage": stage, "what": spec["stages"][stage]["what"], "order_hash": h,
            "total_usd": total, "cap_usd": cap,
            "items": [{"item_key": i.item_key, "scene": i.position, "role": i.role, "kind": i.kind, "model": i.model,
                       "est_usd": i.est_usd, "ref_item": i.ref_item, "clip_sec": i.clip_sec or None, "prompt": i.prompt,
                       "prompt_hash": i.prompt_hash} for i in items]}
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, f"order-stage{stage}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    scenes = spec["scenes"]
    lines = [f"# 주문서 — {spec['topic']['title']} · {stage}단계", "",
             f"- 무엇을: {data['what']}", f"- 예상 금액: **${total:.3f}** · 결재 상한 ${cap:.2f}(실패 재시도 여유 포함 — 넘는 주문은 DB 가 거절)",
             "- 화풍: 운영자가 2026-09-08 확정한 무광 CG(실사형 장면도 사진이 아니라 같은 질감의 3D 연출이다). 그림에 글자는 넣지 않는다",
             f"- 주문서 해시: `{h}` (결재에 남기고, 살 때 다시 대조한다)",
             f"- 출처: {spec['source']['publisher']} 「{spec['source']['title']}」 {spec['source']['url']}",
             f"- 대본 검사(코드): 통과 · 알림 {len(rep.warns)}건" + "".join(f"\n  - {w.code}: {w.message}" for w in rep.warns), ""]
    for i in items:
        sc = scenes[i.position - 1]
        what = "그림" if i.kind == "image" else f"{i.clip_sec}초 움직이는 장면"
        lines += [f"## {i.position}번 장면 — {what} · {i.model} · ${i.est_usd:.3f}", "",
                  f"- 나레이션: {sc['narration']}", f"- 화면(우리 말): {sc.get('explanation') or ''}",
                  f"- 화면 역할: {'3D 도해' if i.role == 'mechanism' else '실사형 연출 장면'}" +
                  (f" · {i.ref_item} 그림을 이어 그림(같은 세계)" if i.ref_item and i.kind == "image" else "") +
                  (f" · 시작 그림 {i.ref_item}" if i.kind == "video" else ""),
                  f"- 화면에 얹는 표기: {'설명용 도해 · 실제 공정을 단순화함' if i.role == 'mechanism' else '연출 장면 · 실제 제품·시설 촬영 아님'}",
                  "- 공급자에 실제로 보내는 문장 전문:", "", "```", i.prompt, "```", ""]
    with open(os.path.join(out, f"order-stage{stage}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return data


def _rpc():
    from engine.drinks_collect import supabase_rpc

    return supabase_rpc()


def _storage(out: str):
    from engine.drinks_produce import Storage

    return Storage("local", os.path.join(out, "storage"))


def do_buy(spec: dict[str, Any], stage: str, out: str, approval_id: str) -> dict[str, Any]:
    script_gate(spec)   # 결재 뒤에 대본이 바뀌어 검사를 못 넘으면 사지 않는다
    items = stage_items(spec, stage)
    rpc, storage = _rpc(), _storage(out)
    ap = rpc("drinks_spend_state", {"approval_id": approval_id})
    if ap.get("order_hash") != order_hash(items):
        raise PaidError("order_mismatch", "결재에 남긴 주문서와 지금 주문서가 다릅니다 — 새 주문서로 다시 결재받으세요")
    bought_dir = os.path.join(out, "bought")
    paths: dict[str, str] = {}
    result = []
    for it in items:
        ref = paths.get(it.ref_item) if it.ref_item else None
        if it.ref_item and not ref:
            ref = _from_cache(rpc, storage, it.ref_item, spec, out)
        b = buy(it, rpc=rpc, storage=storage, approval_id=approval_id, out_dir=bought_dir, ref_path=ref)
        paths[it.item_key] = b.path
        result.append({"item_key": it.item_key, "cost_usd": b.cost_usd, "reused": b.reused, "path": b.path,
                       "width": b.width, "height": b.height})
        print(f"  {it.item_key}: {'재사용 0원' if b.reused else f'${b.cost_usd:.3f}'} → {b.path}")
    state = rpc("drinks_spend_state", {"approval_id": approval_id})
    data = {"stage": stage, "items": result, "approval": state}
    with open(os.path.join(out, f"bought-stage{stage}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def _from_cache(rpc, storage, item_key: str, spec: dict[str, Any], out: str) -> str:
    """앞 단계에서 산 그림을 재사용 목록에서 꺼낸다(다시 사지 않는다). 없으면 멈춘다."""
    pos = int(item_key.split("-")[1])
    want = build_image_items(spec["scenes"], _with_refs(spec["scenes"], pos))[-1]
    hit = rpc("drinks_find_generated", {"prompt_hashes": [want.prompt_hash]}) or []
    if not hit:
        raise PaidError("not_bought", f"{item_key} 그림을 아직 사지 않았습니다 — 앞 단계부터 진행하세요")
    dest = os.path.join(out, "bought", f"{want.item_key}.png")
    storage.get(hit[0]["storage_key"], dest)
    return dest


def do_preview(spec: dict[str, Any], stage: str, out: str) -> str:
    from engine.drinks_render import render_video

    rpc, storage = _rpc(), _storage(out)
    if stage == "1":
        positions = spec["stages"]["1"]["images"]
        scenes = [dict(spec["scenes"][p - 1]) for p in positions]
        images = {}
        for n, p in enumerate(positions, 1):
            images[n] = _from_cache(rpc, storage, f"scene-{p:02d}-x", spec, out)
        work = tempfile.mkdtemp(prefix="drinks_pilot_")
        try:
            r = render_video({"plan": {"scenes": scenes}, "topic": spec["topic"]}, work, tts="edge", images=images)
            dest = os.path.join(out, "preview-stage1.mp4")
            shutil.copyfile(r.files[0]["path"], dest)
            for n in images:
                shutil.copyfile(os.path.join(work, "cards", f"{n:03d}.png"), os.path.join(out, f"preview-stage1-scene{positions[n - 1]}.png"))
            with open(os.path.join(out, "preview-stage1-qa.json"), "w", encoding="utf-8") as f:
                json.dump(r.qa, f, ensure_ascii=False, indent=2)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return dest
    # 2단계: 같은 그림을 무료 카메라 효과(천천히 확대)로 움직인 것 | 산 움직이는 장면 — 나란히
    item = stage_items(spec, "2")[0]
    hit = rpc("drinks_find_generated", {"prompt_hashes": [item.prompt_hash]}) or []
    if not hit:
        raise PaidError("not_bought", "2단계 움직이는 장면을 아직 사지 않았습니다")
    clip = os.path.join(out, "bought", f"{item.item_key}.mp4")
    storage.get(hit[0]["storage_key"], clip)
    still = _from_cache(rpc, storage, item.ref_item, spec, out)
    from engine.assemble import effect_filter

    zoom = os.path.join(out, "compare-stage2-still.mp4")
    subprocess.run(["ffmpeg", "-y", "-loop", "1", "-t", str(item.clip_sec), "-i", still, "-vf",
                    effect_filter(["ken_burns_zoom_in"], item.clip_sec), "-r", str(config.RENDER_FPS), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", zoom], check=True, capture_output=True)
    dest = os.path.join(out, "compare-stage2.mp4")
    subprocess.run(["ffmpeg", "-y", "-i", zoom, "-i", clip, "-filter_complex",
                    "[0:v]scale=-2:960,setsar=1[a];[1:v]scale=-2:960,setsar=1[b];[a][b]hstack=inputs=2", "-an",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", dest], check=True, capture_output=True)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="주류 유료 생성 시험(단계별 결재)")
    ap.add_argument("cmd", choices=["order", "buy", "preview"])
    ap.add_argument("spec")
    ap.add_argument("--stage", required=True, choices=["1", "2"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--approval")
    a = ap.parse_args(argv)
    spec = load_spec(a.spec)
    try:
        if a.cmd == "order":
            d = write_order(spec, a.stage, a.out)
            print(f"주문서: {os.path.join(a.out, f'order-stage{a.stage}.md')} · 예상 ${d['total_usd']:.3f} · 해시 {d['order_hash']}")
        elif a.cmd == "buy":
            if not a.approval:
                print("결재 id(--approval)가 없습니다 — 사지 않았습니다", file=sys.stderr)
                return 2
            d = do_buy(spec, a.stage, a.out, a.approval)
            st = d["approval"]
            print(f"확정 지출 ${float(st['spent_usd']):.3f} · 남은 결재 금액 ${float(st['remaining_usd']):.3f}")
        else:
            print("미리보기:", do_preview(spec, a.stage, a.out))
    except PaidError as exc:
        print(f"멈춤 — {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
