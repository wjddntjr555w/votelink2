import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchOpsAudit } from "../api/client";
import type { OpsAuditApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

/** 접근 이력. **운영자만 본다** — 캠프에게 열지 않기로 했다 (P-003 §5). 화면이
 * 그 한계를 함께 말한다: 캠프당 계정이 1개라 로그는 "이 캠프의 누군가"까지만
 * 말한다. 읽는 사람이 그걸 모르면 로그를 과신한다. */
export function OpsAuditPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const camp = searchParams.get("camp") ?? "";
  const limit = Number(searchParams.get("limit") ?? "200");

  const [data, setData] = useState<OpsAuditApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchOpsAudit({ camp, limit })
      .then(setData)
      .catch(() => setLoadError("알 수 없는 오류가 발생했다"));
  }, [camp, limit]);

  if (loadError) {
    return (
      <div className="shell"><div className="main"><div className="content">
        <div className="banner banner--blocked"><strong>{loadError}</strong></div>
      </div></div></div>
    );
  }
  if (!data) {
    return (
      <div className="shell"><div className="main"><div className="content" style={{ color: "var(--muted)" }}>불러오는 중…</div></div></div>
    );
  }

  return (
    <div className="shell">
      <Sidebar active="audit" lens={null} authOn={data.auth_on} account={data.operator} />
      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />
        <div className="content">
          <div className="page-head"><div><h1>감사 로그</h1></div></div>

          <div className="banner banner--warn">
            <strong>이 로그는 "이 캠프의 누군가"까지만 말한다</strong>
            <p>
              캠프당 계정이 하나이고 캠프원이 공유한다. 캠프 <em>간</em> 경계는 추적되지만 캠프{" "}
              <em>내부</em>의 행위자는 특정되지 않는다. 같은 이유로 시스템은 법률 검토 서명이 그
              사람의 것인지도 보증하지 않는다.
            </p>
          </div>

          <form
            className="form--inline"
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              const next = new URLSearchParams();
              const c = String(form.get("camp") ?? "");
              const l = String(form.get("limit") ?? "");
              if (c) next.set("camp", c);
              if (l) next.set("limit", l);
              setSearchParams(next);
            }}
          >
            <label>
              캠프
              <select name="camp" defaultValue={camp}>
                <option value="">전체</option>
                {data.camps.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label>
              건수
              <input type="number" name="limit" defaultValue={limit} min={1} max={1000} />
            </label>
            <button type="submit">보기</button>
          </form>

          {data.entries.length === 0 ? (
            <p className="muted" style={{ marginTop: 14 }}>기록이 없다.</p>
          ) : (
            <div className="tablewrap" style={{ marginTop: 14 }}>
              <table className="ops">
                <thead>
                  <tr><th>시각</th><th>행위</th><th>계정</th><th>캠프</th><th>대상</th><th>IP</th><th>상세</th></tr>
                </thead>
                <tbody>
                  {data.entries.map((e) => (
                    <tr key={e.id}>
                      <td className="muted small nowrap">{e.at}</td>
                      <td className={e.action === "denied" || e.action === "login_failed" ? "warn-text" : ""}>{e.action}</td>
                      <td className="muted small">{e.account_id ?? "—"}</td>
                      <td>{e.camp_id ? <a href={`/ops/camps/${e.camp_id}`}>{e.camp_id}</a> : <span className="muted">—</span>}</td>
                      <td className="muted small">{e.target ?? "—"}</td>
                      <td className="muted small">{e.ip ?? "—"}</td>
                      <td className="muted small">
                        {Object.entries(e.detail).map(([k, v]) => `${k}=${v}`).join(" · ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small">
                <code>denied</code> 는 <strong>격리가 실제로 막은 순간</strong>이다 — 캠프가 자기
                관할 밖의 화면을 열려 했고 거부됐다. 경쟁 캠프를 함께 받는 제품에서 "유출이
                없었다"를 증명할 수단이 이 줄이다.
              </p>
              <p className="muted small">
                캠프에게는 이 화면을 열지 않는다. 캠프가 자기 공간의 격리를 스스로 확인할 수단이
                없다는 뜻이고, 답은 계약과 운영자의 감사 보고다.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
