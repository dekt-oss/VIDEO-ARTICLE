"""밈 엔진 리허설 — 가짜 카드 6장을 엔진 끝까지 돌린다. 돈·네트워크·공급자 호출·게시 0. docs/deviation-drinks-meme-engine.md

    python -m scripts.meme_rehearsal               # 산출물: docs/preview-<날짜>/meme-rehearsal/ (gitignore)

구성(운영자 확정, 총괄 계획 §7 결정 4): 분위기 음원 4 / 박자 맞춤 1 / 정보 포함 1.
★ 손으로 만든 카드다. 실제 트렌드도, 올릴 글도 아니다. 합격해도 "돌아간다"일 뿐이고 재미·화면 품질은 운영자가 본다.
★ 농담 칸은 사실을 말하지 않는다. 정보 카드의 근거는 EU 규정 1169/2011 부속서 X 원문 한 줄이다(시험용, 운영 근거 묶음이 아니다).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from engine import drinks_meme as dm
from engine.util import today_local
from scripts.explainer_rehearsal import Tripwire

ROOT = Path(__file__).resolve().parents[1]

PRECISE = {
    "beat_count": {"value": "3", "evidence": "operator", "confidence": "high"},
    "cut_lengths": {"value": "3,3,3", "evidence": "operator", "confidence": "high"},
    "twist_at": {"value": "6초", "evidence": "operator", "confidence": "high"},
}

INFO_CLAIMS: list[dict[str, Any]] = [{
    "claim_id": "c1", "claim_type": "regulation", "text": "EU 표시 규칙은 알코올 10% 이상 음료에 최소 보존 기한 표시를 요구하지 않는다",
    "source_refs": [{"original_quote": "beverages containing 10 % or more by volume of alcohol"}],
}]
INFO_SOURCES = [{"title": "Regulation (EU) No 1169/2011, Annex X", "publisher": "EUR-Lex"}]


def _card(card_id: str, name: str, *, structure: str, sync: Optional[str] = None) -> dict[str, Any]:
    fields = dict(PRECISE)
    if sync:
        fields["music_sync"] = {"value": sync, "evidence": "operator", "confidence": "high"}
    return {"id": card_id, "name": name, "structure": structure, "decision": "use", "precision": "precise", "fields": fields}


def fixtures() -> list[dict[str, Any]]:
    """고정 카드 6장 — 틀 ①②를 모두 지나게 섞었다."""
    def b(text: str, keyword: str = "", ms: Optional[int] = None) -> dict[str, Any]:
        return {"text": text, "keyword": keyword, **({"ms": ms} if ms else {})}

    return [
        {"group": "sync_free", "card": _card("fake-01", "라벨 읽는 사람 POV", structure="pov"),
         "spec": dm.build_spec(frame="top_text", top_line="POV: 와인 고르는 척하는 나",
                               beats=[b("앞면을 본다", ms=2600), b("뒷면도 본다", ms=2600), b("가격표만 기억난다", "가격표", ms=3800)],
                               caption="다들 이러잖아요, 그렇죠?", palette="wine")},
        {"group": "sync_free", "card": _card("fake-02", "향 맡는 사람 특징", structure="list"),
         "spec": dm.build_spec(frame="full_title", top_line="위스키 향 맡는 사람 특징", title_keyword="향",
                               beats=[b("일단 잔을 돌린다", "돌린다", ms=3000), b("고개를 끄덕인다", "끄덕인다", ms=3000), b("뭐가 나는지는 모른다", "모른다", ms=4500)],
                               caption="저만 그런 거 아니죠?", palette="amber")},
        {"group": "sync_free", "card": _card("fake-03", "막걸리 앞 고민", structure="twist"),
         "spec": dm.build_spec(frame="top_text", top_line="막걸리 병 앞에서 고민 중",
                               beats=[b("흔들까", ms=2000), b("말까", ms=2000), b("이미 뚜껑을 열었다", "뚜껑", ms=3600)],
                               caption="늘 한 박자 늦어요", palette="moss")},
        {"group": "sync_free", "card": _card("fake-04", "추천해 달라는 친구", structure="reaction"),
         "spec": dm.build_spec(frame="full_title", top_line="친구가 술 추천해 달랄 때", title_keyword="추천",
                               beats=[b("잠깐, 취향이 뭐야?", "취향", ms=3000), b("단 거? 쓴 거?", ms=2800), b("나도 잘 몰라", "몰라", ms=3200)],
                               caption="아는 척은 여기까지", palette="night")},
        {"group": "sync_required", "card": _card("fake-05", "(가짜 음원) 반전 박자", structure="twist", sync="박자에 맞춰야 함(필수)"),
         "spec": dm.build_spec(frame="top_text", top_line="소믈리에 흉내 낸 날",
                               beats=[b("음, 이 향은", ms=3000), b("오크… 그리고…", ms=3000), b("그냥 포도 맛", "포도", ms=3000)],
                               caption="다음엔 더 잘할게요", palette="wine", sync_grade="sync_required",
                               audio={"mode": "app_manual", "title": "(리허설용 가짜 음원)", "audio_id": "fake-audio-05", "start_hint_sec": 12})},
        {"group": "info", "card": _card("fake-06", "유럽 술병 규칙", structure="reaction"), "claims": INFO_CLAIMS, "sources": INFO_SOURCES,
         "spec": dm.build_spec(frame="full_title", top_line="유럽 술병 규칙, 알고 있었어?", title_keyword="규칙",
                               beats=[b("알코올 10% 이상 음료는", "10%", ms=3200), b("최소 보존 기한을\n안 적어도 돼요", "보존 기한", ms=4200)],
                               caption="EU 규정 1169/2011 부속서 X 에 있는 내용이에요", palette="night",
                               audio={"mode": "ambient_local"}, contains_info=True, claim_ids=["c1"])},
    ]


def _frames(final: Path, spec: dict[str, Any], out: Path) -> list[str]:
    """비트마다 가운데 프레임을 뽑는다(눈으로 보기용)."""
    out.mkdir(parents=True, exist_ok=True)
    t, names = 0, []
    for i, beat in enumerate(spec["beats"], 1):
        mid = (t + int(beat["ms"]) / 2) / 1000.0
        p = out / f"beat{i}.png"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{mid:.3f}", "-i", str(final), "-frames:v", "1", str(p)], check=True)
        names.append(str(p.relative_to(out.parent)))
        t += int(beat["ms"])
    return names


def run(out_root: Path) -> dict[str, Any]:
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    with Tripwire() as wire:
        for fx in fixtures():
            card, spec = fx["card"], fx["spec"]
            d = out_root / card["id"]
            res = dm.produce(spec, str(d), claims=fx.get("claims"), sources=fx.get("sources"), card=card)
            row: dict[str, Any] = {"card": card["id"], "group": fx["group"], "frame": spec["frame"], "status": res.status, "error_code": res.error_code,
                                   "error_message": res.error_message, "auto_publish": res.gate["auto_publish"], "gate_code": res.gate["code"],
                                   "qa_warnings": res.qa.get("warnings"), "qa_blocks": res.qa.get("blocks")}
            if res.files:
                final = d / "final.mp4"
                row.update(probe=res.qa["probe"], mean_volume_db=res.qa["mean_volume_db"], freeze=res.qa["freeze"], frames=[f"{card['id']}/{n}" for n in _frames(final, spec, d / "frames")],
                           final=str(final.relative_to(ROOT)))
                try:
                    dm.assert_auto_publishable(spec)
                    row["auto_publish_gate"] = "통과"
                except dm.MemeStop as exc:
                    row["auto_publish_gate"] = f"막힘:{exc.code}"
            rows.append(row)
        # 근거를 뺀 정보 카드 — 멈춰야 한다. 파일이 나오면 불합격.
        info = next(f for f in fixtures() if f["group"] == "info")
        bad_spec = {**info["spec"], "claim_ids": []}
        stop_dir = out_root / "fake-06-no-evidence"
        stopped = dm.produce(bad_spec, str(stop_dir), card=info["card"])
        no_evidence = {"status": stopped.status, "error_code": stopped.error_code, "error_message": stopped.error_message, "file_made": (stop_dir / "final.mp4").exists()}
    groups = [r["group"] for r in rows]
    checks = {
        "구성 4/1/1": groups.count("sync_free") == 4 and groups.count("sync_required") == 1 and groups.count("info") == 1,
        "6장 전부 파일 생성": all(r.get("final") for r in rows),
        "길이 6~15초": all(config.DRINKS_MEME_MIN_SEC - 0.1 <= r["probe"]["duration_sec"] <= config.DRINKS_MEME_MAX_SEC + 0.1 for r in rows if r.get("probe")),
        "1080x1920": all((r["probe"]["width"], r["probe"]["height"]) == (1080, 1920) for r in rows if r.get("probe")),
        "박자 맞춤은 자동 게시 막힘": all(r["status"] == "manual_audio" and r["auto_publish_gate"] == "막힘:sync_required" for r in rows if r["group"] == "sync_required"),
        "나머지 5장은 게시 대기": all(r["status"] == "publish_waiting" for r in rows if r["group"] != "sync_required"),
        "근거 없는 정보 밈은 멈춤": no_evidence["status"] == "stopped" and not no_evidence["file_made"],
        "유료·네트워크 호출 0": not wire.hits,
    }
    report = {"cost_usd": 0, "published": 0, "tripwire_hits": wire.hits, "checks": checks, "cards": rows, "no_evidence_case": no_evidence}
    (out_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="밈 엔진 리허설(0원, 게시 없음)")
    ap.add_argument("--out", default=None, help="산출물 폴더(기본 docs/preview-<오늘>/meme-rehearsal)")
    args = ap.parse_args(argv)
    out_root = Path(args.out) if args.out else ROOT / "docs" / f"preview-{today_local().isoformat()}" / "meme-rehearsal"
    report = run(out_root.resolve())
    for r in report["cards"]:
        p = r.get("probe") or {}
        print(f"{r['card']} {r['group']:<13} {r['frame']:<10} {r['status']:<15} {p.get('duration_sec')}초 {p.get('width')}x{p.get('height')} {r.get('error_code') or ''}")
    print("근거 뺀 정보 카드:", report["no_evidence_case"]["status"], report["no_evidence_case"]["error_code"])
    for name, ok in report["checks"].items():
        print(("  합격 " if ok else "  불합격 ") + name)
    print("비용 $0 · 게시 0건 · 산출물", out_root)
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
