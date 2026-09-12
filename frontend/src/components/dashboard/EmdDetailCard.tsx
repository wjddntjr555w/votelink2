import { Line } from "react-chartjs-2";
import "../../chartSetup";
import type { EmdCard } from "../../api/types";

const LEVELS = ["district", "sigungu", "sido", "nation"] as const;

function MiniSpark({ spark, label, color }: { spark: EmdCard["gap_spark"]; label: string; color: string }) {
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
      <figcaption style={{ fontSize: 11, color: "var(--muted)" }}>
        {label}
        {spark.breaks > 0 && <span style={{ color: "var(--accent-ink)" }}> · {spark.breaks}회 값 없음</span>}
      </figcaption>
      <div style={{ height: 32 }}>
        <Line
          data={{
            labels: spark.labels,
            datasets: [
              {
                data: spark.values,
                spanGaps: false,
                borderColor: color,
                borderWidth: 1.5,
                pointRadius: 1.5,
                tension: 0,
              },
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

/** 행정동 상세 카드 — `_card.html`(Jinja)과 같은 정보 밀도. 규칙5는 이 카드를
 * 부르는 쪽(DashboardPage 의 ComplianceGate)이 이미 게이팅했다. */
export function EmdDetailCard({ card, gapLabels, trendNote }: { card: EmdCard; gapLabels: Record<string, string>; trendNote: string }) {
  return (
    <article className="card" style={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, padding: "14px 16px" }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10 }}>
        <h3 style={{ fontSize: 15 }}>{card.geo_name}</h3>
        <span className="num" style={{ color: "var(--muted)" }}>{card.geo_code}</span>
      </header>

      <div className="camp-bar" style={{ width: "100%", height: 10 }}>
        {card.camp_bar.map((s) => (
          <span key={s.camp} style={{ width: `${s.pct}%`, background: `var(--camp-${s.camp})` }} title={`${s.label} ${s.pct.toFixed(1)}%`} />
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
          {!card.lens_read.in_territory && (
            <span className="status-pill watch" style={{ marginLeft: 6 }} title="이 캠프의 관할 행정동이 아니다">관할 밖</span>
          )}
        </p>
      )}

      <dl style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px 10px", margin: "0 0 12px", fontSize: 12 }}>
        <div><dt style={{ color: "var(--muted)" }}>투표율</dt><dd className="num" style={{ margin: 0 }}>{card.turnout.toFixed(1)}%</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>스윙</dt><dd className="num" style={{ margin: 0 }}>{card.swing.toFixed(1)}%p</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>추세</dt><dd style={{ margin: 0 }} title={trendNote}>{card.trend_label}</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>성비(남/여)</dt><dd className="num" style={{ margin: 0 }}>{card.sex_ratio_text}</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>인구</dt><dd className="num" style={{ margin: 0 }}>{card.population_total.toLocaleString()}</dd></div>
        <div><dt style={{ color: "var(--muted)" }}>신뢰도</dt><dd className="num" style={{ margin: 0 }}>{card.confidence.toFixed(2)}</dd></div>
      </dl>

      <div style={{ marginBottom: 10 }}>
        <span style={{ display: "block", fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>상위 단위 대비 보수 편차</span>
        <ul style={{ listStyle: "none", display: "flex", flexWrap: "wrap", gap: 10, margin: "0 0 4px", padding: 0, fontSize: 12 }}>
          {LEVELS.map((level) => {
            const cell = card.gaps[level];
            if (!cell) return null;
            return (
              <li key={level} style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontSize: 10, color: "var(--muted)" }}>{gapLabels[level] ?? level}</span>
                <span className={cell.css_class === "gap gap--unknown" ? "gap gap--unknown" : "num"} title={cell.title}
                  style={{ color: cell.known ? (cell.value! > 0 ? "var(--camp-conservative)" : cell.value! < 0 ? "var(--camp-progressive)" : undefined) : "var(--muted)" }}>
                  {cell.text}
                </span>
              </li>
            );
          })}
        </ul>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <MiniSpark spark={card.conservative_spark} label={`보수 득표율 ${card.election_count}회`} color="var(--camp-conservative)" />
        <MiniSpark spark={card.gap_spark} label={`지역구 대비 편차 ${card.election_count}회`} color="var(--ink-soft)" />
      </div>

      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 40 }}>
        {card.age_bars.map((a) => (
          <div key={a.band} title={`${a.band}세 ${a.pct.toFixed(1)}%`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", alignItems: "center", height: "100%" }}>
            <div style={{ width: "100%", height: `${a.height_pct}%`, background: "var(--camp-centrist)", borderRadius: "2px 2px 0 0" }} />
          </div>
        ))}
      </div>

      <details style={{ marginTop: 12, fontSize: 12 }}>
        <summary style={{ color: "var(--muted)", cursor: "pointer" }}>
          근거 {card.evidence_count}건 · 최근 선거 {card.latest_election_id}
        </summary>
        <p className="num" style={{ wordBreak: "break-all", color: "var(--muted)" }}>{card.evidence_ids.join(" ")}</p>
      </details>
    </article>
  );
}
