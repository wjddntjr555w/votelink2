import type { DistrictView } from "../../api/types";
import { EmdDetailCard } from "./EmdDetailCard";

/** "상세 데이터" — 접기 기본. 아무것도 지우지 않는다, 그냥 접혀 있을 뿐이다.
 * 수집 진단 + 동별 카드 전부를 그대로 옮긴다. */
export function DetailAccordion({ view }: { view: DistrictView }) {
  const d = view.diagnostics;

  return (
    <details className="details-toggle card">
      <summary style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
        <span className="chevron">▶</span> 상세 데이터 (수집 진단 · 동별 전체 지표)
      </summary>

      <div style={{ marginTop: 18 }}>
        <dl style={{ display: "flex", flexWrap: "wrap", gap: 22, margin: "0 0 8px" }}>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>행정동</dt>
            <dd className="num" style={{ margin: 0, fontWeight: 600, color: d.is_complete ? undefined : "var(--signal-behind)" }}>{view.coverage_text}</dd></div>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>총 인구</dt>
            <dd className="num" style={{ margin: 0, fontWeight: 600 }}>{view.population_total.toLocaleString()}</dd></div>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>인구 기준월</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{view.population_month_text}</dd></div>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>분석 기준월</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{view.as_of_months.join(" · ")}</dd></div>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>최근 선거</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{view.latest_election_date}</dd></div>
          <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>평균 신뢰도</dt>
            <dd className="num" style={{ margin: 0, fontWeight: 600 }}>{view.avg_confidence.toFixed(2)}</dd></div>
          {view.last_updated && (
            <div><dt style={{ fontSize: 12, color: "var(--muted)" }}>마지막 갱신</dt>
              <dd className="num" style={{ margin: 0, fontWeight: 600 }} title="이 화면이 읽은 레코드 중 가장 최근 수집 시각">{view.last_updated}</dd></div>
          )}
        </dl>

        <p style={{ fontSize: 12, color: "var(--muted)" }}>
          출처 {view.source_names.join(" · ")} ({view.source_licenses.join(" · ")})
        </p>

        <p style={{ fontSize: 12, color: "var(--muted)" }}>
          읽음 {d.read}건 · 표시 {d.loaded}건
          {d.outside_district > 0 && ` · 선거구 밖 ${d.outside_district}건 제외`}
          {d.superseded > 0 && ` · 이전 기준월 ${d.superseded}건은 표시하지 않았다`}
          {d.rejected > 0 && (
            <span style={{ color: "var(--signal-behind)" }}> · 계약 위반 {d.rejected}건 격리</span>
          )}
          {view.missing_gaps > 0 && ` · 상위 기준선 ${view.missing_gaps}칸 결측`}
        </p>

        {d.missing_codes.length > 0 && (
          <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
            분석 결과가 없는 행정동: {d.missing_codes.join(", ")}
          </p>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
          {view.cards.map((c) => (
            <EmdDetailCard key={c.geo_code} card={c} gapLabels={view.gap_labels} trendNote={view.trend_note} />
          ))}
        </div>
      </div>
    </details>
  );
}
