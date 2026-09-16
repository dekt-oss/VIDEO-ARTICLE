"use client";

// 홈 **상단** 배치일 바 — "지금 며칠 것을 보고 있나 · 확인 처리 · 다음 날짜로".
//
// 왜 새로 만들었나(운영자 요청):
//  ① 확인 처리 버튼이 페이지 **맨 아래 접힌 패널** 안에만 있었다. 후보를 다 훑고 나면
//     화면 끝까지 내려가 패널을 펴야 눌렀다.
//  ② 확인하고 다음 날짜로 넘어가는 것이 두 동작이었다(확인 → 홈으로 → 날짜 이동).
//  ③ 며칠 밀리면 하루씩 열어 하루씩 눌러야 했다. 실제로 리포트 쪽 미확인이 8일까지 쌓였다.
// 그래서 여기서 셋을 한 줄로 합친다: [← 이전] [오늘로] [다음 →] · [✓ 확인하고 다음 날짜로]
// · [밀린 N일 한번에 확인].
//
// ★ 2026-08-20 — 날짜를 크게 키웠다. 홈이 "가장 오래된 미확인 날짜"로 열리기 때문에,
//   지금 보고 있는 것이 며칠 것인지 한눈에 보이지 않으면 오늘 것인 줄 알고 선별한다.
//   확인 처리 로직은 lib/useBatchReview 에 있다(화면 아래 BatchDateFooter 와 공유).
import { useState } from "react";
import ConfirmModal from "@/components/ConfirmModal";
import { dayLabelWithDate } from "@/lib/date";
import { useBatchReview } from "@/lib/useBatchReview";

export default function BatchDateBar({
  batchDate,
  dates,
  reviewedDates,
  apiPath,
  homeHref,
}: {
  /** 지금 보고 있는 배치일(YYYY-MM-DD) */
  batchDate: string;
  /** 전체 배치일 — 최신순 */
  dates: string[];
  /** 확인 완료된 배치일 */
  reviewedDates: string[];
  apiPath: string;
  homeHref: string;
}) {
  const r = useBatchReview({ batchDate, dates, reviewedDates, apiPath, homeHref });
  const [showBulk, setShowBulk] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  return (
    <section className="batch-bar" aria-label="배치 날짜" id="batch-top">
      <div className="batch-bar-row">
        <div className="batch-bar-nav">
          <button
            className="btn"
            onClick={() => r.go(r.olderDate)}
            disabled={!r.olderDate}
            title="더 오래된 배치"
          >
            ←
          </button>
          <span className="batch-bar-date">
            {r.isReviewed ? "✓ " : ""}
            {dayLabelWithDate(batchDate)}
          </span>
          <button
            className="btn"
            onClick={() => r.go(r.newerDate)}
            disabled={!r.newerDate}
            title="더 최신 배치"
          >
            →
          </button>
          {r.latest && r.latest !== batchDate && (
            <button className="btn" onClick={() => r.go(r.latest)} title="가장 최신 배치로">
              오늘로
            </button>
          )}
        </div>

        <span className="spacer" />

        {r.unreviewed.length > 1 && (
          <button
            className="btn"
            onClick={() => {
              setPicked(new Set(r.unreviewed));
              setShowBulk(true);
            }}
            disabled={r.busy}
          >
            밀린 {r.unreviewed.length}일 한번에 확인
          </button>
        )}
        {r.isReviewed ? (
          <button className="btn" onClick={r.undo} disabled={r.busy} title="확인 완료를 되돌린다">
            ✓ 확인 완료 · 되돌리기
          </button>
        ) : (
          <button className="btn pick" onClick={r.confirmAndNext} disabled={r.busy}>
            {r.busy
              ? "저장 중…"
              : r.nextTarget && r.nextTarget !== batchDate
                ? "✓ 확인하고 다음 날짜로 →"
                : "✓ 확인 완료"}
          </button>
        )}
      </div>

      {/* 밀린 날짜를 **전부 나열한다** — 지금 몇 번째를 보고 있는지, 나머지는 어디 있는지.
        *
        * ★ 왜 필요한가(운영자 지적 2026-09-04): 바가 "미확인 3일"이라고 말하는데 화면에는
        *   **하루치만 보인다.** 나머지 이틀이 어디 있는지 화면 어디에도 없어서, 후보가
        *   사라진 것처럼 보였다. 실제로는 ← → 로 갈 수 있었지만 그걸 알 길이 없었다.
        *   숫자만 말하고 갈 곳을 안 주면 그 숫자는 불안만 만든다. */}
      {r.unreviewed.length > 1 && (
        <div className="batch-bar-pending">
          <span className="muted">밀린 날짜</span>
          {r.unreviewed.map((d, i) => (
            <button
              key={d}
              className={`btn chip${d === batchDate ? " chip-on" : ""}`}
              onClick={() => r.go(d)}
              disabled={d === batchDate}
              title={d === batchDate ? "지금 보고 있는 날짜" : `${d} 후보 보기`}
            >
              {i + 1}/{r.unreviewed.length} · {dayLabelWithDate(d)}
            </button>
          ))}
        </div>
      )}

      {/* 며칠 것을 보고 있는지 · 얼마나 밀렸는지 한 줄로. 홈이 과거 날짜로 열리므로 필요하다. */}
      <div className="batch-bar-sub muted">
        {r.isReviewed
          ? "이 날짜는 확인 완료입니다 — 남은 미결정 후보는 할 일 카운트에서 빠집니다."
          : "이 날짜의 후보를 다 보고 [확인]을 누르면, 낙점하지 않은 나머지는 할 일에서 빠집니다."}
        {r.unreviewed.length > 0 && (
          <>
            {` · 미확인 ${r.unreviewed.length}일`}
            {/* ★ 화면에는 한 날짜만 나온다는 것을 **말로** 못박는다. 숫자를 보고
              *   "3일치가 한 화면에 나오겠거니" 하고 기다린 것이 이번 혼선이었다. */}
            {r.unreviewed.length > 1 && " — 한 화면에 하루씩 보여줍니다. 위 날짜 버튼으로 옮기세요."}
          </>
        )}
      </div>

      <ConfirmModal
        open={showBulk}
        title="여러 날짜 한번에 확인 완료"
        message={`선택한 ${picked.size}일을 확인 완료로 표시합니다. 후보 결정(낙점·탈락)은 바뀌지 않습니다 — "이 날짜는 다 봤다"는 표시만 남습니다.`}
        confirmLabel={`${picked.size}일 확인 완료`}
        busy={r.busy}
        onConfirm={async () => {
          const ok = await r.markMany([...picked]);
          if (ok) {
            setShowBulk(false);
            setPicked(new Set());
          }
        }}
        onCancel={() => setShowBulk(false)}
      >
        <div className="bulk-date-list">
          {r.unreviewed.map((d) => (
            <label key={d} className="bulk-date-item">
              <input
                type="checkbox"
                checked={picked.has(d)}
                onChange={(e) =>
                  setPicked((prev) => {
                    const s = new Set(prev);
                    e.target.checked ? s.add(d) : s.delete(d);
                    return s;
                  })
                }
              />
              <span>
                {dayLabelWithDate(d)}
                {d === batchDate ? " · 지금 보는 날" : ""}
              </span>
            </label>
          ))}
        </div>
      </ConfirmModal>
    </section>
  );
}
