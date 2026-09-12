import type { PulseCard } from "../../api/types";

export function PulsePanel({ pulse, districtId }: { pulse: PulseCard; districtId: string }) {
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
      <p style={{ fontSize: 12 }}>
        <a href={`/d/${districtId}/news`}>원문 목록 보기 →</a>
      </p>
    </section>
  );
}
