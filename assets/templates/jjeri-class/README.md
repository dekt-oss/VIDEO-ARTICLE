# 째리의 술 수업 — 정답 샘플 (1교시 · 버번 vs 셰리 캐스크)

소유자가 승인한 형식의 **손작업 정답지**다(2026-11-26). 엔진(`engine/motion` 계열)이 같은 편 지시서를 받으면
이 폴더가 렌더하는 것과 **같은 화면·같은 시각**을 내야 한다. 구현 지시는 `docs/핸드오프_째리의술수업_엔진_2026-11-26.md`.

## 무엇이 들어 있나

| 파일 | 역할 |
|---|---|
| `episode.example.json` | **엔진이 받을 입력의 정답 모양**(편 지시서). 장면 12개 · 템플릿 이름 · 칸 · 문장 18개 · 장 제목 · 핵심어 색 |
| `timeline.json` | **정답 시간표**. 장면 시작·길이, 문장 시작, 말 길이, 앞 무음 건너뛰기(media_start) |
| `golden/t*.jpg` | 정답 화면 12장(렌더본에서 그 초에 뽑은 프레임, 폭 540) |
| `index.html`, `compositions/*.html` | HyperFrames 프로젝트 — 그대로 렌더된다 |
| `tools/script.py` | 대본 한 곳(자막 = 내레이션). 음성 설정 `VOICE`·`RATE`·`SPEED` |
| `tools/tts.py` | Edge TTS → `atempo` 배속 → 앞뒤 무음 측정 → `assets/vo/vo.json` |
| `tools/build.py` | 장면 HTML·`index.html`·`timeline.json` 생성. 앞부분은 2판(무음판) 부품, `v3:` 아래가 현행 |
| `tools/export_episode.py` | 샘플을 `episode.example.json` 으로 내보낸다 |
| `릴스_설명란.txt` | 게시 캡션 초안 |
| `CREDITS.md`, `assets/sfx/CREDITS.md` | 음악·효과음·글꼴·캐릭터 출처 |

## 다시 만들기 (0원)

```bash
cd assets/templates/jjeri-class
python tools/tts.py            # 음성 18개(무료 Edge TTS, 네트워크 필요) — 이미 들어 있으니 대본을 바꿀 때만
python tools/build.py          # 장면·index.html·timeline.json
npx --yes hyperframes@0.9.72 check --safe-zone reels
npx --yes hyperframes@0.9.72 render -o renders/sample.mp4
```

샘플은 HyperFrames 0.9.19 로 만들기 시작했고, 최종 렌더·정답 화면·검사는 엔진 고정 버전 0.9.72 로 했다.
`renders/`·`.hyperframes/` 는 커밋하지 않는다.

## 정답 수치 (렌더본 실측, 2026-11-26)

- 1080×1920, 30fps, **71.34초**, 장면 12 · 문장 18
- 소리 −15.8 LUFS, 최고 −2.3 dBTP, 클리핑 0 (측정만 — 귀로 듣지 않음)
- `hyperframes@0.9.72 check --safe-zone reels` 오류 0 · 경고 0 (인스타 릴스 안전 영역 포함)
