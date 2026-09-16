"use client";

// 성과 리포트 차트 (recharts). 서버 페이지(/analytics/report)가 집계한 시리즈를 props 로 받아
// 렌더만 한다 — recharts 는 클라이언트 전용이라 이 컴포넌트로 격리(서버 컴포넌트 SSR 이슈 회피).
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export interface DailyPoint {
  day: string;
  views: number;
  subscribers_gained: number;
}
export interface PeriodPoint {
  period: string;
  views: number;
}

const AXIS = "#8a8f98";
const GRID = "#2a2d34";

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="section">
      <h3>{title}</h3>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function PerfCharts({
  daily,
  weekly,
  monthly,
}: {
  daily: DailyPoint[];
  weekly: PeriodPoint[];
  monthly: PeriodPoint[];
}) {
  return (
    <>
      <ChartCard title="일별 조회수 · 구독 전환">
        <LineChart data={daily} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="day" tick={{ fill: AXIS, fontSize: 11 }} minTickGap={24} />
          <YAxis yAxisId="v" tick={{ fill: AXIS, fontSize: 11 }} width={44} />
          <YAxis yAxisId="s" orientation="right" tick={{ fill: AXIS, fontSize: 11 }} width={36} />
          <Tooltip
            contentStyle={{ background: "#16181d", border: `1px solid ${GRID}`, fontSize: 12 }}
            labelStyle={{ color: "#e6e6e6" }}
          />
          <Line yAxisId="v" type="monotone" dataKey="views" name="조회수" stroke="#5b8def" dot={false} strokeWidth={2} />
          <Line yAxisId="s" type="monotone" dataKey="subscribers_gained" name="구독 전환" stroke="#50c878" dot={false} strokeWidth={2} />
        </LineChart>
      </ChartCard>

      <ChartCard title="주별 조회수">
        <BarChart data={weekly} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="period" tick={{ fill: AXIS, fontSize: 11 }} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} width={44} />
          <Tooltip
            contentStyle={{ background: "#16181d", border: `1px solid ${GRID}`, fontSize: 12 }}
            labelStyle={{ color: "#e6e6e6" }}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
          />
          <Bar dataKey="views" name="조회수" fill="#5b8def" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartCard>

      <ChartCard title="월별 조회수">
        <BarChart data={monthly} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="period" tick={{ fill: AXIS, fontSize: 11 }} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} width={44} />
          <Tooltip
            contentStyle={{ background: "#16181d", border: `1px solid ${GRID}`, fontSize: 12 }}
            labelStyle={{ color: "#e6e6e6" }}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
          />
          <Bar dataKey="views" name="조회수" fill="#7c5cff" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartCard>
    </>
  );
}
