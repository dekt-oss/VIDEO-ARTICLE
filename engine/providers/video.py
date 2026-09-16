"""영상(클립) 제공자.

- animation 버전: 작동원리 도해 = Manim(무음·결정론적·무료). M-V6.
- hybrid 버전: 핵심 컷만 I2V(스틸 → 영상). Google Veo API(VIDEO_PROVIDER=veo). start_image 필수.
- higgsfield: I2V 대체 백엔드(미배선).
반환: (clip_path, cost_usd).

★ I2V 경로(start_image 제공)는 Manim 을 우회하고 VIDEO_PROVIDER 를 쓴다. 제공자 미배선/실패는
  예외를 올려 호출측(render.py)이 스틸로 폴백하게 한다(전체 중단 금지).
★ Veo 호출은 이 샌드박스에 키가 없어 미검증이다 — 실제 API 계약은 GEMINI_API_KEY 로 로컬/Actions 검증 필요.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from .. import config, generation_spec, temporal_plan
from ..util import gemini_auth


# ─────────────────────────────────────────────────────────────
# 클립 길이 티어 (수정명세 v1 §3-2). 생성 영상은 임의 길이가 아니라 고정 티어로만 나오므로
# 나레이션 실측 길이에 맞춰 "narration_sec 이상인 최소 티어"를 고른다. 모델 교체 대비로
# 목록은 여기(제공자 모듈)에서 노출하고 값은 config 에 둔다(매직넘버 금지 규약).
# ─────────────────────────────────────────────────────────────
CLIP_SEC_TIERS: tuple[int, ...] = config.VEO_CLIP_SEC_TIERS


def pick_clip_tier(narration_sec: float,
                   max_sec: int | None = None,
                   tiers: tuple[int, ...] | None = None) -> int:
    """나레이션 길이 이상인 최소 티어. 상한(config.VEO_CLIP_MAX_TIER_SEC)을 넘지 않는다.

    예) 나레이션 5.3s → 6s 티어(4s + 늘리기보다 항상 우선). 상한이 4면 4s 로 묶이고,
    남는 갭은 조립 단계의 무료 보정(clip_fit: hold/pingpong)이 흡수한다.
    """
    opts = sorted(tiers if tiers is not None else CLIP_SEC_TIERS)
    if not opts:
        return int(config.VEO_CLIP_SEC)
    cap = int(config.VEO_CLIP_MAX_TIER_SEC if max_sec is None else max_sec)
    allowed = [t for t in opts if t <= cap] or [opts[0]]
    need = float(narration_sec or 0)
    for t in allowed:
        if t >= need:
            return t
    return allowed[-1]


class _VeoError(RuntimeError):
    """Veo 생성 실패(폴백 트리거)."""


class VeoBilledRejection(_VeoError):
    """생성(operation)은 완료됐으나(=과금 유력) 산출물을 못 씀 — 다운로드 실패/mp4 검증 실패.

    §8.5 DoD "미채택 영상 비용도 실효비용에 포함": operation 이 done=True·에러 없음까지 갔다면
    Veo 쪽에서는 생성이 끝난 것이라 과금됐을 가능성이 높다(공식 문서 미검증 — 재확인 필요).
    submit/poll/operation-error/timeout 단계 실패는 생성 자체가 안 됐거나 불확실해 일반 _VeoError
    (비용 0)로 남긴다. 이 예외만 clip_sec 을 실어 호출측(render.py)이 실효 비용을 원장에 남긴다.
    """

    def __init__(self, message: str, clip_sec: int) -> None:
        super().__init__(message)
        self.clip_sec = clip_sec


def build_motion_prompt(cut: dict[str, Any], header: dict[str, Any]) -> str:
    """시작 이미지 + 이 문장 → Veo 클립. **이미지 경로와 같은 규율을 쓴다.**

    ★★ 2026-08-30 이전에는 이랬다:

        prompt = global_style + role_style + visual_prompt + motion_prompt

      즉 **장면 전체를 다시 묘사**하고 있었다. 시작 이미지를 주면서 동시에 "이런 장면을
      그려라"라고 말한 것이다. Phase 0 이 관찰한 "Veo 가 애니메이트한 게 아니라 다시 그린
      쪽에 가깝다"는 결과가 여기서 나왔을 가능성이 크다 — **Veo 한계가 아니라 우리 지시**다.

    ★ 지금은 이미지 참조 조건 생성과 같은 형태다:
        연속 지시문 + 무엇이 움직이는가(motion_prompt) + 화풍
      장면 묘사는 넣지 않는다. 시작 프레임이 이미 장면이다.

    ★ 화풍은 정본에서 온다(generation_spec.effective_visual_role) — 옛 `visual_role` 을
      읽으면 첫 프레임과 클립의 화풍이 갈린다. 그리고 "설명 대상을 다시 칠하라"는 문구는
      **뗀다**: 시작 프레임이 이미 재질을 확정했는데 다시 칠하면 클립 안에서 색이 변한다.
    """
    mp = str(cut.get("motion_prompt") or "").strip()
    role = generation_spec.effective_visual_role(cut)
    role_style = config.VISUAL_ROLE_STYLE.get(role, "")
    for clause in config.STYLE_CLAUSES_DROPPED_WHEN_REFERENCED:
        role_style = role_style.replace(f", {clause}", "").replace(clause, "")
    motion = mp or "subtle motion only"
    # ★★ 연출 계약(v2 Phase E2)이 있으면 **그것이 모션의 본체**다.
    #
    #   8초는 품질이 아니라 품질을 만들 시간 예산이다(코덱스 리뷰 §7). 그냥 길이만
    #   늘리면 "한 장면을 8초 유지"가 되어 지루해진다. 벤치마크는 8초 안에 비트 2~3개를
    #   넣는다 — wide reveal → lateral follow → rapid push-in.
    #
    #   ★ 여기서 소비하지 않으면 `temporal_plan` 은 장식이다. 이 저장소가 여덟 번 겪은
    #     "만들어 놓고 한쪽만 연결"의 아홉 번째가 된다. 그래서 계약이 있으면 자유
    #     문장(motion_prompt)보다 **앞에** 둔다 — 시간축이 연출을 지배한다.
    beats = cut.get("temporal_plan") or []
    if beats and config.VEO_BEAT_ACTION_PROSE:
        # ★ 행동 먼저·카메라 한 벌(config.VEO_BEAT_ACTION_PROSE 주석). 2026-09-14 부터 기본 on.
        beat_prose = temporal_plan.action_prose(beats, cut.get("stage_mutations"))
        rest = temporal_plan.strip_camera_clauses(mp)
        rest = rest[:1].upper() + rest[1:]
        motion = f"{beat_prose}. {rest}" if rest else beat_prose
    elif beats:
        beat_prose = temporal_plan.prose(beats)
        motion = f"{beat_prose}. {motion}" if mp else beat_prose
    body = config.VEO_CONTINUATION_INSTRUCTION + motion
    parts = [p for p in (body, role_style) if p]
    return f"{', '.join(parts)}, vertical 9:16, {config.BURN_IN_NEGATIVE_PROMPT}"


def _veo_i2v(cut: dict[str, Any], header: dict[str, Any], out_path: str,
             duration: int, start_image: str, spec: Any = None) -> tuple[str, float]:
    """Google Veo I2V: 스틸(첫 프레임) + 프롬프트 → 짧은 영상 클립. 비동기(operation) 폴링.

    ★ 미검증: Gemini API Veo 계약(predictLongRunning/응답 형태)은 키로 실제 검증 필요.
    프롬프트는 컷 visual_prompt(카메라·모션 구절 포함) + 9:16 앵커. 나레이션은 파이프라인이 별도로 얹음.
    """
    config.SECRETS.require("gemini_api_key")
    key = config.SECRETS.gemini_api_key
    with open(start_image, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = build_motion_prompt(cut, header)
    # ★★ 호출측이 정한 길이·모델을 **그대로 쓴다**(코덱스 리뷰 P0-2, 2026-08-31).
    #
    #   종전에는 여기서 `pick_clip_tier()` 를 **다시 불러** 전역 상한으로 묶었다.
    #   그래서 상류가 VideoSpec 에 `clip_sec=8`(invest 등급)을 적어도 provider 가
    #   4초로 되돌릴 수 있었다 — 예상 스펙과 발주 스펙이 갈라지는 자리다.
    #   티어 선택은 **한 번만**, 스펙을 만들 때 한다(render.py).
    #
    #   ★ 모델도 같다. 전역 `VEO_MODEL` 을 직접 읽으면 등급별 모델 표가 무력해진다.
    clip_sec = int(spec.clip_sec) if spec is not None else pick_clip_tier(
        float(duration or 0) or config.VEO_CLIP_SEC)
    model = spec.model if spec is not None else config.VEO_MODEL
    submit_url = f"{config.GEMINI_BASE}/{model}:predictLongRunning"
    body = {
        "instances": [{
            "prompt": prompt,
            "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/png"},
        }],
        # ★ generateAudio 는 이 Veo 모델의 predictLongRunning 이 거부한다(400) → 넣지 않는다(무음이 기본).
        #   resolution 도 일부 프리뷰 모델에서 미지원일 수 있어 env 로 껐다 켤 수 있게 한다.
        "parameters": {
            "aspectRatio": "9:16",
            "durationSeconds": clip_sec,
            **({"resolution": config.VEO_RESOLUTION} if config.VEO_SEND_RESOLUTION else {}),
        },
    }
    # ★ Files API 다운로드는 서명된 스토리지 URL 로 리다이렉트되므로 follow_redirects 필수.
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC, follow_redirects=True) as client:
        resp = client.post(submit_url, headers=gemini_auth(), json=body)
        if resp.status_code >= 400:
            raise _VeoError(f"veo submit {resp.status_code}: {resp.text[:200]}")
        op_name = resp.json().get("name")
        if not op_name:
            raise _VeoError("veo: operation name 없음")

        deadline = config.VEO_POLL_TIMEOUT_SEC
        waited = 0.0
        resp_obj: dict[str, Any] | None = None
        while waited < deadline:
            time.sleep(config.VEO_POLL_INTERVAL_SEC)
            waited += config.VEO_POLL_INTERVAL_SEC
            poll = client.get(f"{config.GEMINI_BASE.rsplit('/models', 1)[0]}/{op_name}",
                              headers=gemini_auth())
            if poll.status_code >= 400:
                raise _VeoError(f"veo poll {poll.status_code}: {poll.text[:200]}")
            data = poll.json()
            if data.get("done"):
                if data.get("error"):
                    raise _VeoError(f"veo operation error: {str(data['error'])[:300]}")
                resp_obj = data.get("response") or {}
                break
        if resp_obj is None:
            raise _VeoError("veo: 폴링 타임아웃(operation 미완료)")

        # 완료 응답에서 첫 샘플의 비디오를 찾는다. Veo/Gemini 는 보통 파일 uri 로 준다(base64 폴백).
        samples = (resp_obj.get("generateVideoResponse", {}).get("generatedSamples")
                   or resp_obj.get("generatedVideos") or resp_obj.get("videos") or [])
        video_uri: str | None = None
        video_b64: str | None = None
        if isinstance(samples, list) and samples:
            v0 = samples[0] or {}
            vid = v0.get("video") if isinstance(v0.get("video"), dict) else v0
            video_uri = vid.get("uri") or vid.get("videoUri") or v0.get("uri")
            video_b64 = vid.get("bytesBase64Encoded") or v0.get("bytesBase64Encoded")

        if video_uri:
            # 파일 uri 다운로드. Files API 는 실제 바이트 다운로드에 alt=media 가 필수(없으면 400).
            # ★ 여기서부터의 실패는 operation 이 done=True·에러 없음을 지난 뒤라 생성 자체는 끝났다
            #   (과금 유력) → VeoBilledRejection 으로 구분해 실효 비용을 원장에 남긴다(§8.5).
            dl = client.get(video_uri, headers=gemini_auth(), params={"alt": "media"})
            if dl.status_code >= 400:
                raise VeoBilledRejection(f"veo download {dl.status_code}: {dl.text[:150]}", clip_sec)
            content = dl.content
            # 유효한 mp4 인지 검증(ftyp 박스 + 최소 크기). 아니면 스틸 폴백(깨진 클립으로 렌더 실패 방지).
            if len(content) < 1024 or b"ftyp" not in content[:64]:
                raise VeoBilledRejection(
                    f"veo: 다운로드가 mp4 아님(size={len(content)}, head={content[:16]!r})", clip_sec)
            with open(out_path, "wb") as fout:
                fout.write(content)
        elif video_b64:
            with open(out_path, "wb") as fout:
                fout.write(base64.b64decode(video_b64))
        else:
            # 구조 불일치 → 실제 응답을 로그로 남겨 다음에 정확히 파싱.
            import json as _json
            raise _VeoError(f"veo: 영상 uri/base64 없음. response={_json.dumps(resp_obj)[:600]}")

    # 단가도 스펙에서 온다 — 원장이 "무엇으로 만들었는지"와 "얼마인지"를 같은 곳에서 읽는다.
    per_sec = float(spec.unit_price_usd) if spec is not None else config.VEO_COST_PER_SEC_USD
    cost = clip_sec * per_sec
    return out_path, cost


def generate_clip(cut: dict[str, Any], header: dict[str, Any], out_path: str,
                  duration: int, lang: str = "ko",
                  start_image: str | None = None,
                  fact_sheet: dict[str, Any] | None = None,
                  spec: Any = None) -> tuple[str, float]:
    # I2V(hybrid): 스틸 첫 프레임 → 영상. Manim 우회, VIDEO_PROVIDER 사용.
    if start_image is not None:
        provider = config.VIDEO_PROVIDER
        if provider == "veo":
            return _veo_i2v(cut, header, out_path, duration, start_image, spec)
        if provider == "higgsfield":
            raise NotImplementedError("higgsfield I2V 는 미배선(VIDEO_PROVIDER=veo 사용)")
        # placeholder 등 미배선 → 예외로 올려 render.py 가 스틸로 폴백.
        raise NotImplementedError(f"I2V 영상 제공자 미배선: {provider}")

    # ③ 고효율 씬(motion_graphic/kinetic_typography/data_viz)·animation 버전은 Manim(무음·무료).
    use_manim = header.get("version_type") == "animation" \
        or cut.get("scene_kind") in config.SCENE_HIGH_EFFORT_KINDS
    provider = config.ANIMATION_ENGINE if use_manim else config.VIDEO_PROVIDER
    if provider == "manim":
        from .. import manim_templates
        # fact_sheet 를 흘려 코드 차트 수치를 원장에서 해소한다(M-E4, engine/claim_viz.py).
        manim_templates.render_cut_clip(cut, header, out_path, duration, lang, fact_sheet)
        return out_path, 0.0
    if provider == "higgsfield":
        raise NotImplementedError("higgsfield I2V 는 P-V1(M-V7)에서 배선")
    raise NotImplementedError(f"video 제공자 미지원: {provider}")
