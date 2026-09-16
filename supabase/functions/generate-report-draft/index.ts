// Supabase Edge Function: 리포트 초안 클라우드 자동생성 + 컴플라이언스 게이트 (PF1).
//
// 대시보드 "초안 생성 요청" 버튼 → /api/report-generate-draft(Next.js)가 report_draft_requests 큐에
// 적재하고 이 함수를 호출한다. 함수는 리포트 1건에 대해 Fact Sheet → 대본 → 자기검증 →
// ★컴플라이언스 게이트(3층)를 돌려 report_drafts 행을 쓰고 상태를 갱신한다.
// recheck 모드({recheck:true})면 편집된 대본으로 컴플라이언스만 재실행한다([재검사] 버튼).
//
// ★ 이 파일은 Python engine(engine/report_factsheet · report_scriptgen · report_selfcheck ·
//   report_compliance · report_draft · llm)의 파이프라인을 그대로 이식한 것이다.
//   프롬프트 문자열·정규화 규칙·금지패턴·모델 ID는 Python 원본과 반드시 동기화한다(이중 관리 지점).
//   ★★ 컴플라이언스는 가장 민감한 지점 — engine/report_compliance.py 와 규칙을 어긋나게 두지 말 것.
//
// 배포:  supabase functions deploy generate-report-draft
//
// deno-lint-ignore-file no-explicit-any
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const EdgeRuntime: { waitUntil(p: Promise<unknown>): void };

const ANTHROPIC_API_KEY = Deno.env.get("ANTHROPIC_API_KEY") ?? "";
const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const MODEL_FACTSHEET = Deno.env.get("MODEL_REPORT_FACTSHEET") ?? "gemini-2.5-flash";
const MODEL_SCRIPT = Deno.env.get("MODEL_REPORT_SCRIPT") ?? "gemini-2.5-pro";
const MODEL_SELFCHECK = Deno.env.get("MODEL_REPORT_SELFCHECK") ?? "gemini-2.5-flash";
const MODEL_COMPLIANCE = Deno.env.get("MODEL_REPORT_COMPLIANCE") ?? "gemini-2.5-flash";
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models";

const MAX_RETRIES = 4;
const BACKOFF_BASE_MS = 2000;
const JSON_RETRY = 1;
// engine/config.py:LLM_SCRIPT_MAX_TOKENS 트윈. 6144 에서 대본이 잘려 초안이 3건 연속
// 실패했다(실측 2026-08-03) — 워커만 고치면 대시보드 경로가 같은 사고를 반복한다.
const SCRIPT_MAX_TOKENS = Number(Deno.env.get("LLM_SCRIPT_MAX_TOKENS") ?? "16384");
// engine/config.py:LLM_FACTSHEET_MAX_TOKENS 트윈. 엣지는 2048 이었다 — 워커(8192)보다도 작아
// 전문 주입 뒤에는 확실히 잘린다.
const FACTSHEET_MAX_TOKENS = Number(Deno.env.get("LLM_FACTSHEET_MAX_TOKENS") ?? "16384");
// engine/config.py:FACTSHEET_MAX_NUMBER_FACTS 트윈. 상한 없는 배열이라 모델이 반복 생성해
// 16384 토큰까지 채우고 잘렸다(실측) — 개수를 묶는 것이 상한을 올리는 것보다 확실하다.
const MAX_NUMBER_FACTS = Number(Deno.env.get("FACTSHEET_MAX_NUMBER_FACTS") ?? "20");
const CALL_TIMEOUT_MS = 60_000;

// engine/config.py 트윈 — EVIDENCE_QUOTE_MAX_CHARS · EVIDENCE_MAX_SOURCE_REFS ·
// SELFCHECK_EXEMPT_MAX_RATIO. 값이 어긋나면 같은 대본이 경로에 따라 다르게 판정된다.
const QUOTE_MAX_CHARS = 300;
const SOURCE_REFS_MAX = 3;
const QUOTE_MIN_CHARS = 8;   // EVIDENCE_QUOTE_MIN_CHARS
const EXEMPT_MAX_RATIO = 0.4;

const DISCLAIMER_MARKERS = ["투자 권유가 아", "판단과 책임", "정보 제공 목적"];
// engine/config.py COMPLIANCE_BLOCK_PATTERNS/WARN_PATTERNS 와 동기화(이중관리).
const BLOCK_PATTERNS: Record<string, string[]> = {
  투자권유: ["지금\\s*사(라|세요|자)", "매수\\s*(하세요|추천|의견)", "담(아라|으세요|자)",
    "비중\\s*확대", "풀\\s*매수", "가즈아", "줍줍", "불타기", "영끌"],
  미실현수익률: ["상승\\s*여력", "[+\\-]?\\d+\\s*%\\s*(상승|수익|먹|오)", "목표\\s*수익률",
    "\\d+\\s*배\\s*(간다|갑니다|먹)", "떡상"],
  단정예측: ["무조건", "반드시\\s*오른", "확실히\\s*(오|상승)", "100\\s*%\\s*(오|수익|상승)",
    "보장", "찐", "틀림없"],
};
const WARN_PATTERNS: Record<string, string[]> = {
  과열소재: ["테마주", "급등주", "품절주", "세력"],
};

// ─────────────────────────────────────────────────────────────
// 프롬프트 (engine 의 시스템 프롬프트 verbatim 복사)
// ─────────────────────────────────────────────────────────────
// ★ 엔진(engine/report_factsheet.py:FACTSHEET_SYSTEM)과 짝을 맞춘다. 전문 주입 문구가 한쪽에만
//   있으면 대시보드 초안과 워커 초안이 서로 다른 근거로 만들어진다(tests/test_prompt_sync.py).
const FACTSHEET_SYSTEM = `너는 사실 검증관이다. 아래 증권사 리포트에서 "검증 가능한 사실"만 추출한다.
추측·전망 창작·원문에 없는 내용 금지. 항목별로 근거가 없으면 빈 배열로 둔다.
★ 원문 전문이 <<FULL_SOURCE>> … <</FULL_SOURCE>> 구간으로 주어지면 **그 전문을 근거로 삼아라.**
  요약만 보고 답하지 마라. 전문에 표·재무제표가 있으면 그 수치를 우선한다.
JSON only. 설명 문장·마크다운·코드펜스 금지.
★ 아래 키 순서를 **그대로 지켜 출력하라.** number_facts 가 맨 뒤인 것이 중요하다 —
  길어져서 잘리더라도 opinion·basis·risks 는 이미 나온 뒤여야 한다(리스크가 빠진 영상은 사고다).
{
  "company": "<종목/테마>",
  "what": ["<리포트의 핵심 주장/근거 사실들>"],
  "opinion": "<투자의견 원문 그대로 (예: 'OO증권 매수, 목표가 9만원'). 없으면 ''>",
  "basis": ["<증권사가 제시한 논리/촉매>"],
  "risks": ["<리포트가 언급한 리스크·전제·불확실성>"],
  "source": "<증권사명 + 애널리스트 + 발행일 (있는 것만)>",
  "number_facts": [
    { "fact_id": "<snake_case 식별자. 비우면 코드가 부여>",
      "value": <숫자만 (단위 제외). 수치 아니면 null>,
      "unit": "<단위 (예: 'x','%','원','억','조'). 없으면 ''>",
      "period": "<시점 (예: '2026F','1Q26','TTM'). 없으면 ''>",
      "metric": "<지표명 (예: 'PER','영업이익','목표주가'). 없으면 ''>",
      "comparator": { "basis": "<비교 기준 (컨센서스·전년 동기·직전 분기 등). 없으면 ''>",
                      "value": "<비교 대상 값. 없으면 ''>" },
      "source_refs": [ { "chunk_id": "", "quote": "<이 수치가 나온 **원문 문장 그대로**>" } ],
      "display": "<사람이 읽는 한 줄. 필수>" }
  ]
}
※ ★ number_facts 는 **최대 {MAX_FACTS}개**다. 리포트에 수치가 더 많아도 그 안에서 골라라 —
  25초 영상에 실을 수 있는 수치는 몇 개뿐이고, 고르는 일을 미루면 하류가 대신 못 한다.
  목표주가·투자의견·핵심 실적·밸류에이션처럼 **이 리포트의 주장을 지불하는 수치**를 우선한다.
  같은 수치를 표현만 바꿔 반복하지 마라(예: '영업이익 860억' 과 '860억원 영업이익').
※ ★ source_refs 의 quote 는 **원문에 있는 문장 그대로**여야 한다. 원문 전문이 주어지지 않았으면
  빈 배열로 둬라 — 요약을 인용문인 척 넣지 마라.
※ risks 는 **리포트가 실제로 말한 것만** 적는다. 언급이 없으면 빈 배열로 둬라.
  ★ 예전에는 여기서 일반적 리스크를 지어내 넣으라고 시켰다 — 그건 환각을 명령한 것이었다.`
  .replace("{MAX_FACTS}", String(MAX_NUMBER_FACTS));

const SCRIPT_SYSTEM = `너는 증권사 리포트를 대중용 숏폼 대본으로 각색하는 작가다.
JSON only. 설명·마크다운·코드펜스 금지.

[입력 두 가지 — 쓰임새가 다르다. 헷갈리면 이 대본은 실패한다]
■ <<EVIDENCE_PACKET>> … <</EVIDENCE_PACKET>> : 검증된 근거 묶음(Fact Sheet).
  **화면과 나레이션에 나가는 수치·주장은 여기 있는 것만 쓴다.** 이 묶음에 없는 수치를
  말하면 그 편은 폐기된다.
■ <<FULL_SOURCE>> … <</FULL_SOURCE>> : 리포트 원문 전문(있을 때만 주어진다).
  **맥락을 이해하라고 주는 것이다** — 그 숫자가 왜 나왔는지, 증권사의 논리가 어떤 순서로
  전개되는지, 어떤 표현을 썼는지. 요약만 보고 쓴 대본은 "48.6배입니다"에서 멈추지만,
  전문을 읽은 대본은 "왜 48.6배인지"를 한 문장으로 풀 수 있다. 그 차이를 만들라고 주는 것이다.
  ★ 단, 전문에서 **새 수치를 끌어오지 마라.** 전문에 있고 Fact Sheet 에 없는 수치는
    검증을 안 거친 것이다. 맥락·논리·어감은 전문에서 가져오되, 숫자와 사실 주장은
    Fact Sheet 에서만 가져온다. 이 경계가 이 대본의 생명선이다.
전문이 주어지지 않았으면 Fact Sheet 만으로 쓴다(그때는 해석을 얕게, 사실 위주로).

[대본 생성 규칙 — 절대 준수]
■ 금지 (하나라도 어기면 실패):
  - 매수/매도/보유 등 투자행동 권유 표현 ("사라","지금 담아라","비중 확대" 등)
  - 미실현 수익률·상승여력 광고 ("+35% 상승여력","목표 수익률","2배 간다")
  - 단정적 미래 예측 ("무조건 오른다","확실히","반드시")
  - 리포트를 '내 분석'인 것처럼 서술 (반드시 "OO증권에 따르면"으로 귀속)
  - Fact Sheet에 없는 수치·주장 창작
■ 필수:
  - 목표가·의견은 "사실 인용" 형태로만 ("OO증권은 목표가를 9만원으로 제시했다")
  - 출처(증권사·애널리스트) 최소 1회 명시
  - 리스크 한 줄 포함 — **Fact Sheet 의 risks 가 있을 때만**. ★ risks 가 빈 배열이면
    리스크 씬을 만들지 말고 그 자리를 다른 팩트 비트로 채워라. 없는 리스크를 지어내는 것이
    바로 이 규칙이 막으려는 환각이다.
  - script_md 엔딩에 면책 문구 포함: "정보 제공 목적이며 투자 권유가 아닙니다. 판단·책임은 본인에게."
  - ★ 면책은 script_md 엔딩 텍스트로만. scenes[] 에 면책 전용 씬 금지, 나레이션 낭독 금지
    (영상에서 하단 고정 자막으로 자동 렌더된다).

[대본 구조 — 숏폼 리텐션 문법] 총 20~30초, 씬 6~7개, 씬당 2~5초(빠른 컷 전환):
씬1 후크(2~3초): 스크롤을 멈추는 한 문장(질문/충격형). 인사·제목 낭독 금지.
씬2 맥락(3~4초): 누가·무엇을 — 회사+출처 귀속 ("OO증권에 따르면, XX가…").
씬3~5 팩트 비트(각 3~5초): 한 씬 = 한 팩트, 점점 구체적으로(기술/이벤트 →
  수치/실증 → 증권사 논리·목표가 인용). 수치는 화면 텍스트로도 크게(무음 시청 대비).
  데이터 풍부하면 비트 3개(총 7씬), 적으면 2개(총 6씬). 억지로 늘리지 마라.
씬(끝-1) 리스크 턴(3~4초): "다만—"으로 전환, risks[] 한 줄 짧고 명확하게.
  ★ risks 가 비어 있으면 이 씬을 **건너뛰고** 팩트 비트를 하나 더 둔다.
씬(끝) 페이오프(2~4초): 의미 한 줄로 마무리, 후크에 답해 루프 유도. CTA 반 문장.
마지막 씬까지 콘텐츠다 — source_facts 가 "source.disclaimer" 뿐인 씬 금지.

[각 씬 필수] source_facts 에 근거가 된 Fact Sheet 키를 적는다(예: "numbers[0]","basis[1]","opinion").
근거 없는 씬 금지.

[각 씬 필수] scene_role — 이 씬이 화면에서 하는 일. 훅·질문·마무리(CTA)·연결부(BRIDGE)는
사실 주장이 아니라 수사적 문장이므로 근거 대조에서 면제된다. **면제받으려고 아무 씬에나
HOOK/CTA 를 붙이지 마라** — 수치를 말하는 씬은 EVIDENCE 다.

[OUTPUT JSON SCHEMA]
{
  "upload_title_ko": "<대중이 클릭할 한국어 제목 (사실 왜곡·수익률 훅 금지)>",
  "upload_title_en": "<영어 제목>",
  "script_md": "<전체 대본 마크다운>",
  "video_flow": {
    "logline": "<한 줄 컨셉>",
    "total_duration_sec": <int>,
    "beats": [{"order": <int>, "label": "<구간>", "summary": "<요약>", "transition": "<전환>"}]
  },
  "story_plan": {
    "thesis": "<이 영상이 증명하려는 **한 문장**. 곁가지 금지>",
    "content_profile": "<company_update|earnings_review|industry_report|market_wrap|event_flash|paper_explainer>",
    "audience_question": "<시청자가 품는 질문 한 줄>",
    "claim_chain": [
      { "role": "<hook|reveal|proof|mechanism|valuation|risk|closing>",
        "claim": "<주장 한 줄>",
        "evidence_refs": ["<이 주장을 지불하는 Fact Sheet 의 fact_id>"] }
    ],
    "excluded_evidence": [ { "evidence_ref": "<쓰지 않기로 한 fact_id>", "reason": "<왜 뺐나>" } ]
  },
  "scenes": [
    {
      "scene": <int>,
      "scene_role": "<HOOK|QUESTION|CLAIM|EVIDENCE|MECHANISM|RISK|WATCHPOINT|CTA|BRIDGE>",
      "title": "<씬 제목>",
      "narration_ko": "<한국어 나레이션>", "narration_en": "<영어 나레이션>",
      "duration_sec": <int>,
      "image_prompt": "<영문 text-to-image 프롬프트>", "image_prompt_ko": "<한글 설명>",
      "video_prompt": "<영문 image-to-video 프롬프트>", "video_prompt_ko": "<한글 설명>",
      "source_facts": ["numbers[0]"]
    }
  ]
}`;

const SELFCHECK_SYSTEM = `너는 엄격한 사실 검증관이다. 입력: Fact Sheet(JSON) + 생성된 대본 씬들(JSON).
대본의 각 문장이 Fact Sheet의 항목으로 뒷받침되는지 판정한다.
Fact Sheet에 근거가 없는 문장은 grounded=false 로 표시하고 그 문장을 그대로 적는다.
보수적으로 판단하라: 근거가 모호하면 grounded=false.
JSON only. 설명·마크다운·코드펜스 금지.
{
  "scenes": [
    { "scene": <int>, "grounded": <bool>,
      "unsupported": ["<근거 없는 문장 원문>"],
      "matched_facts": ["<뒷받침하는 Fact Sheet 키>"] }
  ],
  "all_grounded": <bool>
}`;

const JUDGE_SYSTEM = `너는 자본시장법 컴플라이언스 심사관이다. 아래 숏폼 대본을 검사한다.
JSON only. 설명·마크다운·코드펜스 금지. 애매하면 위반(yes)으로 본다(보수적).
{
  "권유": "yes|no",
  "수익률광고": "yes|no",
  "단정": "yes|no",
  "출처": "ok|missing",
  "면책": "ok|missing",
  "근거": "<판정 근거 한두 문장>"
}`;

// ─────────────────────────────────────────────────────────────
// LLM 호출 (engine/llm.py 이식 — generate-draft 와 동일, verbatim)
// ─────────────────────────────────────────────────────────────
function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function extractJSON(text: string): any {
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

// engine/report_evidence.normalize_unit / normalize_period 의 TS 트윈.
// ★ 중복 판정에 쓴다 — '억' 과 '억원', '2026년' 과 '2026' 이 다른 키가 되면 표현만 바꾼
//   반복이 상한을 잡아먹고 정작 필요한 수치가 밀려난다. 파이썬 표와 어긋나면 같은 응답이
//   경로에 따라 다르게 정리된다.
const UNIT_ALIASES: Record<string, string> = {
  "%": "%", "퍼센트": "%", "percent": "%", "％": "%",
  "%p": "%p", "%P": "%p", "퍼센트포인트": "%p", "bp": "bp", "bps": "bp",
  "배": "x", "x": "x", "X": "x", "times": "x",
  "원": "원", "KRW": "원", "won": "원",
  "억": "억원", "억원": "억원", "조": "조원", "조원": "조원",
  "만": "만", "천": "천",
  "달러": "USD", "USD": "USD", "$": "USD", "불": "USD",
  "억달러": "억USD", "억 달러": "억USD",
  "개": "개", "명": "명", "톤": "톤", "대": "대",
};

function normalizeUnit(unit: any): string {
  const raw = String(unit ?? "").trim();
  if (!raw) return "";
  return UNIT_ALIASES[raw] ?? raw;
}

/** 중복 판정 **전용** 기간 정규화 (engine/report_factsheet._canon_period 트윈).
 *
 * ★ report_evidence.normalize_period 를 쓰면 안 된다 — 그쪽은 근거 대조용이라
 *   1H26·2H26 을 둘 다 "26" 으로 접는다. 중복 판정에 쓰면 상·하반기 실적이 같은 값일 때
 *   하나가 근거째 사라진다. 여기서는 "2026년"과 "2026" 같은 표기 별칭만 접는다. */
const PURE_YEAR_RE = /^(\d{2,4})\s*년$/;

function normalizePeriod(period: any): string {
  const trimmed = String(period ?? "").trim();
  const m = PURE_YEAR_RE.exec(trimmed);
  return m ? m[1] : trimmed.toLowerCase().replace(/\s/g, "");
}

/** 비교값 표기 정규화 (engine/report_factsheet._canon_comp_value 트윈).
 *
 * ★ "860억" 과 "860억원" 은 같은 비교다. 최상위 unit 은 정본으로 접으면서 comparator.value 만
 *   날문자열로 두면 표기만 바꾼 반복이 다른 키가 되어 20개 상한을 잡아먹는다. */
const NUM_PREFIX_RE = /^([+-]?[\d.]+)(.*)$/;

function canonCompValue(value: any): string {
  const raw = String(value ?? "").trim().toLowerCase().replace(/,/g, "").replace(/\s/g, "");
  const m = NUM_PREFIX_RE.exec(raw);
  if (!m) return raw;
  return m[1] + normalizeUnit(m[2]).toLowerCase();
}

/** engine/llm.py:OutputTruncatedError 트윈.
 *
 * ★ 일반 오류와 구분하는 이유: 파싱 실패는 재시도가 의미 있지만 절단은 같은 자리에서 똑같이
 *   잘려 재시도가 낭비다. callJSON 의 재시도 루프가 이것을 **다시 던진다**. */
class OutputTruncatedError extends Error {}

async function anthropicText(model: string, system: string, user: string, maxTokens: number): Promise<string> {
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
        body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: [{ role: "user", content: user }] }),
        signal: AbortSignal.timeout(CALL_TIMEOUT_MS),
      });
      if (resp.status === 429 || resp.status >= 500) throw new Error(`anthropic ${resp.status}`);
      if (!resp.ok) {
        const body = await resp.text();
        const err: any = new Error(`anthropic ${resp.status}: ${body.slice(0, 200)}`);
        err.fatal = true;
        throw err;
      }
      const data = await resp.json();
      // ★ 잘림을 여기서 잡는다. 안 잡으면 잘린 JSON 이 파서로 내려가 암호 같은 오류가 된다
      //   (워커에서 실측된 사고 — `Expecting ',' delimiter: line 693 …`).
      //   두 사유의 **처방이 정반대**라 문구를 갈라 둔다.
      if (data?.stop_reason === "max_tokens") {
        throw new OutputTruncatedError(
          `출력이 max_tokens(${maxTokens})에서 잘렸다 — **출력 상한을 올려야** 한다 (model=${model})`);
      }
      if (data?.stop_reason === "model_context_window_exceeded") {
        throw new OutputTruncatedError(
          `입력이 커서 컨텍스트 창을 넘었다 — **입력을 줄여야** 한다 ` +
          `(DRAFT_INCLUDE_FULLTEXT=false 등). 출력 상한을 올리는 것은 역효과다 (model=${model})`);
      }
      return (data.content ?? []).filter((b: any) => b?.type === "text").map((b: any) => b.text).join("");
    } catch (err: any) {
      // 절단은 재시도해도 같은 자리에서 잘린다 — 즉시 올린다.
      if (err instanceof OutputTruncatedError) throw err;
      lastErr = err;
      if (err?.fatal) break;
      if (attempt < MAX_RETRIES - 1) await sleep(BACKOFF_BASE_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

async function geminiText(model: string, system: string, user: string, maxTokens: number): Promise<string> {
  const ml = model.toLowerCase();
  const genConfig: any = { responseMimeType: "application/json", maxOutputTokens: maxTokens, temperature: 0.4 };
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
      // ★ 실효 상한(genConfig.maxOutputTokens)을 적는다 — 2.5-pro 는 위에서 32768 로 덮어쓰므로
      //   인자를 그대로 적으면 운영자가 그 아래로 올려도 아무 변화가 없다.
      if (data?.candidates?.[0]?.finishReason === "MAX_TOKENS") {
        throw new OutputTruncatedError(
          `출력이 maxOutputTokens(${genConfig.maxOutputTokens})에서 잘렸다 — 상한을 올려야 한다 (model=${model})`);
      }
      const parts = data?.candidates?.[0]?.content?.parts ?? [];
      return parts.map((p: any) => p?.text ?? "").join("");
    } catch (err: any) {
      // 절단은 재시도해도 같은 자리에서 잘린다 — 즉시 올린다.
      if (err instanceof OutputTruncatedError) throw err;
      lastErr = err;
      if (err?.fatal) break;
      if (attempt < MAX_RETRIES - 1) await sleep(BACKOFF_BASE_MS * 2 ** attempt);
    }
  }
  throw lastErr;
}

// Gemini 무료 쿼터 소진(429 지속) 시 Anthropic 키가 있으면 sonnet 으로 폴백.
// (채점·번역 등이 같은 Gemini 키를 쓰므로 일일 쿼터가 이 함수보다 먼저 마르는 날이 있다.)
const ANTHROPIC_FALLBACK_MODEL = "claude-sonnet-4-6";

async function llmText(model: string, system: string, user: string, maxTokens: number): Promise<string> {
  if (!model.toLowerCase().startsWith("gemini")) return anthropicText(model, system, user, maxTokens);
  try {
    return await geminiText(model, system, user, maxTokens);
  } catch (err) {
    // 절단은 모델을 바꿔도 같은 프롬프트라 또 잘린다 — 폴백으로 가리지 않는다.
    if (err instanceof OutputTruncatedError) throw err;
    if (!ANTHROPIC_API_KEY) throw err;
    console.warn(`gemini 실패(${String(err).slice(0, 80)}) → anthropic 폴백: ${ANTHROPIC_FALLBACK_MODEL}`);
    return anthropicText(ANTHROPIC_FALLBACK_MODEL, system, user, maxTokens);
  }
}

async function callJSON(model: string, system: string, user: string, maxTokens: number): Promise<any> {
  let lastErr: unknown;
  for (let i = 0; i <= JSON_RETRY; i++) {
    // ★ llmText 가 던지는 OutputTruncatedError 는 try 밖이라 그대로 올라간다 — 의도한 것이다.
    //   재시도 대상은 **파싱 실패**뿐이다.
    const raw = await llmText(model, system, user, maxTokens);
    try {
      return extractJSON(raw);
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

// ─────────────────────────────────────────────────────────────
// 정규화 (engine 의 normalize_* 이식)
// ─────────────────────────────────────────────────────────────
function toInt(v: any, fallback: number): number {
  const n = Math.trunc(Number(v));
  return Number.isFinite(n) ? n : fallback;
}

const FS_LIST_KEYS = ["what", "basis", "risks"] as const;

/** engine/report_evidence._squash 트윈 — 공백·유니코드 폭 차이를 없앤다. */
function squash(text: string): string {
  return (text ?? "").normalize("NFKC").replace(/\s+/g, "");
}

/** engine/report_evidence.locate_chunk 트윈 — 인용문이 실제로 있는 청크의 id.
 *
 *  ★ 모델이 붙인 chunk_id 라벨을 믿지 않는다. 프로덕션 실측에서 19개 ref 전부 chunk_id 가
 *    빈 문자열이었다 — 인용문은 모두 원문에 있었는데 라벨만 안 맞아 버려진 것이다. */
function locateChunk(quote: string, chunks: any[]): string {
  const q = squash(quote);
  if (q.length < QUOTE_MIN_CHARS) return "";
  for (const c of chunks ?? []) {
    if (!c?.chunk_id) continue;
    if (squash(String(c.text ?? "")).includes(q)) return String(c.chunk_id);
  }
  const head = q.slice(0, QUOTE_MIN_CHARS);
  for (const c of chunks ?? []) {
    if (!c?.chunk_id) continue;
    if (squash(String(c.text ?? "")).includes(head)) return String(c.chunk_id);
  }
  return "";
}

/** engine/report_factsheet._normalize_number_fact 의 트윈.
 *
 * ★ 여기가 오래 어긋나 있었다 — Edge 는 number_facts 를 아예 몰라 레거시 문자열 numbers 만
 *   만들었다. 그러면 대시보드로 만든 초안에는 근거 검증(§5)을 걸 대상 자체가 없다. */
function normalizeNumberFact(item: any, index: number, chunks: any[] = []) {
  if (typeof item !== "object" || item === null || Array.isArray(item)) {
    return { fact_id: `num_${index}`, value: null, unit: "", period: "", metric: "",
             comparator: { basis: "", value: "" }, source_refs: [], display: String(item) };
  }
  const rawValue = item.value;
  let value: number | null = null;
  if (typeof rawValue === "number" && Number.isFinite(rawValue)) value = rawValue;
  else if (typeof rawValue === "string") {
    const n = Number(rawValue.replace(/,/g, "").trim());
    value = Number.isFinite(n) ? n : null;
  }
  const comp = (typeof item.comparator === "object" && item.comparator) ? item.comparator : {};
  const unit = String(item.unit ?? "");
  const period = String(item.period ?? "");
  const metric = String(item.metric ?? "");
  const fid = String(item.fact_id ?? "").trim() || `num_${index}`;
  const display = String(item.display ?? "").trim()
    || [metric, value === null ? "" : `${value}${unit}`, period].filter(Boolean).join(" ")
    || fid;
  const sp = item.source_page;
  return {
    fact_id: fid, value, unit, period, metric,
    scope: String(item.scope ?? "company"),
    basis: String(item.basis ?? ""),
    attribution: String(item.attribution ?? ""),
    interpretation: String(item.interpretation ?? "neutral"),
    source_page: (typeof sp === "number" && Number.isFinite(sp)) ? Math.trunc(sp) : null,
    comparator: { basis: String(comp.basis ?? ""), value: String(comp.value ?? "") },
    // engine/report_evidence.normalize_source_refs 트윈 — 길이·개수 상한 + chunk_id 위치 해소.
    source_refs: (Array.isArray(item.source_refs) ? item.source_refs : [])
      .filter((r: any) => r && String(r.quote ?? "").trim())
      .slice(0, SOURCE_REFS_MAX)
      .map((r: any) => {
        const quote = String(r.quote).trim().slice(0, QUOTE_MAX_CHARS);
        return { chunk_id: locateChunk(quote, chunks), quote };
      }),
    display,
  };
}

function normalizeFactsheet(obj: any, chunks: any[] = [], sourceText = "") {
  const out: Record<string, any> = { company: String(obj?.company ?? "") };
  for (const k of FS_LIST_KEYS) {
    let val = obj?.[k] ?? [];
    if (typeof val === "string") val = val ? [val] : [];
    out[k] = (Array.isArray(val) ? val : []).map((x: any) => String(x));
  }
  // number_facts 우선, 없으면 레거시 numbers(문자열)에서 합성 — 엔진과 같은 폴백.
  let raw = obj?.number_facts;
  if (!Array.isArray(raw) || raw.length === 0) {
    let legacy = obj?.numbers ?? [];
    if (typeof legacy === "string") legacy = legacy ? [legacy] : [];
    raw = Array.isArray(legacy) ? legacy : [];
  }
  let facts = raw.map((x: any, i: number) => normalizeNumberFact(x, i, chunks));
  // fact_id 유일성(참조 dangling 방지) — engine._dedupe_fact_ids 트윈.
  // ★ 의미 중복을 **상한보다 먼저** 제거한다(engine/report_factsheet._dedupe_semantic 트윈).
  //   앞에서부터 자르기만 하면 반복 20개가 상한을 채우고 목표주가·실적이 잘린다.
  //   metric·value 가 둘 다 비면 판정 불가라 중복으로 보지 않는다(서술형 사실 보존).
  // ★ 먼저 온 것을 무조건 남기지 않는다. 앞엣것에 쓸 만한 인용이 없고 뒤엣것에 있으면
  //   **유일하게 근거 있는 판본**을 버리는 셈이다(engine/report_factsheet._dedupe_semantic 트윈).
  // ★ 길이만 보면 **원문에 없는 긴 인용**이 "근거 있음"으로 통과한다 — 지어낸 인용을 가진
  //   앞엣것 때문에 진짜 근거를 가진 뒤엣것이 버려진다. 원문이 있으면 실재 여부까지 본다
  //   (engine/report_factsheet._usable_refs 트윈).
  // ★★ locateChunk 를 쓰지 않는다. 그쪽은 청크 경계 인용을 구제하려고 **앞머리 8자만 맞아도**
  //   id 를 돌려주므로, 진짜 문장의 앞머리를 베낀 지어낸 인용이 통과한다. 순위 판정은 나중에
  //   편을 막을 판정(engine/report_evidence.quote_found_in_source)과 같아야 한다.
  const squashedSource = squash(sourceText);
  const usableRefs = (f: any): number =>
    Array.isArray(f?.source_refs)
      ? f.source_refs.filter((r: any) => {
          if (!r || typeof r !== "object") return false;
          const quote = String(r.quote ?? "").trim();
          if (quote.length < QUOTE_MIN_CHARS) return false;
          return squashedSource ? squashedSource.includes(squash(quote)) : true;
        }).length
      : 0;
  const keyAt = new Map<string, number>();
  const kept: any[] = [];
  for (const f of facts) {
    const c = (f.comparator && typeof f.comparator === "object") ? f.comparator : {};
    const metric = String(f.metric ?? "").trim().toLowerCase();
    const scope = String(f.scope ?? "").trim().toLowerCase();
    // ★ scope 가 company 가 아니면 주체를 담을 필드가 스키마에 없다 — 사업부 A 매출 100억과
    //   사업부 B 매출 100억이 같은 키가 된다. 그런 경우도 서술을 봐야 한다.
    const weak = metric === "" || f.value === null || f.value === undefined ||
      (scope !== "" && scope !== "company");
    // 별칭을 정본으로 접는다(engine/report_evidence.normalize_unit · _canon_period 트윈).
    // ★ 수치 식별력이 약하면(metric 없음 / 값 없음 / 전사 아님) **서술까지** 본다 — 서로 다른
    //   서술은 남기고 글자 그대로 같은 반복만 지운다. 통째로 넘기면 같은 서술 20개가 상한을 채운다.
    const key = [metric, f.value,
      normalizeUnit(f.unit).toLowerCase(), normalizePeriod(f.period).toLowerCase(),
      scope,
      String(f.basis ?? "").trim().toLowerCase(), String(c.basis ?? "").trim().toLowerCase(),
      canonCompValue(c.value),
      weak ? squash(String(f.display ?? "")).toLowerCase() : ""].join("\u0000");
    const prev = keyAt.get(key);
    if (prev === undefined) { keyAt.set(key, kept.length); kept.push(f); continue; }
    if (usableRefs(kept[prev]) === 0 && usableRefs(f) > 0) {
      f.fact_id = kept[prev].fact_id;      // 참조 dangling 방지
      kept[prev] = f;
    }
  }
  facts = kept;
  // ★ 프롬프트의 개수 지시를 코드가 다시 강제한다(engine/report_factsheet 트윈).
  //   모델이 안 지키는 것을 실측했으므로 지시만 믿을 수 없다.
  if (facts.length > MAX_NUMBER_FACTS) {
    const cut = facts.slice(MAX_NUMBER_FACTS);
    facts.length = MAX_NUMBER_FACTS;
    // ★ 남긴 것에 쓸 만한 인용이 하나도 없는데 잘려 나갈 쪽에 있으면 맨 뒤 한 자리를 바꾼다 —
    //   그대로 두면 근거 게이트가 no_fact_has_source_ref 로 시트를 통째로 막는다.
    if (facts.length > 0 && !facts.some((f: any) => usableRefs(f) > 0)) {
      const rescue = cut.find((f: any) => usableRefs(f) > 0);
      if (rescue) facts[facts.length - 1] = rescue;
    }
  }
  const seen: Record<string, number> = {};
  for (const f of facts) {
    if (f.fact_id in seen) { seen[f.fact_id] += 1; f.fact_id = `${f.fact_id}_${seen[f.fact_id]}`; }
    else seen[f.fact_id] = 0;
  }
  out.number_facts = facts;
  out.numbers = facts.map((f: any) => f.display);   // back-compat(대시보드·지시서가 읽는다)
  out.opinion = String(obj?.opinion ?? "");
  out.source = obj?.source && typeof obj.source === "object" ? obj.source : String(obj?.source ?? "");
  return out;
}

function normalizeFlow(obj: any) {
  const flow = obj && typeof obj === "object" && !Array.isArray(obj) ? obj : {};
  const beatsIn = Array.isArray(flow.beats) ? flow.beats : [];
  const beats: any[] = [];
  beatsIn.forEach((b: any, i: number) => {
    if (typeof b !== "object" || b === null || Array.isArray(b)) return;
    beats.push({ order: toInt(b.order, i + 1) || i + 1, label: String(b.label ?? ""), summary: String(b.summary ?? ""), transition: String(b.transition ?? "") });
  });
  return { logline: String(flow.logline ?? ""), total_duration_sec: toInt(flow.total_duration_sec, 0), beats };
}

// engine/config.py 의 SCENE_ROLES / SCENE_ROLE_DEFAULT / SCENE_ROLES_EVIDENCE_EXEMPT 트윈.
// ★ 두 경로가 다른 목록을 쓰면 같은 대본이 워커에서는 면제되고 대시보드에서는 오탐이 난다.
const SCENE_ROLES = ["HOOK", "QUESTION", "CLAIM", "EVIDENCE", "MECHANISM", "RISK",
                     "WATCHPOINT", "CTA", "BRIDGE"];
const SCENE_ROLE_DEFAULT = "EVIDENCE";
const SCENE_ROLES_EVIDENCE_EXEMPT = ["HOOK", "QUESTION", "CTA", "BRIDGE"];
// engine/config.py STORY_CLAIM_ROLES · EVIDENCE_PROFILES 트윈.
const STORY_CLAIM_ROLES = ["hook", "reveal", "proof", "mechanism", "valuation", "risk", "closing"];
const EVIDENCE_PROFILES = ["company_update", "earnings_review", "industry_report",
                           "market_wrap", "event_flash", "paper_explainer"];
const EVIDENCE_PROFILE_DEFAULT = "company_update";

function normalizeScript(obj: any) {
  const scenesIn = Array.isArray(obj?.scenes) ? obj.scenes : [];
  const scenes: any[] = [];
  scenesIn.forEach((s: any, i: number) => {
    if (typeof s !== "object" || s === null || Array.isArray(s)) return;
    let sf = s.source_facts ?? [];
    if (typeof sf === "string") sf = [sf];
    const sceneNo = s.scene ? toInt(s.scene, i + 1) : i + 1;
    scenes.push({
      scene: sceneNo || i + 1,
      // v3 §5-4 — 씬 역할. engine/report_scriptgen._enum_role 의 트윈. 화이트리스트 밖은
      // 기본값으로 떨어뜨린다(자유 텍스트가 들어오면 면제도 검사도 안 걸린다).
      scene_role: SCENE_ROLES.includes(String(s.scene_role ?? "").trim().toUpperCase())
        ? String(s.scene_role).trim().toUpperCase() : SCENE_ROLE_DEFAULT,
      title: String(s.title ?? ""),
      narration_ko: String(s.narration_ko ?? ""),
      narration_en: String(s.narration_en ?? ""),
      duration_sec: toInt(s.duration_sec, 0),
      image_prompt: String(s.image_prompt ?? ""),
      image_prompt_ko: String(s.image_prompt_ko ?? ""),
      video_prompt: String(s.video_prompt ?? s.visual_prompt ?? ""),
      video_prompt_ko: String(s.video_prompt_ko ?? ""),
      source_facts: (Array.isArray(sf) ? sf : []).map((x: any) => String(x)),
    });
  });
  return {
    upload_title_ko: String(obj?.upload_title_ko ?? ""),
    upload_title_en: String(obj?.upload_title_en ?? ""),
    script_md: String(obj?.script_md ?? ""),
    video_flow: normalizeFlow(obj?.video_flow),
    story_plan: normalizeStoryPlan(obj?.story_plan, scenes.length),
    scenes,
  };
}

/** engine/report_selfcheck.normalize_selfcheck 의 트윈 — **역할 면제 포함**(v3 §5-4).
 *
 * 면제가 없으면 훅("정말 이제 시작일까요?")과 마무리("댓글로 알려주세요")가 매번 빨간 깃발을
 * 받아 신호가 죽는다(실측: 최근 초안 6/6). rolesByScene 은 호출측이 넘긴 씬에서 읽는다. */
/** engine/report_selfcheck.exempt_scenes 트윈 — 역할 이름표만 믿지 않는다.
 *
 * 모델이 전 씬에 HOOK 을 붙이면 자기검증이 통째로 무력해진다(적대적 리뷰 재현).
 * ① 수치를 말하는 씬은 면제 취소  ② 면제 씬 수 상한. */
function exemptScenes(scenes: any[]): Set<number> {
  const eligible: number[] = [];
  for (const s of scenes ?? []) {
    if (!SCENE_ROLES_EVIDENCE_EXEMPT.includes(String(s?.scene_role ?? ""))) continue;
    if (spokenNumberCount(String(s?.narration_ko ?? "")) > 0) continue;
    eligible.push(toInt(s?.scene, 0));
  }
  const cap = Math.max(1, Math.trunc((scenes ?? []).length * EXEMPT_MAX_RATIO));
  if (eligible.length > cap) {
    // ★ cap 을 실제로 지킨다 — 예전엔 늘 앞뒤 2개를 남겨 씬 2개 대본에서 자기검증이 꺼졌다.
    const sorted = [...eligible].sort((a, b) => a - b);
    const kept = cap === 1
      ? [sorted[0]]
      : [sorted[0], sorted[sorted.length - 1], ...sorted.slice(1, -1)];
    return new Set(kept.slice(0, cap));
  }
  return new Set(eligible);
}

/** engine/report_evidence._PERIOD_MARKER_RE 트윈 — 나레이션에서 **시점**을 가리키는 표기.
 *  뒤에 자릿수 단위가 붙은 것(2,000억)은 값이므로 연도로 보지 않는다. */
const PERIOD_MARKER_RE =
  /(?:19|20)\d{2}\s*년|(?:19|20)\d{2}\s*[FEP]\b|\bFY\s*\d{2,4}|[1-4]\s*[QH]\s*(?:19|20)?\d{2}\b|\d{1,2}\s*분기|\b\d{2}\s*년(?!\d)|(?:19|20)\d{2}(?![\d,.]|\s*[조억만천원%배])/g;

/** engine/report_evidence.spoken_numbers 의 축약 트윈 — 기간 표기를 가린 뒤 수치를 센다.
 *  엔진처럼 값을 돌려주지 않고 **개수만** 센다(면제 판정에 그것만 필요하다).
 *
 *  ★ 예전 트윈은 (a) 리터럴 '년'만 연도로 걸러 2026F·2Q26·3분기를 놓쳤고,
 *    (b) 한국어 자릿수 토막을 전부 1로 뭉개 "5억 15억"을 1개로 셌으며,
 *    (c) `-?\d` 라 "3-5%"의 뒷숫자를 음수로 읽었다. 파이썬 쪽 수정과 맞춘다. */
function spokenNumberCount(text: string): number {
  const body = (text ?? "").replace(PERIOD_MARKER_RE, " ");
  // 자릿수 표기를 한 값으로 묶는 조건은 **둘 다** 필요하다(엔진 korean_scaled_spans 와 동일):
  //   ① 자릿수가 내림차순일 것 — "5억 15억" 은 다른 두 값이다
  //   ② 사이가 공백뿐일 것    — "매출 3조 순익 500억" 은 다른 두 값이다
  const SCALES: Record<string, number> = {
    "조": 1e12, "천억": 1e11, "백억": 1e10, "억": 1e8,
    "천만": 1e7, "백만": 1e6, "만": 1e4, "천": 1e3,
  };
  const SCALE = /(\d[\d,]*(?:\.\d+)?)\s*(조|천억|백억|억|천만|백만|만|천)/g;
  const spans: Array<[number, number]> = [];
  let count = 0;
  let prevEnd = -1;
  let prevScale = Infinity;
  for (const m of body.matchAll(SCALE)) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    const scale = SCALES[m[2]] ?? 0;
    const joined = prevEnd >= 0 && scale < prevScale && /^\s*$/.test(body.slice(prevEnd, start));
    if (!joined) count += 1;                  // 새 값
    spans.push([start, end]);
    prevEnd = end;
    prevScale = scale;
  }
  // 마이너스는 앞이 공백·문두·괄호일 때만(하이픈 범위 표기를 음수로 읽지 않는다).
  const PLAIN = /(?:^|[\s(\[{=])-?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?/g;
  for (const m of body.matchAll(PLAIN)) {
    const at = (m.index ?? 0) + m[0].search(/\d/);
    if (spans.some(([s, e]) => at >= s && at < e)) continue;   // 자릿수 표기의 일부
    count += 1;
  }
  return count;
}

/** engine/report_scriptgen._normalize_story_plan 트윈(§6). */
function normalizeStoryPlan(obj: any, sceneCount: number) {
  const src = (typeof obj === "object" && obj !== null && !Array.isArray(obj)) ? obj : {};
  const chain = (Array.isArray(src.claim_chain) ? src.claim_chain : [])
    .filter((c: any) => typeof c === "object" && c !== null)
    .map((c: any, i: number) => {
      const role = String(c.role ?? "").trim().toLowerCase();
      let refs = c.evidence_refs ?? [];
      if (typeof refs === "string") refs = refs ? [refs] : [];
      return {
        order: i + 1,
        role: STORY_CLAIM_ROLES.includes(role) ? role : "proof",
        claim: String(c.claim ?? ""),
        evidence_refs: (Array.isArray(refs) ? refs : []).map((x: any) => String(x)),
      };
    });
  const profile = String(src.content_profile ?? "").trim();
  return {
    thesis: String(src.thesis ?? ""),
    content_profile: EVIDENCE_PROFILES.includes(profile) ? profile : EVIDENCE_PROFILE_DEFAULT,
    audience_question: String(src.audience_question ?? ""),
    claim_chain: chain,
    excluded_evidence: (Array.isArray(src.excluded_evidence) ? src.excluded_evidence : [])
      .filter((e: any) => e && e.evidence_ref)
      .map((e: any) => ({ evidence_ref: String(e.evidence_ref), reason: String(e.reason ?? "") })),
    scene_count: sceneCount,
  };
}

function normalizeSelfcheck(obj: any, rolesByScene: Record<number, string> = {},
                            exempt: Set<number> | null = null) {
  const scenesIn = Array.isArray(obj?.scenes) ? obj.scenes : [];
  const scenes: any[] = [];
  for (const s of scenesIn) {
    if (typeof s !== "object" || s === null || Array.isArray(s)) continue;
    let unsupported = s.unsupported ?? [];
    if (typeof unsupported === "string") unsupported = unsupported ? [unsupported] : [];
    unsupported = (Array.isArray(unsupported) ? unsupported : []).map((x: any) => String(x));
    let grounded = (s.grounded === undefined ? unsupported.length === 0 : Boolean(s.grounded))
      && unsupported.length === 0;
    const sceneNo = toInt(s.scene, 0);
    const isExempt = exempt !== null
      ? exempt.has(sceneNo)
      : SCENE_ROLES_EVIDENCE_EXEMPT.includes(rolesByScene[sceneNo] ?? "");
    if (isExempt) { grounded = true; unsupported = []; }
    let matched = s.matched_facts ?? [];
    if (typeof matched === "string") matched = [matched];
    scenes.push({ scene: sceneNo, grounded, exempt: isExempt, unsupported, matched_facts: (Array.isArray(matched) ? matched : []).map((x: any) => String(x)) });
  }
  // all_grounded 는 최종 목록에서 재계산(LLM 자기보고 불신 + 면제 반영).
  return { scenes, all_grounded: scenes.every((s) => s.grounded) };
}

// ─────────────────────────────────────────────────────────────
// 컴플라이언스 게이트 (engine/report_compliance.py 이식 — 이중관리)
// ─────────────────────────────────────────────────────────────
function scriptText(script: any): string {
  const parts = [String(script?.script_md ?? "")];
  for (const s of script?.scenes ?? []) if (s && typeof s === "object") parts.push(String(s.narration_ko ?? ""));
  return parts.join("\n");
}

function scanRules(text: string, broker = ""): any[] {
  const flags: any[] = [];
  for (const [category, patterns] of Object.entries(BLOCK_PATTERNS)) {
    for (const p of patterns) {
      for (const m of text.matchAll(new RegExp(p, "g"))) flags.push({ category, severity: "block", hit: m[0] });
    }
  }
  for (const [category, patterns] of Object.entries(WARN_PATTERNS)) {
    for (const p of patterns) {
      for (const m of text.matchAll(new RegExp(p, "g"))) flags.push({ category, severity: "warn", hit: m[0] });
    }
  }
  if (broker && !text.includes(broker)) flags.push({ category: "출처누락", severity: "block", hit: broker });
  if (!DISCLAIMER_MARKERS.some((mk) => text.includes(mk))) flags.push({ category: "면책누락", severity: "block", hit: "" });
  return flags;
}

function normalizeVerdict(obj: any) {
  const yn = (v: any) => ["yes", "y", "true", "1"].includes(String(v).trim().toLowerCase()) ? "yes" : "no";
  const okmiss = (v: any) => ["ok", "yes", "true", "1"].includes(String(v).trim().toLowerCase()) ? "ok" : "missing";
  return { 권유: yn(obj?.["권유"]), 수익률광고: yn(obj?.["수익률광고"]), 단정: yn(obj?.["단정"]), 출처: okmiss(obj?.["출처"]), 면책: okmiss(obj?.["면책"]), 근거: String(obj?.["근거"] ?? "") };
}

// ★ 하드 차단 제거(사용자 요청) — compliance 는 참고 표시 전용. 항상 false.
function computeBlocked(_ruleFlags: any[], _verdict: any, _halluc: any[]): boolean {
  return false;
}

async function runCompliance(script: any, selfCheck: any, broker: string): Promise<any> {
  const text = scriptText(script);
  const ruleFlags = scanRules(text, broker);
  let verdict: any;
  try {
    verdict = normalizeVerdict(await callJSON(MODEL_COMPLIANCE, JUDGE_SYSTEM, text, 1024));
  } catch (_e) {
    verdict = { 권유: "yes", 수익률광고: "yes", 단정: "yes", 출처: "missing", 면책: "missing", 근거: "[심사관 호출 실패 — 보수적 차단]" };
  }
  const halluc = (selfCheck?.scenes ?? []).filter((s: any) => !s.grounded).map((s: any) => ({ scene: s.scene, unsupported: s.unsupported }));
  return { rule_flags: ruleFlags, llm_verdict: verdict, hallucination_flags: halluc, blocked: computeBlocked(ruleFlags, verdict, halluc) };
}

// ─────────────────────────────────────────────────────────────
// 파이프라인 입력·출처 (engine/report_factsheet · report_attribution 이식)
// ─────────────────────────────────────────────────────────────
// 원문 전문 구간. engine/report_source.py:fulltext_block 의 TS 트윈 — 마커 문자열이 같아야
// tests/test_prompt_sync.py 가 두 경로의 계약 일치를 고정할 수 있다.
const FULL_SOURCE_MARKER = "<<FULL_SOURCE>>";
const FULL_SOURCE_END_MARKER = "<</FULL_SOURCE>>";
const FULL_SOURCE_MAX_CHARS = Number(Deno.env.get("SOURCE_FULLTEXT_MAX_CHARS") ?? "40000");
// 초안(대본) 단계 주입 — engine/config.py 의 DRAFT_* 트윈(지시서 §4-2).
const EVIDENCE_MARKER = "<<EVIDENCE_PACKET>>";
const EVIDENCE_END_MARKER = "<</EVIDENCE_PACKET>>";
/** engine/config.py:_get_bool 의 TS 트윈.
 *
 * ★ 처음엔 `!== "false"` 로 썼는데, 파이썬은 **{1,true,yes,on} 만 참**으로 보고 나머지는 전부
 *   거짓이다. 그래서 `DRAFT_INCLUDE_FULLTEXT=0` 이면 워커는 주입을 끄는데 엣지는 계속 켜 두어,
 *   문서에 적어 둔 되돌리기 스위치가 대시보드 경로에서만 안 먹었다. 참 목록을 그대로 옮긴다. */
function envBool(name: string, dflt: boolean): boolean {
  const raw = Deno.env.get(name);
  if (raw === undefined) return dflt;
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
}

const DRAFT_INCLUDE_FULLTEXT = envBool("DRAFT_INCLUDE_FULLTEXT", true);

/** 대본 입력. 근거 묶음 + 원문 전문을 **함께** 넣는다.
 *  engine/report_scriptgen.py:script_user_prompt 의 TS 트윈. */
function scriptUser(factSheet: any, fullText = "", instruction = "",
                    truncated = false): string {
  let base = `${EVIDENCE_MARKER}\n${JSON.stringify(factSheet, null, 2)}\n${EVIDENCE_END_MARKER}`;
  if (DRAFT_INCLUDE_FULLTEXT && fullText) {
    // ★ 잘렸으면 잘렸다고 말한다(engine/report_source.py:fulltext_block 과 같은 문구).
    //   이 한 줄이 없으면 모델은 상한에서 끊긴 원문을 **완전한 리포트로 읽고**, 뒤쪽에 있던
    //   결론·리스크 절이 애초에 없었던 것처럼 논증을 짠다.
    const head = truncated
      ? `${FULL_SOURCE_MARKER}\n(원문이 ${FULL_SOURCE_MAX_CHARS}자 상한에서 잘렸다 — 뒷부분 없음)\n`
      : `${FULL_SOURCE_MARKER}\n`;
    base += `\n\n${head}${fullText}\n${FULL_SOURCE_END_MARKER}`;
  }
  if (instruction) {
    base += "\n\n★사용자 수정 요청(Fact Sheet 사실 범위 내에서만 반영, 규칙 위반 금지):\n" + instruction;
  }
  return base;
}


/** 보관된 원문(report_sources, 0033)을 읽는다.
 *
 * ★ Edge 에는 ARIA 접속이 없다. 수집(engine/report_collect)이 보관해 둔 것을 읽는 것이 이
 *   경로에서 전문을 볼 수 있는 유일한 방법이다. 없으면 예전처럼 요약만 보고 만든다 —
 *   막지 않는다(초안이 아예 안 나오는 것보다 낫다). 그 사실은 fact_sheet.source_depth 에 남는다. */
async function fetchStoredSource(
  supa: any, report: any,
): Promise<{ text: string; depth: string; chunks: any[]; truncated: boolean }> {
  const externalId = report?.external_id;
  if (!externalId) return { text: "", depth: "summary_only", chunks: [], truncated: false };
  // ★ chunks 도 함께 읽는다 — source_refs 의 chunk_id 를 인용문 위치로 다시 매기는 데 쓴다.
  // ★ truncated 도 읽는다 — 수집 때 이미 잘렸을 수 있다. 그 사실을 프롬프트에 전하지 않으면
  //   모델이 끊긴 원문을 완전한 리포트로 읽는다.
  const { data } = await supa.from("report_sources")
    .select("text, source_depth, chunks, truncated")
    .eq("external_id", externalId)
    .order("fetched_at", { ascending: false })
    .limit(1);
  const row = (data ?? [])[0];
  if (!row?.text) return { text: "", depth: "summary_only", chunks: [], truncated: false };
  const raw = String(row.text);
  return {
    text: raw.slice(0, FULL_SOURCE_MAX_CHARS),
    depth: String(row.source_depth ?? "partial_text"),
    chunks: Array.isArray(row.chunks) ? row.chunks : [],
    // 보관 시점에 잘렸거나(플래그), 여기서 상한에 걸려 잘렸거나 — 둘 다 "뒷부분 없음"이다.
    truncated: Boolean(row.truncated) || raw.length > FULL_SOURCE_MAX_CHARS,
  };
}

function factsheetUser(report: any, fullText = "", truncated = false): string {
  const lines = [
    `종목/테마: ${report.company ?? report.theme ?? "(미상)"}`,
    `제목: ${report.title ?? ""}`,
    `증권사: ${report.broker ?? "(미상)"}`,
  ];
  if (report.target_price != null) lines.push(`목표가: ${report.target_price}`);
  if (report.opinion) lines.push(`투자의견: ${report.opinion}`);
  lines.push(`요약: ${report.summary ?? ""}`);
  // 전문이 없으면 마커도 넣지 않는다 — 빈 구간으로 "전문을 줬다"는 착각을 만들지 않는다.
  if (fullText) {
    lines.push("");
    // ★ 잘림 경고는 추출에도 붙는다(engine/report_source.py:fulltext_block 과 같은 문구).
    const head = truncated
      ? `${FULL_SOURCE_MARKER}\n(원문이 ${FULL_SOURCE_MAX_CHARS}자 상한에서 잘렸다 — 뒷부분 없음)\n`
      : `${FULL_SOURCE_MARKER}\n`;
    lines.push(`${head}${fullText}\n${FULL_SOURCE_END_MARKER}`);
  }
  return lines.join("\n");
}

function buildSource(report: any) {
  return {
    broker: report.broker ?? "",
    analyst: report.analyst ?? "",
    company: report.company ?? report.theme ?? "",
    opinion: report.opinion ?? "",
    target_price: report.target_price ?? null,
    url: report.report_url ?? "",
    disclaimer: "본 영상은 정보 제공 목적이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다.",
  };
}

// ─────────────────────────────────────────────────────────────
// 생성 / 재검사
// ─────────────────────────────────────────────────────────────
// = engine/config.VIDEO_VERSIONS 중 리포트 공장이 발주하는 것(web/lib/versions.ts REPORT_VERSION_KEYS).
const CHAINABLE_VERSIONS = new Set(["comic", "photo"]);

function chainableVersions(raw: unknown): string[] {
  const list = Array.isArray(raw) ? raw : [];
  return [...new Set(list.map(String).filter((v) => CHAINABLE_VERSIONS.has(v)))];
}

async function generate(
  supa: any,
  reportId: string,
  instruction = "",
  versionTypes: string[] = [],
): Promise<void> {
  const now = () => new Date().toISOString();
  await supa.from("report_draft_requests").update({ status: "processing", updated_at: now() })
    .eq("report_id", reportId).in("status", ["queued", "processing"]);

  try {
    const { data: report } = await supa.from("reports")
      .select("id, external_id, title, summary, theme, company, ticker, broker, analyst, target_price, opinion, report_url")
      .eq("id", reportId).maybeSingle();
    if (!report) throw new Error(`report 없음: ${reportId}`);

    // 보관된 원문(0033)을 먼저 읽는다 — 없으면 요약만으로 진행하고 그 사실을 남긴다.
    const stored = await fetchStoredSource(supa, report);
    const factSheet = normalizeFactsheet(await callJSON(
      MODEL_FACTSHEET, FACTSHEET_SYSTEM, factsheetUser(report, stored.text, stored.truncated), FACTSHEET_MAX_TOKENS), stored.chunks, stored.text);
    factSheet.source = buildSource(report);
    factSheet.source_depth = stored.depth;
    factSheet.source_chars = stored.text.length;
    const script = normalizeScript(await callJSON(
      MODEL_SCRIPT, SCRIPT_SYSTEM,
      scriptUser(factSheet, stored.text, instruction, stored.truncated),
      SCRIPT_MAX_TOKENS,
    ));
    // ★ scene_role 을 함께 넘긴다 — 빠뜨리면 §5-4 면제가 검증관에 도달하지 못한다
    //   (engine/report_draft.generate_report_draft 와 같은 급소).
    const narrScenes = script.scenes.map((s: any) => (
      { scene: s.scene, scene_role: s.scene_role, narration_ko: s.narration_ko }));
    const rolesByScene: Record<number, string> = {};
    for (const s of script.scenes) rolesByScene[s.scene] = s.scene_role;
    const exempt = exemptScenes(script.scenes);
    const check = normalizeSelfcheck(await callJSON(
      MODEL_SELFCHECK, SELFCHECK_SYSTEM,
      "Fact Sheet:\n" + JSON.stringify(factSheet, null, 2) + "\n\n대본 씬들:\n" + JSON.stringify(narrScenes, null, 2),
      3072,
    ), rolesByScene, exempt);
    const compliance = await runCompliance(script, check, report.broker ?? "");

    await supa.from("report_drafts").upsert({
      report_id: reportId,
      fact_sheet: factSheet,
      upload_title_ko: script.upload_title_ko,
      upload_title_en: script.upload_title_en,
      script_md: script.script_md,
      video_flow: script.video_flow,
      story_plan: script.story_plan,
      scenes: script.scenes,
      self_check: check,
      compliance,
    }, { onConflict: "report_id" });

    await supa.from("report_draft_requests").update({ status: "done", error: null, updated_at: now() })
      .eq("report_id", reportId).in("status", ["queued", "processing"]);
    // ★ 초안 뒤 지시서를 잇는다(0046). 엣지는 큐에 넣기만 하고 생성은 워커가 한다(논문 라인과 같다).
    for (const v of versionTypes) {
      const { data: dup } = await supa.from("report_directive_requests").select("id")
        .eq("report_id", reportId).eq("version_type", v)
        .in("status", ["queued", "processing"]).limit(1).maybeSingle();
      if (dup) continue;
      const { error: qErr } = await supa.from("report_directive_requests")
        .insert({ report_id: reportId, version_type: v, status: "queued" });
      if (qErr) console.warn(`report_directive_requests 적재 실패 report=${reportId} v=${v}: ${qErr.message}`);
    }
    console.log(`report_draft 생성: report=${reportId} scenes=${script.scenes.length} blocked=${compliance.blocked}`);
  } catch (err) {
    await supa.from("report_draft_requests").update({ status: "error", error: String(err).slice(0, 500), updated_at: now() })
      .eq("report_id", reportId).in("status", ["queued", "processing"]);
    throw err;
  }
}

// [재검사] — 편집된 대본으로 컴플라이언스만 재실행하고 compliance 갱신.
async function recheck(supa: any, reportId: string): Promise<void> {
  const { data: draft } = await supa.from("report_drafts")
    .select("script_md, scenes, self_check").eq("report_id", reportId).maybeSingle();
  if (!draft) throw new Error(`report_draft 없음: ${reportId}`);
  const { data: report } = await supa.from("reports").select("broker").eq("id", reportId).maybeSingle();
  const script = { script_md: draft.script_md ?? "", scenes: draft.scenes ?? [] };
  const selfCheck = draft.self_check ?? { scenes: [], all_grounded: true };
  const compliance = await runCompliance(script, selfCheck, report?.broker ?? "");
  await supa.from("report_drafts").update({ compliance }).eq("report_id", reportId);
  console.log(`report 컴플라이언스 재검사: report=${reportId} blocked=${compliance.blocked}`);
}

function json(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });
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
  if ((!GEMINI_API_KEY && !ANTHROPIC_API_KEY) || !SUPABASE_URL || !SERVICE_KEY) {
    return json({ error: "server misconfigured (secrets 누락)" }, 500);
  }
  let body: any;
  try {
    body = await req.json();
  } catch {
    return json({ error: "bad json" }, 400);
  }
  const reportId = body?.report_id;
  if (!reportId) return json({ error: "report_id required" }, 400);

  const supa = createClient(SUPABASE_URL, SERVICE_KEY);
  if (body?.recheck) {
    EdgeRuntime.waitUntil(recheck(supa, reportId).catch((e) => console.error("recheck 실패", reportId, e)));
    return json({ ok: true, status: "processing", mode: "recheck", report_id: reportId }, 202);
  }
  const instruction = String(body?.instruction ?? "").trim().slice(0, 800);
  const versionTypes = chainableVersions(body?.version_types);
  EdgeRuntime.waitUntil(
    generate(supa, reportId, instruction, versionTypes).catch((e) => console.error("report_draft 실패", reportId, e)),
  );
  return json({ ok: true, status: "processing", report_id: reportId }, 202);
});
