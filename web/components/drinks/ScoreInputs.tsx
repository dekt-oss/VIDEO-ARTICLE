"use client";

// 5축 점수 입력(0~4). 가중 합은 화면에서도 계산해 보여주지만, 저장되는 점수는 서버(SQL)가 다시 계산한다.
import { SCORE_AXES, weightedScore, type Scores } from "@/lib/drinks/model";

export default function ScoreInputs({
  value,
  onChange,
  disabled,
}: {
  value: Scores;
  onChange: (v: Scores) => void;
  disabled?: boolean;
}) {
  const total = weightedScore(value as Record<string, unknown>);
  return (
    <div>
      <div className="dk-grid">
        {SCORE_AXES.map((a) => (
          <label key={a.key} className="dk-field" title={`0점: ${a.low} / 4점: ${a.high}`}>
            <span>
              {a.label} {a.weight > 0 ? `(${a.weight})` : "(형식 적합 20 — 둘 중 높은 값)"}
            </span>
            <select
              value={value[a.key] ?? ""}
              disabled={disabled}
              onChange={(e) => {
                const next = { ...value };
                if (e.target.value === "") delete next[a.key];
                else next[a.key] = Number(e.target.value);
                onChange(next);
              }}
            >
              <option value="">—</option>
              {[0, 1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n}
                  {n === 0 ? ` · ${a.low}` : n === 4 ? ` · ${a.high}` : ""}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <p className="dk-kv" style={{ marginTop: 6 }}>
        가중 합: <b>{total === null ? "축을 모두 채우면 계산됩니다" : `${total}점`}</b>
      </p>
    </div>
  );
}
