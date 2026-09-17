"""세마글루타이드 지시서 → Gemini 수동 발주용 지시서 분할표.

★ 비용 0 · 네트워크 0. 실제 렌더가 호출하는 **바로 그 프롬프트 빌더**를 그대로 부른다
  (providers.image._build_image_prompt / providers.video.build_motion_prompt).
  그래서 여기 적힌 문장이 파이프라인이 Gemini 에 보낼 문장과 같다.
"""
import os, sys, json, io
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from supabase import create_client

from engine import config, stage_render, sequence_tier
from engine.providers import image as image_provider
from engine.providers import video as video_provider

DID = "e7793db0-551e-49e5-9ecb-ec42ac57ef42"
JID = "c43d87a4-0833-4db8-83b5-bca0851a6361"
OUT = "docs/발주표_세마글루타이드_Gemini수동.md"

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
d = sb.table("directives").select("header,cuts").eq("id", DID).single().execute().data
j = sb.table("render_jobs").select("qa").eq("id", JID).single().execute().data
header, cuts = d["header"], d["cuts"]
by_no = {int(f["cut_no"]): f for f in j["qa"]["clip_fit"]["cuts"]}
PAD = config.CLIP_FIT_TAIL_PAD_SEC

# 실측 나레이션 길이 + 꼬리 여백 (렌더가 쓰는 값과 같다)
durations = [float(by_no[int(c["cut_no"])]["narration_sec"]) + PAD for c in cuts]
plans = stage_render.plan_stage(cuts, durations)

L: list[str] = []
w = L.append

w("# 발주표 — 세마글루타이드 (Gemini 수동 샘플용)")
w("")
w(f"지시서 `{DID[:8]}` · 컷 {len(cuts)}개 → **장면(stage) {len(plans)}개 · 이미지 "
  f"{len(plans)}장 · 영상 {sum(len(p['clips']) for p in plans)}개**")
w("")
w("> 아래 프롬프트는 파이프라인이 실제로 Gemini 에 보내는 문장 그대로다"
  "(`providers.image._build_image_prompt` · `providers.video.build_motion_prompt` 를 직접 호출).")
w("> ffmpeg·Actions 없이 **손으로 샘플을 만들어 보기 위한 표**다.")
w("")
w("## 만드는 순서")
w("")
w("장면마다 이렇게 한다. 장면끼리는 독립이라 아무 장면이나 먼저 해도 된다.")
w("")
w("```")
w("1) [이미지] 그 장면의 '시작 그림' 1장을 만든다 (9:16 세로)")
w("2) [영상 1] 그 그림을 시작 프레임으로 넣고 → 클립 1 생성")
w("3) [영상 2] 클립 1의 **마지막 프레임**을 캡처해 시작 프레임으로 넣고 → 클립 2 생성")
w("4) 클립이 더 있으면 3) 을 반복 (표의 '시작 프레임' 열을 따른다)")
w("5) 만든 클립들을 순서대로 이어 붙이면 그 장면의 연속 영상이 된다")
w("```")
w("")
w("★ 3) 이 핵심이다. 앞 클립의 마지막 프레임에서 이어받아야 **같은 장면이 계속되는** 느낌이 난다.")
w("   Veo 가 한 번에 8초까지만 만들기 때문에 긴 장면은 이렇게 이어 만드는 수밖에 없다.")
w("")
w("## 매번 넣어야 하는 설정")
w("")
w("아래 각 블록에도 다시 적어 뒀지만, 한 번에 보면 이렇다.")
w("")
w("### 이미지 (그림 만들 때)")
w("")
w("| 항목 | 값 |")
w("|---|---|")
w(f"| 모델 | `{config.IMAGE_MODEL}` |")
w(f"| **종횡비** | **{config.ASPECT_RATIO} (세로)** |")
w("| 출력 | 이미지만 |")
w("")
w("> ⚠️ **종횡비는 반드시 설정 항목으로 넣어야 한다.** 프롬프트 끝의 `vertical 9:16` 이라는")
w("> 글자는 모델이 **무시한다** — 1차 샘플에서 8장이 전부 1024×1024 정사각형으로 나온 직접")
w("> 원인이 이것이다. 만든 뒤 세로가 맞는지 눈으로 확인할 것.")
w("")
w("### 영상 (움직이게 할 때)")
w("")
w("| 항목 | 값 |")
w("|---|---|")
w(f"| 모델 | `{config.VEO_MODEL}` |")
w(f"| **종횡비** | **{config.ASPECT_RATIO} (세로)** |")
w("| 길이 | 블록마다 다름 (8초 / 6초 / 4초) |")
w("| 시작 이미지 | **필수** — 블록에 적힌 것을 첨부 |")
w("| 소리 | **없음(무음)** |")
w(f"| 해상도 | {config.VEO_RESOLUTION} — 단, 파이프라인은 이 값을 **보내지 않는다** |")
w("")
w("> 파이프라인이 해상도를 안 보내는 이유: 이 프리뷰 모델의 `predictLongRunning` 이")
w("> `resolution` 을 거부한 적이 있어 껐다(`VEO_SEND_RESOLUTION=false`).")
w("> 소리도 같은 이유로 안 보낸다(`generateAudio` 400). **나레이션은 따로 붙인다.**")
w("")

total_img = total_vid = 0
for gi, p in enumerate(plans):
    sid = p["stage_id"] or f"(무명 {gi})"
    idxs = p["indexes"]
    lead = cuts[idxs[0]]
    cut_nos = [int(cuts[i]["cut_no"]) for i in idxs]
    need = p["total_sec"]
    made = sum(p["clips"])

    w("---")
    w("")
    w(f"## 장면 {gi+1}/{len(plans)} — `{sid}`")
    w("")
    w(f"- 담는 컷: **{', '.join('컷'+str(n) for n in cut_nos)}**")
    w(f"- 필요한 길이: **{need:.1f}초** (나레이션 실측 합) → 만들 영상 **{made:.0f}초** "
      f"({'+'.join(f'{c:.0f}' for c in p['clips'])})")
    w("")
    w("**이 장면에서 읽는 나레이션**")
    w("")
    for i in idxs:
        c = cuts[i]
        n = by_no[int(c["cut_no"])]["narration_sec"]
        w(f"- 컷{c['cut_no']} ({n:.2f}초) — {c.get('narration_ko')}")
    w("")

    # ── 시작 그림 ──────────────────────────────────────────────
    img_prompt = image_provider._build_image_prompt(lead, header)
    total_img += 1
    w(f"### ① 시작 그림 (이미지 1장)")
    w("")
    w(f"`설정` 모델 `{config.IMAGE_MODEL}` · **종횡비 {config.ASPECT_RATIO} 세로(파라미터로 지정, "
      f"프롬프트 글자는 무시됨)** · 출력 이미지만")
    w("")
    w("```text")
    w(img_prompt.strip())
    w("```")
    w("")

    # ── 영상 클립들 ────────────────────────────────────────────
    windows = p["windows"]
    elapsed = 0.0
    for i, (sec, chained) in enumerate(zip(p["clips"], p["chained"])):
        owner = lead
        for k, (ws, wd) in enumerate(windows):
            if ws <= elapsed < ws + wd:
                owner = cuts[idxs[k]]
                break
        mp = video_provider.build_motion_prompt(owner, header)
        tier = sequence_tier.effective_tier(owner, header)
        start = ("앞 클립(영상 %d)의 **마지막 프레임**" % i) if chained else "① 시작 그림"
        total_vid += 1
        w(f"### ② 영상 {i+1} — {sec:.0f}초 · 시작 프레임: {start}")
        w("")
        w(f"`설정` 모델 `{config.VEO_MODEL}` · **종횡비 {config.ASPECT_RATIO} 세로** · "
          f"**길이 {sec:.0f}초** · 시작 이미지 첨부 · **무음**")
        w("")
        w(f"- 프롬프트 출처: 컷{owner.get('cut_no')} · 등급 `{tier.get('tier')}`")
        w("")
        w("```text")
        w(mp.strip())
        w("```")
        w("")
        elapsed += sec

    # ── 컷이 어느 구간을 보는가 ─────────────────────────────────
    w("### ③ 완성된 장면 영상에서 컷이 가져갈 구간")
    w("")
    w("| 컷 | 시작 | 길이 |")
    w("|---|---:|---:|")
    for k, i in enumerate(idxs):
        ws, wd = windows[k]
        w(f"| 컷{cuts[i]['cut_no']} | {ws:.2f}초 | {wd:.2f}초 |")
    w("")
    if made - need > 0.05:
        w(f"> 남는 {made-need:.2f}초는 **버리지 않는다** — 컷들이 위 구간만 보고 지나갈 뿐이다.")
        w("")

w("---")
w("")
w("## 합계")
w("")
w(f"- 이미지 **{total_img}장** (옛 방식은 컷마다 1장이라 {len(cuts)}장이었다)")
w(f"- 영상 **{total_vid}개**, 총 {sum(sum(p['clips']) for p in plans):.0f}초")
w(f"- 예상 영상비 ${sum(sum(p['clips']) for p in plans) * config.VEO_COST_PER_SEC_USD:.2f} "
  f"(Veo {config.VEO_COST_PER_SEC_USD}/초 기준)")
w("")
w("## 확인할 것 (샘플의 목적)")
w("")
w("1. **장면 안에서 화면이 이어지는가** — 영상 1 끝과 영상 2 시작이 같은 장면으로 보이는가")
w("2. **컷 경계에서 안 끊기는가** — 위 ③ 표의 구간들이 한 영상에서 잘려 나오므로,")
w("   컷이 바뀔 때 인물·배경·조명이 유지되어야 한다")
w("3. **정지가 없는가** — 특히 `S4` 는 옛 방식에서 컷8이 4.66초 얼어붙던 자리다")
w("4. **이어받기 깊이** — 3번째 클립(깊이 2)에서 인물·재질이 흐려지지 않는지")
w(f"   (지금 상한 `MAX_CHAIN_DEPTH={getattr(config, 'MAX_CHAIN_DEPTH', '?')}` 는 아직 실측된 적이 없다)")

io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print(f"작성: {OUT}  ({len(L)} 줄)")
print(f"이미지 {total_img}장 · 영상 {total_vid}개")
