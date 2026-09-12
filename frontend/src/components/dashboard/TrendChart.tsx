import { useMemo, useState } from "react";
import { Line } from "react-chartjs-2";
import "../../chartSetup";
import type { AggregateCard } from "../../api/types";

type MetricKey = "support" | "turnout" | "gap";

const CSS = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name);

/** "최근 판세 변화" — 화면의 핵심 시각화. 탭으로 지지율/투표의향/격차를 전환한다.
 * 데이터는 전부 이미 계산된 값(AggregateCard의 스파크라인)을 그대로 그릴 뿐이다. */
export function TrendChart({ summary }: { summary: AggregateCard }) {
  const [metric, setMetric] = useState<MetricKey>("support");

  const labels = summary.conservative_spark.labels;

  const datasets = useMemo(() => {
    if (metric === "support") {
      return [
        { label: "보수", data: summary.conservative_spark.values, color: "--camp-conservative" },
        { label: "진보", data: summary.progressive_spark.values, color: "--camp-progressive" },
        { label: "중도", data: summary.centrist_spark.values, color: "--camp-centrist" },
      ];
    }
    if (metric === "turnout") {
      return [{ label: "투표 의향", data: summary.turnout_spark.values, color: "--accent" }];
    }
    return [{ label: "지역구 평균 대비 편차", data: summary.gap_spark.values, color: "--accent" }];
  }, [metric, summary]);

  const unit = metric === "gap" ? "%p" : "%";

  const data = {
    labels,
    datasets: datasets.map((d) => ({
      label: d.label,
      data: d.data,
      spanGaps: false,
      borderColor: CSS(d.color).trim() || "#888",
      backgroundColor: "transparent",
      tension: 0.15,
      pointRadius: 3,
    })),
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index" as const, intersect: false },
    plugins: {
      legend: { position: "bottom" as const, labels: { boxWidth: 10 } },
      tooltip: {
        callbacks: {
          label: (ctx: { dataset: { label?: string }; parsed: { y: number | null } }) => {
            const v = ctx.parsed.y;
            return `${ctx.dataset.label} ${v === null ? "값 없음" : v.toFixed(1) + unit}`;
          },
        },
      },
    },
    scales: {
      y: { ticks: { callback: (v: string | number) => `${v}${unit}` } },
    },
  };

  const lastKnown = (values: (number | null)[]) => {
    const known = values.filter((v): v is number => v !== null);
    return known.length ? known[known.length - 1] : null;
  };

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>최근 판세 변화</h2>
        <div className="tabset" role="tablist" aria-label="차트 지표 전환">
          {(["support", "turnout", "gap"] as MetricKey[]).map((key) => (
            <button
              key={key}
              className={metric === key ? "on" : ""}
              onClick={() => setMetric(key)}
              type="button"
            >
              {key === "support" ? "지지율" : key === "turnout" ? "투표의향" : "격차"}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-summary">
        <span className="big num">
          {summary.recent_change.known ? `${lastKnown(summary.conservative_spark.values)?.toFixed(1)}%` : "—"}
        </span>
        <span className="sub">
          최근 조사 대비 {summary.recent_change.text}
          {summary.recent_change.known ? "%p" : ""} · 최근 {labels.length}회 조사
        </span>
      </div>
      <div style={{ height: 260, marginTop: 14 }}>
        <Line data={data} options={options} />
      </div>
    </div>
  );
}
