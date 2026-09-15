import type { CandidateMentionCard, CandidateMentionSeries } from "../../api/types";

const LINEAGE_COLOR: Record<CandidateMentionSeries["lineage"], string> = {
  conservative: "var(--camp-conservative)",
  progressive: "var(--camp-progressive)",
  centrist: "var(--camp-centrist)",
  other: "var(--camp-other)",
};

function ChangeBadge({ pct }: { pct: number | null }) {
  if (pct === null) {
    return <span style={{ color: "var(--muted)" }}>—</span>;
  }
  const up = pct > 0;
  return (
    <span className={`status-pill ${up ? "watch" : "stable"}`}>
      {up ? "▲" : pct < 0 ? "▼" : "—"} {Math.abs(pct).toFixed(0)}%
    </span>
  );
}

function CandidateRow({ series }: { series: CandidateMentionSeries }) {
  const color = LINEAGE_COLOR[series.lineage];
  return (
    <li style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
        <span style={{ fontWeight: 600 }}>{series.name}</span>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>({series.party})</span>
        {series.is_ours && <span className="badge badge--strong">우리</span>}
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          이번 주 {series.latest_count}건
          {series.latest_share_pct !== null && ` · 점유 ${series.latest_share_pct.toFixed(0)}%`}
        </span>
        <ChangeBadge pct={series.latest_wow_change_pct} />
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 36 }}>
        {series.bars.map((b) => (
          <span
            key={b.week_start}
            title={b.title}
            style={{
              flex: 1,
              minHeight: 1,
              height: `${b.height_pct}%`,
              background: color,
              opacity: b.count === 0 ? 0.15 : 1,
              borderRadius: "1px 1px 0 0",
            }}
          />
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "2px 0 0" }}>
        창 합계 {series.total_articles}건
      </p>
    </li>
  );
}

export function CandidateMentionPanel({
  card,
  districtId,
}: {
  card: CandidateMentionCard;
  districtId: string;
}) {
  return (
    <section className="panel">
      <h2>
        후보 언급 비교{" "}
        <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
          · {card.as_of} 기준 · 최근 {card.window_weeks}주
        </span>
      </h2>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        창 합계 {card.total_articles}건 · 뉴스에 이름이 얼마나 나오는가 (감성·유불리 판정 아님)
      </p>

      {card.backfill_distorted && (
        <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
          첫 백필의 검색 API 상한(검색어당 1,000건) 때문에 최근으로 갈수록 기사량이 부풀어 있다.
          증분 수집이 여러 주 쌓이기 전까지 이번 주 변화율을 신뢰하지 않는다.
        </p>
      )}

      {card.highlight && (
        <p className="banner banner--warn" style={{ fontSize: 13 }}>
          이번 주 특이사항: {card.highlight.text}
        </p>
      )}

      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {card.candidates.map((series) => (
          <CandidateRow key={series.name} series={series} />
        ))}
      </ul>

      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        이름의 정확 일치만 본다 — 동명이인·약칭은 걸러내지 않는다. 후보 이름이 흔하면 다른
        인물을 언급한 기사가 섞였을 수 있다.
      </p>
      <p style={{ fontSize: 12 }}>
        <a href={`/d/${districtId}/news`}>원문 목록 보기 →</a>
      </p>
    </section>
  );
}
