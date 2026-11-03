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
from dataclasses import dataclass
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
    # ★ 화풍 부정어(발광·네온·블룸 금지)는 이미지 경로에만 있었다(2026-09-24 2차 렌더 실측:
    #   시작 프레임은 무광이었는데 클립 끝에서 피스톤이 **빛났다**). 클립에도 같은 안전망을 싣는다.
    neg = config.VISUAL_ROLE_NEGATIVE.get(role, "")
    parts = [p for p in (body, role_style, neg) if p]
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


# ─────────────────────────────────────────────────────────────
# 설명형 공급자 어댑터(기획 v2 §3-2, 2026-11-02). ★ 실제 호출 0회 — 요청 모양·응답 해석 순수 함수와 그 단위 테스트만 있다.
#
# 기존 Veo 경로(_veo_i2v·generate_clip)와 나란히 둔다. 그쪽은 종료된 미리보기 모델(config.VEO_MODEL)을 부르며 건드리지 않았다.
# 이 어댑터는 렌더에서 닿지 않는다: drinks_explainer 는 이 모듈을 import 하지 않고(정적 시험), 전송은
# send_explainer_request 하나뿐이며 config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED + 결재 id 가 없으면 거절한다.
#
# ★ 2026-11-02 공식 문서 대조(ai.google.dev/api/interactions · /gemini-api/docs/omni · /api/models · /gemini-api/docs/pricing). 호출은 하지 않았다.
# [검증됨 — 문서] ① Omni
#   · 주소 POST v1beta/interactions, 인증 x-goog-api-key 헤더. 기본은 동기(한 응답에 status=completed). background·store·stream 은 false 권장.
#   · input 은 블록 배열: {"type":"image","data":<base64>,"mime_type":"image/png"} · {"type":"text","text":…}.
#   · generation_config.video_config.task = "image_to_video": **첫 그림이 시작 프레임, 둘째 그림(선택)이 끝 프레임** — §3-5 이어 그리기의 전제가 문서로 확인됐다.
#   · response_format = {"type":"video","aspect_ratio":"9:16"|"16:9","resolution":"360p"|"720p"|"1080p"|"4k","delivery":"inline"|"uri","duration":<문자열>}.
#   · 영상 위치: steps[].{type:"model_output"}.content[].{type:"video", mime_type:"video/mp4", data:<base64>} (delivery=uri 면 data 대신 uri — Files API 폴링 뒤 :download?alt=media).
#   · usage.total_output_tokens · output_tokens_by_modality[{modality:"video", tokens}]. 단가 $17.50/100만 토큰, 720p 초당 5,792토큰.
#   · GET v1beta/interactions/{id} 로 다시 받을 수 있다(inline 으로 온다) → unknown_billed 를 조회로 정정할 길이 있다(§3-3).
#   · 부정 프롬프트 칸은 없다(문서: "negative prompts are not supported as a parameter" — 문장에 쓴다). seed 칸도 영상에는 없다.
#   · 무료 사전 검증: GET v1beta/models/{model} → {name, displayName, supportedGenerationMethods[] …}.
# [미검증] ① Omni
#   · response_format.duration 의 **형식**(칸만 있고 설명 없음). "8s"(protobuf Duration 표기)로 보낸다 — 틀리면 400 → ExplainerNotSent(청구 없음)로 멈춘다.
#     그래도 받은 길이는 E5 가 잰다. 기본 길이·3~10초 범위도 문서에 없다(확장 구간 3~10초만 있다).
#   · 실제 응답에서 영상이 정말 steps 안에 오는지(문서 설명은 있으나 예시 응답은 글 모델 것뿐이다). 모양이 다르면 지어내지 않고 ExplainerOutcomeUnknown.
#   · supportedGenerationMethods 에 어떤 이름이 오는지 — 사전 검증은 모델 **존재**만 거부 조건으로 쓰고 메서드 이름은 기록한다.
# [미검증] ②③ Vertex: 가격표의 "1 count" = 1초 해석, generateAudio·seed·lastFrame 칸 이름, 지원 종료(2026-11-17 이후) 뒤 후속 모델. 전송 미연결.
# ─────────────────────────────────────────────────────────────

class ExplainerProviderError(RuntimeError):
    """요청을 만들 수 없거나(규격 밖), 응답을 해석할 수 없다. 조용히 넘기지 않는다."""


class ExplainerNotSent(ExplainerProviderError):
    """청구 없음이 확실한 실패 — 보내지 않았거나 공급자가 명시적으로 거절했다(4xx). 시도는 failed_unbilled."""


class ExplainerSendRefused(ExplainerNotSent):
    """실제 전송 거절 — 스위치·결재가 없다. 렌더 경로에서는 절대 열리지 않는다."""


class ExplainerOutcomeUnknown(ExplainerProviderError):
    """보냈는데 결과를 모른다(끊김·제한시간·5xx·읽을 수 없는 200 응답). 시도는 unknown_billed — 자동으로 다시 부르지 않는다(§3-3)."""


class ExplainerBilledBadFile(ExplainerProviderError):
    """받았는데 파일로 쓸 수 없다 — 청구 유력. 시도는 failed_billed, 재시도는 새 결재로만(§3-3)."""


@dataclass(frozen=True)
class ExplainerClipInput:
    """공통 입력(§3-2): 시작 그림, (선택) 끝 그림, 움직임 문장, 길이, 해상도, 후보 번호."""
    start_image_b64: str
    motion_prompt: str
    clip_sec: int
    resolution: str = "720p"
    candidate_k: int = 1
    end_image_b64: str = ""
    image_mime: str = "image/png"
    seed: int | None = None       # [미검증] 공급자가 받으면 후보마다 다르게 준다


@dataclass(frozen=True)
class ExplainerRequest:
    """보낼 것 전부 — 비밀값은 싣지 않는다. auth 는 전송할 때 붙일 인증 종류 이름이다."""
    provider: str
    method: str
    url: str
    body: dict[str, Any]
    auth: str                     # gemini_api_key | gcp_bearer
    billing_unit: str             # tokens | seconds_unverified
    unverified: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplainerParsed:
    """응답 해석 결과. video_bytes 또는 gcs_uri 중 하나."""
    provider: str
    request_id: str
    billing_unit: str
    billed_units: float | None
    video_bytes: bytes = b""
    gcs_uri: str = ""
    done: bool = True


@dataclass(frozen=True)
class ExplainerClipOutput:
    """공통 출력(§3-2): mp4 파일, 실측 길이, 공급자 요청 ID, 청구 단위."""
    path: str
    measured_ms: int
    width: int | None
    height: int | None
    frames: int
    request_id: str
    billing_unit: str
    billed_units: float | None


OMNI_UNVERIFIED: tuple[str, ...] = ("response_format.duration 형식('8s')", "실제 응답에서 영상이 steps 안에 오는지", "기본 길이·길이 범위", "supportedGenerationMethods 이름")
OMNI_VERIFIED_BY_DOCS: tuple[str, ...] = ("input 블록 모양(type/data/mime_type)", "video_config.task=image_to_video 첫 그림 = 시작 프레임",
                                           "response_format aspect_ratio·resolution·delivery", "영상 위치 steps[].content[].type=video", "usage.total_output_tokens",
                                           "GET interactions/{id} 조회", "단가 $17.50/M 토큰·720p 초당 5,792토큰")


def omni_duration_value(clip_sec: int) -> str:
    """response_format.duration 문자열. [미검증] protobuf Duration 표기("8s")로 보낸다 — 문서에 칸만 있고 예시가 없다."""
    return f"{int(clip_sec)}s"


def build_omni_request(clip: ExplainerClipInput) -> ExplainerRequest:
    """① Gemini Omni Flash — POST v1beta/interactions(동기). 모양은 2026-11-02 문서 그대로(모듈 머리 주석의 검증됨/미검증 표)."""
    lo, hi = config.DRINKS_EXPLAINER_OMNI_SEC_RANGE
    if not lo <= int(clip.clip_sec) <= hi:
        raise ExplainerProviderError(f"Omni 출력 길이는 {lo}~{hi}초입니다: {clip.clip_sec}")
    if clip.resolution not in config.DRINKS_EXPLAINER_OMNI_RESOLUTIONS:
        raise ExplainerProviderError(f"Omni 해상도가 아닙니다: {clip.resolution}")
    if not clip.start_image_b64 or not clip.motion_prompt.strip():
        raise ExplainerProviderError("시작 그림과 움직임 문장이 필요합니다")
    parts: list[dict[str, Any]] = [{"type": "image", "mime_type": clip.image_mime, "data": clip.start_image_b64}]
    if clip.end_image_b64:
        parts.append({"type": "image", "mime_type": clip.image_mime, "data": clip.end_image_b64})
    # 길이는 전용 칸(duration)과 문장 둘 다에 말한다 — 칸의 형식이 미검증이라 문장이 안전망이다. 실제 길이는 받은 뒤 E5 가 잰다.
    parts.append({"type": "text", "text": f"{clip.motion_prompt.strip()} About {int(clip.clip_sec)} seconds."})
    fmt: dict[str, Any] = {"type": "video", "aspect_ratio": "9:16", "resolution": clip.resolution, "delivery": config.DRINKS_EXPLAINER_OMNI_DELIVERY}
    if config.DRINKS_EXPLAINER_OMNI_SEND_DURATION:
        fmt["duration"] = omni_duration_value(clip.clip_sec)
    body = {"model": config.DRINKS_EXPLAINER_OMNI_MODEL, "input": parts,
            "generation_config": {"video_config": {"task": config.DRINKS_EXPLAINER_OMNI_TASK}},
            "response_format": fmt,
            # 문서 권장: 동기·보관 없음·스트림 없음. store=false 면 previous_interaction_id 편집은 못 하지만 우리는 편집하지 않는다.
            "background": False, "store": False, "stream": False}
    return ExplainerRequest(provider="omni", method="POST", url=config.DRINKS_EXPLAINER_OMNI_URL, body=body,
                            auth="gemini_api_key", billing_unit="tokens", unverified=OMNI_UNVERIFIED)


def build_omni_fetch_request(interaction_id: str) -> ExplainerRequest:
    """GET v1beta/interactions/{id} — 보낸 뒤 결과를 모르는 시도(unknown_billed)를 조회로 정정한다[문서]. 돈이 들지 않는다(조회)."""
    iid = str(interaction_id or "").strip()
    if not iid or "/" in iid:
        raise ExplainerProviderError("조회할 interaction id 가 없습니다")
    return ExplainerRequest(provider="omni", method="GET", url=f"{config.DRINKS_EXPLAINER_OMNI_INTERACTIONS_URL}/{iid}", body={},
                            auth="gemini_api_key", billing_unit="tokens")


def _omni_video_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for step in (data or {}).get("steps") or []:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for c in step.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "video":
                out.append(c)
    return out


def omni_billed_units(data: dict[str, Any]) -> float | None:
    """청구 토큰 — 영상 모달리티 출력 토큰이 있으면 그것, 없으면 total_output_tokens[문서]."""
    usage = (data or {}).get("usage") or {}
    for row in usage.get("output_tokens_by_modality") or []:
        if isinstance(row, dict) and row.get("modality") == "video" and row.get("tokens") is not None:
            return float(row["tokens"])
    units = usage.get("total_output_tokens")
    return float(units) if units is not None else None


def parse_omni_response(data: dict[str, Any]) -> ExplainerParsed:
    """Interaction 자원 → 영상. 문서 모양: {id, status, steps:[{type:"model_output", content:[{type:"video", data|uri, mime_type}]}], usage}.
    status 가 completed 가 아니면 아직(또는 실패)이다. 영상이 없으면 지어내지 않고 멈춘다."""
    status = str((data or {}).get("status") or "")
    rid = str((data or {}).get("id") or "")
    if status in ("in_progress", "requires_action", "requires_continuation"):
        return ExplainerParsed(provider="omni", request_id=rid, billing_unit="tokens", billed_units=omni_billed_units(data), done=False)
    if status and status != "completed":
        raise ExplainerProviderError(f"Omni interaction 이 끝나지 않았습니다: status={status}")
    blocks = _omni_video_blocks(data)
    if not blocks:
        raise ExplainerProviderError(f"Omni 응답에 영상이 없습니다: keys={sorted((data or {}).keys())}, status={status or '-'}")
    v = blocks[0]
    raw = b""
    if v.get("data"):
        try:
            raw = base64.b64decode(v["data"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ExplainerProviderError("Omni 응답의 영상이 base64 가 아닙니다") from exc
    elif not v.get("uri"):
        raise ExplainerProviderError("Omni 영상 블록에 data 도 uri 도 없습니다")
    return ExplainerParsed(provider="omni", request_id=rid, billing_unit="tokens", billed_units=omni_billed_units(data),
                           video_bytes=raw, gcs_uri=str(v.get("uri") or ""))


@dataclass(frozen=True)
class OmniPreflight:
    """무료 사전 검증(GET models/{model}) 결과. ok 가 거짓이면 구매 호출을 **보내기 전에** 거절한다."""
    ok: bool
    model: str
    reason: str = ""
    display_name: str = ""
    methods: tuple[str, ...] = ()
    version: str = ""


def evaluate_omni_model_listing(status_code: int, data: Any, model: str | None = None) -> OmniPreflight:
    """GET v1beta/models/{model} 응답 판정(순수). 404 → 모델 없음(거절). name 불일치 → 거절. 메서드 이름은 기록만(미검증)."""
    want = model or config.DRINKS_EXPLAINER_OMNI_MODEL
    if status_code == 404:
        return OmniPreflight(False, want, "모델이 목록에 없습니다(404) — 이름이 바뀌었거나 종료됐습니다")
    if status_code >= 400:
        return OmniPreflight(False, want, f"모델 조회 실패 {status_code}")
    d = data if isinstance(data, dict) else {}
    name = str(d.get("name") or "")
    if name.split("/")[-1] != want:
        return OmniPreflight(False, want, f"모델 이름이 다릅니다: {name or '(없음)'}")
    methods = tuple(str(m) for m in d.get("supportedGenerationMethods") or [])
    return OmniPreflight(True, want, "", str(d.get("displayName") or ""), methods, str(d.get("version") or ""))


def omni_preflight(client: Any = None) -> OmniPreflight:
    """무료 GET 한 번 — 생성 호출이 아니다. 키가 없으면 보내지 않고 거절한다."""
    if not config.SECRETS.gemini_api_key:
        return OmniPreflight(False, config.DRINKS_EXPLAINER_OMNI_MODEL, "GEMINI_API_KEY 가 없습니다")
    url = f"{config.DRINKS_EXPLAINER_OMNI_MODELS_URL}/{config.DRINKS_EXPLAINER_OMNI_MODEL}"
    own = client is None
    http = client or httpx.Client(timeout=config.DRINKS_EXPLAINER_OMNI_PREFLIGHT_TIMEOUT_SEC)
    try:
        resp = http.get(url, headers=gemini_auth())
    except httpx.HTTPError as exc:
        return OmniPreflight(False, config.DRINKS_EXPLAINER_OMNI_MODEL, f"모델 조회에 닿지 못했습니다: {type(exc).__name__}")
    finally:
        if own:
            http.close()
    try:
        data = resp.json()
    except ValueError:
        data = None
    return evaluate_omni_model_listing(resp.status_code, data)


def _vertex_base(project: str) -> str:
    if not project.strip():
        raise ExplainerProviderError("Vertex 는 구글 클라우드 프로젝트가 필요합니다")
    loc = config.DRINKS_EXPLAINER_VERTEX_LOCATION
    return (f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}"
            f"/publishers/google/models/{config.DRINKS_EXPLAINER_VERTEX_MODEL}")


def build_vertex_veo_request(clip: ExplainerClipInput, project: str, storage_uri: str = "") -> ExplainerRequest:
    """② Veo 3.1 Fast(Vertex) — predictLongRunning + fetchPredictOperation 폴링. 인증은 서비스 계정 토큰(API 키 방식은 문서에서 확인 못 함)."""
    if int(clip.clip_sec) not in config.DRINKS_EXPLAINER_VERTEX_SEC_TIERS:
        raise ExplainerProviderError(f"Veo 3.1 Fast 길이는 {config.DRINKS_EXPLAINER_VERTEX_SEC_TIERS} 중 하나입니다: {clip.clip_sec}")
    if clip.resolution not in config.DRINKS_EXPLAINER_VERTEX_RESOLUTIONS:
        raise ExplainerProviderError(f"Veo 3.1 Fast 해상도가 아닙니다: {clip.resolution}")
    if not clip.start_image_b64 or not clip.motion_prompt.strip():
        raise ExplainerProviderError("시작 그림과 움직임 문장이 필요합니다")
    instance: dict[str, Any] = {"prompt": clip.motion_prompt.strip(), "image": {"bytesBase64Encoded": clip.start_image_b64, "mimeType": clip.image_mime}}
    if clip.end_image_b64:
        instance["lastFrame"] = {"bytesBase64Encoded": clip.end_image_b64, "mimeType": clip.image_mime}
    params: dict[str, Any] = {"aspectRatio": "9:16", "durationSeconds": int(clip.clip_sec), "resolution": clip.resolution,
                              "sampleCount": 1, "generateAudio": False}
    if storage_uri:
        params["storageUri"] = storage_uri
    if clip.seed is not None:
        params["seed"] = int(clip.seed)
    return ExplainerRequest(provider="veo_fast", method="POST", url=f"{_vertex_base(project)}:predictLongRunning",
                            body={"instances": [instance], "parameters": params}, auth="gcp_bearer", billing_unit="seconds_unverified",
                            unverified=("1 count = 1초", "generateAudio·seed·lastFrame 칸 이름", "2026-11-17 이후 지원"))


def build_vertex_fetch_request(operation_name: str, project: str) -> ExplainerRequest:
    if not operation_name:
        raise ExplainerProviderError("작업 이름이 없습니다")
    return ExplainerRequest(provider="veo_fast", method="POST", url=f"{_vertex_base(project)}:fetchPredictOperation",
                            body={"operationName": operation_name}, auth="gcp_bearer", billing_unit="seconds_unverified")


def parse_vertex_operation(data: dict[str, Any], clip_sec: int) -> ExplainerParsed:
    """fetchPredictOperation 응답. done=False 면 아직이다(결과 없음). 영상은 response.videos[0] 의 gcsUri(버킷) 또는 bytesBase64Encoded."""
    name = str((data or {}).get("name") or "")
    if not (data or {}).get("done"):
        return ExplainerParsed(provider="veo_fast", request_id=name, billing_unit="seconds_unverified", billed_units=None, done=False)
    if data.get("error"):
        raise ExplainerProviderError(f"Veo 작업 오류: {str(data['error'])[:300]}")
    videos = ((data.get("response") or {}).get("videos")) or []
    v0 = videos[0] if videos and isinstance(videos[0], dict) else {}
    uri, b64 = str(v0.get("gcsUri") or ""), v0.get("bytesBase64Encoded")
    if not uri and not b64:
        raise ExplainerProviderError(f"Veo 응답에 영상이 없습니다: keys={sorted((data.get('response') or {}).keys())}")
    return ExplainerParsed(provider="veo_fast", request_id=name, billing_unit="seconds_unverified", billed_units=float(clip_sec),
                           video_bytes=base64.b64decode(b64) if b64 else b"", gcs_uri=uri)


def store_parsed_clip(parsed: ExplainerParsed, out_path: str) -> ExplainerClipOutput:
    """받은 바이트를 저장하고 실제로 잰다(E5) — 요청 길이를 적지 않는다. 읽히지 않는 파일은 결과로 돌려주지 않는다."""
    from ..drinks_explainer import probe_clip

    if not parsed.video_bytes:
        raise ExplainerProviderError("저장할 영상 바이트가 없습니다(버킷 파일은 먼저 받아야 합니다)")
    with open(out_path, "wb") as fout:
        fout.write(parsed.video_bytes)
    probe = probe_clip(out_path)
    if not probe["ok"] or not probe["has_video"] or probe["still"]:
        raise ExplainerProviderError(f"받은 파일이 움직이는 영상이 아닙니다: {probe['error'][:200]}")
    return ExplainerClipOutput(path=out_path, measured_ms=int(probe["duration_ms"]), width=probe["width"], height=probe["height"],
                               frames=int(probe["frames"]), request_id=parsed.request_id, billing_unit=parsed.billing_unit, billed_units=parsed.billed_units)


def send_explainer_request(req: ExplainerRequest, *, approval_id: str, client: Any = None) -> dict[str, Any]:
    """실제 전송 — 스위치가 꺼져 있거나 결재 id 가 없으면 거절한다. 렌더는 이 함수에 닿지 않는다(정적 시험). 재시도하지 않는다."""
    if not config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED:
        raise ExplainerSendRefused("설명형 공급자 전송이 꺼져 있습니다(DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED) — S2 결재 뒤에만 켭니다")
    if not str(approval_id or "").strip():
        raise ExplainerSendRefused("결재 id 가 없는 전송은 하지 않습니다")
    if req.auth == "gemini_api_key":
        config.SECRETS.require("gemini_api_key")
        headers = gemini_auth()
    else:
        raise ExplainerSendRefused(f"이 인증({req.auth})의 전송은 아직 연결하지 않았습니다 — 비밀값은 운영자가 넣습니다(§10-3)")
    own = client is None
    http = client or httpx.Client(timeout=config.DRINKS_EXPLAINER_SEND_TIMEOUT_SEC, follow_redirects=True)
    try:
        resp = http.get(req.url, headers=headers) if req.method == "GET" else http.post(req.url, headers=headers, json=req.body)
    except httpx.HTTPError as exc:
        # 보낸 뒤 끊겼을 수 있다. 예외 문장에 주소·키가 실릴 수 있어 종류 이름만 남긴다.
        raise ExplainerOutcomeUnknown(f"{req.provider} 응답을 받지 못했습니다: {type(exc).__name__}") from None
    finally:
        if own:
            http.close()
    if resp.status_code == 408 or resp.status_code >= 500:
        raise ExplainerOutcomeUnknown(f"{req.provider} {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise ExplainerNotSent(f"{req.provider} {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError:
        raise ExplainerOutcomeUnknown(f"{req.provider} 응답을 읽지 못했습니다(200)") from None


def generate_explainer_clip(clip: ExplainerClipInput, out_path: str, *, provider: str, approval_id: str, idempotency_key: str, client: Any = None) -> ExplainerClipOutput:
    """공급자 어댑터 전체(§3-2): 요청 만들기 → 전송(스위치·결재 없으면 거절) → 해석 → 저장·실측. 재시도하지 않는다.

    실패는 청구 여부로 갈라 올린다: ExplainerNotSent(청구 없음) / ExplainerOutcomeUnknown(모름) / ExplainerBilledBadFile(청구 유력).
    [미검증] 응답 모양·첫 프레임 고정·길이 지정은 S2 전까지 가정이다(이 절 머리 주석). 멱등키를 받는 칸이 문서에 없어 공급자에 보내지 않는다 —
    중복 호출은 시도 표(requested → generating 은 한 번뿐)가 막는다."""
    if provider != "omni":
        raise ExplainerSendRefused(f"이 공급자({provider})의 전송은 아직 연결하지 않았습니다")
    if not str(idempotency_key or "").strip():
        raise ExplainerNotSent("멱등키 없는 호출은 하지 않습니다(시도 행을 먼저 만듭니다)")
    try:
        req = build_omni_request(clip)
    except ExplainerProviderError as exc:
        raise ExplainerNotSent(str(exc)) from exc
    if config.DRINKS_EXPLAINER_OMNI_PREFLIGHT_ENABLED and config.DRINKS_EXPLAINER_PROVIDER_SEND_ENABLED and str(approval_id or "").strip():
        # 무료 조회로 모델이 있는지 먼저 본다 — 모양이 다르면 unknown_billed 가 아니라 **보내기 전에** 거절한다(청구 없음).
        pre = omni_preflight(client)
        if not pre.ok:
            raise ExplainerNotSent(f"사전 검증 실패(보내지 않음): {pre.reason}")
    data = send_explainer_request(req, approval_id=approval_id, client=client)
    try:
        parsed = parse_omni_response(data)
    except ExplainerProviderError as exc:
        raise ExplainerOutcomeUnknown(str(exc)) from exc
    if not parsed.done:
        raise ExplainerOutcomeUnknown(f"Omni interaction 이 아직 진행 중입니다(id={parsed.request_id or '-'}) — 조회(GET interactions/{{id}})로 정정합니다")
    if not parsed.video_bytes and parsed.gcs_uri:
        parsed = _omni_download_uri(parsed, client)
    try:
        return store_parsed_clip(parsed, out_path)
    except ExplainerProviderError as exc:
        raise ExplainerBilledBadFile(str(exc)) from exc


def _omni_download_uri(parsed: ExplainerParsed, client: Any = None) -> ExplainerParsed:
    """delivery=uri 로 왔을 때(우리는 inline 을 요청하지만 문서가 둘 다 허용한다). Files API :download?alt=media[문서]. 여기부터의 실패는 청구 유력이다."""
    own = client is None
    http = client or httpx.Client(timeout=config.DRINKS_EXPLAINER_SEND_TIMEOUT_SEC, follow_redirects=True)
    try:
        resp = http.get(parsed.gcs_uri, headers=gemini_auth(), params={"alt": "media"})
    except httpx.HTTPError as exc:
        raise ExplainerBilledBadFile(f"영상 내려받기에 닿지 못했습니다: {type(exc).__name__}") from None
    finally:
        if own:
            http.close()
    if resp.status_code >= 400:
        raise ExplainerBilledBadFile(f"영상 내려받기 {resp.status_code}")
    return ExplainerParsed(provider=parsed.provider, request_id=parsed.request_id, billing_unit=parsed.billing_unit, billed_units=parsed.billed_units,
                           video_bytes=resp.content, gcs_uri=parsed.gcs_uri)


def fetch_omni_interaction(interaction_id: str, *, approval_id: str, client: Any = None) -> ExplainerParsed:
    """결과를 모르는 시도를 조회로 정정한다(§3-3). 생성 호출이 아니라 GET 이지만, 스위치·결재 게이트는 같은 함수(send_explainer_request)를 지난다."""
    req = build_omni_fetch_request(interaction_id)
    data = send_explainer_request(req, approval_id=approval_id, client=client)
    return parse_omni_response(data)


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
