import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchOpsCamp } from "../api/client";
import type { OpsCampApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

const STATUS_LABEL: Record<string, string> = { active: "활성", pending: "대기", suspended: "정지" };

/** 한 캠프의 설정 — `votelink camp show` 의 웹 판. **설정과 메타만 낸다** — 분석
 * 산출물을 올리면 그 순간 verdict 계산이 필요해지고, 운영에 필요한 것은 그게 아니다. */
export function OpsCampPage() {
  const { campId = "" } = useParams();
  const [data, setData] = useState<OpsCampApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchOpsCamp(campId)
      .then(setData)
      .catch(() => setLoadError("알 수 없는 오류가 발생했다"));
  }, [campId]);

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
      <Sidebar active="ops" lens={null} authOn={data.auth_on} account={data.operator} />
      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />
        <div className="content">
          <div className="page-head">
            <div>
              <h1>{campId}{data.info && <span className="muted"> · {data.info.candidate_name}</span>}</h1>
              <p className="muted small"><a href="/ops/">&larr; 캠프 관리</a></p>
            </div>
          </div>

          {data.error ? (
            <div className="banner banner--blocked">
              <strong>캠프 설정을 읽을 수 없다</strong>
              <pre className="errdetail">{data.error}</pre>
            </div>
          ) : (
            <>
              <section className="ops-block">
                <h2>계정</h2>
                {data.account ? (
                  <dl className="kv">
                    <dt>이메일</dt><dd>{data.account.email}</dd>
                    <dt>상태</dt><dd><span className={`tag tag--${data.account.status}`}>{STATUS_LABEL[data.account.status] ?? data.account.status}</span></dd>
                    <dt>마지막 로그인</dt><dd>{data.account.last_login_at ?? "없음"}</dd>
                  </dl>
                ) : (
                  <p className="warn-text">이 캠프에 연결된 계정이 없다. 디스크에 공간만 있고 로그인할 사람이 없는 상태다.</p>
                )}
                <p className="muted small">캠프 생성일 {data.info?.created_at}</p>
              </section>

              <section className="ops-block">
                <h2>선거 주기 <span className="muted">{data.cycles.length}개</span></h2>
                {data.cycles.length === 0 && (
                  <p className="warn-text">
                    온보딩 미완료다. 캠프가 로그인하면 <code>/onboarding</code> 으로 보내진다 —
                    관할을 모르면 무엇을 보여줄지 알 수 없으므로 데이터 화면은 막혀 있다.
                  </p>
                )}
                {data.cycles.map((c) => (
                  <article key={c.id} className="cycle">
                    <header><strong>{c.id}</strong></header>
                    {c.error || !c.cycle ? (
                      <div className="banner banner--blocked">
                        <strong>이 주기의 설정이 깨져 있다</strong>
                        <pre className="errdetail">{c.error}</pre>
                      </div>
                    ) : (
                      <>
                        <dl className="kv">
                          <dt>선거</dt><dd>{c.cycle.election.type} · {c.cycle.election.office}</dd>
                          <dt>선거일</dt>
                          <dd>
                            {c.cycle.election.date ?? (
                              <>
                                <span className="warn-text">미정</span>{" "}
                                <span className="muted small">— 기간에 의존하는 판정이 전부 미검토로 떨어진다</span>
                              </>
                            )}
                          </dd>
                          <dt>진영</dt><dd>{c.cycle.lineage}</dd>
                          <dt>관할</dt>
                          <dd>
                            {c.cycle.territory.emd_codes.length}개 동
                            {c.cycle.territory.preset && <span className="muted small"> (프리셋 {c.cycle.territory.preset})</span>}
                          </dd>
                          <dt>법률 검토자</dt>
                          <dd>{c.cycle.legal_reviewer || <span className="muted">미지정</span>}</dd>
                          {c.roster && (
                            <>
                              <dt>우리 후보</dt>
                              <dd>{c.roster.ours.name} ({c.roster.ours.party})</dd>
                              <dt>상대</dt>
                              <dd>
                                {c.roster.opponents.length > 0 ? (
                                  c.roster.opponents.map((o, i) => (
                                    <span key={o.name}>{i > 0 && " · "}{o.name} ({o.party})</span>
                                  ))
                                ) : (
                                  <span className="muted">아직 없음 — 후보 확정 전이면 비어 있어도 된다</span>
                                )}
                              </dd>
                            </>
                          )}
                        </dl>
                        <p className="muted small">
                          <a href={`/ops/camps/${campId}/cycles/${c.id}/edit`}>이 주기를 대신 수정 &rarr;</a>
                        </p>
                      </>
                    )}
                  </article>
                ))}
              </section>

              <section className="ops-block">
                <h2>최근 이력 <span className="muted">30건</span></h2>
                {data.entries.length === 0 ? (
                  <p className="muted">이 캠프의 기록이 없다.</p>
                ) : (
                  <>
                    <div className="tablewrap">
                      <table className="ops">
                        <thead><tr><th>시각</th><th>행위</th><th>대상</th><th>IP</th></tr></thead>
                        <tbody>
                          {data.entries.map((e) => (
                            <tr key={e.id}>
                              <td className="muted small nowrap">{e.at}</td>
                              <td>{e.action}</td>
                              <td className="muted small">{e.target ?? "—"}</td>
                              <td className="muted small">{e.ip ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="muted small"><a href={`/ops/audit?camp=${campId}`}>전체 이력 보기 &rarr;</a></p>
                  </>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
