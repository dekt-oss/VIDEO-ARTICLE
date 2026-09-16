// 배치/결정 날짜 표시 유틸. 모든 "오늘/어제" 계산은 Asia/Seoul 기준(엔진 TIMEZONE 과 통일).
// 서버 렌더가 UTC 로 돌아도 KST 달력일로 "오늘"을 잡아야, 날짜가 하루 밀려 보이는 혼란을 없앤다.

const TZ = "Asia/Seoul";

// 주어진 Date(기본: 현재)의 Asia/Seoul 달력일을 YYYY-MM-DD 로 반환.
export function todayInSeoul(now: Date = new Date()): string {
  // en-CA 로케일은 YYYY-MM-DD 형식을 준다.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

// YYYY-MM-DD 문자열을 UTC 자정 기준 Date 로(달력일 산술용, 시각/타임존 영향 배제).
function toUtcMidnight(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return Date.UTC(y, (m ?? 1) - 1, d ?? 1);
}

// 오늘(Seoul) 대비 며칠 전인지. 오늘=0, 어제=1, 내일=-1.
export function daysAgoFromToday(isoDate: string, now: Date = new Date()): number {
  const dayMs = 24 * 60 * 60 * 1000;
  return Math.round((toUtcMidnight(todayInSeoul(now)) - toUtcMidnight(isoDate)) / dayMs);
}

// 사람이 읽는 상대 라벨(오늘/어제/N일 전/N일 후). ISO 병기는 호출부에서.
export function relativeDayLabel(isoDate: string | null, now: Date = new Date()): string {
  if (!isoDate) return "날짜 없음";
  const diff = daysAgoFromToday(isoDate, now);
  if (diff === 0) return "오늘";
  if (diff === 1) return "어제";
  if (diff === 2) return "그저께";
  if (diff > 2) return `${diff}일 전`;
  if (diff === -1) return "내일";
  return `${-diff}일 후`;
}

// "오늘 (2026-07-03)" 형태의 완전한 라벨.
export function dayLabelWithDate(isoDate: string | null, now: Date = new Date()): string {
  if (!isoDate) return "날짜 없음";
  return `${relativeDayLabel(isoDate, now)} (${isoDate})`;
}

// timestamptz(ISO) → Asia/Seoul 달력일(YYYY-MM-DD).
export function seoulDateOf(timestamp: string): string {
  return todayInSeoul(new Date(timestamp));
}

// 주간/월간 버킷 키 (성과 리포트 페이지 집계용). 주는 월요일 시작(모호성 없음), 월은 YYYY-MM.
// YYYY-MM-DD 가 속한 주의 월요일 날짜(YYYY-MM-DD).
export function mondayOf(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
  const dow = (dt.getUTCDay() + 6) % 7; // 월=0 ... 일=6
  dt.setUTCDate(dt.getUTCDate() - dow);
  return dt.toISOString().slice(0, 10);
}

// YYYY-MM-DD → 'YYYY-MM'(월 키).
export function monthKey(isoDate: string): string {
  return isoDate.slice(0, 7);
}
