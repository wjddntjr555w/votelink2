import { Line } from "react-chartjs-2";
import "../../chartSetup";
import type { AggregateCard, Sparkline } from "../../api/types";

const TREND_LABELS: Record<string, string> = {
  conservative_shift: "보수 이동",
  stable: "정체",
  progressive_shift: "진보 이동",
};

function trendMixText(mix: Record<string, number>): string {
  const parts = Object.entries(mix)
    .filter(([, n]) => n)
    .map(([t, n]) => `${TREND_LABELS[t] ?? t} ${n}`);
  return parts.length ? parts.join(" · ") : "—";
}

function MiniSpark({ spark, label, color }: { spark: Sparkline; label: string; color: string }) {
  if (spark.values.every((v) => v === null)) {
    return (
      <figure style={{ margin: 0 }}>
        <figcaption style={{ fontSize: 11, color: "var(--muted)" }}>{label}</figcaption>
        <p style={{ fontSize: 11, color: "var(--muted)" }}>값이 없어 그리지 않는다</p>
      </figure>
    );
  }
  return (
    <figure style={{ margin: 0 }}>
      <figcaption style={{ fontSize: 11, color: "var(--muted)" }}>{label}</figcaption>
      <div style={{ height: 32 }}>
        <Line
          data={{
            labels: spark.labels,
            datasets: [
              { data: spark.values, spanGaps: false, borderColor: color, borderWidth: 1.5, pointRadius: 1.5, tension: 0 },
            ],
          }}
          options={{
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { display: false }, tooltip: { enabled: true } },
            scales: { x: { display: false }, y: { display: false } },
          }}
        />
      </div>
    </figure>
  );
}

/** 전국 종합 카드 — 옛 `_agg.html` 매크로와 같은 정보 밀도. `levels=('nation',)`
 * 고정이라 `gaps.nation` 하나만 그린다(다른 단위는 애초에 응답에 없다). */
export function NationSummaryCard({ card, gapLabels }: { card: AggregateCard; gapLabels: Record<string, string> }) {
  const gap = card.gaps.nation;
  return (
    <article style={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, padding: "14px 16px" }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15 }}>{card.label}</h3>
        <span className="muted small">동 {card.member_count}곳 묶음</span>
        {card.approx && (
          <span className="badge badge--approx" title={card.approx_reason}>근사</span>
        )}
      </header>

      <div className="camp-bar" style={{ width: "100%", height: 10 }} title="진영별 득표 구성(인구·투표율 가중)">
        {card.camp_bar.map((s) => (
          <span key={s.camp} style={{ width: `${s.pct}%`, background: `var(--camp-${s.camp})` }} />
        ))}
      </div>
      <ul style={{ listStyle: "none", display: "flex", flexWrap: "wrap", gap: 10, margin: "6px 0 12px", padding: 0, fontSize: 12, color: "var(--muted)" }}>
        {card.camp_bar.map((s) => (
          <li key={s.camp} style={{ fontWeight: s.ours ? 700 : 400 }}>
            <i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, marginRight: 4, background: `var(--camp-${s.camp})` }} />
            {s.label} {s.pct.toFixed(1)}%
            {s.ours && <span className="status-pill watch" style={{ marginLeft: 4 }}>우리</span>}
          </li>
        ))}
      </ul>

      {card.lens_read && (
        <p style={{ fontSize: 12, margin: "0 0 10px", color: card.lens_read.ahead ? "var(--signal-ahead)" : "var(--signal-behind)" }}>
          우리 {card.lens_read.ours.toFixed(1)}% · 상대 {card.lens_read.theirs.toFixed(1)}%{" "}
          <strong>{card.lens_read.lead_text}</strong>
        </p>
      )}

      <dl style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px 10px", margin: "0 0 12px", fontSize: 12 }}>
        <div>
          <dt style={{ color: "var(--muted)" }}>투표율</dt>
          <dd className="num" style={{ margin: 0 }}>
            {card.turnout.toFixed(1)}%
            {card.turnout_known < card.turnout_total && (
              <span style={{ color: "var(--review-block-line)", marginLeft: 4 }}>
                ({card.turnout_total}곳 중 {card.turnout_known}곳)
              </span>
            )}
          </dd>
        </div>
        <div><dt style={{ color: "var(--muted)" }}>스윙</dt><dd className="num" style={{ margin: 0 }}>{card.swing.toFixed(1)}%p</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>추세 분포</dt><dd style={{ margin: 0 }}>{trendMixText(card.trend_mix)}</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>성비(남/여)</dt><dd className="num" style={{ margin: 0 }}>{card.sex_ratio_text}</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>인구</dt><dd className="num" style={{ margin: 0 }}>{card.population_total.toLocaleString()}</dd></div>
      </dl>

      {gap && (
        <div style={{ marginBottom: 10 }}>
          <span style={{ display: "block", fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>
            {gapLabels.nation ?? "전국"} 대비 보수 편차 (동별 요약)
          </span>
          <span className={gap.mean === null ? "gap gap--unknown" : "num"}>{gap.text}</span>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <MiniSpark spark={card.conservative_spark} label="보수 득표율" color="var(--camp-conservative)" />
        <MiniSpark spark={card.gap_spark} label="기준 대비 편차" color="var(--ink-soft)" />
      </div>

      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 40 }}>
        {card.age_bars.map((a) => (
          <div key={a.band} title={`${a.band}세 ${a.pct.toFixed(1)}%`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "center", height: "100%" }}>
            <div style={{ width: "100%", height: `${a.height_pct}%`, background: "var(--camp-centrist)", borderRadius: "2px 2px 0 0" }} />
          </div>
        ))}
      </div>
    </article>
  );
}
