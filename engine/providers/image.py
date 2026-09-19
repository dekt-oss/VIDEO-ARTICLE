"""이미지 제공자. P-V0: placeholder(단색+ASCII 라벨 9:16 PNG). P-V1: gemini(nano banana).

placeholder 라벨은 CI 폰트 의존을 피하려 ASCII 만 쓴다(한글 자막 번인은 조립 단계에서 처리).
반환: (asset_path, cost_usd).
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .. import config, generation_spec, sequence_render, visual_sequence
from ..util import RateLimiter, gemini_auth, log

_image_limiter = RateLimiter(config.GEMINI_IMAGE_MIN_INTERVAL_SEC)


class _ImageTransientError(RuntimeError):
    """429/5xx 등 재시도 가능한 이미지 생성 오류."""


def _stage_of(cut: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    """이 컷이 담당하는 시퀀스 stage. 없으면 빈 dict(옛 지시서 — 종전 경로)."""
    seqs = (header or {}).get("visual_sequences")
    if not isinstance(seqs, list) or not seqs:
        return {}
    return visual_sequence.cut_to_stage(seqs).get(int(cut.get("cut_no") or 0)) or {}


def _build_image_prompt(cut: dict[str, Any], header: dict[str, Any],
                        *, referenced: bool = False) -> str:
    """visual_prompt + global_style 앵커 + 9:16 규격을 하나의 프롬프트로.

    ★ 품질 접미사는 버전마다 다르다. 기본 "high detail" 은 실사 쪽으로 밀어붙이는 표현이라
      webtoon 에서는 평면 채색 쪽 문구로 바꾸고 화풍 부정어를 구조적으로 덧붙인다 —
      프롬프트 지시만으로는 모델이 실사로 되돌아간다는 것이 1차 샘플에서 확인됐다.
    ★ comic 의 출력 문자열은 **바이트 단위로 이전과 같다**. A/B 비교에서 화면 설계 말고 다른
      변수가 끼면 판정이 무의미해진다.
    """
    gs = str((header or {}).get("global_style") or "").strip()
    vp = str(cut.get("visual_prompt") or "").strip()
    # ★ 참조 이미지를 함께 보낼 때는 **무엇을 유지하고 무엇만 바꾸는지**를 앞에 못박는다.
    #   Phase 0 실측: 이 문구가 없으면 모델이 참조를 받고도 장면을 다시 그린다.
    if referenced:
        stage = _stage_of(cut, header)
        # ★★ 뒤에 붙는 것은 **변화**다. 장면 전체 묘사를 붙이면 "이것만 바꿔라" 하고
        #   전부 바꾸라는 말이 된다(2026-08-30 채팅 실측 — 6장에서 구도가 계속 헤맸다).
        delta = (sequence_render.change_prose(stage)
                 if (config.SEQUENCE_REFERENCE_USES_DELTA and stage) else "")
        # ★ 새로 등장하는 개체는 **어떻게 생겼는지도** 말해야 한다(2026-08-30 채팅 실측).
        #   안 그러면 모델이 알아서 정한다 — 궤적선을 "파란 선"으로 선언해 뒀는데
        #   화면엔 주황색으로 나왔다(화풍의 amber accent 가 대신 결정했다).
        looks = sequence_render.appearing_entity_prose(stage, stage.get("_sequence"))
        if looks:
            delta = f"{delta} ({looks})" if delta else looks
        # ★ 도해 구조의 **변화·강조만** 덧붙인다(2026-09-18, 연구 T1-a). 전·후를 다 말하면
        #   "이것만 바꿔라"와 싸운다 — 그래서 referenced 변형을 따로 둔다.
        if config.IMAGE_PROMPT_CARRIES_MECHANISM:
            mech = visual_sequence.mechanism_prose(cut, referenced=True)
            if mech:
                delta = f"{delta}. {mech}" if delta else mech
        head = (config.SEQUENCE_REFERENCE_INSTRUCTION_MOVING
                if str(stage.get("camera_operation") or "HOLD") != "HOLD"
                else config.SEQUENCE_REFERENCE_INSTRUCTION)
        body = head + (delta or vp or "the scene continues")
    else:
        # ★★ **세계 선언을 프롬프트에 싣는다**(2026-09-08). 여기가 오래 끊겨 있었다 —
        #   `visual_sequence.world_prose` 는 world 의 style·lighting·background 를 한 줄로
        #   만드는 함수인데 **저장소 어디에서도 불리지 않았다.** 즉 지시서가 세계를 선언해도
        #   그림에는 닿지 않았고, 세계는 장식이었다.
        #   실측 사고(2026-09-07 시퀀스 렌더): world 가 "cutaway teaching model of an animal
        #   cell" 이라고 선언했는데 그 세계를 여는 컷이 벤 다이어그램을 그렸고, **세포 모형이
        #   영상에서 통째로 사라졌다**(뒤 stage 가 참조로 그 오해를 물려받는다).
        #   낱말 겹침으로 어긋남을 잡아 보려 했지만 "studio tabletop" 을 공유해 통과했다 —
        #   대리 판정으로 막을 문제가 아니라 **세계를 실제로 보내야 하는** 문제였다.
        #
        # ★ 왜 지금까지 잇지 않았나: world 선언 안에 실패 어휘가 들어 있었다
        #   ("Soft, internal glow" · "blurred cellular matrix"). 그대로 이으면 발광·흐림이
        #   프롬프트에 실려 더 나빠진다. 이제 그 어휘는 게이트가 막고 코드가 걷어낸다
        #   (`photo_contract.normalize_optics` · `photo_style_word_in_prompt`).
        #   **선언을 청소한 다음에 배선한다** — 순서가 중요했다.
        #
        # ★★★ 참조 컷에는 붙이지 않는다(위 분기). 거기서는 첨부한 그림이 이미 세계를
        #   확정했고, 세계를 말로 다시 설명하면 "이것만 바꿔라"와 싸운다.
        world = ""
        if config.IMAGE_PROMPT_CARRIES_WORLD:
            stage = _stage_of(cut, header)
            world = visual_sequence.world_prose(
                ((stage or {}).get("_sequence") or {}).get("world") or {})
        # ★★ **도해 구조를 프롬프트에 싣는다**(2026-09-18, 연구_기전시퀀스_교육력 T1-a).
        #   `mechanism` 은 지시서가 채우고 게이트가 검사했지만 여기까지 **오지 않았다** —
        #   world_prose 가 그랬던 것과 똑같은 "만들고 배선 안 함"이었다(연구 §3-1). 그래서
        #   구조가 완벽한 컷도 화면은 visual_prompt 의 배경 사진이었다. 세계 다음, 장면 앞에
        #   놓는다 — 무엇이 보여야 하고 무엇이 바뀌는지가 장면 묘사보다 먼저다.
        #   mechanism 이 없는 컷·버전(comic 등)은 빈 문자열이라 출력이 바이트 단위로 같다.
        mech = (visual_sequence.mechanism_prose(cut)
                if config.IMAGE_PROMPT_CARRIES_MECHANISM else "")
        parts = [p for p in (gs, world, mech, vp) if p]
        body = ", ".join(parts) if parts else "abstract conceptual illustration"
    version = str((header or {}).get("version_type") or "")
    # ★ 컷 화면 역할이 있으면 그것이 버전 접미사를 이긴다(2026-08-20). 같은 실사형 안에서도
    #   3D 도해 컷과 실사 컷의 화풍이 달라야 한다 — 단면·흐름은 사진으로 못 찍고, 현장 앵커는
    #   3D 로 그리면 신뢰를 잃는다. 역할이 없는 컷·버전은 예전 경로 그대로다(출력 불변).
    # ★★ 역할은 **정본에서 온다**(2026-08-30 프롬프트 실측). 옛 `visual_role` 을 그대로
    #   읽었더니 시퀀스 한복판에서 화풍이 뒤집혔다:
    #     1단계(라벨 REALITY)  … not an illustration, no 3D render, no painting
    #     2단계(라벨 MECHANISM) … not a photograph, no photorealistic texture
    #   그러면서 2단계 프롬프트는 "앞 이미지와 SAME setting/lighting/materials 를 유지하라"
    #   고 말한다 — **사진으로 만든 그림을 첨부하고 사진이면 안 된다고 하는 것**이다.
    #   사슬이 이어질 수가 없다.
    #   모델 선택(generation_spec)과 화풍 선택이 서로 다른 값을 보고 있었다. 같은 값을 본다.
    role = generation_spec.effective_visual_role(cut)
    quality = config.VISUAL_ROLE_STYLE.get(
        role, config.IMAGE_QUALITY_SUFFIX_BY_VERSION.get(
            version, config.DEFAULT_IMAGE_QUALITY_SUFFIX))
    # ★★ 참조 컷에서는 **다시 칠하라는 문구를 뗀다**(2026-08-30 실측).
    #   "설명 중인 부품을 호박색으로" 는 컷마다 대상이 바뀌므로 정의상 물체 색을 매 컷
    #   바꾼다. 같은 프롬프트의 "keep the SAME materials" 와 정면으로 싸우고, 실제로
    #   은색 엔진이 금색이 됐다. 첫 컷에서는 옳은 규칙이라 그대로 둔다 —
    #   이어지는 컷에서는 참조 이미지가 이미 재질을 확정했다.
    if referenced:
        for clause in config.STYLE_CLAUSES_DROPPED_WHEN_REFERENCED:
            quality = quality.replace(f", {clause}", "").replace(clause, "")
    # ★ 버전별 화풍 부정어 표를 직접 본다(config.IMAGE_STYLE_NEGATIVE_BY_VERSION).
    #   예전에는 "품질 접미사 표에 키가 있으면 webtoon 부정어"라는 대리 판정이었는데,
    #   실사형을 추가하는 순간 실사형에 "NOT photorealistic" 이 붙어 정반대로 동작한다.
    #   comic·image_sequence 는 표에 없으므로 출력이 예전과 바이트 단위로 같다.
    neg = config.VISUAL_ROLE_NEGATIVE.get(
        role, config.IMAGE_STYLE_NEGATIVE_BY_VERSION.get(version, ""))
    style_negative = f", {neg}" if neg else ""
    # ★ 설명판형 전용 네거티브(최종명세 v3.3 §21 K1). 공통 BURN_IN_NEGATIVE_PROMPT 에는
    #   `no numbers` 만 있어 **차트·대시보드 모양 자체는 막지 못한다** — 실제로 가짜 대시보드가
    #   그려졌다. 공통 상수를 건드리면 comic 출력이 바뀌므로(바이트 불변 계약) 여기서만 덧붙인다.
    if version == "explainer":
        style_negative += f", {config.EXPLAINER_IMAGE_NEGATIVE_PROMPT}"
    # ⑤ Burn-in 금지(§5.3): 언어 텍스트가 이미지에 구워지면 언어 공유가 깨진다. 공통 negative 제약.
    return (f"{body}, vertical 9:16 portrait aspect ratio, {quality}, "
            f"{config.BURN_IN_NEGATIVE_PROMPT}{style_negative}")


def _aspect_generation_config() -> dict[str, Any]:
    """종횡비를 요청 파라미터로 싣는 generationConfig 조각.

    ★ 프롬프트의 "vertical 9:16" 은 무시된다 — 1차 샘플에서 8장 전부 1024×1024 로 나온 직접
      원인이다. 종횡비는 파라미터로 보내야 한다.
    ⚠ 필드 경로가 확정적이지 않다(config.IMAGE_ASPECT_CONFIG_SHAPE 주석 참조). 라이브 키로
      400 이 나면 `IMAGE_ASPECT_RATIO_PARAM=false` 한 줄로 즉시 이전 동작으로 돌아간다.
      그리고 파라미터가 먹었는지는 믿지 않고 `_gen_still` 이 산출물 크기를 실측한다.
    """
    if not config.IMAGE_ASPECT_RATIO_PARAM:
        return {}
    if config.IMAGE_ASPECT_CONFIG_SHAPE == "response_format":
        return {"responseFormat": {"image": {"aspectRatio": config.ASPECT_RATIO}}}
    return {"imageConfig": {"aspectRatio": config.ASPECT_RATIO}}


def _reference_part(ref_path: str) -> dict[str, Any]:
    """참조 이미지 → inlineData 파트. **Phase 0 실측이 검증한 형태 그대로**다."""
    with open(ref_path, "rb") as f:
        return {"inlineData": {"mimeType": "image/png",
                               "data": base64.b64encode(f.read()).decode()}}


def _image_request_body(cut: dict[str, Any], header: dict[str, Any],
                        ref_path: str | None = None) -> dict[str, Any]:
    """Realtime·Batch 공통 GenerateContentRequest 바디(작업 A, §7).

    ★ 실시간 경로와 Batch 경로가 이 함수 하나를 공유한다 — 여기만 고치면 양쪽이 함께 고쳐지고,
      반대로 여기서 빠뜨리면 양쪽이 함께 틀린다. 테스트가 두 경로를 다 단언하는 이유다.

    ★★ `ref_path` 를 주면 **같은 세계의 다음 상태**를 만든다(v3 Phase 3).
      이미지 파트를 **텍스트보다 앞에** 싣는다 — Phase 0 실측이 검증한 배치다
      (scripts/probe_continuity.py). 순서를 바꿔도 되는지는 재 본 적이 없으므로 바꾸지 않는다.

    ★★ Batch 는 `ref_path` 를 받을 수 없다. Batch 요청은 렌더 **시작 전에** 한꺼번에
      제출되는데 참조로 쓸 앞 stage 의 그림은 그때 존재하지 않기 때문이다.
      그래서 참조가 필요한 컷은 실시간으로 돌린다(config.SEQUENCE_REFERENCE_FORCES_REALTIME).
    """
    parts: list[dict[str, Any]] = []
    if ref_path:
        parts.append(_reference_part(ref_path))
    parts.append({"text": _build_image_prompt(cut, header, referenced=bool(ref_path))})
    return {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], **_aspect_generation_config()},
    }


def is_portrait_916(width: int, height: int) -> bool:
    """산출 이미지가 세로 9:16 인가(허용 오차 포함). 순수 — 라이브 키 없이 테스트된다.

    모델이 1088×1920 처럼 살짝 어긋나게 줄 수 있어 정확 비교가 아니라 비율 오차로 본다.
    """
    if width <= 0 or height <= 0:
        return False
    target = config.RENDER_WIDTH / config.RENDER_HEIGHT
    return abs(width / height - target) <= config.IMAGE_ASPECT_TOLERANCE


def measure_aspect(path: str) -> tuple[int, int] | None:
    """생성된 파일의 실제 크기. Pillow 가 없거나 못 읽으면 None(렌더를 막지 않는다)."""
    try:
        from PIL import Image  # noqa: PLC0415 — 지연 import
        with Image.open(path) as img:
            return img.width, img.height
    except Exception as exc:  # noqa: BLE001 — 실측 실패가 렌더를 세우면 안 된다
        log.warning("이미지 크기 실측 실패(무시): %s", exc)
        return None


def _extract_inline_image_b64(response: dict[str, Any]) -> str | None:
    """GenerateContentResponse → inlineData base64 문자열(Realtime·Batch 응답 공통 파싱)."""
    parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline["data"]
    return None


@retry(
    reraise=True,
    stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
    wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=config.HTTP_BACKOFF_BASE_SEC),
    retry=retry_if_exception_type((_ImageTransientError, httpx.TimeoutException, httpx.TransportError)),
)
def _gemini_image(cut: dict[str, Any], header: dict[str, Any], out_path: str,
                  model: str = "", ref_path: str | None = None) -> None:
    """Gemini(nano banana) 텍스트→이미지. 응답 inlineData(base64) → 파일 저장.

    engine/llm.py:_gemini_create 골격 재사용(엔드포인트/키/레이트리밋/백오프). body 는
    responseModalities=["IMAGE"], 파싱은 parts[].inlineData.data 를 base64 디코드.
    """
    config.SECRETS.require("gemini_api_key")
    _image_limiter.wait()  # 무료등급 RPM 대비
    # ★ 컷 역할이 모델을 고른다(2026-08-28). 3D 도해(MECHANISM)는 구조를 정확히 그려야 해서
    #   프리미엄 모델을 쓰고, 실사·그 외 컷은 기존 모델 그대로다 — 출력·비용 불변.
    model = model or config.image_model_for(cut.get("visual_role"))
    url = f"{config.GEMINI_BASE}/{model}:generateContent"
    body = _image_request_body(cut, header, ref_path=ref_path)
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
        resp = client.post(url, headers=gemini_auth(), json=body)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _ImageTransientError(f"{resp.status_code} from gemini image")
        resp.raise_for_status()
        data = resp.json()
    b64 = _extract_inline_image_b64(data)
    if not b64:
        raise RuntimeError("Gemini 이미지 응답에 inlineData 없음")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))


# 컷 번호로 배경색을 정해 컷 구분이 눈에 보이게(플레이스홀더 식별용).
_PALETTE = [
    (34, 40, 49), (57, 62, 70), (0, 173, 181), (78, 52, 46),
    (44, 62, 80), (39, 60, 117), (76, 40, 130), (33, 33, 33),
]


def _placeholder_image(cut: dict[str, Any], header: dict[str, Any], out_path: str) -> None:
    from PIL import Image, ImageDraw

    w, h = config.RENDER_WIDTH, config.RENDER_HEIGHT
    bg = _PALETTE[(int(cut.get("cut_no", 1)) - 1) % len(_PALETTE)]
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    version = header.get("version_type", "")
    label = f"CUT {cut.get('cut_no', '?')}  |  {cut.get('visual_type', '')}  |  {cut.get('estimated_sec', 0)}s"
    sub = f"[{version}] placeholder asset"
    # 기본 비트맵 폰트(ASCII). 중앙 상단에 라벨, 그 아래 부제.
    draw.text((60, int(h * 0.30)), label, fill=(240, 240, 240))
    draw.text((60, int(h * 0.30) + 28), sub, fill=(180, 180, 180))
    # 세이프에어리어 가이드(하단) — 자막이 여기 위에 얹힘.
    draw.rectangle([0, int(h * (1 - config.SUBTITLE_SAFE_BOTTOM)), w, h], outline=(120, 120, 120))
    img.save(out_path, "PNG")


def _reuse_image(cut: dict[str, Any], out_path: str) -> None:
    """**이미 만들어 둔 그림**을 그대로 쓴다(생성 호출 0, 비용 0).

    ★ 왜 필요한가(2026-09-19 운영자: "너가 그냥 테스트하는 방법은 없나?? 돈쓰기 싫은데"):
      돈이 드는 것은 **그림 생성 하나뿐**이다. 자막·범례·화살표·전후 분할·조립은 전부 공짜다.
      그런데 placeholder 는 회색 판이라 그 위에 얹힌 것이 실제로 어떻게 보이는지 알 수 없다.
      지난 렌더의 **진짜 그림**을 재사용하면 생성 말고 **나머지 전부**를 사실대로 볼 수 있다.

    ★ 이것이 검증하지 **못하는** 것: 새 프롬프트가 그리는 **그림 자체**. 그건 사는 수밖에 없다.
      그래서 이 경로는 `placeholder` 와 나란히 두고 이름을 `reuse` 로 못박는다 — 무엇을
      검증하고 무엇을 검증하지 못하는지 이름으로 드러난다.

    컷 번호 순서대로 `config.IMAGE_REUSE_DIR` 의 PNG 를 하나씩 쓴다(모자라면 앞으로 돌아간다).
    """
    import glob  # noqa: PLC0415 — 이 경로에서만 쓴다
    import shutil  # noqa: PLC0415

    pool = sorted(glob.glob(os.path.join(config.IMAGE_REUSE_DIR, "*.png")))
    if not pool:
        raise RuntimeError(f"재사용할 그림이 없다: {config.IMAGE_REUSE_DIR}")
    idx = max(0, int(cut.get("cut_no") or 1) - 1) % len(pool)
    shutil.copyfile(pool[idx], out_path)
    log.info("컷 %s 그림 재사용(생성 0회): %s", cut.get("cut_no"), os.path.basename(pool[idx]))


def generate_image(cut: dict[str, Any], header: dict[str, Any], out_path: str,
                   model: str = "", ref_path: str | None = None) -> tuple[str, float]:
    """컷 → 이미지 파일. model 을 주면 **그 모델로 강제**한다(역할 상향 실패 시 폴백용).

    `ref_path` 를 주면 그 그림을 시작 프레임으로 삼아 **같은 세계의 다음 상태**를 만든다.
    ★ 단가는 참조 유무와 무관하다 — Phase 0 실측에서 확인했다(장당 $0.134, 현행 1.00배).
    """
    provider = config.IMAGE_PROVIDER
    if provider == "placeholder":
        _placeholder_image(cut, header, out_path)
        return out_path, 0.0
    if provider == "reuse":
        _reuse_image(cut, out_path)
        return out_path, 0.0
    if provider == "gemini":
        _gemini_image(cut, header, out_path, model=model, ref_path=ref_path)
        eff = model or config.image_model_for(cut.get("visual_role"))
        return out_path, float(config.PRICING.get(eff, {}).get(
            "image_standard", config.GEMINI_IMAGE_COST_USD))
    if provider == "higgsfield":
        raise NotImplementedError("higgsfield 이미지 제공자는 P-V1에서 배선")
    log.warning("알 수 없는 IMAGE_PROVIDER=%s → placeholder", provider)
    _placeholder_image(cut, header, out_path)
    return out_path, 0.0


# ─────────────────────────────────────────────────────────────
# 작업 A: 이미지 Batch (명세 §7). Feature Flag(config.IMAGE_GENERATION_MODE) 뒤에 둔다.
#
# ★ 계약 근거: ai.google.dev/gemini-api/docs/batch-api, ai.google.dev/api/batch-mode 공식 문서로
#   구조를 확인(제출 엔드포인트, JSONL 매핑 필드가 metadata.key 인 것, 50% 할인, 폴링 GET). 단,
#   라이브 GEMINI_API_KEY 로 실제 응답을 받아본 적은 없다(이 샌드박스엔 키 없음) — 특히 폴링 응답의
#   done/state/inlinedResponses 정확한 중첩 위치는 문서 설명에 약간의 모호함이 있어 아래 파서는
#   방어적으로(여러 후보 경로) 값을 찾는다. 착수(라이브 키 확보) 시 실제 응답으로 재검증 필요.
# ─────────────────────────────────────────────────────────────
def build_batch_key(directive_id: str, cut_no: int) -> str:
    """지시서·컷 → Batch 요청 key(§7.3). 논리 자산ID — API 시도ID(idempotency_key)와 분리."""
    return f"{directive_id}__cut{cut_no}"


def build_batch_requests(directive_id: str, cuts: list[dict[str, Any]],
                         header: dict[str, Any]) -> list[dict[str, Any]]:
    """컷 목록 → Batch inline 요청 목록(key 로 결과를 되찾는다).

    ★ 이 함수는 **한 모델에 보낼 묶음**만 만든다. 모델이 섞인 목록을 그대로 넘기면 안 된다 —
      Batch 엔드포인트가 모델별로 갈리기 때문이다(`{model}:batchGenerateContent`).
      호출부는 group_batch_requests 로 먼저 모델별로 쪼갠다.
    """
    return [
        {"metadata": {"key": build_batch_key(directive_id, int(c.get("cut_no") or 0))},
         "request": _image_request_body(c, header)}
        for c in cuts
    ]


def group_batch_requests(directive_id: str, cuts: list[dict[str, Any]],
                         header: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """**실제 생성 모델별로** Batch 요청을 나눈다 → {model: [request, ...]}.

    ★ 왜 필요한가(2026-08-29 리뷰): Batch 제출이 `config.IMAGE_MODEL` 하나로 전 컷을 보냈다.
      실시간 경로는 역할별로 프리미엄 모델을 쓰는데 Batch 는 안 썼으니, 기본 모드(batch)에서
      **3D 도해가 flash 로 생성돼 캐시에 굳었다.** 모델을 올린 의미가 사라지는 자리였다.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for c in cuts:
        model = generation_spec.image_spec(c, header, generation_mode="batch").model
        grouped.setdefault(model, []).append(c)
    return {model: build_batch_requests(directive_id, group, header)
            for model, group in grouped.items()}


def batch_payload_hash(requests: list[dict[str, Any]]) -> str:
    """제출 페이로드 해시(§7.3) — 동일 페이로드 중복 제출 방지(제출 전 대조용)."""
    import hashlib
    import json
    raw = json.dumps(requests, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def submit_batch(requests: list[dict[str, Any]], display_name: str, model: str) -> str:
    """Batch 제출. 반환: provider_job_id(예: "batches/xxxx").

    ★ model 은 **필수 인자다**(기본값을 두지 않는다). 예전엔 config.IMAGE_MODEL 을 그대로 썼고,
      그래서 역할별 모델 상향이 Batch 경로에서 통째로 무시됐다. 기본값을 다시 두면 같은 버그가
      조용히 돌아온다.
    """
    config.SECRETS.require("gemini_api_key")
    url = f"{config.GEMINI_BASE}/{model}:batchGenerateContent"
    body = {"batch": {"display_name": display_name,
                      "input_config": {"requests": {"requests": requests}}}}
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
        resp = client.post(url, headers=gemini_auth(), json=body)
        resp.raise_for_status()
        data = resp.json()
    name = data.get("name")
    if not name:
        raise RuntimeError(f"Batch 제출 응답에 name 없음: {str(data)[:300]}")
    return name


def poll_batch(job_name: str) -> dict[str, Any]:
    """Batch 상태 조회. 반환: {"done": bool, "state": str, "raw": dict}."""
    config.SECRETS.require("gemini_api_key")
    url = f"{config.GEMINI_BASE.rsplit('/models', 1)[0]}/{job_name}"
    with httpx.Client(timeout=config.HTTP_TIMEOUT_SEC) as client:
        resp = client.get(url, headers=gemini_auth())
        resp.raise_for_status()
        data = resp.json()
    done = bool(data.get("done"))
    # state 는 문서상 Batch 리소스 필드 — 정확한 중첩 위치가 미검증이라 여러 후보를 본다.
    state = (data.get("metadata", {}).get("state") or (data.get("response") or {}).get("state")
             or ("SUCCEEDED" if done else "RUNNING"))
    return {"done": done, "state": state, "raw": data}


def fetch_batch_results(poll_response: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    """완료된 Batch 폴링 응답 → {key: (image_b64 or None, error or None)}.

    inlinedResponses 위치가 response.dest 또는 response.batch.dest 등 문서상 모호해 방어적으로 찾는다.
    """
    raw = poll_response.get("raw") or {}
    if raw.get("error"):
        raise RuntimeError(f"Batch operation error: {str(raw['error'])[:300]}")
    resp_obj = raw.get("response") or {}
    dest = resp_obj.get("dest") or (resp_obj.get("batch") or {}).get("dest") or {}
    inlined = dest.get("inlinedResponses") or dest.get("inlined_responses") or []

    out: dict[str, tuple[str | None, str | None]] = {}
    for item in inlined:
        meta = item.get("metadata") or {}
        key = meta.get("key")
        if not key:
            continue
        if item.get("error"):
            out[key] = (None, str(item["error"])[:300])
            continue
        response = item.get("response") or {}
        b64 = _extract_inline_image_b64(response)
        if b64:
            out[key] = (b64, None)
        else:
            out[key] = (None, "응답에 inlineData 없음")
    return out
