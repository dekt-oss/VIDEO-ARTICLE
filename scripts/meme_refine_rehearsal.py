"""밈 틀 정밀화 리허설 — 가짜 Apify 응답 + 가짜 분석 모델로 끝까지(0원, 네트워크·DB 0). docs/deviation-drinks-stage3-4.md

    python -m scripts.meme_refine_rehearsal           # 산출물: docs/preview-<날짜>/meme-refine/ (gitignore)

보이는 것:
  1. [쓰자] 카드(가짜, 릴스 3개) → 정밀화 요청 → 영상 3편(ffmpeg 시험 영상, 컷을 일부러 넣음) → 컷 길이·비트 수 측정 → 모델 답(가짜) 걸러 칸 채움 → 임시 파일 삭제 확인.
  2. 연령 제한 1편은 돈만 나가고 분석이 안 된다(partial) — 실패를 0건으로 바꾸지 않는다.
  3. 채워진 칸으로 카드가 정밀 틀이 되고, 그 카드로 **리허설(scripts/meme_rehearsal.py)과 같은 코드 경로**(drinks_meme.spec_from_llm → produce)로 제작까지 간다.
★ 가짜 영상·가짜 답이다. 실제 릴스의 컷 수·반전 시점이 아니다. 합격은 "돌아간다"일 뿐이다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from engine import config
from engine import drinks_meme as dm
from engine import drinks_meme_refine as rf
from engine.util import today_local
from scripts.explainer_rehearsal import Tripwire

ROOT = Path(__file__).resolve().parents[1]

REELS = [
    {"media_id": "m1", "username": "fake_meme_a", "permalink": "https://www.instagram.com/reel/FAKE00001/", "view_count": 120000},
    {"media_id": "m2", "username": "fake_meme_b", "permalink": "https://www.instagram.com/reel/FAKE00002/", "view_count": 80000},
    {"media_id": "m3", "username": "fake_meme_c", "permalink": "https://www.instagram.com/reel/FAKE00003/", "view_count": 50000},
]
CARD = {"id": "fake-card-01", "name": "(리허설) 라벨 읽는 척 POV", "structure": None, "audio_id": None,
        "fields": {"caption_hook": {"value": "다들 이러잖아요", "evidence": "caption", "confidence": "low"}}}
# 가짜 모델 답 — 영상마다 하나. 2번은 허용 어휘 밖 값을 섞어 코드가 버리는지 본다.
FAKE_ANSWERS = {
    0: {"frame": "top_text", "text_position": "top", "cover_text": "POV: 라벨 읽는 척", "first_1_5s": "손이 병을 들어 라벨을 본다",
        "twist_at_sec": 6.2, "structure": "pov", "music_sync": "free", "notes": "검은 바탕 위 글 한 줄"},
    1: {"frame": "vertical_weird", "text_position": "left", "cover_text": "https://cdninstagram.example/x.mp4", "first_1_5s": "",
        "twist_at_sec": 99, "structure": "montage", "music_sync": "maybe", "notes": "허용 어휘 밖 — 전부 버려져야 한다"},
}


def _run(argv: list[str]) -> None:
    p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {(p.stderr or '')[-300:]}")


def make_cut_video(path: str, segments_sec: list[float]) -> None:
    """컷마다 색이 다른 시험 영상 — 장면 전환 감지가 컷 길이를 되살려야 한다."""
    parts = []
    for i, s in enumerate(segments_sec):
        parts.append(f"color=c=0x{(0x203040 + i * 0x40_20_10) & 0xFFFFFF:06x}:s=720x1280:r=24:d={s:.3f}[v{i}]")
    chain = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(segments_sec))) + f"concat=n={len(segments_sec)}:v=1:a=0,format=yuv420p[out]"
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={sum(segments_sec):.3f}",
          "-filter_complex", chain, "-map", "[out]", "-map", "0:a", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", path])


def fake_items(video_dir: Path) -> list[dict[str, Any]]:
    """Apify 모양 그대로. 3번은 연령 제한(검토 §6 시험 2 의 ladbible 처럼 돈은 나가고 영상은 없다)."""
    return [
        {"inputUrl": REELS[0]["permalink"], "videoDuration": 11.5, "videoPlayCount": 120000, "videoUrl": str(video_dir / "reel0.mp4"),
         "musicInfo": {"audio_id": "fake-audio-1", "uses_original_audio": True}, "timestamp": "2026-10-30T10:00:00.000Z"},
        {"inputUrl": REELS[1]["permalink"], "videoDuration": 9.0, "videoPlayCount": 80000, "videoUrl": str(video_dir / "reel1.mp4"),
         "musicInfo": {"audio_id": "fake-audio-2", "uses_original_audio": False}, "timestamp": "2026-10-29T10:00:00.000Z"},
        {"inputUrl": REELS[2]["permalink"], "error": "age-restricted", "errorDescription": "This content is age-restricted"},
    ]


class MemRpc:
    """DB 없이 — 0070 drinks_apify_finish 가 하는 일(메타만 저장, 운영자 칸은 덮지 않음)을 흉내 낸다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.card_fields: dict[str, dict[str, Any]] = dict(CARD["fields"])

    def __call__(self, fn: str, p: dict[str, Any]) -> Any:
        self.calls.append((fn, p))
        if fn == "drinks_apify_finish":
            rf.assert_no_media_url({"results": p["results"], "analysis": p["analysis"]})
            written = []
            if p["outcome"] in ("done", "partial"):
                for f in p["fields"]:
                    cur = self.card_fields.get(f["field"])
                    if cur and cur["evidence"] == "operator":
                        continue
                    self.card_fields[f["field"]] = {"value": f["value"], "evidence": f["evidence"], "confidence": f["confidence"]}
                    written.append(f["field"])
            precise = all(k in self.card_fields and self.card_fields[k]["evidence"] in ("video", "operator") for k in ("beat_count", "cut_lengths", "twist_at"))
            return {"request_id": p["request_id"], "status": p["outcome"], "actual_usd": p["actual_usd"], "fields_written": written,
                    "precision": "precise" if precise else "reference"}
        raise AssertionError(fn)


def run(out_root: Path) -> dict[str, Any]:
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    videos = out_root / "_fake_videos"
    videos.mkdir()
    make_cut_video(str(videos / "reel0.mp4"), [3.0, 3.2, 5.3])     # 11.5초, 컷 3
    make_cut_video(str(videos / "reel1.mp4"), [4.5, 4.5])          # 9초, 컷 2
    job = {"request_id": "req-fake-01", "lease_token": "lease-1", "kind": "meme_refine", "cap_usd": config.DRINKS_APIFY_RUN_CAP_USD["meme_refine"],
           "card": CARD, "reels": REELS, "hooks": ["다들 이러잖아요"], "month": {"spent_usd": 0, "month_cap_usd": config.DRINKS_APIFY_MONTH_CAP_USD}}
    seen_paths: list[str] = []

    def analyzer(path: str, duration: float, cuts: list[float]):
        seen_paths.append(path)
        idx = int(os.path.basename(path)[4:-4])
        return FAKE_ANSWERS.get(idx), config.DRINKS_APIFY_ANALYSIS_EST_USD

    provider = rf.FakeApify(items=fake_items(videos), usage_usd=0.0088)
    rpc = MemRpc()
    tmp_root = out_root / "_tmp"
    tmp_root.mkdir()
    with Tripwire() as wire:
        res = rpc_res = rf.process_job(job, rpc, provider=provider, analyzer=analyzer, tmp_root=str(tmp_root))
    finish = rpc.calls[-1][1]
    leftovers = [str(p) for p in tmp_root.glob("*")]
    # 정밀 틀이 된 카드로 제작까지 — 리허설(meme_rehearsal)과 같은 함수(drinks_meme.produce)다.
    card_after = {**CARD, "fields": rpc.card_fields, "decision": "use", "precision": rpc_res["precision"]}
    llm_out = {"top_line": "POV: 와인 라벨 읽는 척하는 나", "beats": [{"text": "앞면을 본다", "keyword": ""}, {"text": "뒷면도 본다", "keyword": ""}, {"text": "가격표만 기억난다", "keyword": "가격표"}],
               "caption": "다들 이러죠?"}
    spec = dm.spec_from_llm(llm_out, frame="top_text", palette="wine", card=card_after)
    with Tripwire() as wire2:
        produced = dm.produce(spec, str(out_root / "meme"), card=card_after, hooks=job["hooks"])
    picked = finish["fields"]
    by_field = {f["field"]: f for f in picked}
    checks = {
        "영상 2편 분석·1편 연령 제한 → partial": finish["outcome"] == "partial" and [r["status"] for r in finish["results"]] == ["ok", "ok", "age_restricted"],
        "컷 길이를 ffmpeg 가 되살림(3컷·2컷)": [v.get("measured", {}).get("beat_count") for v in finish["analysis"]["per_video"][:2]] == [3, 2],
        "허용 어휘 밖 모델 답은 버려짐": all(k not in by_field or by_field[k]["value"] not in ("montage", "maybe") for k in ("structure", "music_sync")) and "cdninstagram" not in json.dumps(finish, ensure_ascii=False),
        "저장 데이터에 영상 주소 없음": not rf._MEDIA_URL.search(json.dumps({"results": finish["results"], "analysis": finish["analysis"], "fields": finish["fields"]}, ensure_ascii=False)),
        "빌린 영상은 분석 뒤 삭제": finish["analysis"]["deleted"] is True and not leftovers and all(not os.path.exists(p) for p in seen_paths),
        "실행 상한 안(maxTotalChargeUsd 전달)": provider.calls[0]["cap_usd"] == job["cap_usd"] and finish["actual_usd"] <= job["cap_usd"],
        "운영자 입력 칸은 덮지 않음(캡션 훅은 caption 근거 유지)": rpc.card_fields["caption_hook"]["evidence"] == "caption",
        "카드가 정밀 틀이 됨": rpc_res["precision"] == "precise",
        "컷 길이가 제작안 비트에 그대로 쓰임": [b["ms"] for b in spec["beats"]] == [int(round(float(x) * 1000)) for x in by_field["cut_lengths"]["value"].split(",")],
        "같은 코드 경로로 제작 완료(게시 대기)": produced.status == "publish_waiting" and bool(produced.files),
        "유료·네트워크 호출 0": not wire.hits and not wire2.hits,
    }
    report = {"cost_usd": 0, "published": 0, "tripwire_hits": wire.hits + wire2.hits, "checks": checks,
              "finish_payload": {k: v for k, v in finish.items() if k != "lease_token"}, "card_fields_after": rpc.card_fields, "spec": spec,
              "produce": {"status": produced.status, "error_code": produced.error_code, "qa_blocks": produced.qa.get("blocks"), "probe": produced.qa.get("probe")},
              "note": "가짜 영상·가짜 답·가짜 Apify. 실제 릴스의 수치가 아니다."}
    (out_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    shutil.rmtree(videos, ignore_errors=True)
    shutil.rmtree(tmp_root, ignore_errors=True)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="밈 틀 정밀화 리허설(0원, 네트워크·DB 없음)")
    ap.add_argument("--out", default=None, help="산출물 폴더(기본 docs/preview-<오늘>/meme-refine)")
    args = ap.parse_args(argv)
    out_root = Path(args.out) if args.out else ROOT / "docs" / f"preview-{today_local().isoformat()}" / "meme-refine"
    report = run(out_root.resolve())
    for r in report["finish_payload"]["results"]:
        print(f"{r['input_url']}  {r['status']:<15} {r['duration_sec']}초  재생 {r['play_count']}")
    for f in report["finish_payload"]["fields"]:
        print(f"  칸 {f['field']:<12} = {f['value']}  ({f['evidence']}, {f['confidence']})")
    for name, ok in report["checks"].items():
        print(("  합격 " if ok else "  불합격 ") + name)
    print(f"비용 $0 · 게시 0건 · 제작 {report['produce']['status']} · 산출물 {out_root}")
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
