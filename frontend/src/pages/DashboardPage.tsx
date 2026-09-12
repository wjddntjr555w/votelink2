import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { fetchDashboard, ApiError } from "../api/client";
import type { DashboardResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { ComplianceGate } from "../components/compliance/ComplianceGate";
import { SituationHero } from "../components/dashboard/SituationHero";
import { KpiGrid } from "../components/dashboard/KpiGrid";
import { TrendChart } from "../components/dashboard/TrendChart";
import { CampaignInsights } from "../components/dashboard/CampaignInsights";
import { Watchlist } from "../components/dashboard/Watchlist";
import { RegionalAnalysisTable } from "../components/dashboard/RegionalAnalysisTable";
import { CandidateComparison } from "../components/dashboard/CandidateComparison";
import { DetailAccordion } from "../components/dashboard/DetailAccordion";
import { PulsePanel } from "../components/dashboard/PulsePanel";
import { IssueBoardPanel } from "../components/dashboard/IssueBoardPanel";

export function DashboardPage() {
  const { districtId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const sort = searchParams.get("sort") ?? "code";
  const electionType = searchParams.get("election_type") ?? "presidential";

  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchDashboard(districtId, { sort, electionType })
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
  }, [districtId, sort, electionType]);

  const handleSortChange = useCallback(
    (key: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("sort", key);
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const handleElectionTypeChange = useCallback(
    (value: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("election_type", value);
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

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

  const { view, pulse, issue_board, candidate_comparison } = data;

  return (
    <div className="shell">
      <Sidebar
        districtId={districtId}
        districtName={view.district_name}
        electionTypeLabel={view.election_type_label}
        active="dashboard"
        lens={view.lens}
        authOn={data.auth_on}
        account={data.account}
      />

      <div className="main">
        <TopBar
          electionTypes={data.election_types}
          electionType={electionType}
          districts={data.districts}
          districtId={districtId}
          authOn={data.auth_on}
          onElectionTypeChange={handleElectionTypeChange}
        />

        <div className="content">
          <div className="page-head">
            <div>
              <div className="eyebrow">
                {view.election_type_label}
                {view.latest_election_date && ` · ${view.latest_election_date}`}
              </div>
              <h1>{view.district_name}</h1>
            </div>
            <div className="updated">
              행정동 {view.coverage_text}
              {view.last_updated && (
                <>
                  {" "}
                  · 마지막 업데이트 <span className="num">{view.last_updated}</span>
                </>
              )}
            </div>
          </div>

          {view.lens && (
            <p className="banner banner--lens">
              <strong>{view.lens.label}</strong> 캠프의 관점으로 보고 있다 — {view.lens.lineage} 진영을
              "우리"로 읽는다.
              <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                숫자 자체는 진영 중립으로 계산된 공용 값이며 캠프마다 같다.{" "}
                <strong>"상대"는 우리 진영을 뺀 전부</strong>다 — 중도·기타가 함께 들어간다.
              </span>
            </p>
          )}

          {view.is_empty && (
            <div className="banner banner--warn">
              <strong>{view.election_type_label} 분석 결과가 없다</strong>
              <p>먼저 분석기를 돌린다:</p>
              <p className="num">uv run votelink analyze voter_profile --district {districtId}</p>
              <p style={{ fontSize: 12, color: "var(--muted)" }}>
                선거구 정의는 행정동 {view.diagnostics.expected}곳을 말하는데 읽은 레코드는{" "}
                {view.diagnostics.read}건이다.
              </p>
            </div>
          )}

          {!view.is_empty && (
            <>
              <ComplianceGate verdict={view.verdict}>
                {view.situation && <SituationHero situation={view.situation} lens={view.lens} insights={view.insights} />}
                {view.situation && <KpiGrid situation={view.situation} />}
                <div className="analytics-grid">
                  {view.summary_card && <TrendChart summary={view.summary_card} />}
                  <CampaignInsights insights={view.insights} />
                </div>
                <Watchlist cards={view.watchlist} />
                <RegionalAnalysisTable view={view} onSortChange={handleSortChange} />
                {candidate_comparison && <CandidateComparison cc={candidate_comparison} />}
              </ComplianceGate>

              <ComplianceGate verdict={view.verdict}>
                <DetailAccordion view={view} />
              </ComplianceGate>
            </>
          )}

          {pulse && (
            <ComplianceGate verdict={pulse.verdict}>
              <PulsePanel pulse={pulse} districtId={districtId} />
            </ComplianceGate>
          )}
          {issue_board && (
            <ComplianceGate verdict={issue_board.verdict}>
              <IssueBoardPanel issueBoard={issue_board} districtName={view.district_name} districtId={districtId} />
            </ComplianceGate>
          )}

          <footer className="page-foot">
            <span>산출물의 적법성은 이 시스템이 판정하지 않는다. 최종 판단자는 캠프의 법률 검토다.</span>
            <span className="ok">
              <i /> 시스템 정상 운영
            </span>
          </footer>
        </div>
      </div>
    </div>
  );
}
