import { useEffect, useState } from "react";
import { fetchCycles, ApiError } from "../api/client";
import type { CyclesApiResponse, CycleRow } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

/** **캠프는 영속이고 선거가 그 안에서 바뀐다** (P-001 §7). 지금 보는 주기는
 * 캠프가 고르는 게 아니라 선거일이 정한다 — `current` 플래그가 그것을 말한다.
 * `/cycles/new`·`/cycles/{id}/edit` 는 동 이름 shuttle 을 쓰는 폼이라 아직 Jinja다
 * (온보딩과 함께 옮길 예정) — 이 화면의 링크는 그리로 그냥 풀 페이지 이동한다. */
export function CyclesPage() {
  const [data, setData] = useState<CyclesApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCycles()
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
      <Sidebar active="cycles" lens={data.lens} authOn={data.auth_on} account={data.account} />

      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />

        <div className="content">
          <div className="page-head">
            <div><h1>선거 주기</h1></div>
          </div>
          <p className="muted small">
            화면은 <strong>아직 안 지난 선거 중 가장 가까운 주기</strong>를 봅니다. 전부
            지났으면 가장 최근에 치른 것을 봅니다. 주기를 더해도 선거일이 더 뒤라면 지금
            보는 화면은 바뀌지 않습니다.
          </p>

          {data.rows.map((row) => (
            <CycleCard key={row.id} row={row} today={data.today} />
          ))}

          <p><a className="button-link" href="/cycles/new">다음 선거 주기 추가</a></p>
          <p className="muted small">
            주기를 더해도 <strong>기존 주기는 그대로 남습니다.</strong> 지난 주기의 설정은
            여기서 계속 볼 수 있습니다 — 다만 지난 주기의 관점으로 분석 화면을 다시 그리는
            기능은 아직 없습니다.
          </p>
        </div>
      </div>
    </div>
  );
}

function CycleCard({ row, today }: { row: CycleRow; today: string }) {
  return (
    <article className={`cycle ${row.current ? "cycle--current" : ""}`}>
      <header>
        <strong>{row.id}</strong>
        {row.current && <span className="tag tag--ours">지금 보는 주기</span>}
        <span className="spacer" />
        <a href={`/cycles/${row.id}/edit`}>주기 수정</a>
        <a href={`/cycles/${row.id}/roster`}>후보 로스터</a>
      </header>

      {row.error || !row.cycle ? (
        <div className="banner banner--blocked">
          <strong>이 주기의 설정이 깨져 있다</strong>
          <pre className="errdetail">{row.error}</pre>
          <p className="muted small">고치기 전까지 이 주기는 화면에 뜨지 않습니다. 운영자에게 알리십시오.</p>
        </div>
      ) : (
        <dl className="kv">
          <dt>선거</dt>
          <dd>{row.cycle.election.type} · {row.cycle.election.office}</dd>
          <dt>선거일</dt>
          <dd>
            {row.cycle.election.date ? (
              <>
                {row.cycle.election.date}{" "}
                <span className="muted small">
                  {row.cycle.election.date >= today ? "(예정)" : "(지난 선거)"}
                </span>
              </>
            ) : (
              <>
                <span className="warn-text">미정</span>{" "}
                <span className="muted small">
                  — 선거일을 모르면 공표 금지기간(§108) 같은 기간 판정을 계산할 수 없어 그
                  산출물들이 전부 미검토로 떨어집니다. 정해지면{" "}
                  <code>cycles/{row.id}/election.yaml</code> 을 고치도록 운영자에게 알리십시오.
                </span>
              </>
            )}
          </dd>
          <dt>진영</dt>
          <dd>{row.cycle.lineage}</dd>
          <dt>관할</dt>
          <dd>
            {row.cycle.territory.emd_codes.length}개 동
            {row.cycle.territory.preset && (
              <span className="muted small"> (프리셋 {row.cycle.territory.preset})</span>
            )}
          </dd>
          <dt>법률 검토자</dt>
          <dd>{row.cycle.legal_reviewer || <span className="muted">미지정</span>}</dd>
          {row.roster && (
            <>
              <dt>후보</dt>
              <dd>
                {row.roster.ours.name} ({row.roster.ours.party})
                {row.roster.opponents.length > 0 ? (
                  <span className="muted"> · 상대 {row.roster.opponents.length}명</span>
                ) : (
                  <span className="muted"> · 상대 미등록</span>
                )}
              </dd>
            </>
          )}
        </dl>
      )}
    </article>
  );
}
