import type { PulseCard } from "../../api/types";

const PUBLISHER_CONCENTRATION_WARN_PCT = 30;
/** 창 전체 기사의 이 비율 이상이 한 언론사에서 나오면 쏠림 경고를 띄운다.
 * IssueBoardPanel 의 `unclassified_pct >= 50` 과 같은 성격의 화면단 임계값 —
 * 데이터 파이프라인 판단이 아니라 표시 여부만 정하므로 meta.yaml 이 아니라 여기 둔다. */

export function PulsePanel({ pulse, districtId }: { pulse: PulseCard; districtId: string }) {
  const topPublisher = pulse.top_publishers[0];
  const topPublisherSharePct =
    topPublisher && pulse.total_articles > 0 ? (topPublisher[1] / pulse.total_articles) * 100 : null;

  return (
    <section className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <h2>
          뉴스 펄스 <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>· {pulse.as_of} 기준 · 최근 {pulse.window_weeks}주</span>
        </h2>
      </div>
      <p style={{ margin: "8px 0" }}>
        최근 주({pulse.latest_week}) <strong className="num">{pulse.latest_count}건</strong>{" "}
        <span style={{ color: "var(--muted)" }}>(동·지명 직접 {pulse.latest_district_specific})</span>{" "}
        <span className={`status-pill ${pulse.latest_spike ? "watch" : "stable"}`}>
          {pulse.latest_spike ? "급증" : "평상"} {pulse.latest_z_text}
        </span>
      </p>

      {pulse.backfill_distorted && (
        <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
          첫 백필의 검색 API 상한(검색어당 1,000건) 때문에 최근으로 갈수록 기사량이 부풀어 있다.
          증분 수집이 여러 주 쌓이기 전까지 급증 판정을 신뢰하지 않는다.
        </p>
      )}

      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 60, margin: "8px 0" }}>
        {pulse.bars.map((b) => (
          <span
            key={b.week_start}
            title={b.title}
            style={{
              flex: 1,
              minHeight: 1,
              height: `${b.height_pct}%`,
              background: b.spike ? "var(--accent)" : "var(--muted)",
              borderRadius: "1px 1px 0 0",
            }}
          />
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        창 합계 {pulse.total_articles}건 · 급증 주 {pulse.spike_weeks}
      </p>

      {pulse.top_publishers.length > 0 && (
        <p style={{ fontSize: 12, margin: "4px 0" }}>
          자주 등장한 언론사:{" "}
          {pulse.top_publishers.map(([name, n]) => (
            <span key={name} className="chip">{name} {n}</span>
          ))}
        </p>
      )}
      {topPublisherSharePct !== null && topPublisherSharePct >= PUBLISHER_CONCENTRATION_WARN_PCT && (
        <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
          창 전체 기사의 {topPublisherSharePct.toFixed(0)}%가 '{topPublisher[0]}' 하나에서
          나왔다 — 논조가 한 매체에 쏠려 있을 수 있다.
        </p>
      )}
      {pulse.top_places.length > 0 && (
        <p style={{ fontSize: 12, margin: "4px 0" }}>
          자주 언급된 지명:{" "}
          {pulse.top_places.map(([name, n]) => (
            <span key={name} className="chip">{name} {n}</span>
          ))}
        </p>
      )}
      {pulse.top_persons.length > 0 && (
        <p style={{ fontSize: 12, margin: "4px 0" }}>
          자주 언급된 인물:{" "}
          {pulse.top_persons.map(([name, n]) => (
            <span key={name} className="chip">{name} {n}</span>
          ))}
        </p>
      )}

      <p style={{ fontSize: 12 }}>
        <a href={`/d/${districtId}/news`}>원문 목록 보기 →</a>
      </p>
    </section>
  );
}
