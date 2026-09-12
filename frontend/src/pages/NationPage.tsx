import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchNation, ApiError } from "../api/client";
import type { NationApiResponse, NationView } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { ComplianceGate } from "../components/compliance/ComplianceGate";
import { EmdDetailCard } from "../components/dashboard/EmdDetailCard";
import { NationSummaryCard } from "../components/nation/NationSummaryCard";

// is_empty/shown_text 는 백엔드 `NationView` 의 @property 라 JSON에 없다 — 다시 계산한다.
function isEmpty(view: NationView) { return view.cards.length === 0; }
function shownText(view: NationView) { return `표시 ${view.diagnostics.loaded}곳`; }

export function NationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sort = searchParams.get("sort") ?? "code";
  const electionType = searchParams.get("election_type") ?? "presidential";

  const [data, setData] = useState<NationApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchNation({ sort, electionType })
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

  return (
    <div className="shell">
      <Sidebar active="nation" lens={data.lens} authOn={data.auth_on} account={data.account} />

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
              <h1>전국 전체 동</h1>
            </div>
          </div>

          {isEmpty(view) ? (
            <div className="banner banner--warn">
              <strong>{view.election_type_label} 분석 결과가 없다</strong>
              <p className="num">uv run votelink analyze voter_profile</p>
            </div>
          ) : (
            <>
              <dl className="news-summary">
                <div><dt>표시</dt><dd>{shownText(view)}</dd></div>
                <div><dt>총 인구</dt><dd>{view.population_total.toLocaleString()}</dd></div>
                <div><dt>분석 기준월</dt><dd>{view.as_of_months.join(" · ")}</dd></div>
                <div><dt>최근 선거</dt><dd>{view.latest_election_date}</dd></div>
              </dl>
              <p className="muted small">
                출처 {view.source_names.join(" · ")} ({view.source_licenses.join(" · ")})
              </p>
              <p className="muted small">
                읽음 {view.diagnostics.read}건 · 표시 {view.diagnostics.loaded}건
                {view.diagnostics.other_election_type > 0 &&
                  ` · 다른 계열 ${view.diagnostics.other_election_type}건 제외`}
                {view.diagnostics.superseded > 0 &&
                  ` · 이전 기준월 ${view.diagnostics.superseded}건은 표시하지 않았다`}
                {view.diagnostics.rejected > 0 && (
                  <> · <span className="warn-text">계약 위반 {view.diagnostics.rejected}건 격리</span></>
                )}
              </p>
              <p className="muted small">
                선거구 소속 필터를 의도적으로 건너뛴다 — 전국은 선거구 하나가 아니다. 편차는 전국
                대비만 유효하다.
              </p>

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

              <ComplianceGate verdict={view.verdict}>
                {view.summary_card && (
                  <div style={{ marginBottom: 16 }}>
                    <NationSummaryCard card={view.summary_card} gapLabels={view.gap_labels} />
                  </div>
                )}
                <div className="nation-cards">
                  {view.cards.map((c) => (
                    <EmdDetailCard key={c.geo_code} card={c} gapLabels={view.gap_labels} trendNote={view.trend_note} />
                  ))}
                </div>
              </ComplianceGate>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
