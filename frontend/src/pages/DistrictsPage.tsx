import { useEffect, useState } from "react";
import { fetchDistricts, ApiError } from "../api/client";
import type { DistrictsApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

/** `/` 는 선거구가 하나뿐이거나(또는 `WebSettings.district_id`) 캠프 관할이 하나면
 * `app.py::index` 가 이미 그 선거구로 302 를 보낸다 — 이 화면은 여럿일 때만 뜬다. */
export function DistrictsPage() {
  const [data, setData] = useState<DistrictsApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDistricts()
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, []);

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

  return (
    <div className="shell">
      <Sidebar active="districts" lens={data.lens} authOn={data.auth_on} account={data.account} />

      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={data.districts} authOn={data.auth_on} onElectionTypeChange={() => {}} />

        <div className="content">
          <div className="page-head">
            <div><h1>선거구를 고르세요</h1></div>
          </div>
          <p className="muted small">
            정의된 선거구가 여럿이라 무엇을 볼지 골라야 한다. 선거구 정의는{" "}
            <code>data/shared/reference/districts.yaml</code> 에 있다.
          </p>

          {data.districts.length > 0 ? (
            <ul className="district-list">
              {data.districts.map(([id, name]) => (
                <li key={id}>
                  <a href={`/d/${id}/`}>{name}</a> <span className="muted small">{id}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="banner banner--warn">
              <strong>정의된 선거구가 없다</strong>
              <p><code>data/shared/reference/districts.yaml</code> 에 선거구를 추가하라.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
