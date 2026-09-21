// Supabase Edge Function: 초안 클라우드 자동생성 (P1).
//
// 대시보드 "초안 생성 요청" 버튼 → /api/generate-draft(Next.js)가 draft_requests 큐에 적재하고
// 이 함수를 호출한다. 함수는 논문 1편에 대해 Fact Sheet → 대본/영상프롬프트 → 자기검증을 돌려
// drafts 행을 쓰고 draft_requests 상태를 갱신한다.
//
// ★ 이 파일은 Python engine(engine/factsheet.py · engine/scriptgen.py · engine/selfcheck.py ·
//   engine/draft.py · engine/llm.py)의 3단계 파이프라인을 그대로 이식한 것이다.
//   프롬프트 문자열·정규화 규칙·모델 ID는 Python 원본과 반드시 동기화한다(이중 관리 지점).
//
// ★ 환각 방지 불변식 유지: 대본 생성 입력은 Fact Sheet "만", 씬별 source_facts, JSON only.
//
// 배포:  supabase functions deploy generate-draft
// 시크릿: supabase secrets set GEMINI_API_KEY=…   (기본 백엔드 — 무료 등급)
//        Anthropic 을 쓰려면 대신 ANTHROPIC_API_KEY 를 넣고 MODEL_* 를 claude-* 로 지정.
//        SUPABASE_URL·SUPABASE_SERVICE_ROLE_KEY 는 Edge 런타임에 기본 주입된다.
//
// deno-lint-ignore-file no-explicit-any
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// Edge 런타임 백그라운드 태스크(응답 후에도 계속 실행)
declare const EdgeRuntime: { waitUntil(p: Promise<unknown>): void };

const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY") ?? "";
const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// 모델 ID — env 로 교체 가능(engine/config.py 와 동일 규약). 기본은 Gemini(운영자 지정, 무료 등급).
// 모델 id 가 "gemini" 로 시작하면 Gemini REST, 아니면 Anthropic 로 라우팅(engine/llm.py 와 동일).
const MODEL_FACTSHEET = Deno.env.get("MODEL_FACTSHEET") ?? "gemini-2.5-flash"; // Fact Sheet 추출
const MODEL_SCRIPT = Deno.env.get("MODEL_SCRIPT") ?? "gemini-2.5-pro"; // 대본 합성(나레이션 서사 품질↑)
const MODEL_SELFCHECK = Deno.env.get("MODEL_SELFCHECK") ?? "gemini-2.5-flash"; // 자기검증
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models";

// 재시도/백오프 — engine/config.py:108,122-123 과 동일.
const MAX_RETRIES = 4; // 5xx/타임아웃 지수 백오프
const BACKOFF_BASE_MS = 2000;
const JSON_RETRY = 1; // JSON 파싱 실패 시 재시도 횟수
// = engine/config.py:LLM_HTTP_TIMEOUT_SEC. 사고형 모델(gemini-2.5-pro)은 60초 안에 안 돌아온다
// (2026-07-29 실측 60.5초).
const CALL_TIMEOUT_MS = 180_000;

// 단계별 출력 예산 — Python 원본과 **같아야 한다**(tests/test_prompt_sync.py 가 감시).
//  ★ 2026-07-29: Fact Sheet 만 2048 이었다. claims 원장(항목 20개짜리 claim 배열)이 붙은 뒤
//    출력이 예산을 넘겨 잘렸고, 잘린 JSON 이 "Expected ',' or ']' after array element" 로 터졌다.
//    Python(engine/factsheet.py)은 max_tokens 를 안 넘겨 config.LLM_MAX_TOKENS(8192)를 쓰므로
//    로컬 워커는 멀쩡했다 — 이중관리 지점이 갈라진 전형적 사고다.
//  ★★ 2026-09-22: 셋 다 올렸다. 파이썬 쪽 상한이 **제미나이 씀씀이에 맞춰져 있었고**,
//    말이 2.4배 긴 공급자(DeepSeek)를 붙이는 순간 잘린다는 것이 원장 실측으로 드러났다
//    (deepseek-flash 가 지시서 32,768 정각 3회, Fact Sheet 8,192 정각 — 그걸 보고 "모델이
//    못한다"고 오판했다). 근거는 engine/config.py 의 LLM_PAPER_SCRIPT_MAX_TOKENS 주석.
//    엣지가 낮은 채로 남으면 **엣지 경로만** 잘린다 — 2026-07-29 사고가 정확히 그 모양이었다.
const MAX_TOKENS_FACTSHEET = 16384; // = engine/config.py:LLM_FACTSHEET_MAX_TOKENS
const MAX_TOKENS_SCRIPT = 32768; // = engine/config.py:LLM_PAPER_SCRIPT_MAX_TOKENS
const MAX_TOKENS_SELFCHECK = 16384; // = engine/config.py:LLM_SELFCHECK_MAX_TOKENS

// ─────────────────────────────────────────────────────────────
// 프롬프트 (engine 의 시스템 프롬프트 verbatim 복사)
// ─────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────
// 근거밀도·가변길이 개정 상수 (engine/config.py 와 동기화 — 수정명세서_근거밀도_가변길이_v1.md)
// ─────────────────────────────────────────────────────────────
const CLAIM_KINDS = [
  "main_result", "method", "scope", "number", "mechanism",
  "moderator", "subgroup", "limitation", "author_interpretation", "background",
];
const DEFAULT_CLAIM_KIND = "main_result";
const CAUSAL_STRENGTHS = [
  "descriptive", "association_only", "quasi_causal", "causal", "projection", "speculation",
];
const DEFAULT_CAUSAL_STRENGTH = "association_only";
const EVIDENCE_GRADES = ["A", "B", "C", "D"];
const DEFAULT_EVIDENCE_GRADE = "C";
const ABSTRACT_ONLY_MAX_GRADE = "B";
const EFFECT_DIRECTIONS = ["increase", "decrease", "no_change", "mixed", "unspecified"];
const DEFAULT_EFFECT_DIRECTION = "unspecified";
const SOURCE_SECTIONS = ["abstract", "body", "table", "figure"];
const CLAIM_NULLABLE_FIELDS = [
  "population", "sample_size", "geography", "study_period", "study_design",
  "treatment_or_exposure", "comparison", "outcome", "outcome_definition",
  "effect_size", "effect_unit", "uncertainty", "statistical_significance",
  "source_page", "table_or_figure", "source_quote",
];
const CONTENT_MODES = ["flash", "standard", "deep", "extended", "series_split"];
const DEFAULT_CONTENT_MODE = "standard";
const CONTENT_MODE_DURATION: Record<string, [number, number]> = {
  flash: [25, 35], standard: [36, 50], deep: [51, 65], extended: [66, 80],
};
const MODE_UNITS_FLASH_MAX = 3;
const MODE_UNITS_STANDARD_MAX = 5;
const MODE_UNITS_DEEP_MAX = 6;
const MODE_FLASH_WARN_UNITS = 6;
const EVIDENCE_UNITS = ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"];
const EVIDENCE_UNITS_REQUIRED = ["E1", "E2", "E7"];
const EVIDENCE_ROLES = [
  "primary_result", "scope", "method", "magnitude", "mechanism",
  "moderator", "caveat", "implication", "connective", "cta",
];
const DEFAULT_EVIDENCE_ROLE = "connective";
const EVIDENCE_DELIVERY = ["spoken", "visual", "both", "caption", "omit"];
const DEFAULT_EVIDENCE_DELIVERY = "spoken";
const MAX_SPOKEN_NUMBERS = 2;
const HOOK_ANGLES = [
  "personal_cost", "competition", "daily_life", "risk", "counterintuition",
  "mechanism", "future_impact", "human_scale", "scientific_wonder",
];
const DEFAULT_HOOK_ANGLE = "counterintuition";
const HOOK_STRONG_CLAIM_WORDS = [
  "증명했다", "완전히", "무조건", "전부", "인류", "지구를 망친다",
  "폭락", "폭증", "급감", "압도적", "충격적인 진실", "최종 답",
];
const SELFCHECK_TRISTATE = ["pass", "fail", "not_applicable"];
// = engine/config.SELFCHECK_FLUENCY_KINDS. 어긋나면 같은 대본이 경로에 따라 다른 검수를 받는다.
const SELFCHECK_FLUENCY_KINDS = [
  "translationese",
  "particle",
  "register_mix",
  "long_modifier",
  "reading",
];
// = engine/config.SCRIPT_POLISH_ENABLED · SCRIPT_POLISH_LEN_TOLERANCE
const SCRIPT_POLISH_ENABLED = (Deno.env.get("SCRIPT_POLISH_ENABLED") ?? "true") !== "false";
const SCRIPT_POLISH_LEN_TOLERANCE = Number(
  Deno.env.get("SCRIPT_POLISH_LEN_TOLERANCE") ?? "0.25",
);
const SCRIPT_POLISH_LEN_FLOOR_CHARS = Number(
  Deno.env.get("SCRIPT_POLISH_LEN_FLOOR_CHARS") ?? "12",
);
// ★ 줄어드는 쪽을 더 허용한다 — 번역투 제거는 정의상 문장을 줄인다(실측 −26~−44%).
const SCRIPT_POLISH_SHRINK_TOLERANCE = Number(
  Deno.env.get("SCRIPT_POLISH_SHRINK_TOLERANCE") ?? "0.50",
);
// ★ 그래서 **내용이 안 빠졌는가**를 줄기 보존율로 따로 본다(실측: 정당 53~82% / 삭제 29~33%).
const SCRIPT_POLISH_MIN_STEM_RETENTION = Number(
  Deno.env.get("SCRIPT_POLISH_MIN_STEM_RETENTION") ?? "0.45",
);
const MAX_TOKENS_POLISH = 4096; // = engine/script_polish.py 의 max_tokens
const CONTENT_MODE_HARD_MAX_SEC = 80;
const CONTENT_MODE_SOFT_MIN_SEC = 25;

// ★ engine/config.py:EVIDENCE_RULES_SHARED 와 **자구까지 동일**해야 한다.
//   tests/test_prompt_sync.py 가 첫 줄을 앵커로 감시한다.
const EVIDENCE_RULES_SHARED = `- 모든 사실 나레이션은 근거 Claim(claim_ids)을 가져야 한다. 연결어·질문·CTA 만 예외다.
- 소리 내 읽는 대표 숫자는 영상 전체 최대 2개, 한 컷에 1개. 나머지 수치는 화면(자막·오버레이)이 담당한다.
- 표본·기간·지역·세부 통계는 나레이션으로 나열하지 말고 화면으로 보여준다.
- 방법 설명은 기본 1문장. 통계 모델명은 그 방법 자체가 신뢰성 이해에 필요할 때만 말한다.
- 효과 크기가 없으면 '폭락·폭증·급감·압도적' 같은 강도 부사를 쓰지 마라. 유의성만 있으면 "차이가 나타났다" 수준으로.
- 한계는 "하지만 한계가 있습니다" 같은 면책 문구가 아니라, 훅이 넓혔던 범위를 정확히 회수하는 반전으로 쓴다.
- 같은 결과를 표현만 바꿔 두 번 말하지 마라. 5~7초마다 새 Claim·새 비교·새 시각 상태 중 하나가 등장해야 한다.
- 마지막 문장은 핵심 Claim 에 대한 정확한 답이다. 논문에 없는 교훈·도덕적 메시지·사회적 주장을 덧붙이지 마라.`;

const FACTSHEET_SYSTEM = `너는 사실 검증관이다. 아래 논문 초록에서 "검증 가능한 사실"만 추출한다.
추측·일반상식·초록에 없는 내용 금지. 항목별로 초록에 근거가 없으면 빈 배열로 둔다.
JSON only. 설명 문장·마크다운·코드펜스 금지.
{
  "what_found": ["<핵심 발견들>"],
  "how": ["<방법 요약>"],
  "numbers": ["<구체 수치와 그 의미>"],
  "limitations": ["<한계·표본·조건>"],
  "claim_strength": "<저자 주장의 강도: 강/중/약 + 근거>",
  "claims": [
    { "claim_id": "<비우면 코드가 C01, C02 … 로 부여>",
       "claim_kind": "<${CLAIM_KINDS.join("|")}>",
       "claim_ko": "<이 주장 한 문장(한국어)>",
       "population": "<연구 대상. 없으면 null>",
       "sample_size": "<표본 수. 없으면 null>",
       "geography": "<지역. 없으면 null>",
       "study_period": "<분석 기간. 없으면 null>",
       "study_design": "<연구 설계. 없으면 null>",
       "treatment_or_exposure": "<개입·노출. 없으면 null>",
       "comparison": "<비교군. 없으면 null>",
       "outcome": "<결과 지표. 없으면 null>",
       "outcome_definition": "<결과 지표 정의. 없으면 null>",
       "effect_direction": "<${EFFECT_DIRECTIONS.join("|")}>",
       "effect_size": "<효과 크기. 없으면 null>",
       "effect_unit": "<효과 크기 단위. 없으면 null>",
       "uncertainty": "<신뢰구간·표준오차. 없으면 null>",
       "statistical_significance": "<유의성 서술. 없으면 null>",
       "causal_strength": "<${CAUSAL_STRENGTHS.join("|")}>",
       "source_section": "<abstract|body|table|figure>",
       "source_page": <정수. 없으면 null>,
       "table_or_figure": "<표/그림 번호. 없으면 null>",
       "source_quote": "<이 주장을 지지하는 원문 한 구절(검증용). 없으면 null>",
       "limitations": ["<이 주장에 붙는 한계>"],
       "evidence_grade": "<${EVIDENCE_GRADES.join("|")}>" }
  ]
}
※ claims 규칙(★환각 방지의 핵심):
- 찾지 못한 값은 **추정하지 말고 null**. 빈 문자열도 쓰지 마라. 없는 표본 수·기간·효과 크기를 지어내면 안 된다.
- 상관과 인과를 구조적으로 구분하라. 논문이 인과 설계를 쓰지 않았으면 causal_strength 는 association_only 이하다.
- evidence_grade: A 는 본문·표·그림과 효과 크기를 실제로 확인한 경우만. **초록만 주어졌으면 A 를 쓰지 마라**
  (초록의 포괄적 결론만 확인되면 C). B 는 초록에서 명확히 확인되는 결과.
- 효과 크기가 없으면 "얼마나"를 임의로 보충하지 마라.
- 각 claim 은 하나의 주장만 담는다. 여러 결과를 한 claim 에 몰아넣지 마라.`;

const SCRIPT_SYSTEM = `너는 대중 과학 숏폼 대본 작가 겸 영상 연출자다. 입력으로 주어지는 것은 오직 "Fact Sheet"(JSON)뿐이다.
★ 절대 규칙: Fact Sheet에 없는 내용을 추가하지 마라. 수치·주장·예시는 Fact Sheet에 있는 것만 사용한다.
각 씬에는 그 씬이 근거한 Fact Sheet 항목 키를 source_facts 로 남긴다(예: "what_found[0]", "numbers[1]").
Fact Sheet 에 claims(주장 원장)가 있으면 각 씬에 claim_ids 로 **원장에 실제로 있는 id 만** 남겨라.
근거가 없으면 그 씬을 만들지 마라.

산출물은 "단계별로 미디어화 가능한 제작 지시서"다. 네 가지를 만든다:
(1) content_plan — 무엇을 몇 초에 담을지의 계획. ★대본보다 **먼저** 세운다.
(2) video_flow — 전체 세부 영상 흐름(스토리보드). 영상이 처음부터 끝까지 어떻게 흘러가는지.
(3) scenes — 주요 장면마다 [이미지 프롬프트 → 영상 프롬프트 → 나레이션]. 제작 순서는
    각 장면의 스틸 이미지를 먼저 만들고 → 그 이미지를 움직여 영상화 → 나레이션으로 진행한다.
(4) script_md — 사람이 읽는 전체 대본(나레이션 흐름 전문).

[★ content_plan — 길이를 먼저 고정하지 마라. 논문 복잡도가 길이를 정한다.]
순서: ①핵심 주장 1개(primary_claim_id) 선택 → ②정확한 이해에 꼭 필요한 Evidence Unit 선택 →
③그 개수로 content_mode 결정 → ④그 모드 범위 안에서 **가장 짧은** 길이 선택.
 Evidence Unit: E1 핵심결과 / E2 대상·지역·기간 / E3 비교방식·연구설계 / E4 효과크기·대표수치 /
   E5 작동원리 / E6 조건·예외·하위집단 / E7 한계·인과범위 / E8 논문이 직접 지지하는 의미
   ★ E1·E2·E7 은 모든 영상 필수. 나머지는 정말 필요할 때만 넣어라(넣을수록 영상이 길어진다).
   조건부 필수: 수치 연구면 E4 / 인과 표현을 쓰면 E3 / 조절효과를 훅에 쓰면 E6 / 원리가 핵심이면 E5.
 content_mode: flash 25~35초(필수 근거 3개 이하 + 단일 수치나 명확한 반전)
   / standard 36~50초(범위·방법·결과·한계가 모두 필요 — 기본값)
   / deep 51~65초(조절효과·메커니즘이 결론에 중요해서 생략하면 인과 오해가 생김)
   / extended 66~80초(★예외 모드 — 65초로 압축하면 사실 왜곡이 생기는 경우만. compression_risk=high 근거 필수)
   / series_split(독립적인 핵심 주장이 2개 이상 — 한 편을 늘리지 말고 분할을 제안하라)
 ★ 60초를 채우려고 일상 예시·반복·CTA 를 늘리지 마라. 근거가 적으면 28초로 끝내는 게 정답이다.
 ★ 80초를 넘겨야 하면 한 편을 늘리지 말고 series_split 을 고르고 series_split_reason 을 적어라.
 evidence_delivery — 각 Evidence Unit 을 어떻게 전달할지 정한다:
   spoken(나레이션) / visual(화면에만) / both(말하고 강조) / caption(설명란) / omit(이번엔 안 씀).
   권장: 핵심 결과·대표 수치=both, 표본·기간=visual, 연구 방법=한 문장 spoken,
        상세 통계=visual, 부차 한계=caption, 핵심 일반화 한계=spoken.

[★ 서사 배치 — 근거를 "설명"으로 나열하지 말고 반전 장치로 써라]
나쁨: 결과 → 방법 설명 → 표본 설명 → 기간 설명 → 한계 설명(면책 문구)
좋음: 강한 결과 → "그런데 이건 X 자체를 조사한 게 아닙니다" → 실제 연구 범위 공개 →
     비교 결과 → 예외 조건 → 한계를 포함한 정확한 결론
★ 한 영상에 핵심 주장은 1개다. 보조 주장은 핵심 주장을 설명하거나 제한하는 역할만 한다.
  독립적인 두 번째 결과가 중요하면 나열하지 말고 series_split 을 제안하라.
각 씬은 evidence_role 로 자기가 맡은 근거 역할을 밝힌다:
  ${EVIDENCE_ROLES.join("|")}

[★ 나레이션 서사 규칙]
- 한 씬 = 한 메시지. 한 씬에 여러 사실·여러 수치를 몰아넣지 마라.
- 앞뒤 문맥 연결: 각 씬 나레이션은 이전 씬을 자연스럽게 이어받아라(그래서/하지만/즉 등). 순서대로 읽으면 하나의 이야기가 되게.
${EVIDENCE_RULES_SHARED}
- 숫자 나열·괄호·기호·긴 수식은 나레이션에서 금지(소리 내 읽기 어렵다). 친구에게 말하듯 구어체로.
- 마지막 씬은 후크에서 던진 궁금증에 답한다.
- ★출처 구체화: "한 연구/어떤 연구"처럼 추상적으로 말하지 말고, Fact Sheet의 source로 구체적으로 지칭하라.
  ★지칭 우선순위: 기관 > 저자명 > 게재처. 기관(institutions)이 있으면 "스탠퍼드 연구팀이"처럼, 없으면
  저자명(authors)으로 "제인 도 연구진이", "○○○ 팀이"처럼 사람 이름을 써라. 게재처만으로 "arXiv에 발표된
  연구"처럼 밋밋하게 끝내지 마라 — 저자명이 있으면 반드시 사람 이름을 넣는다(예: "제인 도 등 연구진의
  이번 arXiv 논문은"). 저자·기관이 모두 없을 때만 게재처/분야로 특정한다. ★source에 있는 것만 써라 —
  없는 기관·저자를 절대 지어내지 마라. 최소 1회는 도입부에서 누가 한 연구인지 밝혀라.

[image_prompt 작성 규칙 — 텍스트-투-이미지 AI(Midjourney/Imagen/Flux 등 도구 무관)에 그대로 붙여
스틸 한 장을 뽑을 수준으로. 영어로, 콤마로 이어지는 하나의 리치 프롬프트. "정지 이미지" 관점.]
반드시 아래 정적 요소를 순서대로 구체적으로 포함:
1) shot/framing — 예: extreme close-up, wide establishing shot, macro, split-screen
2) main subject + 구체적 외형 묘사
3) setting/environment
4) lens/optics — 예: 35mm, shallow depth of field, macro
5) lighting — 예: volumetric, soft rim light, chiaroscuro, high-key
6) color palette / mood
7) ★화풍·매체 어휘를 **쓰지 마라** — webtoon / comic / photorealistic / 3D render / illustration /
   cel shading / ink outlines 같은 말을 넣지 않는다. 화풍은 초안이 아니라 **지시서 단계에서 버전별로
   코드가 붙인다**(만화식·3D 그래픽 중 운영자가 고른다). 여기서는 장면만 적는다 — 누가·어디서·무엇을·
   어떤 구도로. 같은 인물이 다시 나오면 외형 묘사를 같게 유지한다(화풍이 아니라 **생김새**로).
8) technical tags — "vertical 9:16, 4K, high detail, no on-screen text"

[video_prompt 작성 규칙 — 이미지-투-영상 AI(Runway/Kling/Veo 등 도구 무관)에 그대로 붙여
위 스틸을 "움직이는 영상"으로 만들 지시. 영어로, 콤마로 이어지는 하나의 리치 프롬프트.
"animate the still image" 관점 — 정적 요소는 반복하지 말고 '움직임'만 지시.]
반드시 포함:
1) camera movement — 예: slow dolly-in, orbit, crane-up, whip-pan, rack-focus, parallax push
2) subject motion/action — 화면 안 피사체·요소의 구체적 움직임
3) pacing/speed — 예: slow-mo, steady, quick burst
4) 지속시간감과 루프 여부(예: seamless subtle loop)
공통 제약:
- 시각은 Fact Sheet 사실의 "시각화·은유"만. Fact Sheet에 없는 구체 수치·결과·객체를 지어내지 마라.
- 화면 안에 읽히는 글자/숫자/자막/워터마크 렌더 금지("no on-screen text" 명시).
- 영상이므로 정지컷 금지 — video_prompt엔 반드시 카메라 무빙과 모션 포함.
- ★만화 그림을 그대로 애니메이션하는 관점(웹툰 화풍 유지) — 실사화·3D화 금지, 정적 요소의 화풍은 image_prompt와 동일하게.

[한국어 설명 병기 — image_prompt_ko / video_prompt_ko]
image_prompt·video_prompt는 툴에 그대로 붙일 "영문"이고, 각각에 대응하는 한국어 설명을
image_prompt_ko(어떤 스틸 장면인지)·video_prompt_ko(어떻게 움직이는지)에 1~2문장으로 적어라.
사람이 영문을 안 읽어도 무엇을 만들지 이해하도록. 영문 프롬프트의 충실한 한국어 요약이어야 한다.

[★ 훅 후보 3개 — hook_candidates]
영상 첫 1.5초를 책임질 훅 후보를 **정확히 3개** 만들고, 그중 하나를 selected_hook_id 로 고른다.
- 각 훅은 반드시 claim_ids 로 특정 주장과 연결된다. 연결이 없는 훅은 만들지 마라.
- 자극성은 낮추지 말고 **범위를 좁혀라**. 허용: 반전 / 충격 수치 / 비교 / 개인 영향 / 인과 미스터리 /
  상식 충돌 / 도발적 질문.
- 금지: 연구 대상을 기술·산업·인류 전체로 확대 / 상관관계를 원인으로 단정 / 일부 기업·일부 지역의
  결과를 전체로 확대 / 수치 없는 결과에 "폭락·급감·압도적" 사용 / 논문이 검증하지 않은 피해·위험 추가 /
  본문에서 지불하지 못하는 약속.
- scope_preserved: 훅의 주어·범위가 연결된 Claim 의 범위를 넘지 않으면 true.
- causal_calibrated: 훅의 인과 표현이 그 Claim 의 causal_strength 를 넘지 않으면 true.
- ★ evidence_grade 가 C 인 Claim 에는 단정형 충격수치 훅을 쓰지 마라(보수적 표현만 가능).
- promise 에는 "이 훅이 시청자에게 약속하는 것"을 적어라. 본문이 그걸 실제로 지불해야 한다.
예) 나쁨 "블록체인 기술이 지구를 망친다고요?"(기술 전체·지구로 확대)
    좋음 "블록체인을 장려했더니 기업이 덜 친환경적으로 변했다고요?"(정책·기업으로 범위 축소, 반전 유지)

[★ 유튜브 업로드용 제목 — upload_title_ko / upload_title_en]
숏폼(유튜브 Shorts) 업로드 제목을 한국어·영어로 각각 만든다. 논문 원제는 밋밋하니 쓰지 마라.
- 클릭을 부르는 자극적·호기심 유발형 훅. 시청자가 "뭐라고?" 하고 멈추게.
- 짧게(한국어 대략 15~30자, 영어 대략 40~70자). 한 줄, 문장부호 최소.
- 언어별 독립 트랜스크리에이션(직역 금지) — 각 언어에서 자연스럽고 강한 표현으로.
- ★환각 금지: Fact Sheet에 없는 수치·주장·결과를 지어내지 마라. 과장 표현은 되지만 없는 사실은 금지.
- 낚시성 거짓(clickbait 허위)은 금지 — 영상 내용과 어긋나면 안 된다.

출력은 JSON only. 설명·마크다운·코드펜스 금지.
{
  "upload_title_ko": "<자극적 한국어 업로드 제목 한 줄>",
  "upload_title_en": "<자극적 영어 업로드 제목 한 줄>",
  "content_plan": {
    "primary_claim_id": "<핵심 주장 1개의 claim_id. 원장이 없으면 빈 문자열>",
    "supporting_claim_ids": ["<핵심 주장을 설명·제한하는 보조 주장 id>"],
    "essential_evidence_units": ["E1", "E2", "E7"],
    "evidence_delivery": { "E1": "both", "E2": "visual", "E7": "spoken" },
    "complexity": "<low|medium|high>",
    "visualizability": "<low|medium|high>",
    "compression_risk": "<low|medium|high — 더 짧게 줄이면 사실 왜곡·인과 오해가 생길 위험>",
    "selected_mode": "<${CONTENT_MODES.join("|")}>",
    "target_duration_min_sec": <int>,
    "target_duration_max_sec": <int>,
    "duration_reason": "<왜 이 길이가 필요한지 한 문장>",
    "series_split_reason": "<series_split 일 때만: 무엇과 무엇으로 나눌지 한 문장. 아니면 빈 문자열>"
  },
  "hook_candidates": [
    { "hook_id": "H-A",
      "text_ko": "<훅 한 줄(한국어)>",
      "angle": "<${HOOK_ANGLES.join("|")}>",
      "claim_ids": ["<이 훅이 근거하는 claim_id>"],
      "scope_preserved": <bool>,
      "causal_calibrated": <bool>,
      "promise": "<이 훅이 약속하는 것>",
      "risk": "<low|medium|high>" }
  ],
  "selected_hook_id": "<hook_candidates 중 1개의 hook_id>",
  "video_flow": {
    "logline": "<이 영상 한 줄 컨셉(한국어)>",
    "total_duration_sec": <int>,
    "beats": [
      { "order": <int>, "label": "<후크/개념/수치/일상연결/의심/CTA 등>",
        "summary": "<이 비트에서 화면에 무엇이 보이고 무엇을 전달하는가(한국어)>",
        "transition": "<다음 장면으로의 전환 방식(예: 매치컷, 페이드, 급속 줌)>" }
    ]
  },
  "script_md": "<읽기용 대본 전문(한국어 나레이션 흐름)>",
  "scenes": [
    {
      "scene": <int>,
      "title": "<장면 짧은 제목(한국어)>",
      "narration_ko": "<한국어 나레이션>",
      "narration_en": "<영어 나레이션>",
      "duration_sec": <int>,
      "image_prompt": "<위 규칙대로 매우 상세한 영문 텍스트→이미지 프롬프트(스틸)>",
      "image_prompt_ko": "<image_prompt의 한국어 설명 — 어떤 스틸 장면인지 1~2문장>",
      "video_prompt": "<위 규칙대로 영문 이미지→영상 프롬프트(그 스틸의 모션)>",
      "video_prompt_ko": "<video_prompt의 한국어 설명 — 어떻게 움직이는지 1~2문장>",
      "source_facts": ["<Fact Sheet 항목 키>"],
      "claim_ids": ["<이 씬이 근거하는 claim_id — 원장에 있는 것만>"],
      "evidence_role": "<${EVIDENCE_ROLES.join("|")}>",
      "evidence_delivery": "<${EVIDENCE_DELIVERY.join("|")} — 이 씬의 근거를 어떻게 전달하는가>"
    }
  ]
}`;

const SELFCHECK_SYSTEM = `너는 엄격한 사실 검증관이다. 입력: Fact Sheet(JSON) + 생성된 대본 씬들(JSON).
대본의 각 문장이 Fact Sheet의 항목으로 뒷받침되는지 판정한다.
Fact Sheet에 근거가 없는 문장은 grounded=false 로 표시하고 그 문장을 그대로 적는다.
보수적으로 판단하라: 근거가 모호하면 grounded=false.

Fact Sheet 에 claims(주장 원장)가 있으면 씬마다 아래를 **따로** 판정한다. "비슷하다"로 뭉뚱그리지 마라.
- matched_claim_ids: 이 씬을 실제로 뒷받침하는 claim_id 들. 원장에 있는 id 만 쓴다.
- scope_match: 씬이 말하는 대상·지역·기간의 범위가 Claim 의 범위를 넘지 않으면 true.
  ★일부 기업·일부 지역 결과를 "기업들은"·"전 세계"로 넓혔으면 false.
- causal_calibration: 씬의 인과 표현이 Claim 의 causal_strength 를 넘지 않으면 "pass".
  ★association_only 인 Claim 을 "때문에·유발한다·낮췄다"로 말했으면 "fail".
  인과 표현이 아예 없으면 "not_applicable".
- numeric_match: 씬의 숫자·단위·증감 방향이 Claim 과 일치하면 "pass", 어긋나면 "fail",
  숫자가 없으면 "not_applicable".
- qualifier_preserved: Claim 의 조건·단서(일부·평균적으로·특정 조건에서)가 씬에서 지워지지
  않았으면 true.
- editorial_inference: 논문이 지지하지 않는 새 해석·교훈·사회적 주장을 씬이 덧붙였으면 true.
  ★특히 마지막 결론 문장을 엄격히 보라("결국 사람의 비전이 중요하다" 같은 일반 철학으로의 확대).

■■ 아래 한 축만은 **사실이 아니라 문장**을 본다(운영자 지시 2026-09-10).
   이 대본은 **소리 내어 읽히는 나레이션**이다. 눈으로 읽어 말이 되는 것으로는 부족하고,
   귀로 들어서 걸리는 데가 없어야 한다. 사실 판정과 **섞지 마라** — 여기서 내용이 틀렸는지는
   보지 않는다.
- korean_natural: 그 씬의 나레이션이 한국어로 자연스러우면 true, 어색하면 false.
- awkward_spans: 어색한 **구절을 원문 그대로** 옮겨 적는다(문장 전체가 아니라 걸리는 부분).
- fluency_issues: 무엇이 어색한지 아래 표에서 고른다(여러 개 가능).
  "translationese" 번역투 — "~에 대한", "~를 통해", "~에 있어서", "가지고 있다",
                    불필요한 피동("~되어진다"), 영어 어순을 그대로 옮긴 긴 주어.
  "particle"        조사가 어색하다 — 은/는·이/가·을/를 자리가 틀렸거나 겹친다.
  "register_mix"    문어체와 구어체가 한 대본 안에서 섞인다("~한다" ↔ "~합니다").
  "long_modifier"   수식이 겹겹이 쌓여 한 호흡에 못 읽는다(관형절 3개 이상, 60자 넘는 한 문장).
  "reading"         소리 내 읽을 때 걸린다 — 숫자·단위·영어 약어가 어떻게 읽히는지 불분명
                    ("NAD+" 를 뭐라고 읽나, "92일" 이 "구십이 일"인가 "구십 이일"인가).
★ 보수적으로 판단하라. 취향 문제(더 멋진 표현이 있다)는 어색함이 아니다 —
  **읽다가 걸리는 것만** false 로 한다. 애매하면 true.

JSON only. 설명·마크다운·코드펜스 금지.
{
  "scenes": [
    { "scene": <int>, "grounded": <bool>,
      "unsupported": ["<근거 없는 문장 원문>"],
      "matched_facts": ["<뒷받침하는 Fact Sheet 키>"],
      "matched_claim_ids": ["<뒷받침하는 claim_id>"],
      "scope_match": <bool>,
      "causal_calibration": "<${SELFCHECK_TRISTATE.join("|")}>",
      "numeric_match": "<${SELFCHECK_TRISTATE.join("|")}>",
      "qualifier_preserved": <bool>,
      "editorial_inference": <bool>,
      "korean_natural": <bool>,
      "awkward_spans": ["<어색한 구절 원문 그대로>"],
      "fluency_issues": ["<${SELFCHECK_FLUENCY_KINDS.join("|")} 중>"],
      "issues": ["<사람이 읽을 문제 요약 한 줄>"] }
  ],
  "all_grounded": <bool>
}`;

// engine/script_polish.py:POLISH_SYSTEM 이식. **표현만** 고치고 사실은 못 건드리게 한다.
const POLISH_SYSTEM = `너는 한국어 나레이션 교정자다. 입력: 어색하다고 표시된 대본 씬들.

■ 하는 일은 **하나뿐이다: 한국어를 자연스럽게 다듬는다.**
  이 글은 소리 내어 읽힌다. 귀로 들어 걸리는 데가 없게 고쳐라.
  · 번역투를 우리말로 — "~에 대한 연구" → "~를 다룬 연구", "~를 통해" → "~로",
    "가지고 있다" → "있다", "~되어진다" → "~된다".
  · 조사를 바로잡는다(은/는·이/가·을/를).
  · 문체를 통일한다 — 한 대본 안에서 "~합니다" 와 "~한다" 를 섞지 마라.
  · 수식이 겹치면 문장을 **끊어라**. 한 문장은 한 호흡(60자 안쪽)이 좋다.
  · 소리 내 읽었을 때 모호한 것을 풀어라 — 영어 약어는 한글 표기를 덧붙이고
    ("NAD+" → "엔에이디 플러스"), 숫자·단위는 읽히는 대로 띄어 준다.

■■ **절대 하지 마라 — 사실을 건드리는 것.**
  · 숫자·단위·퍼센트·배수를 **바꾸거나 빼거나 더하지 마라.** 원문에 있는 그대로 옮긴다.
  · 대상·기간·지역의 **범위를 넓히거나 좁히지 마라**("일부 쥐에서" → "쥐에서" 금지).
  · 단서·조건을 **지우지 마라**("평균적으로", "특정 조건에서", "~로 보입니다").
  · 인과를 **세게 만들지 마라**("연관이 있었다" → "때문이다" 금지).
  · 없던 설명·비유·감상을 **덧붙이지 마라.** 문장 수와 길이를 크게 바꾸지 마라.
  ★ 고칠 것이 없으면 원문을 그대로 돌려줘라. 억지로 바꾸지 마라.

JSON only. 설명·마크다운·코드펜스 금지.
{
  "scenes": [
    { "scene": <int>, "narration_ko": "<다듬은 나레이션 전문>",
      "changed": <bool>, "note": "<무엇을 고쳤는지 한 줄>" }
  ]
}`;

// ─────────────────────────────────────────────────────────────
// LLM 호출 (engine/llm.py 이식: JSON only + 파싱 1회 재시도 + 5xx/타임아웃 지수 백오프)
// ─────────────────────────────────────────────────────────────
function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function extractJSON(text: string): any {
  // 코드펜스/잡텍스트를 관용적으로 벗겨 JSON 객체 파싱 (engine/llm.py:_extract_json 이식).
  let s = text.trim();
  if (s.startsWith("```")) {
    const fenceCount = (s.match(/```/g) ?? []).length;
    s = fenceCount >= 2 ? s.split("```")[1] ?? s : s.replace(/`/g, "");
    if (s.trimStart().toLowerCase().startsWith("json")) s = s.trimStart().slice(4);
  }
  const start = s.indexOf("{");
  const end = s.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) throw new Error("JSON 객체를 찾지 못함");
  return JSON.parse(s.slice(start, end + 1));
}

async function anthropicText(
  model: string,
  system: string,
  user: string,
  maxTokens: number,
): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const resp = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": ANTHROPIC_API_KEY,
          "anthropic-version": "2023-06-01",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model,
          max_tokens: maxTokens,
          system,
          messages: [{ role: "user", content: user }],
        }),
        signal: AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
      // 429/5xx 만 재시도. 그 외 4xx 는 즉시 실패(재시도 무의미).
      if (resp.status === 429 || resp.status >= 500) {
        throw new Error(`anthropic ${resp.status}`);
      }
      if (!resp.ok) {
        const body = await resp.text();
        const err: any = new Error(`anthropic ${resp.status}: ${body.slice(0, 200)}`);
        err.fatal = true;
        throw err;
      }
      const data = await resp.json();
      // Gemini 쪽과 같은 이유 — 잘린 응답은 원인을 밝혀 실패시킨다(재시도해도 또 잘린다).
      if (data?.stop_reason === "max_tokens") {
        const err: any = new Error(`anthropic 출력이 max_tokens(${maxTokens}) 에서 잘렸다 — JSON 미완성`);
        err.fatal = true;
        throw err;
      }
      return (data.content ?? [])
        .filter((b: any) => b?.type === "text")
        .map((b: any) => b.text)
        .join("");
    } catch (err: any) {
      lastErr = err;
      if (err?.fatal) break; // 재시도 불가 오류는 즉시 중단
      if (attempt < MAX_RETRIES - 1) await sleep(BACKOFF_BASE_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

async function geminiText(
  model: string,
  system: string,
  user: string,
  maxTokens: number,
): Promise<string> {
  // Gemini REST 호출 (engine/llm.py:_gemini_create 이식). responseMimeType=json 으로 JSON 강제.
  // gemini-2.5 사고 처리: flash 는 사고 끔(budget 0), pro 등은 사고 필수(budget 0 거부) → 출력 예산을 키워 JSON 절단 방지.
  const ml = model.toLowerCase();
  const genConfig: any = {
    responseMimeType: "application/json",
    maxOutputTokens: maxTokens,
    temperature: 0.4,
  };
  if (ml.includes("2.5") && ml.includes("flash")) genConfig.thinkingConfig = { thinkingBudget: 0 };
  else if (ml.includes("2.5")) genConfig.maxOutputTokens = Math.max(maxTokens, 32768);
  let lastErr: unknown;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const resp = await fetch(`${GEMINI_BASE}/${model}:generateContent?key=${GEMINI_API_KEY}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          system_instruction: { parts: [{ text: system }] },
          contents: [{ role: "user", parts: [{ text: user }] }],
          generationConfig: genConfig,
        }),
        signal: AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
      if (resp.status === 429 || resp.status >= 500) throw new Error(`gemini ${resp.status}`);
      if (!resp.ok) {
        const body = await resp.text();
        const err: any = new Error(`gemini ${resp.status}: ${body.slice(0, 200)}`);
        err.fatal = true;
        throw err;
      }
      const data = await resp.json();
      const cand = data?.candidates?.[0];
      // 예산 초과로 잘린 응답은 반드시 JSON 파싱에서 깨진다. 그때의 SyntaxError 는 원인을
      // 못 알려주므로(2026-07-29 장애) 여기서 잘렸다는 사실 자체를 오류로 올린다.
      // 같은 예산으로 다시 불러도 또 잘리니 재시도하지 않는다(fatal).
      if (cand?.finishReason === "MAX_TOKENS") {
        const err: any = new Error(
          `gemini 출력이 maxOutputTokens(${genConfig.maxOutputTokens}) 에서 잘렸다 — JSON 미완성`,
        );
        err.fatal = true;
        throw err;
      }
      const parts = cand?.content?.parts ?? [];
      return parts.map((p: any) => p?.text ?? "").join("");
    } catch (err: any) {
      lastErr = err;
      if (err?.fatal) break;
      if (attempt < MAX_RETRIES - 1) await sleep(BACKOFF_BASE_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

// 모델 id 로 백엔드 라우팅 — "gemini*" 면 Gemini, 아니면 Anthropic (engine/llm.py 와 동일).
function llmText(model: string, system: string, user: string, maxTokens: number): Promise<string> {
  return model.toLowerCase().startsWith("gemini")
    ? geminiText(model, system, user, maxTokens)
    : anthropicText(model, system, user, maxTokens);
}

async function callJSON(
  stage: string,
  model: string,
  system: string,
  user: string,
  maxTokens: number,
): Promise<any> {
  let lastErr: unknown;
  for (let i = 0; i <= JSON_RETRY; i++) {
    let raw: string;
    try {
      raw = await llmText(model, system, user, maxTokens);
    } catch (err) {
      // 어느 단계에서 터졌는지 큐(draft_requests.error)·대시보드에 남긴다.
      throw new Error(`[${stage}] ${err}`);
    }
    try {
      return extractJSON(raw);
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(`[${stage}] ${lastErr}`);
}

// ─────────────────────────────────────────────────────────────
// 정규화 (engine 의 normalize_* 이식 — drafts 스키마와 동일 shape 보장)
// ─────────────────────────────────────────────────────────────
const LIST_KEYS = ["what_found", "how", "numbers", "limitations"] as const;

const sanEnum = (v: unknown, allowed: string[], def: string): string => {
  const tok = String(v ?? "").trim().toLowerCase();
  return allowed.includes(tok) ? tok : def;
};

const strList = (v: any): string[] => {
  if (typeof v === "string") return v ? [v] : [];
  if (!Array.isArray(v)) return [];
  return v.map((x) => String(x));
};

// "없으면 null" — 빈 문자열을 남기면 "확인됨"으로 오독된다(engine/factsheet.py:_nullable 이식).
const NULLISH = ["null", "none", "n/a", "na", "미상", "없음", "불명"];
function nullable(v: any): any {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const s = String(v).trim();
  if (!s || NULLISH.includes(s.toLowerCase())) return null;
  return s;
}

// engine/factsheet.py:_normalize_claim 이식. 코드가 덮어쓰는 것:
// claim_id(결정론적) · missing_fields(재계산) · evidence_grade(초록만이면 A→B 강등).
function normalizeClaim(item: any, index: number) {
  const src = item && typeof item === "object" && !Array.isArray(item) ? item : {};
  const out: Record<string, any> = {
    claim_id: String(src.claim_id ?? "").trim() || `C${String(index + 1).padStart(2, "0")}`,
    claim_kind: sanEnum(src.claim_kind, CLAIM_KINDS, DEFAULT_CLAIM_KIND),
    claim_ko: (item && typeof item === "object")
      ? String(src.claim_ko ?? "").trim()
      : String(item ?? "").trim(),
  };
  for (const f of CLAIM_NULLABLE_FIELDS) out[f] = nullable(src[f]);
  const page = out.source_page;
  out.source_page = typeof page === "number" && Number.isFinite(page) ? Math.trunc(page) : null;

  out.effect_direction = sanEnum(src.effect_direction, EFFECT_DIRECTIONS, DEFAULT_EFFECT_DIRECTION);
  out.causal_strength = sanEnum(src.causal_strength, CAUSAL_STRENGTHS, DEFAULT_CAUSAL_STRENGTH);
  out.source_section = sanEnum(src.source_section, SOURCE_SECTIONS, "abstract");
  out.limitations = strList(src.limitations).map((x) => x.trim()).filter(Boolean);

  let grade = String(src.evidence_grade ?? "").trim().toUpperCase();
  if (!EVIDENCE_GRADES.includes(grade)) grade = DEFAULT_EVIDENCE_GRADE;
  // EVIDENCE_GRADES 는 강한 순(A→D)이라 인덱스가 작을수록 강하다.
  const ceiling = EVIDENCE_GRADES.indexOf(ABSTRACT_ONLY_MAX_GRADE);
  if (out.source_section === "abstract" && EVIDENCE_GRADES.indexOf(grade) < ceiling) {
    grade = ABSTRACT_ONLY_MAX_GRADE;
  }
  out.evidence_grade = grade;
  out.missing_fields = CLAIM_NULLABLE_FIELDS.filter((f) => out[f] === null);
  return out;
}

function dedupeClaimIds(claims: any[]): any[] {
  const seen = new Map<string, number>();
  for (const c of claims) {
    const cid = c.claim_id;
    if (seen.has(cid)) {
      const n = (seen.get(cid) ?? 0) + 1;
      seen.set(cid, n);
      c.claim_id = `${cid}_${n}`;
    } else {
      seen.set(cid, 0);
    }
  }
  return claims;
}

function normalizeFactsheet(obj: any) {
  const out: Record<string, any> = {};
  for (const k of LIST_KEYS) {
    let val = obj?.[k] ?? [];
    if (typeof val === "string") val = val ? [val] : [];
    out[k] = (Array.isArray(val) ? val : []).map((x: any) => String(x));
  }
  out.claim_strength = String(obj?.claim_strength ?? "");
  // claims 는 기존 5키 **위에 병렬 추가**한다(원장 없는 과거 초안도 그대로 동작).
  const raw = obj?.claims;
  out.claims = Array.isArray(raw)
    ? dedupeClaimIds(raw.map((c: any, i: number) => normalizeClaim(c, i)))
    : [];
  return out;
}

function claimIdsOf(factSheet: any): Set<string> {
  const claims = Array.isArray(factSheet?.claims) ? factSheet.claims : [];
  return new Set(claims.map((c: any) => String(c?.claim_id ?? "")).filter(Boolean));
}

function toInt(v: any, fallback: number): number {
  const n = Math.trunc(Number(v));
  return Number.isFinite(n) ? n : fallback;
}

function normalizeFlow(obj: any) {
  const flow = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
  const beatsIn = Array.isArray(flow.beats) ? flow.beats : [];
  const beats: any[] = [];
  beatsIn.forEach((b: any, i: number) => {
    if (typeof b !== "object" || b === null || Array.isArray(b)) return;
    beats.push({
      order: toInt(b.order, i + 1) || i + 1,
      label: String(b.label ?? ""),
      summary: String(b.summary ?? ""),
      transition: String(b.transition ?? ""),
    });
  });
  return {
    logline: String(flow.logline ?? ""),
    total_duration_sec: toInt(flow.total_duration_sec, 0),
    beats,
  };
}

// engine/content_mode.py:select_mode 이식.
function selectMode(
  unitCount: number, deepForcing: boolean, compressionRisk: string, independentMain: number,
): string {
  if (independentMain >= 2) return "series_split";
  if (unitCount > MODE_UNITS_DEEP_MAX) return compressionRisk === "high" ? "extended" : "deep";
  if (unitCount >= MODE_UNITS_DEEP_MAX || deepForcing) return "deep";
  if (unitCount <= MODE_UNITS_FLASH_MAX) return "flash";
  if (unitCount <= MODE_UNITS_STANDARD_MAX) return "standard";
  return "deep";
}

// engine/content_mode.py:normalize_content_plan 이식. 코드가 덮어쓰는 것:
// 필수 Evidence Unit 강제 · selected_mode 재판정 · target_duration_* 를 모드에서 재유도.
function normalizeContentPlan(obj: any, known: Set<string>, independentMain: number) {
  const src = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
  const units = strList(src.essential_evidence_units).filter((u) => EVIDENCE_UNITS.includes(u));
  for (const req of EVIDENCE_UNITS_REQUIRED) if (!units.includes(req)) units.push(req);
  units.sort();

  let primary = String(src.primary_claim_id ?? "").trim();
  if (known.size && !known.has(primary)) primary = "";
  const supporting = strList(src.supporting_claim_ids)
    .filter((c) => (!known.size || known.has(c)) && c !== primary);

  const delivery: Record<string, string> = {};
  if (src.evidence_delivery && typeof src.evidence_delivery === "object") {
    for (const [unit, mode_] of Object.entries(src.evidence_delivery)) {
      if (EVIDENCE_UNITS.includes(unit.trim())) {
        delivery[unit.trim()] = sanEnum(mode_, EVIDENCE_DELIVERY, DEFAULT_EVIDENCE_DELIVERY);
      }
    }
  }

  const compressionRisk = sanEnum(src.compression_risk, ["low", "medium", "high"], "medium");
  const deepForcing = units.includes("E5") || units.includes("E6");
  const warnings: string[] = [];
  const proposed = CONTENT_MODES.includes(String(src.selected_mode ?? "").trim())
    ? String(src.selected_mode).trim() : "";
  const derived = selectMode(units.length, deepForcing, compressionRisk, independentMain);
  let mode = proposed || derived;

  if (mode === "extended" && compressionRisk !== "high") {
    mode = "deep";
    warnings.push("extended_demoted_no_compression_risk");
  }
  if (mode === "flash" && units.length >= MODE_FLASH_WARN_UNITS) {
    warnings.push("flash_with_many_evidence_units");
  }
  if (independentMain >= 2 && mode !== "series_split") {
    mode = "series_split";
    warnings.push("forced_series_split_multiple_main_claims");
  }
  if (proposed && proposed !== mode) warnings.push(`mode_overridden:${proposed}->${mode}`);
  else if (proposed && proposed !== derived) warnings.push(`mode_differs_from_rule:${derived}`);

  const [lo, hi] = CONTENT_MODE_DURATION[mode] ?? [36, 50];
  return {
    primary_claim_id: primary,
    supporting_claim_ids: supporting,
    essential_evidence_units: units,
    evidence_delivery: delivery,
    complexity: sanEnum(src.complexity, ["low", "medium", "high"], "medium"),
    visualizability: sanEnum(src.visualizability, ["low", "medium", "high"], "medium"),
    compression_risk: compressionRisk,
    selected_mode: mode,
    target_duration_min_sec: lo,
    target_duration_max_sec: hi,
    duration_reason: String(src.duration_reason ?? "").trim(),
    series_split_reason: String(src.series_split_reason ?? "").trim(),
    mode_warnings: warnings,
  } as Record<string, any>;
}

// 나레이션에서 "소리 내 읽는 숫자" 계수(engine/scriptgen.py:_SPOKEN_NUMBER_RE 와 동일 패턴).
const SPOKEN_NUMBER_RE = /\d+(?:[.,]\d+)*\s*(?:%|퍼센트|배|명|개|건|년|개월|일|시간|원|달러|p|%p)?/g;
function countSpokenNumbers(narration: string): number {
  return (String(narration ?? "").match(SPOKEN_NUMBER_RE) ?? []).length;
}

// engine/scriptgen.py:_normalize_hook_candidates 이식 — 즉시탈락(§8-2)은 코드가 판정한다.
function normalizeHookCandidates(raw: any, selected: any, known: Set<string>, factSheet: any) {
  const grades = new Map<string, string>();
  for (const c of (Array.isArray(factSheet?.claims) ? factSheet.claims : [])) {
    if (c?.claim_id) grades.set(String(c.claim_id), String(c.evidence_grade ?? DEFAULT_EVIDENCE_GRADE));
  }
  const items = Array.isArray(raw) ? raw : [];
  const out: any[] = [];
  items.forEach((h: any, i: number) => {
    const src = h && typeof h === "object" ? h : {};
    let ids = strList(src.claim_ids).map((x) => x.trim()).filter(Boolean);
    if (known.size) ids = ids.filter((x) => known.has(x));
    const text = String(src.text_ko ?? "").trim();
    const cand: Record<string, any> = {
      hook_id: String(src.hook_id ?? "").trim() || `H-${String.fromCharCode(65 + i)}`,
      text_ko: text,
      angle: sanEnum(src.angle, HOOK_ANGLES, DEFAULT_HOOK_ANGLE),
      claim_ids: ids,
      scope_preserved: src.scope_preserved === true,
      causal_calibrated: src.causal_calibrated === true,
      promise: String(src.promise ?? "").trim(),
      risk: String(src.risk ?? "medium").trim().toLowerCase(),
    };
    const bad: string[] = [];
    if (!text) bad.push("empty_text");
    if (known.size && !ids.length) bad.push("no_claim_link");
    if (!cand.scope_preserved) bad.push("scope_not_preserved");
    if (!cand.causal_calibrated) bad.push("causal_not_calibrated");
    if (!cand.promise) bad.push("no_promise");
    const weak = ids.filter((c) => ["C", "D"].includes(grades.get(c) ?? DEFAULT_EVIDENCE_GRADE));
    if (weak.length && HOOK_STRONG_CLAIM_WORDS.some((w) => text.includes(w))) {
      bad.push("bold_claim_on_weak_evidence");
    }
    cand.disqualify_reasons = bad;
    cand.eligible = bad.length === 0;
    out.push(cand);
  });
  if (!out.length) return { hooks: [], selected: "" };
  const byId = new Map(out.map((c) => [c.hook_id, c]));
  let chosen = String(selected ?? "").trim();
  if (!byId.has(chosen) || !byId.get(chosen)!.eligible) {
    chosen = out.find((c) => c.eligible)?.hook_id ?? "";
  }
  return { hooks: out, selected: chosen };
}

function normalizeScript(obj: any, factSheet?: any) {
  const known = factSheet ? claimIdsOf(factSheet) : new Set<string>();
  const scenesIn = Array.isArray(obj?.scenes) ? obj.scenes : [];
  const scenes: any[] = [];
  scenesIn.forEach((s: any, i: number) => {
    if (typeof s !== "object" || s === null || Array.isArray(s)) return;
    let sf = s.source_facts ?? [];
    if (typeof sf === "string") sf = [sf];
    let cid = strList(s.claim_ids).map((x) => x.trim()).filter(Boolean);
    if (known.size) cid = cid.filter((x) => known.has(x));  // 원장에 없는 참조 드롭
    const sceneNo = s.scene ? toInt(s.scene, i + 1) : i + 1;
    // 하위호환: 옛 단일 visual_prompt 만 온 경우 video_prompt 로 승계.
    const videoPrompt = String(s.video_prompt ?? s.visual_prompt ?? "");
    scenes.push({
      scene: sceneNo || i + 1,
      title: String(s.title ?? ""),
      narration_ko: String(s.narration_ko ?? ""),
      narration_en: String(s.narration_en ?? ""),
      duration_sec: toInt(s.duration_sec, 0),
      image_prompt: String(s.image_prompt ?? ""),
      image_prompt_ko: String(s.image_prompt_ko ?? ""),
      video_prompt: videoPrompt,
      video_prompt_ko: String(s.video_prompt_ko ?? ""),
      source_facts: (Array.isArray(sf) ? sf : []).map((x: any) => String(x)),
      claim_ids: cid,
      evidence_role: sanEnum(s.evidence_role, EVIDENCE_ROLES, DEFAULT_EVIDENCE_ROLE),
      evidence_delivery: sanEnum(s.evidence_delivery, EVIDENCE_DELIVERY, DEFAULT_EVIDENCE_DELIVERY),
    });
  });

  // 계획·훅은 video_flow 안에 얹는다(drafts 에 빈 컬럼이 없어 마이그레이션을 늘리지 않는다).
  const flow = normalizeFlow(obj?.video_flow) as Record<string, any>;
  const mainClaims = (Array.isArray(factSheet?.claims) ? factSheet.claims : [])
    .filter((c: any) => c?.claim_kind === "main_result").length;
  const plan = normalizeContentPlan(obj?.content_plan, known, Math.max(1, mainClaims));
  const spoken = scenes
    .filter((s) => s.evidence_delivery !== "visual")
    .reduce((acc, s) => acc + countSpokenNumbers(s.narration_ko), 0);
  plan.spoken_number_count = spoken;
  if (spoken > MAX_SPOKEN_NUMBERS) plan.mode_warnings = [...plan.mode_warnings, "too_many_spoken_numbers"];

  const { hooks, selected } = normalizeHookCandidates(
    obj?.hook_candidates, obj?.selected_hook_id, known, factSheet,
  );
  flow.content_plan = plan;
  flow.hook_candidates = hooks;
  flow.selected_hook_id = selected;

  return {
    upload_title_ko: String(obj?.upload_title_ko ?? ""),
    upload_title_en: String(obj?.upload_title_en ?? ""),
    script_md: String(obj?.script_md ?? ""),
    video_flow: flow,
    scenes,
  };
}

// ─────────────────────────────────────────────────────────────
// 대본 한국어 다듬기 (engine/script_polish.py 이식)
//
// ★★ 사실은 **코드가** 지킨다. "사실을 바꾸지 마라"는 프롬프트 문장만으로는 안 막힌다는
//   것이 이 저장소의 반복된 실측이다 — 숫자·단서·길이가 어긋난 교정은 버리고 원문을 둔다.
// ─────────────────────────────────────────────────────────────
const POLISH_NUMBER =
  // 긴 단위를 앞에 둔다(개월 > 개, ml > m) — 교대는 먼저 맞는 것을 고른다. = engine/script_polish._NUMBER
  /\d+(?:[.,]\d+)?\s*(?:%|퍼센트|배|년|개월|주|일|시간|분|초|명|마리|건|개|회|kg|km|mg|ml|mm|cm|g|m|L)?/g;
// 지켜야 할 **뜻의 갈래**. 낱말이 아니라 **부류**로 본다(= engine/script_polish._MEANING_CLASSES).
// ★ 낱말을 그대로 대조하면 **정상 교정이 막힌다**(2026-09-10 실측):
//   "평균 30% 늘었습니다" → "평균 30% 증가했습니다" 가 '늘' 이 사라졌다고 거부됐다.
const POLISH_MEANING_CLASSES: Record<string, string[]> = {
  up: ["증가", "늘", "상승", "높", "향상", "개선"],
  down: ["감소", "줄", "하락", "낮", "악화"],
  hedge: ["평균", "일부", "약", "가량", "정도", "경향", "특정", "대체로"],
  // ★ `보이다` 는 완곡 어미일 때만 단서다 — 어간만 보면 "보여집니다"→"보입니다" 라는
  //   정상 교정이 막히고, `보여` 를 통째로 넣으면 "보여주고 있습니다"(= shows)까지 잡힌다.
  uncertain: ["가능성", "추정", "보입", "보인", "보여집", "보여진", "듯", "예상", "시사"],
  assoc: ["연관", "상관", "관련"],
  negation: ["않", "못", "없", "아니"],
};

function polishNumbers(text: string): string[] {
  const out: string[] = [];
  for (const m of String(text ?? "").matchAll(POLISH_NUMBER)) {
    const tok = m[0].replace(/\s+/g, "");
    if (/\d/.test(tok)) out.push(tok);
  }
  return out.sort();
}

/** 이 문장이 담고 있는 **뜻의 갈래**. 다듬기 전후로 같아야 한다. */
function meaningClasses(text: string): Set<string> {
  const t = String(text ?? "");
  const out = new Set<string>();
  for (const [name, terms] of Object.entries(POLISH_MEANING_CLASSES)) {
    if (terms.some((term) => t.includes(term))) out.add(name);
  }
  return out;
}

const POLISH_HANGUL_WORD = /[가-힣]+/g;

/** 어절의 앞 두 글자. 조사·어미가 붙어도 줄기는 남는다(약물의→약물). */
function polishStems(text: string): Set<string> {
  const out = new Set<string>();
  for (const m of String(text ?? "").matchAll(POLISH_HANGUL_WORD)) {
    if (m[0].length >= 2) out.add(m[0].slice(0, 2));
  }
  return out;
}

/** 다듬은 문장이 원문의 낱말 줄기를 얼마나 지켰는가(0~1). */
function polishStemRetention(before: string, after: string): number {
  const b = polishStems(before);
  if (!b.size) return 1;
  const a = polishStems(after);
  let kept = 0;
  for (const w of b) if (a.has(w)) kept += 1;
  return kept / b.size;
}

/** 다듬은 문장을 **버려야 하는 이유** — 없으면 빈 문자열. */
function polishRejectionReason(before: string, after: string): string {
  const a = String(before ?? "").trim();
  const b = String(after ?? "").trim();
  if (!b) return "polish_empty";
  const na = polishNumbers(a), nb = polishNumbers(b);
  if (na.length !== nb.length || na.some((x, i) => x !== nb[i])) {
    return "polish_numbers_changed";
  }
  const ca = meaningClasses(a), cb = meaningClasses(b);
  const drift = [
    ...Array.from(ca).filter((x) => !cb.has(x)),
    ...Array.from(cb).filter((x) => !ca.has(x)),
  ].sort();
  if (drift.length) return "polish_meaning_changed:" + drift.slice(0, 3).join(",");
  if (a && polishStemRetention(a, b) < SCRIPT_POLISH_MIN_STEM_RETENTION) {
    return "polish_content_dropped";
  }
  const gap = b.length - a.length;
  const limit = gap > 0 ? SCRIPT_POLISH_LEN_TOLERANCE : SCRIPT_POLISH_SHRINK_TOLERANCE;
  if (a && Math.abs(gap) > SCRIPT_POLISH_LEN_FLOOR_CHARS && Math.abs(gap) / a.length > limit) {
    return "polish_length_drift";
  }
  return "";
}

function awkwardScenes(check: any): number[] {
  const out = new Set<number>();
  for (const s of check?.scenes ?? []) {
    if (s && s.korean_natural === false) {
      const no = toInt(s.scene, 0);
      if (no) out.add(no);
    }
  }
  return Array.from(out).sort((x, y) => x - y);
}

/** 다듬은 결과를 **검사하고** 씬에 적용한다(제자리 수정) → 보고. */
function applyPolish(scenes: any[], polished: any) {
  const byNo = new Map<number, any>();
  for (const s of scenes) byNo.set(toInt(s?.scene, 0), s);
  const applied: number[] = [];
  const rejected: { scene: number; reason: string }[] = [];
  const unchanged: number[] = [];
  for (const row of polished?.scenes ?? []) {
    if (!row) continue;
    const no = toInt(row.scene, 0);
    const target = byNo.get(no);
    if (!target) continue;
    const before = String(target.narration_ko ?? "");
    const after = String(row.narration_ko ?? "").trim();
    if (after === before.trim()) { unchanged.push(no); continue; }
    const reason = polishRejectionReason(before, after);
    if (reason) { rejected.push({ scene: no, reason }); continue; }
    target.narration_ko = after;
    applied.push(no);
  }
  return {
    applied: applied.sort((a, b) => a - b),
    rejected,
    unchanged: unchanged.sort((a, b) => a - b),
  };
}

/** 읽기용 대본에도 같은 교정을 반영한다. **그대로 있는 문장만** 바꾼다. */
function rewriteScriptMd(scriptMd: string, pairs: [string, string][]): [string, number] {
  let out = String(scriptMd ?? "");
  let hit = 0;
  for (const [before, after] of pairs) {
    const b = String(before ?? "").trim();
    if (b && out.includes(b)) {
      out = out.split(b).join(String(after ?? "").trim());
      hit += 1;
    }
  }
  return [out, hit];
}

// engine/selfcheck.py:normalize_selfcheck 이식. coverage·approval_blocked 는 **코드가** 계산한다.
function normalizeSelfcheck(obj: any, factSheet?: any, contentPlan?: any, totalSec?: number) {
  const known = factSheet ? claimIdsOf(factSheet) : new Set<string>();
  const scenesIn = Array.isArray(obj?.scenes) ? obj.scenes : [];
  const scenes: any[] = [];
  let anyUnsupported = false;
  const block: string[] = [];
  const warnings: string[] = [];

  for (const s of scenesIn) {
    if (typeof s !== "object" || s === null || Array.isArray(s)) continue;
    let unsupported = s.unsupported ?? [];
    if (typeof unsupported === "string") unsupported = unsupported ? [unsupported] : [];
    unsupported = (Array.isArray(unsupported) ? unsupported : []).map((x: any) => String(x));
    // 기본값: unsupported 가 없으면 grounded=true. LLM 자기보고는 신뢰하지 않고 아래서 재계산.
    let grounded = s.grounded === undefined ? unsupported.length === 0 : Boolean(s.grounded);
    if (unsupported.length > 0) {
      grounded = false;
      anyUnsupported = true;
    }
    let matched = s.matched_facts ?? [];
    if (typeof matched === "string") matched = [matched];
    const rawIds = strList(s.matched_claim_ids).map((x) => x.trim()).filter(Boolean);
    const dangling = known.size ? rawIds.filter((c) => !known.has(c)) : [];
    const claimIds = known.size ? rawIds.filter((c) => known.has(c)) : rawIds;
    const sceneNo = toInt(s.scene, 0);
    const row = {
      scene: sceneNo,
      grounded,
      unsupported,
      matched_facts: (Array.isArray(matched) ? matched : []).map((x: any) => String(x)),
      matched_claim_ids: claimIds,
      scope_match: s.scope_match === undefined ? true : Boolean(s.scope_match),
      causal_calibration: sanEnum(s.causal_calibration, SELFCHECK_TRISTATE, "not_applicable"),
      numeric_match: sanEnum(s.numeric_match, SELFCHECK_TRISTATE, "not_applicable"),
      qualifier_preserved: s.qualifier_preserved === undefined ? true : Boolean(s.qualifier_preserved),
      editorial_inference: Boolean(s.editorial_inference ?? false),
      // ★ 한국어 문장 축(2026-09-10). **사실 축과 섞지 않는다** — 승인에도 커버리지에도
      //   닿지 않고, 오직 경고와 다듬기 되먹임에만 쓰인다.
      korean_natural: s.korean_natural === undefined ? true : Boolean(s.korean_natural),
      awkward_spans: strList(s.awkward_spans),
      fluency_issues: strList(s.fluency_issues).filter((k) =>
        SELFCHECK_FLUENCY_KINDS.includes(k)
      ),
      issues: strList(s.issues),
    };
    // ★ 원장이 없으면(레거시) 이 축은 아예 돌지 않는다 — 과거 초안이 새 규칙에 막히지 않는다.
    // ★ 차단은 코드가 데이터로 확정하는 것만. 나머지는 **LLM 판단**이라 경고다(운영자 결정,
    //   2026-07-27 — 리포트 라인 컴플라이언스 하드차단 제거 커밋 6a28761 과 같은 이유).
    if (known.size) {
      for (const cid of dangling) block.push(`claim_id_invalid:${cid}#${sceneNo}`);
      if (!row.scope_match) warnings.push(`scope_expanded#${sceneNo}`);
      if (!row.qualifier_preserved) warnings.push(`qualifier_dropped#${sceneNo}`);
      if (row.causal_calibration === "fail") warnings.push(`causal_overreach#${sceneNo}`);
      if (row.numeric_match === "fail") warnings.push(`numeric_mismatch#${sceneNo}`);
      if (row.editorial_inference) warnings.push(`editorial_inference#${sceneNo}`);
    }
    // ★ 문장 축은 `known`(주장 원장) 바깥에 둔다 — 원장이 없는 옛 초안도 한국어는 똑같이
    //   어색할 수 있고, 이 축은 승인·커버리지 어디에도 닿지 않는다.
    if (!row.korean_natural) warnings.push(`korean_awkward#${sceneNo}`);
    scenes.push(row);
  }

  const primary = String(contentPlan?.primary_claim_id ?? "");
  const required = [primary, ...(contentPlan?.supporting_claim_ids ?? []).map((x: any) => String(x))]
    .filter(Boolean);
  const covered = new Set<string>();
  for (const s of scenes) for (const c of s.matched_claim_ids) covered.add(c);
  const uniqueRequired = Array.from(new Set(required));
  const coverage = {
    required_claim_ids: uniqueRequired,
    spoken_claim_ids: Array.from(covered),
    visual_claim_ids: [] as string[],
    missing_claim_ids: uniqueRequired.filter((c) => !covered.has(c)),
    primary_claim_covered: Boolean(primary) && covered.has(primary),
  };

  if (contentPlan) {
    if (uniqueRequired.length && coverage.missing_claim_ids.length) block.push("missing_required_claims");
    if (uniqueRequired.length && !coverage.primary_claim_covered) block.push("primary_claim_not_covered");
    if (contentPlan.selected_mode === "series_split") block.push("series_split_required");
    if (typeof totalSec === "number" && totalSec > CONTENT_MODE_HARD_MAX_SEC) block.push("over_max_duration");
    if (typeof totalSec === "number" && totalSec < CONTENT_MODE_SOFT_MIN_SEC) {
      warnings.push("below_soft_min_duration");
    }
    for (const w of (contentPlan.mode_warnings ?? [])) warnings.push(String(w));
  } else if (known.size) {
    warnings.push("no_content_plan");
  }
  if (!known.size) warnings.push("legacy_no_claim_ledger");

  return {
    scenes,
    all_grounded: !anyUnsupported,
    coverage,
    block_reasons: Array.from(new Set(block)).sort(),
    warnings: Array.from(new Set(warnings)).sort(),
    approval_blocked: block.length > 0,
  };
}

// ─────────────────────────────────────────────────────────────
// 3단계 파이프라인 (engine/draft.py:generate_draft 이식)
// ─────────────────────────────────────────────────────────────
function factsheetUser(paper: any): string {
  return `제목: ${paper.title ?? ""}\n게재처: ${paper.venue ?? "(미상)"}\n초록: ${paper.abstract ?? ""}`;
}

// 출처 메타(검증 가능 — LLM 아님). 나레이션 구체화·발행 캡션의 근거. authors=[{name,institution}].
function buildSource(paper: any) {
  const authors = Array.isArray(paper.authors) ? paper.authors : [];
  const names = authors.map((a: any) => a?.name).filter(Boolean).slice(0, 3);
  const institutions = [
    ...new Set(authors.map((a: any) => a?.institution).filter(Boolean)),
  ].slice(0, 3);
  const year = paper.published_date ? String(paper.published_date).slice(0, 4) : "";
  return {
    title: paper.title ?? "",
    venue: paper.venue ?? "",
    year,
    authors: names,
    institutions,
    url: paper.url ?? "",
  };
}

// = engine/config.VIDEO_VERSIONS 중 발주 가능한 것(web/lib/versions.ts VERSION_KEYS). 초안 뒤
// 이어서 만들 지시서 버전은 이 목록 안에서만 받는다 — 미허용 값이 큐에 들어가면 워커의
// VERSION_GUIDANCE 가 기본 버전으로 조용히 갈아치운다(2026-08-20 사고).
const CHAINABLE_VERSIONS = new Set(["comic", "photo"]);

function chainableVersions(raw: unknown): string[] {
  const list = Array.isArray(raw) ? raw : [];
  return [...new Set(list.map(String).filter((v) => CHAINABLE_VERSIONS.has(v)))];
}

async function generate(
  supa: any,
  paperId: string,
  instruction = "",
  versionTypes: string[] = [],
): Promise<void> {
  const now = () => new Date().toISOString();
  // 큐 행을 processing 으로(중복 dedupe 로 활성 요청은 1건).
  await supa
    .from("draft_requests")
    .update({ status: "processing", updated_at: now() })
    .eq("paper_id", paperId)
    .in("status", ["queued", "processing"]);

  try {
    const { data: paper } = await supa
      .from("papers")
      .select("id, title, abstract, venue, authors, url, published_date")
      .eq("id", paperId)
      .maybeSingle();
    if (!paper) throw new Error(`paper 없음: ${paperId}`);

    const factSheet = normalizeFactsheet(
      await callJSON(
        "factsheet", MODEL_FACTSHEET, FACTSHEET_SYSTEM, factsheetUser(paper), MAX_TOKENS_FACTSHEET,
      ),
    );
    // ★ 출처 블록(검증 가능한 메타데이터 — LLM 아님)을 Fact Sheet에 부착.
    //   대본은 "Fact Sheet만" 입력이므로, 기관/저자를 구체적으로 쓰려면 여기에 담겨야 한다(환각 방지 유지).
    factSheet.source = buildSource(paper);
    const script = normalizeScript(
      await callJSON(
        "script",
        MODEL_SCRIPT,
        SCRIPT_SYSTEM,
        "Fact Sheet:\n" + JSON.stringify(factSheet, null, 2) +
          (instruction
            ? "\n\n★사용자 수정 요청(반드시 반영하라. 단 Fact Sheet 사실 범위 내에서만 — 없는 사실을 지어내지 말고" +
              " 표현·구성·난이도만 조정):\n" + instruction
            : ""),
        // content_plan·hook_candidates·씬별 근거 필드로 출력이 약 900토큰 늘었다(6144 는 잘림 위험).
        MAX_TOKENS_SCRIPT,
      ),
      factSheet,
    );
    // 자기검증은 '나레이션'만 대상(이미지/영상 프롬프트는 사실주장이 아니라 시각화 지시 → 오탐 방지).
    // claim_ids·evidence_role 은 산문이 아니라 메타데이터라 오탐을 만들지 않고, 없으면 검증관이
    // "이 씬이 어느 주장을 지불하는지"를 대조할 수 없다.
    const narrScenes = script.scenes.map((s: any) => ({
      scene: s.scene,
      narration_ko: s.narration_ko,
      claim_ids: s.claim_ids ?? [],
      evidence_role: s.evidence_role ?? "",
    }));
    const contentPlan = (script.video_flow as any)?.content_plan ?? null;
    const totalSec = script.scenes.reduce((acc: number, s: any) => acc + (s.duration_sec || 0), 0);
    const check = normalizeSelfcheck(
      await callJSON(
        "selfcheck",
        MODEL_SELFCHECK,
        SELFCHECK_SYSTEM,
        "Fact Sheet:\n" + JSON.stringify(factSheet, null, 2) +
          "\n\n대본 씬들:\n" + JSON.stringify(narrScenes, null, 2),
        // 씬마다 축 5개가 늘어 3072 는 씬 8편에서 잘릴 수 있다.
        MAX_TOKENS_SELFCHECK,
      ),
      factSheet,
      contentPlan,
      totalSec,
    );

    // ★ 한국어가 어색하다고 찍힌 씬만 **한 번 다시 쓰게** 한다(운영자 지시 2026-09-10).
    //   어색한 씬이 없으면 LLM 을 부르지 않는다(비용 0).
    //   ★★ 씬만 고치면 script_md 와 어긋난다 — ⑤ 지시서는 **둘 다** 입력으로 받는다.
    const polishTargets = awkwardScenes(check);
    let polishReport: any = { ran: false, reason: SCRIPT_POLISH_ENABLED
      ? "no_awkward_scene"
      : "disabled" };
    if (SCRIPT_POLISH_ENABLED && polishTargets.length) {
      const byNo = new Map<number, any>();
      for (const sc of script.scenes) byNo.set(toInt(sc?.scene, 0), sc);
      const beforeText = new Map<number, string>();
      for (const [no, sc] of byNo) beforeText.set(no, String(sc?.narration_ko ?? ""));
      const payload = polishTargets.map((no) => {
        const judged = (check.scenes ?? []).find((x: any) => toInt(x?.scene, 0) === no) ?? {};
        return {
          scene: no,
          narration_ko: String(byNo.get(no)?.narration_ko ?? ""),
          어색한_구절: judged.awkward_spans ?? [],
          어색함의_종류: judged.fluency_issues ?? [],
        };
      });
      polishReport = applyPolish(
        script.scenes,
        await callJSON(
          "script_polish",
          MODEL_SCRIPT,
          POLISH_SYSTEM,
          "아래 씬들의 한국어를 다듬어라. 사실·숫자·범위·단서는 그대로 둔다.\n" +
            JSON.stringify(payload, null, 2),
          MAX_TOKENS_POLISH,
        ),
      );
      polishReport.ran = true;
      polishReport.targets = polishTargets;
      if (polishReport.applied.length) {
        const pairs: [string, string][] = polishReport.applied.map((no: number) => [
          beforeText.get(no) ?? "",
          String(byNo.get(no)?.narration_ko ?? ""),
        ]);
        const [md, synced] = rewriteScriptMd(script.script_md, pairs);
        script.script_md = md;
        polishReport.script_md_synced = synced;
      }
      console.log(
        `대본 다듬기: 적용 ${JSON.stringify(polishReport.applied)} · 버림 ${
          JSON.stringify((polishReport.rejected ?? []).map((r: any) => r.reason))
        }`,
      );
    }
    check.korean_polish = polishReport;

    await supa.from("drafts").upsert(
      {
        paper_id: paperId,
        fact_sheet: factSheet,
        upload_title_ko: script.upload_title_ko,
        upload_title_en: script.upload_title_en,
        script_md: script.script_md,
        video_flow: script.video_flow,
        video_prompts: script.scenes,
        self_check: check,
      },
      { onConflict: "paper_id" },
    );

    await supa
      .from("draft_requests")
      .update({ status: "done", error: null, updated_at: now() })
      .eq("paper_id", paperId)
      .in("status", ["queued", "processing"]);

    // ★ 초안 뒤 지시서를 잇는다(0046, 설계안 v2 §3). 엣지는 **큐에 넣기만** 한다 — 지시서
    //   생성은 워커 독점이다(2026-08-29 리뷰 §8: 엣지가 백그라운드 생성하다 런타임이 끊겨
    //   요청이 영구 processing 으로 남았다). 워커(draft.yml/queues 크론/로컬)가 집어간다.
    //   같은 논문·버전이 이미 대기 중이면 또 넣지 않는다(/api/directive-generate 와 같은 dedupe).
    for (const v of versionTypes) {
      const { data: dup } = await supa
        .from("directive_requests")
        .select("id")
        .eq("paper_id", paperId)
        .eq("version_type", v)
        .in("status", ["queued", "processing"])
        .limit(1)
        .maybeSingle();
      if (dup) continue;
      const { error: qErr } = await supa
        .from("directive_requests")
        .insert({ paper_id: paperId, version_type: v, status: "queued" });
      if (qErr) console.warn(`directive_requests 적재 실패 paper=${paperId} v=${v}: ${qErr.message}`);
    }

    const flagged = check.scenes.reduce(
      (acc: number, s: any) => acc + (s.unsupported?.length ?? 0),
      0,
    );
    console.log(`draft 생성: paper=${paperId} scenes=${script.scenes.length} 빨간깃발=${flagged}`);
  } catch (err) {
    await supa
      .from("draft_requests")
      .update({ status: "error", error: String(err).slice(0, 500), updated_at: now() })
      .eq("paper_id", paperId)
      .in("status", ["queued", "processing"]);
    throw err;
  }
}

// ─────────────────────────────────────────────────────────────
// HTTP 핸들러 — paper_id 를 받아 백그라운드 생성 후 즉시 202.
// verify_jwt(기본 on)로 미인증 호출은 게이트웨이에서 차단된다.
// ─────────────────────────────────────────────────────────────
function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// ★ 공개 저장소 대비(2026-09-15): **서버 전용 공유 비밀**이 있어야 일한다.
//   verify_jwt 는 서명만 본다 — 공개 anon 키도 유효한 JWT 라 누구나 이 함수를 불러 유료 LLM 을
//   돌릴 수 있었다. 역할 클레임(service_role) 검사는 못 쓴다: 이 프로젝트의 서버 키는 JWT 가 아닌
//   신형 sb_secret 형식이다. 그래서 대시보드 서버 라우트만 아는 EDGE_INVOKE_SECRET 을 헤더로 받는다.
//   미설정이면 **막는다**(fail-closed). 설정: supabase secrets set EDGE_INVOKE_SECRET=… + Vercel 같은 값.
const MIN_SECRET_LEN = 32;

function callerCheck(req: Request): { ok: boolean; reason: string } {
  const expected = Deno.env.get("EDGE_INVOKE_SECRET") ?? "";
  const got = req.headers.get("x-edge-secret") ?? "";
  // ★ 사유를 구분해 돌려준다(값은 절대 싣지 않는다). 2026-09-16 실측: 대시보드 호출이 403 인데
  //   "시크릿 미설정"인지 "짧아서 거부"인지 "값 불일치"인지 알 수 없어 원인 규명이 막혔다.
  if (!expected) return { ok: false, reason: "secret_not_configured_on_function" };
  if (expected.length < MIN_SECRET_LEN) return { ok: false, reason: "function_secret_too_short" };
  if (!got) return { ok: false, reason: "caller_sent_no_secret" };
  if (got.length !== expected.length) return { ok: false, reason: "mismatch_length" };
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ got.charCodeAt(i);
  return diff === 0 ? { ok: true, reason: "ok" } : { ok: false, reason: "mismatch_value" };
}

function isTrustedCaller(req: Request): boolean {
  return callerCheck(req).ok;
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);
  const caller = callerCheck(req);
  if (!caller.ok) return json({ error: "forbidden", reason: caller.reason }, 403);
  // LLM 키는 Gemini 또는 Anthropic 중 하나 이상 있어야 한다(선택 모델에 맞춰 라우팅).
  if ((!GEMINI_API_KEY && !ANTHROPIC_API_KEY) || !SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server misconfigured (secrets 누락)" }, 500);
  }

  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const paperId = body?.paper_id;
  if (!paperId) return json({ error: "paper_id required" }, 400);
  // 선택: 사용자 수정 요청(예: "P=NP 같은 어려운 용어를 풀어써줘"). 대본 생성 프롬프트에 주입.
  const instruction = String(body?.instruction ?? "").trim().slice(0, 800);
  // 초안 뒤 이어서 만들 지시서 버전(0046). 없으면 옛 동작(지시서 자동 생성 없음).
  const versionTypes = chainableVersions(body?.version_types);

  const supa = createClient(SUPABASE_URL, SERVICE_KEY);
  // 생성(30~90초)은 백그라운드로, 응답은 즉시 202. UI 는 /api/draft-status 로 폴링.
  EdgeRuntime.waitUntil(
    generate(supa, paperId, instruction, versionTypes).catch((e) =>
      console.error("draft 실패", paperId, e)
    ),
  );
  return json({ ok: true, status: "processing", paper_id: paperId }, 202);
});
