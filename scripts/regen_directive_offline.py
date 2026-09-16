"""Supabase 402 우회: 완성 영상의 자막·오버레이에서 복구한 대본으로 지시서를 새로 만든다.

★ 정직하게 적어 둔다 — fact_sheet 는 **재구성본**이다(원본은 Supabase 에 있고 402 로 잠겼다).
  claim 문구가 원본과 다를 수 있으므로, 여기서 보려는 것은 문구가 아니라 **구조**다:
  컷 수, 재사용이 진행인가 반복인가, 도해가 실제로 무엇을 자르는가, 게이트가 무엇을 잡는가.

★ claim 은 **초록에서 확인되는 것만** 넣는다(출처: PubMed PMC13462352,
  DOI 10.1073/pnas.2602655123). 초기 재구성본에는 "이중맹검·위약대조"가 들어 있었는데
  그것은 초록에 없는 말이었고, 지시서 컷3 이 그것을 그대로 화면에 실었다 —
  **Fact Sheet 에 들어간 것은 화면까지 간다**는 실증이라 여기 남겨 둔다.
  원문 전문은 확보되지 않았다(체인 전부 403, PMC full_text 비어 있음).
"""
import json, os, pathlib, sys
sys.path.insert(0, os.getcwd())
for _l in pathlib.Path('.env').read_text(encoding='utf-8').splitlines():
    if '=' in _l and not _l.strip().startswith('#'):
        _k, _v = _l.split('=', 1); os.environ.setdefault(_k.strip(), _v.strip())

from engine import directive as D

SCRIPT = """원래 남을 잘 못 믿는 사람에게 신뢰를 '주입'할 수 있을까요?
독일 오토 폰 게리케 대학의 보도 포크트 연구팀이 그 답을 찾기 위해, 아주 엄격하게 설계된 연구를 진행했습니다.
연구팀은 원래 남을 잘 믿지 않는 남성 359명에게 옥시토신을 투여하고, 신뢰 게임을 진행했습니다.
결과는 놀라웠습니다.
옥시토신을 투여한 그룹은 위약 그룹보다 신뢰 행동이 약 15% 증가했습니다.
심지어 이전 연구 데이터까지 합쳐 분석했더니, 그 효과는 더 강력하고 일관되게 나타났습니다.
즉, 이 결과는 '원래 의심이 많은 남성'에 한정된 것입니다.
하지만 이들에게만큼은 옥시토신이 신뢰를 높인다는 강력한 증거가 확인된 셈입니다."""

FACT_SHEET = {
    "title": "Oxytocin increases trust in men low in dispositional trust",
    "venue": "Proceedings of the National Academy of Sciences",
    "doi": "10.1073/pnas.2602655123",
    "claims": [
        {"claim_id": "C01", "evidence_role": "primary_result",
         "text": "비강 옥시토신 투여군은 위약군보다 신뢰 게임에서 신뢰 행동이 약 15% 증가했다.",
         "numbers": ["+15%"]},
        {"claim_id": "C02", "evidence_role": "scope",
         "text": "대상은 기질적 신뢰가 낮은(low-trusting) 남성 359명이다.",
         "numbers": ["359"]},
        {"claim_id": "C03", "evidence_role": "method",
         "text": "사전등록된 고검정력(95%) 설계로 완전 익명 신뢰 게임을 수행했다.", "numbers": ["95%"]},
        {"claim_id": "C04", "evidence_role": "magnitude",
         "text": "선행 연구(n=219)를 합친 통합 분석에서 효과는 +16.9% 로 더 크고 일관됐다.",
         "numbers": ["+16.9%", "n=219"]},
        {"claim_id": "C05", "evidence_role": "caveat",
         "text": "효과는 기질적 신뢰가 낮은 남성에 한정되며 일반 인구로 확장되지 않는다.",
         "numbers": []},
    ],
}
DRAFT = {
    "paper_id": "d64d86ef-2698-4b80-b8b7-bd393d29795e",
    "script_md": SCRIPT,
    "fact_sheet": FACT_SHEET,
    "video_prompts": [],
    "video_flow": {"content_plan": {
        "selected_mode": "standard",
        "essential_evidence_units": ["primary_result", "scope", "method", "magnitude", "caveat"],
        "primary_claim_id": "C01",
        "supporting_claim_ids": ["C02", "C03", "C04", "C05"],
    }},
}

d = D.generate(DRAFT, "photo")
json.dump(d, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
h = d["header"]
print("컷:", len(d["cuts"]), "| 차단:", h.get("approval_blocked"))
print("block:", h.get("block_reasons"))
print("warn :", (h.get("photo_gate") or {}).get("warnings"))
