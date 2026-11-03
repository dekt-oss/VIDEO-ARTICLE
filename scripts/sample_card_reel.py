"""카드뉴스 릴스 샘플을 로컬에서 만든다(0원 — 모델·이미지·네트워크 호출 없음). docs/deviation-drinks-card-reels.md

    python -m scripts.sample_card_reel [출력 폴더]     # 기본 docs/preview-2026-11-02/card-reel (gitignore)

★ 카드 글은 **손으로 쓴 시험용 입력**이다. 모델이 쓴 대본이 아니고, 대본 품질을 판정하는 재료가 아니다.
  근거는 docs/deviation-drinks-develop.md 1단계의 위스키 인용 형태를 흉내 낸 것으로, 코드 검사(check_card_plan)를 통과하는지 함께 본다.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

from engine import drinks_card_plan as cp
from engine.drinks_cards import render_carousel

QUOTES = {
    "c1": "Spirits such as whisky do not spoil the way wine does because their high alcohol content prevents microbes from growing.",
    "c2": "Once a bottle is opened, the air in the bottle slowly changes the flavour of the whisky over time.",
    "c3": "Labels on spirits may show a production or bottling lot instead of an expiry date.",
}
CLAIMS = [{"claim_id": k, "text": t, "claim_type": "process", "support_review": "supported",
           "source_refs": [{"snapshot_id": "s1", "original_quote": q}]}
          for (k, q), t in zip(QUOTES.items(), ("도수가 높아 미생물이 자라지 못해 와인처럼 상하지 않는다", "병을 열면 공기가 맛을 천천히 바꾼다", "라벨에는 유통기한 대신 제조·병입 번호가 있을 수 있다"))]
SOURCES = [{"snapshot_id": "s1", "publisher": "시험용 출처", "title": "위스키 보관 안내(샘플 입력)", "url": "https://example.org/whisky"}]
PLAN = {
    "pages": [
        {"role": "cover", "heading": "위스키는 왜 안 상할까요?", "body": "", "claim_ids": []},
        {"role": "explain", "heading": "술이 세서 그래요", "body": "도수가 높으면\n미생물이 자라지 못해요\n그래서 와인처럼 상하지 않아요", "claim_ids": ["c1"]},
        {"role": "explain", "heading": "그럼 맛도 그대로일까요?", "body": "병을 따면 얘기가 달라져요\n병 속 공기가\n맛을 천천히 바꿔요", "claim_ids": ["c2"]},
        {"role": "explain", "heading": "라벨에 날짜가 없다면요?", "body": "유통기한 대신\n제조·병입 번호가\n적혀 있을 수 있어요", "claim_ids": ["c3"]},
        {"role": "explain", "heading": "정리하면 이래요", "body": "안 상하는 건 도수 덕분이에요\n다만 열어 둔 병의 맛은\n조금씩 달라져요", "claim_ids": ["c1", "c2"]},
        {"role": "source", "heading": "출처", "body": "", "claim_ids": []},
    ],
    "reel": {"hook_title": "위스키는 왜 안 상할까요?", "share_line": "오래된 병 고민하는 친구에게 보내 주세요"},
    "viewer_conclusion": {"text": "위스키는 도수가 높아 잘 상하지 않지만, 열어 둔 병은 맛이 조금씩 달라져요.", "claim_ids": ["c1", "c2"]},
}


def main(argv: list[str]) -> int:
    out = argv[0] if argv else os.path.join("docs", "preview-2026-11-02", "card-reel")
    os.makedirs(out, exist_ok=True)
    review = {"claims": CLAIMS, "sources": SOURCES, "brief": {"selected_claim_ids": ["c1", "c2", "c3"], "required_claims": {"carousel": ["c1", "c2", "c3"]}}}
    topic = {"title": "위스키에도 유통기한이 있을까?", "question": "위스키는 왜 안 상할까?"}
    rep = cp.check_card_plan(PLAN, review, topic)
    clean = cp.clean_plan(PLAN)
    job = {"topic": topic, "claims": CLAIMS, "sources": SOURCES, "plan": clean}
    r = render_carousel(job, os.path.join(out, "work"))
    for f in r.files:
        if f["role"] == "final_video":
            shutil.copyfile(f["path"], os.path.join(out, "card_reel.mp4"))
        elif f["role"] == "cover":
            shutil.copyfile(f["path"], os.path.join(out, "cover.jpg"))
    report = {"script_check": rep.as_dict(), "qa": r.qa, "costs": r.costs, "files": [{k: v for k, v in f.items() if k != "path"} for f in r.files]}
    with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({"script_check_ok": rep.ok, "warns": [w.code for w in rep.warns], "probe": r.qa.get("probe"), "warnings": r.qa.get("warnings"),
                      "timings": r.qa["card_reel"]["timings_sec"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
