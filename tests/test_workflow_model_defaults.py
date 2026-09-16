"""워크플로 입력의 모델 기본값이 **존재하는 모델**인지 검사한다 (2026-09-16).

★ 왜 생겼나 — 실측 사고: 결제가 막혀 Actions 가 0초에 죽는 동안 `draft.yml` 의 기본값이
  `gemini-2.0-flash` 를 가리킨 채 남아 있었다. 공개 전환으로 Actions 가 살아나자
  **초안 생성이 매번 404 로 실패**했다(공개 저장소 f62a0f3 에서 2.5-flash 로 수정).
  핸드오프가 "나머지 워크플로도 같은 종류의 낡은 기본값이 있을 수 있다"를 후속으로 남겼는데,
  눈으로 대조하는 일은 다음에 또 빠진다. 그래서 검사로 옮긴다.

★ 무엇을 진실원으로 삼나: `engine/config.py` 의 `TEXT_PRICING`.
  비용 원장이 단가를 아는 모델 = 이 저장소가 실제로 쓰는 모델이다. 새 모델을 쓰기 시작하면
  단가를 먼저 등록해야 하고(안 하면 호출이 원장에 안 남는다), 그 등록이 이 검사도 통과시킨다.
  ▸ 이 검사는 "오타·낡은 이름"을 잡는다. 공급자가 모델을 **폐기**한 경우까지는 못 잡는다
    — 그건 실제 호출만 알 수 있다.
"""
import pathlib
import re

from engine import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# `      score_model:` 로 열리는 입력 블록 안의 `        default: "gemini-2.5-flash"` 를 짝짓는다.
# 정규식 하나로 블록을 잡으려다 한 번 실패했다(`\s*$` 가 줄바꿈을 먹어 body 가 늘 비었다).
# 줄 단위로 읽는 편이 형식 변화에도 덜 부서진다.
INPUT_OPEN = re.compile(r"^ {6}([a-z_]*model):\s*$")
DEFAULT = re.compile(r"""^ {8}default:\s*["']?([^"'\s]+)["']?\s*$""")


def _workflow_model_defaults():
    for f in sorted(WORKFLOWS.glob("*.yml")):
        current = None
        for line in f.read_text(encoding="utf-8").splitlines():
            opened = INPUT_OPEN.match(line)
            if opened:
                current = opened.group(1)
                continue
            if current is None:
                continue
            if not line.startswith(" " * 8):
                current = None  # 블록이 끝났다
                continue
            d = DEFAULT.match(line)
            if d:
                yield f.name, current, d.group(1)
                current = None


def test_workflow_inputs_name_a_model_the_repo_knows():
    found = list(_workflow_model_defaults())
    # 검사 자체가 조용히 0건이 되면(정규식이 형식 변화에 못 따라가면) 아무것도 안 지킨다.
    assert found, "워크플로에서 *_model 입력 기본값을 하나도 못 읽었다 — 정규식이 낡았다"

    unknown = [
        f"{wf}:{name} = {model}"
        for wf, name, model in found
        if model not in config.TEXT_PRICING
    ]
    assert not unknown, (
        "config.TEXT_PRICING 에 없는 모델을 기본값으로 쓴다(낡은 이름이면 라이브에서 404):\n  "
        + "\n  ".join(unknown)
        + f"\n등록된 모델: {sorted(config.TEXT_PRICING)}"
    )


def test_config_text_model_defaults_are_priced():
    """config 쪽 기본값도 같은 표 안에 있어야 한다.

    빠지면 404 는 아니지만 **비용 원장에 단가가 안 남는다** — TEXT_PRICING 이 생긴 이유가
    "어제 얼마를 뭐에 썼나"에 답하는 것이었다(config.py 의 2026-08-29 주석).
    """
    unpriced = []
    for name in dir(config):
        if not name.startswith("MODEL_"):
            continue
        value = getattr(config, name)
        if not isinstance(value, str) or not value:
            continue
        # 이미지·영상 모델은 PRICING(장당/초당)이 따로 본다. 여기선 텍스트만.
        if "image" in value or "veo" in value:
            continue
        if value not in config.TEXT_PRICING:
            unpriced.append(f"{name} = {value}")
    assert not unpriced, (
        "TEXT_PRICING 에 단가가 없는 텍스트 모델 기본값(원장에 비용이 안 남는다):\n  "
        + "\n  ".join(unpriced)
    )
