import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { fetchMap, ApiError } from "../api/client";
import type { MapApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { ComplianceGate } from "../components/compliance/ComplianceGate";
import { MapCanvas } from "../components/map/MapCanvas";
import { MapLegend } from "../components/map/MapLegend";

const DEFAULT_METRIC = "gap_district";

export function MapPage() {
  const { districtId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const metric = searchParams.get("metric") ?? DEFAULT_METRIC;
  const electionType = searchParams.get("election_type") ?? "presidential";

  const [data, setData] = useState<MapApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchMap(districtId, { metric, electionType })
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
  }, [districtId, metric, electionType]);

  const handleElectionTypeChange = (value: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("election_type", value);
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

  const { view, map } = data;

  return (
    <div className="shell">
      <Sidebar
        districtId={districtId}
        districtName={view.district_name}
        electionTypeLabel={view.election_type_label}
        active="map"
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
              <div className="eyebrow">{view.election_type_label}</div>
              <h1>{view.district_name} · 지도</h1>
            </div>
          </div>

          {!map.is_real_boundary && (
            // 경계 파일이 없을 때만 뜬다. 파일이 들어오면 자동으로 사라진다.
            <p className="banner banner--note">
              <strong>실제 행정동 경계가 아니다 — 격자 배치다.</strong> 칸은 행정동코드 오름차순이며
              지리적 인접성을 뜻하지 않는다.
            </p>
          )}

          <nav className="map-metric-nav">
            {Object.entries(map.metrics).map(([key, m]) => {
              const next = new URLSearchParams(searchParams);
              next.set("metric", key);
              return (
                <a
                  key={key}
                  className={map.metric.key === key ? "on" : ""}
                  href={`?${next.toString()}`}
                  onClick={(e) => {
                    e.preventDefault();
                    setSearchParams(next);
                  }}
                >
                  {m.label}
                </a>
              );
            })}
          </nav>

          {view.is_empty ? (
            <div className="banner banner--warn">
              <strong>표시할 분석 결과가 없다</strong>
              <p className="num">uv run votelink analyze voter_profile --district {districtId}</p>
            </div>
          ) : (
            <ComplianceGate verdict={map.verdict}>
              <div className="map-wrap">
                <MapCanvas map={map} />
                <MapLegend map={map} />
              </div>
            </ComplianceGate>
          )}
        </div>
      </div>
    </div>
  );
}
