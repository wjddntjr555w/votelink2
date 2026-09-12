import type { EmdCard } from "../../api/types";

function sparkPoints(values: (number | null)[]): string | null {
  const known = values.filter((v): v is number => v !== null);
  if (known.length < 2) return null;
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const span = hi - lo || 1;
  const step = 60 / Math.max(values.length - 1, 1);
  const pts: string[] = [];
  values.forEach((v, i) => {
    if (v === null) return;
    const x = (i * step).toFixed(1);
    const y = (18 - ((v - lo) / span) * 16).toFixed(1);
    pts.push(`${x},${y}`);
  });
  return pts.join(" ");
}

/** "주의 지역" — 카드 나열이 아니라 순위 목록(원장 형태). */
export function Watchlist({ cards }: { cards: EmdCard[] }) {
  if (cards.length === 0) return null;

  return (
    <section className="panel">
      <h2>🚩 주의 지역</h2>
      <ol className="ledger">
        {cards.map((c, i) => {
          const wv = c.recent_change.known ? c.recent_change.value : c.gaps["district"]?.value ?? null;
          const points = sparkPoints(c.gap_spark.values);
          return (
            <li key={c.geo_code}>
              <span className="rank num">{String(i + 1).padStart(2, "0")}</span>
              <span className="place">{c.geo_name}</span>
              {points ? (
                <svg className="spark" viewBox="0 0 60 20" aria-hidden="true">
                  <polyline points={points} fill="none" stroke="var(--muted)" strokeWidth={1.5} />
                </svg>
              ) : (
                <span />
              )}
              <span
                className={`delta num ${(wv ?? 0) < 0 ? "down" : (wv ?? 0) > 0 ? "up" : ""}`}
                title={c.recent_change.known ? c.recent_change.title : c.gaps["district"]?.title}
              >
                {c.recent_change.known ? c.recent_change.text : c.gaps["district"]?.text}%p
              </span>
              <span className="arrow">{(wv ?? 0) < 0 ? "↓" : (wv ?? 0) > 0 ? "↑" : ""}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
