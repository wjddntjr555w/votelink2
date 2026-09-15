import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchCompare, ApiError } from "../api/client";
import type { CompareApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { ComplianceGate } from "../components/compliance/ComplianceGate";

export function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sort = searchParams.get("sort") ?? "name";
  const electionType = searchParams.get("election_type") ?? "presidential";

  const [data, setData] = useState<CompareApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchCompare({ sort, electionType })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
    return () => {
      cancelled = true;
    };
  }, [sort, electionType]);

  const handleElectionTypeChange = (value: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("election_type", value);
    setSearchParams(next);
  };

  const setSort = (key: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("sort", key);
    setSearchParams(next);
  };

  if (error) {
    return (
      <div className="shell">
        <div className="main">
          <div className="content">
            <div className="banner banner--blocked">
              <strong>화면을 불러오지 못했다</strong>
              <p>{error}</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="shell">
        <div className="main">
          <div className="content" style={{ color: "var(--muted)" }}>불러오는 중…</div>
        </div>
      </div>
    );
  }

  const { view } = data;
  const openIds = new Set(data.districts.map(([id]) => id));
  const isEmpty = view.rows.length === 0;
  // 캠프 계정은 관할 선거구가 있다 — 이 화면에도 대시보드·지도·뉴스 링크를 계속
  // 보여준다("전국"류 화면을 본다고 사이드바 메뉴가 통째로 달라지면 안 된다).
  // 운영자는 "지금 이 선거구"가 없으므로 여전히 그 링크들을 안 그린다.
  const homeDistrictId = data.lens ? data.districts[0]?.[0] : undefined;

  return (
    <div className="shell">
      <Sidebar active="compare" districtId={homeDistrictId} lens={data.lens} authOn={data.auth_on} account={data.account} />

      <div className="main">
        <TopBar
          electionTypes={data.election_types}
          electionType={electionType}
          districts={data.districts}
          authOn={data.auth_on}
          onElectionTypeChange={handleElectionTypeChange}
        />

        <div className="content">
          <div className="page-head">
            <div>
              <div className="eyebrow">{view.election_type_label}</div>
              <h1>선거구 비교</h1>
            </div>
          </div>
          <p className="muted small">
            각 선거구의 모든 행정동을 하나로 묶은 <strong>근사 집계</strong>다 (인구·투표율 가중). 지금은
            행정동코드가 확정된 선거구만 나온다.
          </p>

          {!isEmpty && (
            <nav className="map-metric-nav">
              {Object.entries(view.sorts).map(([key, label]) => (
                <a
                  key={key}
                  className={sort === key ? "on" : ""}
                  href="?"
                  onClick={(e) => {
                    e.preventDefault();
                    setSort(key);
                  }}
                >
                  {label}
                </a>
              ))}
            </nav>
          )}

          {isEmpty ? (
            <div className="banner banner--warn">
              <strong>{view.election_type_label}로 비교할 선거구가 없다</strong>
              <p className="muted small">아래 목록의 조치를 먼저 한다.</p>
            </div>
          ) : (
            <ComplianceGate verdict={view.verdict}>
              <div className="news-table-wrap">
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>선거구</th>
                      <th>진영 구성</th>
                      {data.lens && <th title="우리 진영 − 나머지 전부(중도·기타 포함). 집계 근사다">우리 우열</th>}
                      <th>투표율</th>
                      <th>스윙</th>
                      <th>{view.gap_labels.nation} 대비</th>
                      <th>인구</th>
                      <th title="최근 12주 창 합계 (같은 자치구 선거구는 값이 같다 — 뉴스는 시군구 단위다)">뉴스량</th>
                      <th>동</th>
                      <th>검토</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.rows.map((row) => (
                      <tr key={row.district_id}>
                        <td>
                          {openIds.has(row.district_id) ? (
                            <a href={`/d/${row.district_id}/?election_type=${view.election_type}`}>
                              {row.district_name}
                            </a>
                          ) : (
                            <span className="muted" title="관할 밖이라 열 수 없다">{row.district_name}</span>
                          )}
                        </td>
                        <td>
                          <div className="camp-bar" title="진영별 득표 구성">
                            {row.agg.camp_bar.map((s) => (
                              <span key={s.camp} style={{ width: `${s.pct}%`, background: `var(--camp-${s.camp})` }} />
                            ))}
                          </div>
                        </td>
                        {data.lens && (
                          <td className={row.agg.lens_read?.ahead ? "up" : "down"}>
                            {row.agg.lens_read ? row.agg.lens_read.lead_text : "—"}
                          </td>
                        )}
                        <td className="num">{row.agg.turnout.toFixed(1)}%</td>
                        <td className="num">{row.agg.swing.toFixed(1)}%p</td>
                        <td className="num">{row.agg.gaps.nation?.text}</td>
                        <td className="num">{row.agg.population_total.toLocaleString()}</td>
                        <td className="num">
                          {row.news_total_articles !== null ? (
                            `${row.news_total_articles.toLocaleString()}건`
                          ) : (
                            <span className="muted" title="수집 전이거나 검토 전이라 표시하지 않는다">—</span>
                          )}
                        </td>
                        <td className={row.loaded === row.expected ? "" : "warn-text"}>
                          {row.loaded} / {row.expected}
                        </td>
                        <td>
                          {row.agg.verdict && row.agg.verdict.status !== "cleared" ? (
                            <span className="warn-text small">{row.agg.verdict.status}</span>
                          ) : (
                            <span className="muted small">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ComplianceGate>
          )}

          {view.skipped.length > 0 && (
            <section style={{ marginTop: 22 }}>
              <h2 className="muted" style={{ fontSize: 15 }}>제외된 선거구 {view.skipped.length}곳</h2>
              <ul className="skipped-list">
                {view.skipped.map((s) => (
                  <li key={s.district_id}>
                    <strong>{s.district_name}</strong>
                    <span className="muted small">{s.reason}</span>
                    <p className="num small">{s.fix}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
