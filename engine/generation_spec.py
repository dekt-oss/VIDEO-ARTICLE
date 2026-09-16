"""생성 사양의 단일 출처 (2026-08-29 리뷰 반영).

무엇을 푸는가: "이 컷을 무엇으로, 어떤 설정으로 만드는가"를 **여섯 곳이 각자 판단**하고 있었다.

    실시간 이미지 호출 → config.image_model_for(role)   ← 역할별 프리미엄 모델
    Batch 제출        → config.IMAGE_MODEL              ← ★ 역할 무시(전부 flash)
    예상 비용         → config.IMAGE_MODEL              ← ★ 프리미엄 컷을 싸게 계산
    비용 원장         → config.IMAGE_MODEL              ← ★ 실제 호출 모델과 다른 값 기록
    이미지 캐시 키    → 모델·역할 없음                   ← ★ flash 캐시가 프리미엄 컷에 재사용
    예산 가드         → 위 값들을 그대로 신뢰

그래서 실제로는 `gemini-3-pro-image`($0.134)로 그려 놓고 원장에는
`gemini-2.5-flash-image`($0.039)로 남는 일이 가능했다. 캐시는 더 나빴다 — 역할이 키에 없으니
과거 flash 로 만든 그림이 MECHANISM 컷에 그대로 재사용된다(모델 상향이 무효화된다).

이 모듈이 **한 번 결정하고 전원이 그것을 읽는다.** 순수 함수다(네트워크·DB 없음).

★ 캐시 정책(의도적 무효화): ImageSpec 의 model·visual_role·style_version·output 설정이
  캐시 키에 들어간다. 그래서 이 커밋 이후 **기존 render_assets 캐시는 전부 미스가 된다.**
  호환을 택하지 않은 이유: 조건부로 키를 넣으면 "어떤 컷은 모델이 키에 있고 어떤 컷은 없는"
  상태가 되어, 지금 고치려는 종류의 버그를 다시 만든다. 이미 렌더가 끝난 영상은 mp4 로
  남아 있으므로 깨지지 않고, 재렌더할 때만 다시 생성된다(그때 비용이 든다 — 보고서에 적는다).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from . import config, cost as cost_table, photo_contract


@dataclass(frozen=True)
class ImageSpec:
    """이미지 1장을 만드는 **실제** 사양. 모든 소비자가 이 값을 쓴다."""

    provider: str            # gemini | placeholder
    model: str               # 실제로 호출되는 모델(역할 상향 반영 후)
    visual_role: str         # MECHANISM | REALITY | "" (레거시·만화식)
    generation_mode: str     # realtime | batch
    unit_type: str           # image_standard | image_batch (단가표 항목)
    unit_price_usd: float
    aspect_ratio: str
    output_resolution: str   # 요청에 실을 해상도. 지정하지 않으면 "provider_default"
    style_version: str       # 프롬프트·화풍 계약 버전(바뀌면 그림이 바뀐다 → 캐시 무효)
    # ★ 참조 조건 생성의 입력 해시("" = 참조 없음, 텍스트 전용). v3 Phase 3.
    reference_key: str = ""

    def cache_fields(self) -> dict[str, Any]:
        """캐시 키에 들어갈 부분. ★ 단가는 뺀다 — 가격이 바뀌어도 그림은 그대로다.

        ★★ `reference_key` 가 여기 있는 것이 v3 Phase 3 의 핵심이다.
          이 저장소는 같은 교훈을 이미 한 번 배웠다 — `VideoSpec.start_asset_hash` 가 없던
          시절 I2V 연쇄에서 **앞 컷이 바뀌어도 뒤 컷이 옛 클립을 재사용**했다. 참조 조건
          생성을 이미지에 붙이면 똑같은 구멍이 이미지 쪽에 생긴다: 앞 stage 의 그림이
          바뀌어도 이 컷은 옛 그림을 그대로 쓴다. 그러면 "연속성"이 캐시 우연에 달린다.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "visual_role": self.visual_role,
            "aspect_ratio": self.aspect_ratio,
            "output_resolution": self.output_resolution,
            "style_version": self.style_version,
            "reference_key": self.reference_key,
        }


@dataclass(frozen=True)
class VideoSpec:
    """클립 1개를 만드는 실제 사양."""

    provider: str            # gemini(veo) | placeholder
    model: str
    visual_role: str
    generation_mode: str     # standard (Veo 는 Batch 할인이 없다)
    unit_type: str           # video_720p_per_sec 등
    unit_price_usd: float
    clip_sec: int            # 요청 티어(초) — **provider 가 이 값을 그대로 쓴다**
    tier: str                # 시퀀스 등급(invest|standard|economy). 등급제 밖이면 ""
    candidates: int          # 이 컷을 몇 번 생성해 고를 것인가(invest=2)
    resolution: str
    aspect_ratio: str
    style_version: str
    start_asset_hash: str    # I2V 시작 이미지의 논리적 해시("" = 시작 이미지 없음)

    def cache_fields(self) -> dict[str, Any]:
        """★ start_asset_hash 가 여기 있는 것이 이 모듈의 두 번째 목적이다.

        I2V 연쇄에서 이 컷의 시작 화면은 **앞 영상 컷의 마지막 프레임**이다. 앞 컷이 바뀌면
        시작 프레임이 바뀌고 결과 영상도 바뀌는데, 예전 캐시 키에는 그 사실이 없어서
        **앞이 바뀌어도 뒤는 옛 클립을 그대로 재사용**했다(연쇄가 조용히 어긋난다).
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "visual_role": self.visual_role,
            "clip_sec": self.clip_sec,
            # ★ 등급이 캐시 키에 들어간다 — 등급을 바꾸면 **의도적으로** 재생성된다.
            #   (start_asset_hash 를 넣은 것과 같은 이유. 없으면 8초로 올려도 옛 4초
            #    클립이 그대로 재사용된다.)
            "tier": self.tier,
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
            "style_version": self.style_version,
            "start_asset_hash": self.start_asset_hash,
        }


def effective_visual_role(cut: dict[str, Any]) -> str:
    """이 컷을 **실제로 무엇으로 그리는가** — 모델 선택이 읽는 유일한 값.

    ★ 정본은 `resolved_visual_plan` 이다(코덱스 리뷰 R3). 옛 `visual_role` 은 모델이 붙인
      라벨이라 코드의 라우팅 판정과 어긋날 수 있고, 실제로 어긋났다 — 골든B 재생성에서
      라우터가 기전 시퀀스로 판정한 컷 둘의 라벨이 `REALITY` 였다. 그대로 두면 3D 도해를
      **flash 모델로** 그리게 되고, flash 는 도해에 깨진 글자 라벨을 그린다(실측).

    ★ `beat_declared` 가 거짓이면 정본의 base 는 판정이 아니라 **합성된 기본값**이다.
      그때는 옛 라벨을 그대로 쓴다 — 만화식·옛 지시서를 건드리지 않기 위해서다.
    """
    plan = cut.get("resolved_visual_plan")
    label = str(cut.get("visual_role") or "").strip()
    if isinstance(plan, dict) and plan.get("beat_declared"):
        base = str(plan.get("base") or "")
        if base == "MECHANISM_SEQUENCE":
            # ★★ **시퀀스 소속 ≠ 3D 도해**(2026-09-03 첫 실사형 렌더 실측).
            #   라우터의 MECHANISM_SEQUENCE 는 "이 컷이 진행하는 세계 안에 있다"는 **연속성**
            #   판정이다. 그것을 그대로 화풍·모델 선택에 썼더니, 모델이 REALITY 로 라벨한
            #   컷 10개 중 5개(1·4·6·7·10 — 사유는 `in_visual_sequence` 하나)가 MECHANISM 으로
            #   뒤집혀 "isometric cutaway 3D render, no photorealistic texture, no people in
            #   focus" 를 받았다. 사무실의 실제 사람들이 **회색 마네킹이 든 아이소메트릭
            #   단면**으로 나왔고, 참조 사슬("keep the SAME materials")이 그 룩을 뒤 컷까지
            #   끌고 갔다. 실사로 남은 건 2·3·9·12·13 뿐 — 화면과 정확히 일치했다.
            #
            #   도해 화풍을 받을 자격은 **자를 구조가 선언돼 있는가**다(photo_contract §5:
            #   subject·components≥2·relationship·transformation). 실측 지시서에서 그 구조가
            #   완비된 컷은 정확히 5·8·11(모델도 MECHANISM 이라 라벨함)이고, 뒤집힌 다섯은
            #   전부 미완비였다. 구조 없는 REALITY 컷은 세계는 잇되 **사진으로** 그린다.
            #   골든B 의 원래 걱정(라우터=기전인데 라벨=REALITY → flash 가 깨진 글자를 그림)은
            #   구조가 선언된 컷에서만 성립하므로 그 경우는 그대로 승격한다.
            if label == "MECHANISM" or photo_contract.mechanism_spec_complete(
                    photo_contract.mechanism_spec_of(cut)):
                return "MECHANISM"
            return label or "REALITY"
        if base == "REALITY":
            return "REALITY"
        # CODE_VIZ·OVERLAY 는 역할 상향 대상이 아니다 — 옛 라벨을 그대로 둔다.
    return label


def _image_unit_type(mode: str | None = None) -> str:
    """현재 이미지 생성 모드의 단가 항목(Batch 는 반값)."""
    m = mode or config.IMAGE_GENERATION_MODE
    return "image_batch" if m == "batch" else "image_standard"


def image_spec(cut: dict[str, Any], header: dict[str, Any] | None = None,
               *, generation_mode: str | None = None,
               provider: str | None = None,
               reference_key: str = "") -> ImageSpec:
    """컷 + 헤더 → 이미지 생성 사양. **여기가 모델을 고르는 유일한 자리다.**

    generation_mode 를 명시하면 그것을 쓴다(Batch 제출은 항상 "batch"). 안 주면 config.
    `reference_key` 를 주면 참조 조건 생성으로 만든 그림임을 캐시 키가 안다(v3 Phase 3).
    """
    role = effective_visual_role(cut)
    model = config.image_model_for(role)
    mode = generation_mode or config.IMAGE_GENERATION_MODE
    unit_type = _image_unit_type(mode)
    return ImageSpec(
        provider=provider or config.IMAGE_PROVIDER,
        model=model,
        visual_role=role,
        generation_mode=mode,
        unit_type=unit_type,
        unit_price_usd=float(cost_table.unit_price(model, unit_type)),
        aspect_ratio=config.ASPECT_RATIO,
        output_resolution=config.IMAGE_OUTPUT_RESOLUTION,
        style_version=config.PROMPT_CONTRACT_VERSION,
        reference_key=str(reference_key or ""),
    )


def video_spec(cut: dict[str, Any], header: dict[str, Any] | None = None,
               *, clip_sec: int, start_asset_hash: str = "",
               tier: str = "", candidates: int = 1) -> VideoSpec:
    """컷 + 요청 티어 → 영상 생성 사양. **이것이 단일 실행 계약이다.**

    ★★ 코덱스 리뷰 P0-2: provider 가 tier·model·길이를 **다시 판단하면** 여기 적은 값이
      거짓이 된다(실제로 `_veo_i2v` 가 `pick_clip_tier` 를 재호출하고 전역 `VEO_MODEL` 을
      썼다). 그러면 이 저장소가 여덟 번 겪은 "만들어 놓고 소비자가 안 읽는" 실패가
      **돈에서** 재현된다 — 8초로 예상하고 4초를 사는 것이다.

      계약: **예상한 스펙 = 발주한 스펙 = 기록한 스펙.**
      cost_plan · 캐시 키 · 원장 · provider 요청이 전부 이 객체 하나를 읽는다.
    """
    unit_type = f"video_{config.VEO_RESOLUTION}_per_sec"
    model = config.video_model_for_tier(tier) if tier else config.VEO_MODEL
    return VideoSpec(
        provider=config.VIDEO_PROVIDER,
        model=model,
        visual_role=effective_visual_role(cut),
        generation_mode="standard",
        unit_type=unit_type,
        unit_price_usd=float(cost_table.unit_price(model, unit_type)),
        clip_sec=int(clip_sec),
        tier=str(tier or ""),
        candidates=max(1, int(candidates)),
        resolution=config.VEO_RESOLUTION,
        aspect_ratio=config.ASPECT_RATIO,
        style_version=config.PROMPT_CONTRACT_VERSION,
        start_asset_hash=str(start_asset_hash or ""),
    )


def asset_logical_hash(payload: Any) -> str:
    """시작 에셋의 '논리적' 해시.

    파일 바이트가 아니라 **그 에셋을 결정한 값**을 해시한다 — 같은 입력이면 같은 그림이
    나온다는 전제 위에서, 렌더를 돌리지 않고도(=파일이 없어도) 캐시 키를 계산할 수 있어야
    하기 때문이다. 연쇄의 경우 payload 는 앞 컷의 클립 캐시 키다.
    """
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def spec_summary(spec: ImageSpec | VideoSpec) -> dict[str, Any]:
    """로그·원장 메타에 실을 요약(디버깅용). 전체 필드를 그대로 편다."""
    return asdict(spec)
