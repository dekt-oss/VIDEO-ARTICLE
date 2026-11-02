"""설명형 제작 큐 0원 리허설 — 진짜 SQL 함수(PGlite) + 진짜 워커 + **가짜 공급자**. 돈·네트워크·공급자 호출 0.

    python -m scripts.explainer_queue_rehearsal

한 편을 [지시서 → 결재 → 구매 → 후보 검수·선택 → 조립 → 자동 검사 → 사람 검수 → 게시 대기]까지 큐에서 돌리고, 멈춰야 하는 경우를 일부러 만든다:
클립 삭제·손상·짧음, 결재 상한 초과, 결과 불명(unknown_billed), 후보 전부 불합격, 실호출 스위치 꺼짐, 옛 렌더 요청.

★ 화면은 ffmpeg testsrc2, 말은 시험음이다. 술에 관한 사실을 말하지 않는다. 통과해도 "돌아간다"일 뿐이다.
★ DB 는 메모리 PGlite 다(web/scripts/pglite-rpc-stdio.mjs). 운영 DB 에 닿지 않는다. web 에서 npm ci 가 돼 있어야 한다.
산출물: docs/preview-<날짜>/explainer-queue/ (gitignore)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from engine import config
from engine import drinks_explainer as dx
from engine import drinks_explainer_queue as q
from engine import drinks_paid as dpaid
from engine import drinks_produce as dp
from engine.drinks_collect import _DB_CODE, DbError
from engine.util import today_local
from scripts import explainer_rehearsal as base

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BODY = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking in order to further enhance the taste."
QUOTE = "Whisky enthusiasts often also add a few drops of water to the spirit before drinking"
SCORES = {"relevance": 4, "utility": 4, "curiosity": 3, "fit_video": 3, "fit_carousel": 4, "timeliness": 2}
PROCESS_CHECKS = {"directive_matches_clips": True, "selection_reasons_ok": True, "cost_matches_approval": True}
QUALITY_CHECKS = {"stops_in_first_1_5s": True, "no_photo_like_scene": True, "match_boundaries_connect": True, "mechanism_explains_why": True, "no_fake_text": True, "loop_natural": True}
OUTPUT_CHECKS = {"scene_types_labeled": True, "no_real_product_implied": True, "claims_match_evidence": True, "audio_subtitles_ok": True, "vertical_ok": True}

# (역할, TTS ms, 이어짐) — 기획 v2 §3-6-2 표와 같은 길이. 합계 57.6초(꼬리 포함) → 최종 48초.
SCENE_PLAN: tuple[tuple[str, int, Optional[str]], ...] = (
    ("reality", 3600, None), ("mechanism", 7500, None), ("mechanism", 7500, None), ("reality", 5400, None), ("reality", 5400, "ref:4"),
    ("reality", 6600, "ref:5"), ("mechanism", 7500, None), ("reality", 7500, None), ("reality", 6000, "ref:8"),
)


class PgRpc:
    """메모리 PGlite 에 줄 단위로 묻는다. 소켓을 쓰지 않는다 — 그래서 시험에서 네트워크를 통째로 막을 수 있다."""

    def __init__(self) -> None:
        env = dict(os.environ)
        self.proc = subprocess.Popen(["node", str(WEB / "scripts" / "pglite-rpc-stdio.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     encoding="utf-8", cwd=str(WEB), env=env)
        self.n = 0
        line = self.proc.stdout.readline()
        if not line or not json.loads(line).get("ready"):
            raise RuntimeError(f"PGlite 시작 실패: {self.proc.stderr.read()[-800:] if self.proc.poll() is not None else line}")

    def _ask(self, req: dict[str, Any]) -> Any:
        self.n += 1
        self.proc.stdin.write(json.dumps({"id": self.n, **req}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        res = json.loads(self.proc.stdout.readline())
        if res.get("error"):
            m = _DB_CODE.search(res["error"])
            if m:
                raise DbError(m.group(1), res["error"])
            raise RuntimeError(res["error"])
        return res["data"]

    def __call__(self, fn: str, p: dict[str, Any]) -> Any:
        return self._ask({"fn": fn, "p": p})

    def sql(self, query: str, params: Optional[list[Any]] = None) -> list[dict[str, Any]]:
        return self._ask({"sql": query, "params": params or []})

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=20)


ORDINALS = ("첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째")


def _scenes() -> list[dict[str, Any]]:
    out = []
    for i, (role, _ms, cont) in enumerate(SCENE_PLAN, 1):
        out.append({"narration": f"리허설 {ORDINALS[i - 1]} 자리 표시 문장이에요." if i != 2 else "애호가들은 물을 몇 방울 넣어요.", "visual_role": role,
                    **({"mechanism": {"subject": "rehearsal subject", "components": ["part a", "part b"], "relationship": "part a meets part b", "transformation": "part a changes part b", "initial_state": "apart", "final_state": "joined"}} if role == "mechanism" else {}),
                    "content_kind": "fact" if i == 2 else "transition", "claim_ids": ["c1"] if i == 2 else [], "timing_sec": _ms / 1000.0,
                    "visual_prompt": f"Rehearsal placeholder scene {i}, part a and part b, a plain glass on a table", "motion_prompt": f"Rehearsal placeholder motion {i}, the camera slowly pushes in",
                    **({"continuity": cont} if cont else {})})
    return out


def visual_claims(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = config.DRINKS_EXPLAINER_DEPICTION_LABELS
    return [{"scene": i, "claim_ids": sc["claim_ids"], "visual_claim_ko": "화면이 나레이션을 보여 준다" if sc["claim_ids"] else f"{config.DRINKS_EXPLAINER_MOOD_PREFIX}: 리허설",
             "allowed_simplification": "없음", "forbidden_misreading": "실제 제품 촬영으로 오해", "depiction_label": labels[sc["visual_role"]]} for i, sc in enumerate(scenes, 1)]


def seed_plan(db: PgRpc, *, question: str = "왜 안 상할까요?", scenes: Optional[list[dict[str, Any]]] = None, claims_table: Any = "auto", explainer: bool = True) -> str:
    """승인된 설명형 제작안 한 건. 대본은 개발 요청 결과로 저장돼 시각 주장표가 함께 남는다(운영 경로와 같다).
    형식 의도는 승인 뒤에 표에 직접 넣는다 — [이걸로]→[승인] 경로 자체는 web/lib/drinks/singleApproval.db.test.ts 가 본다."""
    scenes = scenes if scenes is not None else _scenes()
    qtext = f"{question} {uuid.uuid4().hex[:4]}" if len(question) < 12 else question
    topic = db("drinks_create_topic", {"title": "리허설 소재", "question": qtext, "categories": ["whisky"], "lane": "evergreen"})["topic_id"]

    def ver() -> int:
        return db.sql("select version from drink_topics where id = $1", [topic])[0]["version"]

    def review(rid: str) -> dict[str, Any]:
        return db.sql("select * from drink_topic_reviews where id = $1", [rid])[0]

    db("drinks_triage", {"topic_id": topic, "expected_version": ver(), "scores": SCORES})
    db("drinks_topic_action", {"topic_id": topic, "expected_version": ver(), "action": "start_research"})
    url = f"https://example.org/{uuid.uuid4().hex}"
    snap = db("drinks_add_source", {"topic_id": topic, "source": {"url_raw": url, "canonical_url": url, "body_text": BODY, "rights_status": "quote_ok"}})
    brief = {"audience_question": "왜", "core_takeaway": "리허설", "selected_claim_ids": ["c1"], "proposed_formats": ["video"], "required_claims": {"video": ["c1"]}}
    pack = {"claims": [{"claim_id": "c1", "text": "애호가들은 마시기 전에 물을 몇 방울 넣는다", "claim_type": "process", "support_review": "supported",
                        "source_refs": [{"snapshot_id": snap["snapshot_id"], "original_quote": QUOTE}]}]}
    rid = db("drinks_save_review", {"topic_id": topic, "expected_topic_version": ver(), "scores": SCORES, "brief": brief, "evidence_pack": pack})["review_id"]
    r = review(rid)
    db("drinks_review_action", {"review_id": r["id"], "expected_version": r["version"], "action": "submit"})
    r = review(rid)
    db("drinks_review_action", {"review_id": r["id"], "expected_version": r["version"], "action": "approve"})
    r = review(rid)
    db("drinks_select", {"topic_id": topic, "expected_version": ver(), "review_id": r["id"], "review_input_hash": r["approved_hash"], "formats": ["video"], "editorial_week": "2026-11-02"})
    budget = db("drinks_open_develop_budget", {"cap_usd": 1, "stage": "리허설", "purpose": "리허설", "approver_words": "(리허설) 가짜 결재"})["budget_id"]
    db("drinks_request_develop", {"topic_id": topic, "kind": "plan", "budget_id": budget})
    g = db("drinks_start_develop", {"worker_id": "rehearsal"})
    lease = {"request_id": g["job"]["request_id"], "lease_token": g["job"]["lease_token"]}
    plan_id = db("drinks_develop_save_plan", {**lease, "plan_json": {"scenes": scenes}})["revision_id"]
    table = visual_claims(scenes) if claims_table == "auto" else claims_table
    db("drinks_finish_develop", {**lease, "outcome": "succeeded", "result": {"visual_claims": table} if table else {}})
    pl = db.sql("select version from drink_plan_revisions where id = $1", [plan_id])[0]
    db("drinks_plan_action", {"revision_id": plan_id, "expected_version": pl["version"], "action": "submit"})
    pl = db.sql("select version from drink_plan_revisions where id = $1", [plan_id])[0]
    db("drinks_plan_action", {"revision_id": plan_id, "expected_version": pl["version"], "action": "approve"})
    if explainer:
        db.sql("insert into drink_topic_picks (topic_id, format_intent, editorial_week) values ($1, 'explainer', '2026-11-02')", [topic])
    return plan_id


def fake_tts(scenes: Optional[list[dict[str, Any]]] = None, *, extra_ms: int = 0) -> Any:
    table = {sc["narration"]: SCENE_PLAN[i][1] for i, sc in enumerate(scenes or _scenes())}

    def tts(text: str, path: str) -> None:
        base.make_tone(path, table.get(text, 4000) + extra_ms)
    return tts


class FakeAdapter:
    """가짜 공급자. 실제 호출 없이 어댑터 계약(§3-2 출력)을 흉내 낸다. behaviors = {후보 id 또는 '*': 'short'·'corrupt'·'unknown'·'unbilled'}."""

    live = False
    provider = "omni"

    def __init__(self, clip_dir: Path, behaviors: Optional[dict[str, str]] = None):
        self.clip_dir = clip_dir
        self.behaviors = behaviors or {}
        self.keys: list[str] = []
        self.calls: list[str] = []
        self.images: list[tuple[str, Optional[str]]] = []
        clip_dir.mkdir(parents=True, exist_ok=True)

    def check_ready(self, approval: Optional[dict[str, Any]]) -> None:
        return None

    def image(self, item: dpaid.OrderItem, out: str, ref_path: Optional[str]) -> float:
        from PIL import Image

        Image.new("RGB", (768, 1344), (40, 50, 60)).save(out)
        self.images.append((item.item_key, ref_path))
        return item.est_usd

    def _clip_file(self, ms: int) -> Path:
        p = self.clip_dir / f"fake_{ms}.mp4"
        if not p.exists():
            base.make_fake_clip(str(p), ms)
        return p

    def clip(self, item: dpaid.OrderItem, out: str, start_image: str, *, approval_id: str, idempotency_key: str) -> Any:
        from engine.providers import video as vp

        assert os.path.isfile(start_image) and approval_id
        self.keys.append(idempotency_key)
        self.calls.append(item.candidate_id or item.item_key)
        how = self.behaviors.get(item.candidate_id or "", self.behaviors.get("*", ""))
        if how == "unknown":
            raise vp.ExplainerOutcomeUnknown("시험: 응답을 받지 못했습니다")
        if how == "unbilled":
            raise vp.ExplainerNotSent("시험: 429")
        if how == "corrupt":
            raise vp.ExplainerBilledBadFile("시험: 깨진 파일")
        ms = item.clip_sec * 1000 - (1500 if how == "short" else 0)
        shutil.copyfile(self._clip_file(ms), out)
        return SimpleNamespace(path=out, request_id=f"fake-{idempotency_key[:8]}", billing_unit="tokens", billed_units=5792.0 * item.clip_sec)


class Wire:
    """실제 공급자·네트워크 경로에 거는 줄. 닿으면 세고 예외를 던진다. '0회'를 숫자로 남긴다."""

    def __init__(self, *, render_phase: bool = False):
        self.hits: list[str] = []
        self.render_phase = render_phase
        self._saved: list[tuple[Any, str, Any]] = []

    def _wire(self, obj: Any, name: str, label: str) -> None:
        self._saved.append((obj, name, getattr(obj, name)))

        def tripped(*_a: Any, **_k: Any) -> Any:
            self.hits.append(label)
            raise RuntimeError(f"줄에 걸렸습니다: {label}")
        setattr(obj, name, tripped)

    def __enter__(self) -> "Wire":
        from engine.providers import image, video

        for obj, name, label in ((video, "generate_explainer_clip", "video.generate_explainer_clip"), (video, "send_explainer_request", "video.send_explainer_request"),
                                 (video, "generate_clip", "video.generate_clip"), (video, "_veo_i2v", "video._veo_i2v"), (image, "generate_image", "image.generate_image"),
                                 (socket.socket, "connect", "socket.connect"), (socket, "create_connection", "socket.create_connection")):
            self._wire(obj, name, label)
        if self.render_phase:
            self._wire(dpaid, "buy", "drinks_paid.buy")
            self._wire(dpaid, "buy_clip_attempt", "drinks_paid.buy_clip_attempt")
        return self

    def __exit__(self, *_exc: Any) -> None:
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)


def run_one(db: PgRpc, storage: dp.Storage, deps: Optional[q.Deps]) -> dict[str, Any]:
    res = dp.run_queue(db, storage, worker_id="rehearsal", tts="placeholder", max_jobs=1, explainer_deps=deps)
    assert res, "큐에 작업이 없습니다"
    return res[0]


def status(db: PgRpc, plan_id: str) -> dict[str, Any]:
    return db("drinks_explainer_status", {"plan_revision_id": plan_id})


def state_of(db: PgRpc, plan_id: str) -> Optional[str]:
    return (status(db, plan_id).get("episode") or {}).get("state")


def open_approval(db: PgRpc, plan_id: str, cap: float, kinds: tuple[str, ...] = ("image", "video")) -> str:
    ep = status(db, plan_id)["episode"]
    return db("drinks_open_spend_approval", {"plan_revision_id": plan_id, "stage": "리허설", "purpose": "리허설 — 가짜 공급자", "cap_usd": cap, "allowed_kinds": list(kinds),
                                             "approved_by": "operator", "approver_words": "(리허설) 가짜 결재", "order_hash": ep["order_hash"]})["approval_id"]


def judge_and_select(db: PgRpc, plan_id: str) -> int:
    """사람 차례 시늉: 자동 합격 후보를 사람 합격으로 올리고 고른다. 고른 슬롯 수."""
    n = 0
    for s in status(db, plan_id)["slots"]:
        if s["status"] in ("selected", "no_pass"):
            continue
        cands = s["candidates"]
        if len(cands) < s["candidates_planned"] or any(c["status"] != "stored" or not c["auto_verdict"] for c in cands):
            continue
        for c in cands:
            if c["auto_verdict"] == "pass" and not c["human_verdict"]:
                db("drinks_explainer_verdict", {"candidate_id": c["candidate_id"], "human_verdict": "pass"})
        db("drinks_explainer_select", {"slot_id": s["slot_id"], "candidate_id": cands[0]["candidate_id"], "selected_by": "리허설 운영자", "reason": "리허설 — 첫 후보"})
        n += 1
    return n


def buy_all(db: PgRpc, storage: dp.Storage, plan_id: str, approval: str, deps: q.Deps) -> list[dict[str, Any]]:
    """구매 → 사람 선택 → 이어서 구매를 슬롯이 다 찰 때까지 돌린다."""
    log: list[dict[str, Any]] = []
    for _ in range(len(SCENE_PLAN) + 3):
        if state_of(db, plan_id) == "assets_complete":
            break
        db("drinks_explainer_request_buy", {"plan_revision_id": plan_id, "spend_approval_id": approval})
        res = run_one(db, storage, deps)
        log.append({"job": res.get("status"), "stop": (res.get("result") or {}).get("status_code"), "selected_now": judge_and_select(db, plan_id)})
    return log


def stored_key(db: PgRpc, plan_id: str, n: int) -> tuple[str, str]:
    row = db("drinks_explainer_selected_asset", {"slot_id": dx.slot_id(plan_id, n)})
    return row["storage_key"], row["sha256"]


def _local(storage: dp.Storage, key: str) -> Path:
    return Path(storage.root) / key[len("local:"):].replace("/", os.sep)


def assemble_expect_stop(db: PgRpc, storage: dp.Storage, plan_id: str, deps: q.Deps) -> dict[str, Any]:
    before = len(db.sql("select 1 from drink_asset_manifests where plan_revision_id = $1", [plan_id]))
    holds = db.sql("select count(*)::int n from drink_spend_holds")[0]["n"]
    db("drinks_explainer_request_assemble", {"plan_revision_id": plan_id})
    with Wire(render_phase=True) as wire:
        res = run_one(db, storage, deps)
    job = db.sql("select status, error_code from drink_production_jobs where id = $1", [res["job_id"]])[0]
    return {"job": job["status"], "code": job["error_code"], "state": state_of(db, plan_id), "paid_or_network_hits": wire.hits,
            "new_holds": db.sql("select count(*)::int n from drink_spend_holds")[0]["n"] - holds, "new_manifests": len(db.sql("select 1 from drink_asset_manifests where plan_revision_id = $1", [plan_id])) - before}


def run_full_episode(db: PgRpc, out_root: Path) -> dict[str, Any]:
    """한 편을 큐에서 끝까지. 도중에 렌더 강제 멈춤 셋(삭제·손상·짧음)을 같은 편으로 시험한다 — 다시 사지 않고 파일만 되돌린다."""
    storage = dp.Storage("local", str(out_root / "storage"))
    adapter = FakeAdapter(out_root / "fake-clips")
    tts = fake_tts()
    deps = q.Deps(adapter=adapter, tts_fn=tts)
    plan = seed_plan(db)
    trail = [state_of(db, plan)]
    db("drinks_explainer_request_plan", {"plan_revision_id": plan})
    with Wire() as wire_plan:
        run_one(db, storage, deps)
    st = status(db, plan)
    directive = st["episode"]["directive"]
    trail.append(st["episode"]["state"])
    approval = open_approval(db, plan, directive["estimate"]["suggested_cap_usd"])
    with Wire() as wire_buy:
        rounds = buy_all(db, storage, plan, approval, deps)
    st = status(db, plan)
    trail.append(st["episode"]["state"])

    forced: list[dict[str, Any]] = []
    # ① 클립 삭제
    key, _sha = stored_key(db, plan, 3)
    path = _local(storage, key)
    keep = path.read_bytes()
    path.unlink()
    forced.append({"case": "클립 삭제", "expected": "clip_missing", **assemble_expect_stop(db, storage, plan, deps)})
    path.write_bytes(keep)
    # ② 끝을 잘라 손상
    path.write_bytes(keep[: len(keep) // 2])
    forced.append({"case": "파일 끝을 잘라 손상", "expected": "clip_corrupt", **assemble_expect_stop(db, storage, plan, deps)})
    path.write_bytes(keep)
    # ③ 나레이션이 길어져 클립이 모자람(§3-6 "TTS 가 바뀌면") — 해시도 멀쩡하다. 실측만이 잡는다.
    long_deps = q.Deps(adapter=adapter, tts_fn=fake_tts(extra_ms=900))
    forced.append({"case": "나레이션이 0.9초 길어져 클립이 짧음", "expected": "clip_short", **assemble_expect_stop(db, storage, plan, long_deps)})

    # 정상 조립
    db("drinks_explainer_request_assemble", {"plan_revision_id": plan})
    with Wire(render_phase=True) as wire_render:
        rendered = run_one(db, storage, deps)
    st = status(db, plan)
    trail.append(st["episode"]["state"])
    job = db.sql("select id, status, error_code, error_message, result_manifest_id from drink_production_jobs where id = $1", [rendered["job_id"]])[0]
    if job["status"] != "succeeded":
        raise RuntimeError(f"조립 실패: {job['error_code']}: {job['error_message']}")
    review = db.sql("select * from drink_output_reviews where manifest_id = $1", [job["result_manifest_id"]])[0]
    # 품질 검수 전에는 파일을 승인할 수 없다
    early_code = ""
    try:
        db("drinks_output_review_action", {"review_id": review["id"], "expected_version": review["version"], "action": "approve", "checklist": OUTPUT_CHECKS})
    except DbError as exc:
        early_code = exc.code
    db("drinks_explainer_review", {"plan_revision_id": plan, "stage": "process", "outcome": "pass", "checks": PROCESS_CHECKS})
    trail.append(state_of(db, plan))
    db("drinks_explainer_review", {"plan_revision_id": plan, "stage": "quality", "outcome": "pass", "checks": QUALITY_CHECKS})
    trail.append(state_of(db, plan))
    review = db.sql("select * from drink_output_reviews where manifest_id = $1", [job["result_manifest_id"]])[0]
    db("drinks_output_review_action", {"review_id": review["id"], "expected_version": review["version"], "action": "approve", "checklist": OUTPUT_CHECKS})
    trail.append(state_of(db, plan))
    files = db.sql("select m.storage_key, ma.role, m.duration_ms from drink_manifest_assets ma join drink_media_assets m on m.id = ma.asset_id where ma.manifest_id = $1", [job["result_manifest_id"]])
    final = next(f for f in files if f["role"] == "final_video")
    shutil.copyfile(_local(storage, final["storage_key"]), out_root / "final.mp4")
    st = status(db, plan)
    spent = db.sql("select coalesce(sum(actual_usd), 0)::float8 usd from drink_spend_holds where approval_id = $1", [approval])[0]["usd"]
    qa = review["qa_summary"]
    return {"plan_id": plan, "states": trail, "final_state": st["episode"]["state"], "directive_estimate": directive["estimate"], "slots": len(directive["slots"]), "edit_cuts": directive["edit_cuts"],
            "final_ms_planned": directive["final_ms"], "rounds": rounds, "forced_render_stops": forced, "early_output_approve": early_code,
            "auto_qa": qa["auto_qa"], "continuity": qa["continuity"], "video_fallbacks": qa["video_fallbacks"], "cuts_all_clip": all(c["kind"] == "clip" for c in qa["cuts"]),
            "provider_calls": len(adapter.calls), "duplicate_idempotency_keys": len(adapter.keys) - len(set(adapter.keys)), "fake_cost_usd": spent, "cap_usd": directive["estimate"]["suggested_cap_usd"],
            "paid_or_network_hits": wire_plan.hits + wire_buy.hits + wire_render.hits, "slot_costs": [{"n": s["n"], "image_usd": s["image_usd"], "clips_usd": sum(float(c["cost_usd"]) for c in s["candidates"])} for s in st["slots"]],
            "match_refs": [k for k, r in adapter.images if r], "final_duration_ms": final["duration_ms"]}


def plan_to_directive(db: PgRpc, storage: dp.Storage, deps: q.Deps, **seed: Any) -> str:
    plan = seed_plan(db, **seed)
    db("drinks_explainer_request_plan", {"plan_revision_id": plan})
    run_one(db, storage, deps)
    return plan


def case_budget(db: PgRpc, out_root: Path) -> dict[str, Any]:
    storage = dp.Storage("local", str(out_root / "storage"))
    adapter = FakeAdapter(out_root / "fake-clips")
    deps = q.Deps(adapter=adapter, tts_fn=fake_tts())
    plan = plan_to_directive(db, storage, deps)
    approval = open_approval(db, plan, 0.3)   # 첫 그림은 되고 첫 클립(4초 ≈ $0.41)에서 넘는다
    db("drinks_explainer_request_buy", {"plan_revision_id": plan, "spend_approval_id": approval})
    res = run_one(db, storage, deps)
    job = db.sql("select status, error_code from drink_production_jobs where id = $1", [res["job_id"]])[0]
    view = db("drinks_spend_state", {"approval_id": approval})
    return {"job": job["status"], "code": job["error_code"], "state": state_of(db, plan), "provider_calls": len(adapter.calls), "committed_usd": float(view["spent_usd"]) + float(view["held_usd"]), "cap_usd": 0.3,
            "attempts": db.sql("select count(*)::int n from drink_explainer_attempts a join drink_explainer_slots s on s.slot_id = a.slot_id where s.plan_revision_id = $1", [plan])[0]["n"]}


def case_unknown(db: PgRpc, out_root: Path) -> dict[str, Any]:
    storage = dp.Storage("local", str(out_root / "storage"))
    adapter = FakeAdapter(out_root / "fake-clips", {"*": "unknown"})
    deps = q.Deps(adapter=adapter, tts_fn=fake_tts())
    plan = plan_to_directive(db, storage, deps)
    approval = open_approval(db, plan, 5)
    db("drinks_explainer_request_buy", {"plan_revision_id": plan, "spend_approval_id": approval})
    res = run_one(db, storage, deps)
    job = db.sql("select status, error_code from drink_production_jobs where id = $1", [res["job_id"]])[0]
    st = status(db, plan)
    out: dict[str, Any] = {"job": job["status"], "code": job["error_code"], "state": st["episode"]["state"], "unknown": st["unknown_attempts"], "provider_calls": len(adapter.calls)}
    view = db("drinks_spend_state", {"approval_id": approval})
    out["held_while_unknown"] = float(view["held_usd"])
    try:
        db("drinks_explainer_request_buy", {"plan_revision_id": plan, "spend_approval_id": approval})
        out["rebuy_while_unknown"] = "통과"
    except DbError as exc:
        out["rebuy_while_unknown"] = exc.code
    db("drinks_explainer_close_unknown", {"attempt_id": st["unknown_attempts"][0], "resolution": "billed", "closed_by": "리허설 운영자", "note": "리허설 — 청구된 것으로", "actual_usd": 0.41})
    view = db("drinks_spend_state", {"approval_id": approval})
    out.update(state_after_close=state_of(db, plan), held_after_close=float(view["held_usd"]), spent_after_close=float(view["spent_usd"]))
    return out


def case_no_pass(db: PgRpc, out_root: Path) -> dict[str, Any]:
    storage = dp.Storage("local", str(out_root / "storage"))
    adapter = FakeAdapter(out_root / "fake-clips", {"*": "short"})
    deps = q.Deps(adapter=adapter, tts_fn=fake_tts())
    plan = plan_to_directive(db, storage, deps)
    approval = open_approval(db, plan, 5)
    db("drinks_explainer_request_buy", {"plan_revision_id": plan, "spend_approval_id": approval})
    res = run_one(db, storage, deps)
    job = db.sql("select status, error_code from drink_production_jobs where id = $1", [res["job_id"]])[0]
    st = status(db, plan)
    # 1번 슬롯은 짧아도 필요한 길이를 넘는다. 2번(훅, 후보 2)에서 둘 다 clip_short 로 떨어진다.
    bad = next(s for s in st["slots"] if s["status"] == "no_pass")
    c = bad["candidates"][0]
    return {"job": job["status"], "code": job["error_code"], "state": st["episode"]["state"], "slot": bad["n"], "slot_status": bad["status"], "auto_blocks": (c["auto_report"] or {}).get("blocks"),
            "provider_calls": len(adapter.calls), "duration_ms": c["asset"]["duration_ms"], "slots_after": len(st["slots"]) - bad["n"]}


def case_switch_off(db: PgRpc, out_root: Path) -> dict[str, Any]:
    """어댑터를 주지 않으면 실제 공급자 경로다. 스위치가 꺼져 있으면 가잡기도 시도 행도 만들지 않는다."""
    storage = dp.Storage("local", str(out_root / "storage"))
    deps_plan = q.Deps(adapter=FakeAdapter(out_root / "fake-clips"), tts_fn=fake_tts())
    plan = plan_to_directive(db, storage, deps_plan)
    approval = open_approval(db, plan, 5)
    db("drinks_explainer_request_buy", {"plan_revision_id": plan, "spend_approval_id": approval})
    prev = config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED
    config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED = False
    try:
        with Wire() as wire:
            res = run_one(db, storage, q.Deps(tts_fn=fake_tts()))
    finally:
        config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED = prev
    job = db.sql("select status, error_code from drink_production_jobs where id = $1", [res["job_id"]])[0]
    return {"job": job["status"], "code": job["error_code"], "state": state_of(db, plan), "provider_hits": wire.hits,
            "holds": db.sql("select count(*)::int n from drink_spend_holds where approval_id = $1", [approval])[0]["n"],
            "attempts": db.sql("select count(*)::int n from drink_explainer_attempts where approval_id = $1", [approval])[0]["n"]}


def case_old_render(db: PgRpc, out_root: Path) -> dict[str, Any]:
    plan = seed_plan(db)
    out: dict[str, Any] = {}
    for key, payload in (("local", {"plan_revision_id": plan}),):
        try:
            db("drinks_request_render", payload)
            out[key] = "통과"
        except DbError as exc:
            out[key] = exc.code
    out["jobs"] = db.sql("select count(*)::int n from drink_production_jobs where plan_revision_id = $1", [plan])[0]["n"]
    return out


def run(out_root: Path) -> dict[str, Any]:
    db = PgRpc()
    try:
        full = run_full_episode(db, out_root)
        report = {"full_episode": full, "budget": case_budget(db, out_root), "unknown_billed": case_unknown(db, out_root), "no_pass": case_no_pass(db, out_root),
                  "switch_off": case_switch_off(db, out_root), "old_render": case_old_render(db, out_root)}
    finally:
        db.close()
    f = report["full_episode"]
    checks = {
        "끝까지 게시 대기": f["final_state"] == "ready_to_publish",
        "자동 검사 통과": f["auto_qa"]["state"] == "auto_qa_pass",
        "사진 대체 0": f["video_fallbacks"] == [] and f["cuts_all_clip"],
        "렌더 멈춤 3종": all(c["code"] == c["expected"] and c["state"] == "blocked_assets" and c["new_holds"] == 0 and c["new_manifests"] == 0 and not c["paid_or_network_hits"] for c in f["forced_render_stops"]),
        "품질 검수 전 파일 승인 불가": f["early_output_approve"] == "review_blocked",
        "실제 공급자·네트워크 0회": not f["paid_or_network_hits"] and not report["switch_off"]["provider_hits"],
        "멱등키 중복 0": f["duplicate_idempotency_keys"] == 0,
        "상한 초과에서 멈춤": report["budget"]["code"] == "budget_exceeded" and report["budget"]["state"] == "blocked_budget" and report["budget"]["provider_calls"] == 0 and report["budget"]["committed_usd"] <= 0.3,
        "결과 불명에서 멈춤": report["unknown_billed"]["state"] == "unknown_billed" and report["unknown_billed"]["rebuy_while_unknown"] == "unknown_billed_open" and report["unknown_billed"]["provider_calls"] == 1,
        "후보 전부 불합격에서 멈춤": report["no_pass"]["state"] == "blocked_no_pass" and report["no_pass"]["provider_calls"] == 3 and report["no_pass"]["auto_blocks"] == ["clip_short"] and report["no_pass"]["slots_after"] == 0,
        "스위치 꺼짐에서 아무것도 안 함": report["switch_off"]["code"] == "provider_send_disabled" and report["switch_off"]["holds"] == 0 and report["switch_off"]["attempts"] == 0,
        "옛 렌더 차단": report["old_render"]["local"] == "not_renderable" and report["old_render"]["jobs"] == 0,
    }
    report["checks"] = checks
    report["passed"] = all(checks.values())
    return report


def main(argv: Optional[list[str]] = None) -> int:
    argparse.ArgumentParser(description="설명형 제작 큐 0원 리허설").parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    out_root = ROOT / "docs" / f"preview-{today_local().isoformat()}" / "explainer-queue"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    report = run(out_root)
    with open(out_root / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    shutil.rmtree(out_root / "storage", ignore_errors=True)
    shutil.rmtree(out_root / "fake-clips", ignore_errors=True)
    full = report["full_episode"]
    print("상태 흐름:", " → ".join(str(s) for s in full["states"]))
    print(f"슬롯 {full['slots']}개 · 편집 컷 {full['edit_cuts']}개 · 최종 {full['final_duration_ms'] / 1000:.2f}초 · 가짜 공급자 호출 {full['provider_calls']}회 · 원장 금액(가짜) ${full['fake_cost_usd']:.3f} / 상한 ${full['cap_usd']}")
    print("구매 회차:", full["rounds"])
    for c in full["forced_render_stops"]:
        print(f"멈춤 시험: {c['case']} → {c['code']}({c['state']}) 새 가잡기 {c['new_holds']} · 새 묶음 {c['new_manifests']} · 줄 {c['paid_or_network_hits']}")
    for name in ("budget", "unknown_billed", "no_pass", "switch_off", "old_render"):
        print(f"{name}: {report[name]}")
    for k, v in report["checks"].items():
        print(("통과 " if v else "실패 ") + k)
    print(f"결과물: {out_root}")
    print("★ 화면은 시험 영상이다. 합격은 '큐가 끝까지 돈다'일 뿐이고 그림·움직임 품질은 본 적 없다.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
