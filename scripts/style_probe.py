"""화풍 실험용 — 지시서 → Gemini 수동 발주 프롬프트를 뽑는다. **Gemini 호출 0(비용 0).**
지시서·렌더 잡은 Supabase 에서 읽는다(읽기만).

렌더 파이프라인이 실제로 부르는 프롬프트 빌더(providers.image._build_image_prompt)를
그대로 호출하므로, 여기 찍힌 문장이 Gemini 에 나가는 문장과 같다.
화풍을 바꿔 보려면 아래 B_STYLE / B_NEGATIVE / OPTICS 를 고치고 다시 돌린다.

    python -m scripts.style_probe
      → docs/이미지지시서_세마글루타이드_도해CG.md     (시도 2 — 6장 전체, 출력 불변)
      → docs/이미지지시서_그림4_5_실물모형가설.md      (가설 1 — 세포 세계 2장)

★ 배경은 docs/핸드오프_화풍전환_2026-09-07.md 를 먼저 읽을 것.
★ 가설(§4 첫 가설)은 아래 MECH_STYLE / MECH_NEGATIVE / SCENE_REWRITE 로 조정한다.
  접미사·부정어는 시도 3 과 **같고**, 바꾸는 것은 장면 묘사 하나다 — 한 번에 한 변수.
"""
import os, sys, io, re
from unittest import mock
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from supabase import create_client

from engine import config, generation_spec, photo_contract, stage_render
from engine.providers import image as image_provider

DID = "e7793db0-551e-49e5-9ecb-ec42ac57ef42"
JID = "c43d87a4-0833-4db8-83b5-bca0851a6361"
OUT = "docs/이미지지시서_세마글루타이드_도해CG.md"

B_STYLE = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, even studio lighting, "
    "limited desaturated palette with a single amber accent, neutral background, "
    "technical illustration clarity"
)
B_NEGATIVE = (
    "not a photograph, no photorealistic detail, no fur or skin micro-texture, "
    "no pores, no lens blur, no bokeh, no film grain, "
    "no cartoon outlines, no anime, no flat vector art"
)
B_GLOBAL = ("Scientific 3D visualization, clean and precise, with a focus on "
            "biological processes and laboratory settings.")

# ── 세포 세계 가설 시험(핸드오프 §4 첫 가설) ────────────────────────────────────────
# 접미사·부정어는 **시도 3 과 글자 하나 안 다르다**(docs/이미지지시서_MECHANISM재시도.md).
# 시도 3 이 이 조합으로 실패했으므로, 이번에 결과가 달라지면 원인은 장면 묘사 하나다.
MECH_STYLE = (
    "stylized 3D render, simplified geometric forms with clean silhouettes, "
    "matte surfaces with minimal micro-texture, "
    "isometric cutaway with crisp layer separation, "
    "even studio lighting, limited desaturated palette with a single amber accent, "
    "neutral background"
)
MECH_NEGATIVE = (
    "not a photograph, no photorealistic detail, "
    "no cartoon outlines, no line art, no ink contours, no cel shading, "
    "no flat vector art, no anime, "
    "no glowing effects, no neon, no bloom, no light emission, "
    "no lens blur, no bokeh, no film grain"
)
# 가설: 세포·분자는 실물 사진이 없어 모델이 **교과서 삽화**를 떠올린다. 그래서 "세포를
# 그려라"가 아니라 "세포 **모형**을 스튜디오에서 찍어라"로 바꾼다 — 대상을 실존하는
# 물리적 오브젝트(박물관 교육용 모형)로 만들어 모델이 실물 렌더를 떠올리게 한다.
# 무엇이 화면에 있는지(세포 · 붉은 가시 분자 여러 개 · 초록 긴 분자 하나 · 접근 방향)는
# 원문 그대로다. 바뀐 것은 "무엇으로 존재하는가"뿐이다.
#
# ★★ 대상이 **둘**인 이유(2026-09-07 구조 확인). 파이프라인이 텍스트만으로 그리는 그림은
#   6장 중 2장뿐이다 — `continuity_mode=NEW_WORLD` 인 S1·S4. 나머지 4장은 앞 그림을
#   참조로 받아 상속한다(`sequence_render.reference_decision`). 즉 **S5 는 실제 렌더에서
#   텍스트로 만들어지지 않는다** — S4 를 물려받는다. S5 만 고쳐 봐야 파이프라인이 묻지 않는
#   질문에 답하는 셈이다. 세포 세계의 화풍을 정하는 그림은 **S4** 다.
SCENE_REWRITE: dict[str, str] = {
    # ── 세포 세계의 문지기. 이 그림이 정한 화풍을 S5 가 참조로 물려받는다 ──
    "S4_CALORIE_RESTRICTION_ANALOGY": (
        "Two matte physical teaching models of an aged animal cell, each about the size of a "
        "grapefruit, standing side by side on a plain studio tabletop. Beside the left model "
        "lies a small empty ceramic plate, representing calorie restriction. Beside the right "
        "model lies a single green elongated resin piece, representing a semaglutide molecule, "
        "resting against the model as if pressed into it. Around the right model are a few small "
        "amber-painted resin pieces standing for nerve tissue and pancreatic tissue, arranged in "
        "a neat row. The right model is built in brighter, cleaner parts than the dull left one. "
        "Every part is a solid painted object with a matte surface, like a museum display model. "
        "No on-screen text."
    ),
    "S5_SEMAGLUTIDE_MECHANISM": (
        "A matte physical teaching model of an animal cell, about the size of a grapefruit, "
        "resting on a plain studio tabletop. Scattered around the base of the model are many "
        "small red spiky resin pieces, each representing an inflammatory cytokine molecule. "
        "A single green elongated resin piece, representing a semaglutide molecule, rests just "
        "beside them, angled toward the red pieces as if about to push them away. Every part is "
        "a solid painted object with a matte surface, like a museum display model. "
        "No on-screen text."
    ),
}
OUT5 = "docs/이미지지시서_그림4_5_실물모형가설.md"

# 광학/사진 어휘 → 배치 표현. **정본은 engine/config.PHOTO_OPTICS_REWRITES 하나다.**
#   ★ 예전엔 이 파일이 자기 표를 따로 들고 있었다. 그러면 엔진과 실측이 서로 다른 프롬프트를
#     보게 되고, 실측으로 통과시킨 화풍이 렌더에서 재현되지 않는다 — 이 저장소가 값 이중화로
#     이미 여러 번 겪은 드리프트다. 엔진이 실제로 적용하는 함수를 그대로 부른다.


def strip_optics(cut):
    c = dict(cut)
    c["visual_prompt"] = photo_contract.strip_optics(c.get("visual_prompt") or "")
    return c


sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
d = sb.table("directives").select("header,cuts").eq("id", DID).single().execute().data
j = sb.table("render_jobs").select("qa").eq("id", JID).single().execute().data
header, cuts = d["header"], d["cuts"]
by_no = {int(f["cut_no"]): f for f in j["qa"]["clip_fit"]["cuts"]}
durations = [float(by_no[int(c["cut_no"])]["narration_sec"]) + config.CLIP_FIT_TAIL_PAD_SEC
             for c in cuts]
plans = stage_render.plan_stage(cuts, durations)

header_b = dict(header)
header_b["global_style"] = B_GLOBAL

L: list[str] = []
w = L.append
w("# 이미지 지시서 — 세마글루타이드 (도해 CG 화풍)")
w("")
w("**시작 그림 6장.** 영상은 이 그림들이 정해진 뒤에 만든다 —")
w("영상 프롬프트는 `Keep the SAME design and materials ... do not restyle any object` 라")
w("**화풍을 첨부 이미지가 100% 결정하기 때문**이다(2026-09-07 실측: 영상으로는 화풍이 안 갈렸다).")
w("")
w(f"`설정` 모델 `{config.IMAGE_MODEL}` · **종횡비 {config.ASPECT_RATIO} 세로 — 반드시 설정 "
  "항목으로. 프롬프트의 `vertical 9:16` 글자는 모델이 무시한다** · 출력 이미지만")
w("")
w("## 지난 시험에서 바뀐 것")
w("")
w("S1(주사 펜)은 실사로, S2(사육장)는 도해로 나왔다. 같은 접미사인데 갈린 이유는")
w("**장면 묘사 안의 광학 어휘**였다 — `shallow depth of field` 가 부정어 `no lens blur` 를 이겼다.")
w("그래서 이번에는 두 곳을 같이 고쳤다.")
w("")
w("| | 지난번 | 이번 |")
w("|---|---|---|")
w("| 화풍 접미사 | `physically based materials, fine surface detail` (사실성을 **올리는** 어휘) | `simplified geometric forms, minimal micro-texture` |")
w("| 장면 묘사 | 그대로 (`shallow depth of field`, `macro detail`, `blurred`) | **광학 어휘 제거**(배치 정보는 유지) |")
w("")
w("> MECHANISM 컷(세포·분자)은 **손대지 않았다** — 이미 3D 도해이고 광학 어휘도 없다.")
w("")

for gi, p in enumerate(plans):
    idxs = p["indexes"]
    lead = cuts[idxs[0]]
    role = lead.get("visual_role")
    cut_nos = [int(cuts[i]["cut_no"]) for i in idxs]
    is_reality = role == "REALITY"

    if is_reality:
        ctxs = (mock.patch.dict(config.VISUAL_ROLE_STYLE, {"REALITY": B_STYLE}),
                mock.patch.dict(config.VISUAL_ROLE_NEGATIVE, {"REALITY": B_NEGATIVE}))
        for c in ctxs:
            c.start()
        try:
            prompt = image_provider._build_image_prompt(strip_optics(lead), header_b)
        finally:
            for c in ctxs:
                c.stop()
    else:
        prompt = image_provider._build_image_prompt(lead, header_b)

    w("---")
    w("")
    w(f"## 그림 {gi+1}/6 — `{p['stage_id']}`  ({role})")
    w("")
    w(f"담는 컷: **{', '.join('컷'+str(n) for n in cut_nos)}**")
    w("")
    for i in idxs:
        c = cuts[i]
        w(f"- 컷{c['cut_no']} — {c.get('narration_ko')}")
    w("")
    if is_reality:
        before = (lead.get("visual_prompt") or "")
        after = strip_optics(lead)["visual_prompt"]
        if before != after:
            w("<details><summary>이 컷에서 걷어낸 광학 어휘</summary>")
            w("")
            w("```diff")
            w(f"- {before[:300]}")
            w(f"+ {after[:300]}")
            w("```")
            w("</details>")
            w("")
    else:
        w("> MECHANISM — 기존 3D 도해 화풍 그대로다.")
        w("")
    w("```text")
    w(prompt.strip())
    w("```")
    w("")

w("---")
w("")
w("## 볼 것")
w("")
w("1. **6장이 한 화면 언어로 보이는가** — 특히 그림 1·2(실험실)와 그림 4·5(세포)가")
w("   같은 작품처럼 보여야 한다. 지금까지는 여기서 화면이 튀었다")
w("2. **쥐가 보기 견딜 만한가** — 그림 2가 정면 승부다")
w("3. **그림 1이 이번엔 도해로 나오는가** — 지난번 실사로 갔던 컷이다")
w("4. 세로 9:16 · 글자 없음")
w("")
w("## 통과하면")
w("")
w("`engine/config.py` 두 곳을 바꾼다 —")
w("`VISUAL_ROLE_STYLE[\"REALITY\"]` / `VISUAL_ROLE_NEGATIVE[\"REALITY\"]`,")
w("그리고 **지시서 생성 프롬프트**에서 광학 어휘를 금지한다(둘 다 해야 한다).")

io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print(f"작성: {OUT} ({len(L)}줄)")


# ── 세포 세계 2장 — 가설 1 시험 문서 ─────────────────────────────────────────────
def build_mech(cut: dict, scene: str | None = None) -> str:
    """시도 3 접미사·부정어로 MECHANISM 프롬프트를 만든다. scene 이 있으면 장면 묘사만 바꾼다."""
    c = dict(cut)
    if scene is not None:
        c["visual_prompt"] = scene
    ctxs = (mock.patch.dict(config.VISUAL_ROLE_STYLE, {"MECHANISM": MECH_STYLE}),
            mock.patch.dict(config.VISUAL_ROLE_NEGATIVE, {"MECHANISM": MECH_NEGATIVE}))
    for x in ctxs:
        x.start()
    try:
        return image_provider._build_image_prompt(c, header_b)
    finally:
        for x in ctxs:
            x.stop()


targets = [(gi, p) for gi, p in enumerate(plans) if p["stage_id"] in SCENE_REWRITE]
assert targets, f"SCENE_REWRITE 의 stage_id 가 지시서에 없다: {list(SCENE_REWRITE)}"

M: list[str] = []
m = M.append
m("# 이미지 지시서 — 그림 4·5 · 가설 1 \"실물이냐 추상이냐\" (2026-09-07)")
m("")
m("핸드오프 `docs/핸드오프_화풍전환_2026-09-07.md` §4 첫 가설을 **세포 세계 두 장**으로 시험한다.")
m("")
m("## ★ 먼저 — 시험 대상이 그림 5 가 아니라 **그림 4** 다")
m("")
m("핸드오프는 \"그림 5 하나로 시험하라\"고 했지만, 구조를 확인해 보니 **그림 5 는 실제")
m("렌더에서 텍스트로 만들어지지 않는다.** 6장 중 텍스트만으로 그리는 것은 2장뿐이다 —")
m("`continuity_mode=NEW_WORLD` 인 S1·S4. 나머지는 앞 그림을 참조로 받아 화풍을 상속한다.")
m("")
m("| stage | continuity_mode | 그림을 얻는 방식 |")
m("|---|---|---|")
m("| S1_HOOK_MICE | NEW_WORLD | **텍스트 전용** — 실험실 세계의 화풍을 여기서 정한다 |")
m("| S2 · S3 | CONTINUE_WORLD | S1 을 참조로 상속 |")
m("| **S4_CALORIE_RESTRICTION_ANALOGY** | **NEW_WORLD** | **텍스트 전용 — 세포 세계의 화풍을 여기서 정한다** |")
m("| S5_SEMAGLUTIDE_MECHANISM | CONTINUE_WORLD | **S4 를 참조로 상속** |")
m("| S6 | RETURN_WORLD | S3 을 참조로 상속 |")
m("")
m("그래서 그림 4 를 먼저 본다. **그림 4 가 실패하면 그림 5 는 그 실패를 물려받는다** —")
m("그림 5 만 고치는 것은 파이프라인이 묻지 않는 질문에 답하는 것이다.")
m("(지금까지의 수동 실측은 6장을 전부 따로 만들었기 때문에 이 상속이 안 보였다.)")
m("")
m("가설: 그림 2·3(사육장·장갑 낀 손)은 실물이라 목표 화풍이 나왔고, 그림 4·5(세포·분자)는")
m("실물 사진이 없어 모델이 **생물 교과서 삽화**를 학습한 대로 그린다. 그래서 대상을")
m("\"세포\"가 아니라 **\"세포 모형(박물관 교육용 모형)을 스튜디오 탁자에 놓고 찍은 것\"** 으로 묘사한다.")
m("")
m("## ★ 그리고 — 화풍이 정해지는 곳은 **두 곳이 아니라 세 곳**이다")
m("")
m("핸드오프 §3-② 는 `visual_prompt` 와 `VISUAL_ROLE_STYLE` 접미사 두 곳이라고 적었다.")
m("세 번째가 있다 — 지시서의 `world` 선언이다. 지시서 생성 프롬프트가 LLM 에게")
m("`world.style` 을 **\"화풍·재질 한 구절\"** 로 직접 써 내라고 시킨다(`engine/directive.py`).")
m("이번 지시서에서 LLM 이 쓴 답은 이렇다.")
m("")
m("| 세계 | 담당 그림 | `style` | `lighting` | `background` |")
m("|---|---|---|---|---|")
m("| LAB_ENVIRONMENT | 1·2·3·6 | Modern, sterile laboratory with scientific equipment… | Bright, even fluorescent lighting | Clean, white laboratory benches |")
m("| CELLULAR_ENVIRONMENT | **4·5** | **Microscopic, detailed 3D rendering of cellular structures…** | **Soft, internal glow** | **Subtle, blurred cellular matrix** |")
m("")
m("**성공·실패가 이 표와 정확히 갈린다.** 실험실 세계에서 LLM 은 `style` 에 **장소**를 적었고")
m("그림 2·3 이 목표 화풍으로 나왔다. 세포 세계에서는 **그리는 기법**을 적었다 —")
m("그리고 `Soft, internal glow`(그림 4의 발광) 와 `blurred`(흐림) 가 거기 그대로 있다.")
m("")
m("즉 핸드오프 §4 의 \"실물이냐 추상이냐\"는 **어느 그림이 실패하는지**를 맞혔고, 이 표는")
m("**왜**를 말해 준다 — 대상에 실제 장소가 없으면 LLM 은 화풍 질문에 **삽화 기법**으로 답하고,")
m("같은 생각으로 `visual_prompt` 를 쓴다. 그래서 말을 바꿔도 같은 곳으로 돌아왔다.")
m("")
m("> ⚠️ **단, 이 문자열들이 이미지 모델에 직접 가지는 않는다.** `visual_sequence.world_prose`")
m("> (world 의 style·lighting·background 를 프롬프트에 붙이는 함수)는 저장소 어디에서도")
m("> **호출되지 않는다**(`camera_prose` 도 테스트에서만 부른다). 그래서 world 선언은")
m("> 지금은 **LLM 의 의도를 읽는 창**이지 원인 경로가 아니다.")
m("> 그리고 **지금 이 배선을 그냥 이으면 안 된다** — `Soft, internal glow` 가 프롬프트에")
m("> 그대로 붙어 그림 4 가 더 나빠진다. 선언을 고친 뒤에 잇는다.")
m("")
m("**바꾼 변수는 장면 묘사 하나다.** 접미사·부정어는 시도 3")
m("(`docs/이미지지시서_MECHANISM재시도.md`)과 글자 하나 안 다르다. 시도 3 이 그 조합으로")
m("실패했으므로, 이번에 결과가 달라지면 원인은 장면 묘사다.")
m("")
m(f"`설정` 모델 `{config.IMAGE_MODEL}` · **종횡비 {config.ASPECT_RATIO} 세로 — 반드시 설정 "
  "항목으로. 프롬프트의 `vertical 9:16` 글자는 모델이 무시한다** · 출력 이미지만")
m("")
for gi, p in targets:
    idxs = p["indexes"]
    lead = cuts[idxs[0]]
    role = generation_spec.effective_visual_role(lead)
    cut_nos = [int(cuts[i]["cut_no"]) for i in idxs]
    before = str(lead.get("visual_prompt") or "").strip()
    after = SCENE_REWRITE[p["stage_id"]]
    m("---")
    m("")
    m(f"## 그림 {gi+1} — `{p['stage_id']}`  ({role})")
    m("")
    m(f"담는 컷: **{', '.join('컷'+str(n) for n in cut_nos)}**")
    m("")
    for i in idxs:
        c = cuts[i]
        m(f"- 컷{c['cut_no']} — {c.get('narration_ko')}")
    m("")
    m("### 장면 묘사 — 무엇이 바뀌었나")
    m("")
    m("```diff")
    m(f"- {before}")
    m(f"+ {after}")
    m("```")
    m("")
    m("화면에 있는 것(어떤 개체가 몇 개, 어디에, 어느 방향으로)은 그대로다.")
    m("바뀐 것은 그것들이 **무엇으로 존재하는가** — 그림이 아니라 탁자 위의 **물건**이다.")
    m("장면에서 `stylized`·`glowing`·`become more vibrant` 를 뺐다(삽화·발광을 부르는 단어다).")
    m("접미사의 `stylized 3D render` 는 변수 통제를 위해 **그대로 둔다**.")
    m("")
    m("### 발주 프롬프트 (이것을 Gemini 에 넣는다)")
    m("")
    m("```text")
    m(build_mech(lead, after).strip())
    m("```")
    m("")
    m("<details><summary>대조군 — 시도 3 프롬프트(이미 실패한 것, 다시 만들 필요 없음)</summary>")
    m("")
    m("```text")
    m(build_mech(lead).strip())
    m("```")
    m("</details>")
    m("")
m("---")
m("")
m("## 볼 것 — 그림 2·3 옆에 놓고 판정한다")
m("")
m("| 항목 | 통과 | 실패 |")
m("|---|---|---|")
m("| 윤곽선 | 물체 경계가 **음영**으로 갈린다 | 검은/진한 **선**으로 둘러져 있다(시도 3 증상) |")
m("| 채색 | 면에 명암이 있고 재질이 무광 | 평면 채색·파스텔 광택·발광(시도 2 증상) |")
m("| 존재감 | 탁자 위에 **놓인 물건**으로 보인다(그림자·접지) | 허공에 뜬 도식 |")
m("| 한 작품인가 | 그림 2·3 과 같은 스튜디오에서 찍은 것 같다 | 삽화 vs 렌더로 갈린다 |")
m("")
m("`isometric cutaway` 는 접미사에 남아 있다 — 모형에 단면이 보이면 좋지만 이번 판정 기준은")
m("**아니다**. 이번엔 화풍(선화냐 렌더냐)만 본다.")
m("")
m("## 결과별 다음 행동")
m("")
m("**그림 4 가 통과** → 가설 확정. 그림 5 도 같이 보고(상속이 되는지), 고칠 곳은 **세 곳**이다")
m("(핸드오프 §6 은 두 곳으로 적혀 있다):")
m("")
m("1. **지시서 생성 프롬프트 — `world.style` 을 먼저 고친다.** 지금은 LLM 에게 \"화풍·재질")
m("   한 구절\"을 시키는데, 그러면 장소 없는 세계에서 삽화 기법이 나온다(위 표).")
m("   `world` 는 **어디인가**만 적게 하고 화풍은 코드가 정한다 — 핸드오프 §6 이 이미")
m("   \"어떻게 그릴지는 코드가 정한다\"고 적어 둔 원칙을 `world` 에도 적용하는 것이다.")
m("2. **같은 프롬프트 — `visual_prompt` 를 \"물리적 모형\" 프레임으로.** 화풍·광학·발광")
m("   어휘(`stylized`·`glowing`·`vibrant`·`photoreal`·`blurred`)를 금지한다.")
m("   ★ 금지만 적으면 지켜지지 않는다 — **검사 + 재생성**을 함께 붙인다(`gate-prompt-feedback-parity`).")
m("   검사 대상 필드가 `world.style` 과 `visual_prompt` 로 이미 구조화돼 있어 붙이기 쉽다.")
m("3. `engine/config.py` `VISUAL_ROLE_STYLE`/`VISUAL_ROLE_NEGATIVE` 의 `MECHANISM`·`REALITY`")
m("")
m("**그림 4 가 실패** → 장면 묘사만으로는 안 된다. 아래를 **하나씩**(한 번에 한 변수):")
m("1. 접미사의 `stylized 3D render` → `studio product render` (단어 하나 교체)")
m("2. `isometric cutaway` 제거 → 자연 시점")
m("3. 그림 2·3 을 **참조 이미지로 첨부**")
m("")
m("> ⚠️ 3번은 핸드오프가 \"`_image_request_body(ref_path=...)` 가 이미 지원한다\"고 적었지만")
m("> **이 용도로는 지원하지 않는다.** `ref_path` 는 `stage_assets[continuity_from]` —")
m("> 즉 **같은 영상 안 앞 stage 의 그림**만 올 수 있다. 바깥 화풍 견본을 넣는 길이 없다.")
m("> 게다가 참조가 붙으면 `_build_image_prompt` 가 **다른 가지**로 간다 — 화풍 절을 빼고")
m("> \"앞 그림과 SAME design·materials 를 유지하라\"고 말한다. 그건 **연속성** 지시지")
m("> 화풍 이식이 아니다. 그래서 3번은 설정 토글이 아니라 **코드 작업**이다.")
m("")
m("판정 결과는 이 문서 아래에 날짜와 함께 적고 핸드오프 §2 에 \"시도 4\"로 올린다.")

io.open(OUT5, "w", encoding="utf-8", newline="\n").write("\n".join(M) + "\n")
print(f"작성: {OUT5} ({len(M)}줄)")
