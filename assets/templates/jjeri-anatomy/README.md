# 째리의 술 해부 — 정답 샘플 (막걸리, 2.5D 단면)

소유자가 승인하고 **2026-11-28 유튜브·인스타에 게시한** 손작업 정답지다. 엔진이 같은 편 지시서를 받으면 이 폴더가 렌더하는 것과
같은 화면·같은 시각을 내야 한다. 구현 지시는 `docs/핸드오프_째리의술해부_엔진_2026-11-28.md`.

- 게시본: 유튜브 https://youtube.com/shorts/hYlHkgMKY2M · 인스타 https://www.instagram.com/reel/DgRHKWTBLg-/
- 원본: 2026-11-18 인스타 막걸리 릴스(점토 AI 영상) 대본을 "그림부터" 다시 씀

| 파일 | 역할 |
|---|---|
| `episode.example.json` | **엔진 입력 정답 모양** — 세계 4개, 세계마다 부품·층·토큰 사슬·HUD·사건(문장 시작 + 초), 장 제목, 창문 |
| `timeline.json` | **시간 정답** — 세계 시작·길이, 문장 시작·말 길이·앞 무음 |
| `golden/t*.jpg` | **화면 정답** 14장(렌더본 프레임, 폭 540) |
| `tools/art25.py` | **2.5D 그림 규칙과 부품** — 이걸 엔진 그림 라이브러리의 출발점으로 쓴다 |
| `tools/build.py` | 세계 4개 장면·고정 틀·소리 배치·timeline.json 생성 |
| `tools/script.py` · `tools/tts.py` | 대본(문장 = 자막 = 내레이션) · Edge TTS → atempo → 무음 측정 |
| `tools/export_episode.py` | 샘플 → episode.example.json |

## 다시 만들기 (0원)

```bash
cd assets/templates/jjeri-anatomy
python tools/build.py
npx --yes hyperframes@0.9.72 check --safe-zone reels
npx --yes hyperframes@0.9.72 render -o renders/sample.mp4     # 약 2분 30초(로컬 실측). check 와 한 명령에 묶으면 10분 넘을 수 있다
```

## 정답 수치 (렌더본 실측, 2026-11-28)

- 1080×1920 · 30fps · **46.62초** · 세계 4 · 문장 10
- −15.8 LUFS · 최고 −2.8 dBTP · 클리핑 0 (측정만 — 귀로 듣지 않음)
- `check --safe-zone reels`: 오류 0 · 경고 2(빨리 감기 단계 0.35초씩 — 일부러 빠르게 넘기는 연출)
- gsap 은 아직 CDN(`cdn.jsdelivr.net/npm/gsap@3.15.0`) — 엔진 템플릿으로 옮길 때 `assets/lib/` 로 내린다(hf_render 규칙)
