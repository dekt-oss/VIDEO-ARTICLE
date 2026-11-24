// 영어 논문 라인 일시 중지(2026-11-24 운영자 지시). 영어 채널('a Paper a Day')은 술째리고 홍보 채널로 바뀌었다.
// 이 표 하나가 영어 렌더 발주·언어 추가·유튜브 업로드를 막는다(서버 라우트가 거부, 화면은 선택지를 끈다).
// 다시 열려면 여기서 "en" 을 빼고, 엔진의 채널 레지스트리(engine/youtube_channels.py)에 영어 채널을 새로 등록한다.
export const PAUSED_LANGS: readonly string[] = ["en"];
export const LANG_PAUSED_MESSAGE = "영어 논문 라인은 일시 중지됐습니다(영어 채널을 술째리고 홍보 채널로 전환) — 한국어만 만들 수 있습니다";
export const isLangPaused = (lang: unknown): boolean => PAUSED_LANGS.includes(String(lang));
