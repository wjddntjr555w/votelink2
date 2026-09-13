import { useEffect, useRef, useState } from "react";
import {
  fetchOpsNewsParties,
  addNewsParty,
  renameNewsParty,
  deleteNewsParty,
  fetchNewsCollectJobs,
  collectAllNews,
  collectDistrictNews,
  collectDistrictCandidatesNews,
  ApiError,
} from "../api/client";
import type { OpsNewsPartiesApiResponse, NewsParty, NewsCollectJob } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

const JOB_STATUS_LABEL: Record<string, string> = { running: "실행중", done: "완료", failed: "실패" };
const JOB_POLL_MS = 3000;

/** 뉴스 검색용 정당명 전역 목록. 캠프 단위가 아니라 모든 지역구가 공유하는 하나의
 * 목록이다 — 개수 제한 없이 추가·수정·삭제한다. 판단 근거가 없는 단순 문자열
 * 리스트라 `party_lineage.yaml` 과 달리 일반 CRUD 로 관리한다(P-006 §5). */
export function OpsNewsPartiesPage() {
  const [data, setData] = useState<OpsNewsPartiesApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [jobs, setJobs] = useState<NewsCollectJob[]>([]);
  const [selectedDistrict, setSelectedDistrict] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = () => {
    fetchOpsNewsParties()
      .then((d) => {
        setData(d);
        setSelectedDistrict((prev) => prev || d.districts[0] || "");
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  };

  const loadJobs = () => {
    fetchNewsCollectJobs()
      .then((d) => setJobs(d.jobs))
      .catch(() => {});
  };

  useEffect(load, []);
  useEffect(loadJobs, []);

  // 실행 중인 작업이 있는 동안만 폴링한다 — 다 끝났으면 화면이 조용해야 한다.
  useEffect(() => {
    const hasRunning = jobs.some((j) => j.status === "running");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(loadJobs, JOB_POLL_MS);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [jobs]);

  const after = (result: { ok: true; message?: string } | { error: string }) => {
    if ("error" in result) {
      setError(result.error);
      setMessage(null);
    } else {
      setMessage(result.message ?? "완료했다");
      setError(null);
      load();
    }
  };

  const afterCollect = (result: { ok: true; message?: string } | { error: string }) => {
    after(result);
    loadJobs();
  };

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
      <Sidebar active="news-parties" lens={null} authOn={data.auth_on} account={data.account} />
      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />
        <div className="content">
          <div className="page-head">
            <div>
              <h1>뉴스 검색 정당</h1>
              <p className="muted small">
                여기 등록한 정당명마다 "정당명+지역명", "정당명 단독" 검색어가 모든
                지역구의 뉴스 수집에 자동으로 더해진다. 지역과 무관한 기사는 지역 스코프
                필터를 통과하지 못해 저장되지 않는다.
              </p>
            </div>
          </div>

          {message && <div className="banner banner--note"><strong>{message}</strong></div>}
          {error && <div className="banner banner--blocked"><strong>{error}</strong></div>}

          <section className="ops-block">
            <h2>수집 실행</h2>
            <p className="muted small">
              지금은 이 버튼으로 수동 실행한다. 나중에 cron 으로 자동화할 예정이지만
              그때도 이 버튼은 남는다 — 자동 실행을 기다리지 않고 즉시 돌려야 할 때가 있다.
            </p>

            <form
              className="form--inline"
              onSubmit={async (e) => {
                e.preventDefault();
                afterCollect(await collectAllNews());
              }}
            >
              <button
                type="submit"
                disabled={jobs.some((j) => j.status === "running" && j.args.includes("--all-districts"))}
              >
                전체 지역구 수집
              </button>
            </form>

            <form
              className="form--inline"
              onSubmit={async (e) => {
                e.preventDefault();
                afterCollect(await collectDistrictNews(selectedDistrict));
              }}
            >
              <label>
                지역구
                <select value={selectedDistrict} onChange={(e) => setSelectedDistrict(e.target.value)}>
                  {data.districts.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </label>
              <button type="submit" disabled={!selectedDistrict}>
                이 지역구만 수집
              </button>
            </form>

            <form
              className="form--inline"
              onSubmit={async (e) => {
                e.preventDefault();
                afterCollect(await collectDistrictCandidatesNews(selectedDistrict));
              }}
            >
              <button type="submit" disabled={!selectedDistrict}>
                이 지역구 후보 뉴스만 재수집
              </button>
              <span className="muted small">
                지명·정당 검색어는 건너뛰고 후보·상대후보 검색어만 돈다 — 로스터를
                막 갱신했을 때 전체를 다시 안 돌리고 빠르게 보충하는 용도다.
              </span>
            </form>

            {jobs.length === 0 ? (
              <p className="muted small" style={{ marginTop: 14 }}>실행 이력이 없다.</p>
            ) : (
              <div className="tablewrap" style={{ marginTop: 14 }}>
                <table className="ops">
                  <thead>
                    <tr><th>대상</th><th>상태</th><th>시작</th><th>종료</th><th>종료 코드</th></tr>
                  </thead>
                  <tbody>
                    {jobs.map((j) => (
                      <tr key={j.id}>
                        <td className="muted small">{j.note ?? (j.args.join(" ") || j.target)}</td>
                        <td>
                          <span className={j.status === "failed" ? "warn-text" : ""}>
                            {JOB_STATUS_LABEL[j.status] ?? j.status}
                          </span>
                        </td>
                        <td className="muted small nowrap">{j.started_at}</td>
                        <td className="muted small nowrap">{j.finished_at ?? "—"}</td>
                        <td className="muted small">{j.exit_code ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted small">
                  로그 본문은 여기 표시하지 않는다 — 수집기가 URL 에 API 키를 붙이면
                  로그 파일에 그대로 남을 수 있다. 상세 로그는 서버의{" "}
                  <code>data/logs/jobs/</code> 에서 직접 확인한다.
                </p>
              </div>
            )}
          </section>

          <section className="ops-block">
            <h2>정당 <span className="muted">{data.parties.length}개</span></h2>
            <div className="tablewrap">
              <table className="ops">
                <thead>
                  <tr><th>정당명</th><th>조치</th></tr>
                </thead>
                <tbody>
                  {data.parties.map((p) => (
                    <PartyRow key={p.id} party={p} onDone={after} />
                  ))}
                </tbody>
              </table>
            </div>

            <form
              className="form--inline"
              style={{ marginTop: 14 }}
              onSubmit={async (e) => {
                e.preventDefault();
                const result = await addNewsParty(newName);
                setNewName("");
                after(result);
              }}
            >
              <label>
                새 정당명
                <input
                  type="text"
                  value={newName}
                  onChange={(ev) => setNewName(ev.target.value)}
                  required
                />
              </label>
              <button type="submit">추가</button>
            </form>
          </section>
        </div>
      </div>
    </div>
  );
}

function PartyRow({
  party,
  onDone,
}: {
  party: NewsParty;
  onDone: (r: { ok: true; message?: string } | { error: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(party.name);

  return (
    <tr>
      <td>
        {editing ? (
          <form
            className="form--inline ops-actions"
            onSubmit={async (e) => {
              e.preventDefault();
              onDone(await renameNewsParty(party.id, name));
              setEditing(false);
            }}
          >
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
            <button type="submit">저장</button>
            <button type="button" className="linkish" onClick={() => { setName(party.name); setEditing(false); }}>
              취소
            </button>
          </form>
        ) : (
          party.name
        )}
      </td>
      <td className="ops-actions">
        {!editing && (
          <>
            <button type="button" className="linkish" onClick={() => setEditing(true)}>
              수정
            </button>
            <button
              type="button"
              className="linkish danger"
              onClick={async () => onDone(await deleteNewsParty(party.id))}
            >
              삭제
            </button>
          </>
        )}
      </td>
    </tr>
  );
}
