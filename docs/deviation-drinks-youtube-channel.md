# 이탈 기록 — 'a Paper a Day' 채널을 술째리고 홍보 채널로 전환, 영어 논문 라인 일시 중지 (2026-11-24)

## 운영자 지시 (원문 요지)
> 진행. 기존 영상은 비공개로 돌리고 영어 라인은 접자. 영어 논문 영상 라인은 일시 중지합니다. 막아주세요.
> 채널 이름도 술째리고로 바꾸고, 소개도 바꿔주세요.

## 무엇이 바뀌나
| 대상 | 전 | 후 |
|---|---|---|
| 유튜브 채널 `UCU9XJcPFQtGXZAENFOMS7QQ` | a Paper a Day(영어 논문) | 술째리고(주류 쇼츠). 기존 영상 비공개 |
| 영어 논문 라인 | 렌더·업로드 가능 | **일시 중지** — 웹 라우트가 거부(`web/lib/langPause.ts`), 엔진 업로드·성과 수집이 건너뜀(`config.YOUTUBE_PAUSED_LANGS`) |
| 주류 발행 | 인스타만 | 인스타 + 유튜브 쇼츠(같은 스튜디오 [게시] 흐름, 계정만 하나 더) |

## 설계
- 주류 발행 흐름(0055: 승인·예약·임대·게시 직전 재확인·unknown 대조)을 **그대로** 쓴다. 0090 이 계정 표에
  `platform 'youtube'` + `connection 'google_oauth'` 를 열고, 워커가 연결 방식으로 공급자를 고른다
  (`engine/providers/instagram.provider_for` → `engine/providers/drinks_youtube.DrinksYouTube`).
- 유튜브 공급자는 인스타와 같은 모양이다: 컨테이너 = 파일 주소 기억, publish = 실제 업로드.
  **채널 가드는 게시 호출 전**(컨테이너 단계)에 돈다 — 토큰의 채널이 등록한 채널 ID 와 다르면 paused.
- 토큰은 옛 영어 채널 토큰(`YOUTUBE_REFRESH_TOKEN_EN`, 업로드 스코프)을 그대로 쓴다. 계정 등록의 비밀 이름에 그 이름을 적는다.
- 공개 상태: **public**(`config.DRINKS_YT_PRIVACY`). 스튜디오 [게시]는 인스타처럼 "공개 게시"이고, 승인·예약을 거친 편만 올라간다.
  논문 업로드의 "기본 비공개"(docs/deviation-youtube-upload.md)와 다르다 — 그쪽은 버튼 하나로 바로 올라가는 흐름이라서다.

## 한계 (알고 둔 것)
- 인스타 음원(ig_audio)은 유튜브에 못 붙는다 → 음원이 필수인 카드 릴스는 유튜브 계정에서 paused(음원 없이 올리지 않는다).
  나레이션 설명형 릴스·음악을 깐 렌더(licensed_mix)는 올라간다.
- 게시 여부 불명(unknown)은 업로드 스코프로 채널 영상을 조회할 수 없어 자동 대조하지 않는다 — 유튜브 스튜디오에서 확인.
- 유튜브 쇼츠 성과 수집은 아직 없다(주류 성과 단계는 유튜브 게시물을 `metrics_unsupported` 로 실패 기록).
- 옛 영어 논문 성과 기록(`youtube_analytics*` 의 `lang='en'`)은 지우지 않고 역사로 남긴다. 새 수집은 하지 않는다.

## 되돌리기
`web/lib/langPause.ts` 와 `config.YOUTUBE_PAUSED_LANGS` 에서 `en` 을 빼고, 영어 논문용 **새 채널**을 발급해
`engine/youtube_channels.py` 의 `paper_en` 을 그 채널로 바꾼다(이 채널은 이제 술째리고다).
