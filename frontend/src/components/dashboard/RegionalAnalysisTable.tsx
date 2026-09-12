import { useState } from "react";
import type { DistrictView } from "../../api/types";

const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "conservative", label: "보수 우세" },
  { key: "progressive", label: "진보 우세" },
  { key: "contested", label: "경합" },
];

function statusClass(cssClass: string): string {
  if (cssClass === "text-warn") return "watch";
  if (cssClass.startsWith("text-camp")) return "strong";
  return "stable";
}

/** "지역별 판세" — 표 + 미니 시각화 + 상태 배지. 탭은 클라이언트 필터라
 * 서버 재요청이 없다(정렬은 여전히 sort= 쿼리로 서버가 한다). */
export function RegionalAnalysisTable({
  view,
  onSortChange,
}: {
  view: DistrictView;
  onSortChange: (key: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const districtLabel = view.gap_labels["district"] ?? "지역구";

  const rows = view.cards.filter(
    (c) => filter === "all" || view.region_category[c.geo_code] === filter,
  );

  return (
    <section className="panel">
      <div className="panel__head">
        <h2>지역별 판세</h2>
        <nav className="sorts">
          {Object.entries(view.sorts).map(([key, label]) => (
            <a
              key={key}
              href={`?sort=${key}`}
              className={view.sort === key ? "on" : ""}
              onClick={(e) => {
                e.preventDefault();
                onSortChange(key);
              }}
            >
              {label}
            </a>
          ))}
        </nav>
      </div>
      <div className="tabset" role="tablist" aria-label="지역별 판세 필터">
        {FILTERS.map((f) => (
          <button key={f.key} className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table className="regional">
          <thead>
            <tr>
              <th>행정동</th>
              <th>진영 구성</th>
              <th>{districtLabel} 평균 대비</th>
              <th>추세</th>
              <th>상태</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const gap = c.gaps["district"];
              const status = view.region_status[c.geo_code];
              return (
                <tr key={c.geo_code}>
                  <td>{c.geo_name}</td>
                  <td>
                    <div className="camp-bar" title="진영별 득표 구성">
                      {c.camp_bar.map((s) => (
                        <span key={s.camp} style={{ width: `${s.pct}%`, background: `var(--camp-${s.camp})` }} />
                      ))}
                    </div>
                  </td>
                  <td className={`num ${gap && (gap.value ?? 0) > 0 ? "gap-pos" : "gap-neg"}`} title={gap?.title}>
                    {gap?.text}
                  </td>
                  <td>{c.trend === "conservative_shift" ? "↗" : c.trend === "progressive_shift" ? "↘" : "→"}</td>
                  <td>
                    {status && <span className={`status-pill ${statusClass(status.css_class)}`}>{status.label}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
