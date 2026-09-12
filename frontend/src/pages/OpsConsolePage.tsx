import { useEffect, useState } from "react";
import {
  fetchOpsConsole,
  approveSignup,
  rejectSignup,
  setAccountStatus,
  forceLogout,
  setAccountPassword,
  ApiError,
} from "../api/client";
import type { OpsConsoleApiResponse, SignupQueueItem, OpsAccountRow } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

const STATUS_LABEL: Record<string, string> = { active: "활성", pending: "대기", suspended: "정지" };

/** 운영자의 홈 — 승인 대기 큐 + 계정 목록. 승인하면 **디스크에 캠프 공간이 생긴다.**
 * 관할·진영·선거일은 여기서 대신 입력하지 않는다 — 캠프가 승인 뒤 직접 채운다. */
export function OpsConsolePage() {
  const [data, setData] = useState<OpsConsoleApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    fetchOpsConsole()
      .then(setData)
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  };

  useEffect(load, []);

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
      <Sidebar active="ops" lens={null} authOn={data.auth_on} account={data.account} />
      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />
        <div className="content">
          <div className="page-head">
            <div>
              <h1>캠프 관리</h1>
              <p className="muted small">
                승인하면 <strong>디스크에 캠프 공간이 생긴다.</strong> 관할·진영·선거일은 캠프가
                승인 뒤 웹에서 직접 채운다 — 여기서 대신 입력하지 않는다.
              </p>
            </div>
          </div>

          {data.bootstrap && (
            <div className="banner banner--blocked">
              <strong>배포 기본 비밀번호를 그대로 쓰고 있습니다</strong>
              <p>아는 비밀번호가 서버에 있으면 인증이 없는 것과 같습니다. 바꾸기 전까지 이 서버는{" "}
                <code>127.0.0.1</code> 밖으로 열리지 않습니다 — <a href="/me">내 계정</a>에서 지금 바꾸십시오.</p>
            </div>
          )}
          {message && <div className="banner banner--note"><strong>{message}</strong></div>}
          {error && <div className="banner banner--blocked"><strong>{error}</strong></div>}

          <section className="ops-block">
            <h2>승인 대기 <span className="muted">{data.queue.length}건</span></h2>
            {data.queue.length === 0 ? (
              <p className="muted">대기 중인 신청이 없다.</p>
            ) : (
              data.queue.map((item) => <QueueItem key={item.id} item={item} onDone={after} />)
            )}
          </section>

          <section className="ops-block">
            <h2>계정 <span className="muted">{data.rows.length}개</span></h2>
            <div className="tablewrap">
              <table className="ops">
                <thead>
                  <tr>
                    <th>id</th><th>이메일</th><th>역할</th><th>캠프</th><th>상태</th>
                    <th>온보딩</th><th>세션</th><th>마지막 로그인</th><th>조치</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <AccountRow key={row.account.id} row={row} self={data.account} onDone={after} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              비밀번호 재발급은 <strong>기존 세션도 함께 끊는다.</strong> 재발급의 이유가 유출일 수
              있고, 그때 남은 세션을 살려두면 재발급이 무의미하다. 메일 발송을 두지 않아 이것이
              비밀번호를 잊은 캠프의 유일한 통로다 — 발급한 값을 캠프에 직접 전달한다.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function QueueItem({
  item,
  onDone,
}: {
  item: SignupQueueItem;
  onDone: (r: { ok: true; message?: string } | { error: string }) => void;
}) {
  const [campId, setCampId] = useState(item.suggested);
  const [approveNote, setApproveNote] = useState("");
  const [rejectNote, setRejectNote] = useState("");

  return (
    <article className="signup">
      <header>
        <strong>{item.candidate_name}</strong>
        <span className="muted">{item.email} · {item.contact}</span>
      </header>
      <dl className="kv">
        {item.wanted_election && <><dt>희망 선거</dt><dd>{item.wanted_election}</dd></>}
        <dt>신청 시각</dt><dd>{item.requested_at}</dd>
      </dl>

      <form
        className="form--inline"
        onSubmit={async (e) => {
          e.preventDefault();
          onDone(await approveSignup(item.id, campId, approveNote));
        }}
      >
        <label>
          camp_id
          <input
            type="text"
            value={campId}
            onChange={(e) => setCampId(e.target.value)}
            pattern="[a-z0-9][a-z0-9\-]*"
            required
          />
          <span className="muted small">
            경로가 된다(<code>data/camps/&lt;id&gt;/</code>). 소문자·숫자·하이픈만.{" "}
            <strong>한 번 정하면 바꾸기 어렵다.</strong>
            {item.taken && <><br /><span className="warn-text">이 id 는 이미 쓰이고 있다. 다른 값을 넣어야 저장된다.</span></>}
          </span>
        </label>
        <label>
          판단 근거 <span className="muted small">(선택)</span>
          <input type="text" value={approveNote} onChange={(e) => setApproveNote(e.target.value)} />
        </label>
        <button type="submit">승인</button>
      </form>

      <form
        className="form--inline"
        onSubmit={async (e) => {
          e.preventDefault();
          onDone(await rejectSignup(item.id, rejectNote));
        }}
      >
        <label>
          거절 사유 <span className="muted small">— 신청자가 무엇을 고쳐야 하는지 알아야 한다</span>
          <input type="text" value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} required />
        </label>
        <button type="submit" className="danger">거절</button>
      </form>
    </article>
  );
}

function AccountRow({
  row,
  self,
  onDone,
}: {
  row: OpsAccountRow;
  self: { email: string; is_operator: boolean };
  onDone: (r: { ok: true; message?: string } | { error: string }) => void;
}) {
  const { account: a, sessions, onboarded } = row;
  const [password, setPassword] = useState("");
  const isSelf = a.email === self.email;

  return (
    <tr>
      <td className="num">{a.id}</td>
      <td>{a.email}</td>
      <td>{a.is_operator ? "운영자" : "캠프"}</td>
      <td>{a.camp_id ? <a href={`/ops/camps/${a.camp_id}`}>{a.camp_id}</a> : <span className="muted">—</span>}</td>
      <td><span className={`tag tag--${a.status}`}>{STATUS_LABEL[a.status] ?? a.status}</span></td>
      <td>
        {a.is_operator ? <span className="muted">해당 없음</span> : onboarded ? "완료" : <span className="warn-text">미완료</span>}
      </td>
      <td className="num">{sessions}</td>
      <td className="muted small">{a.last_login_at ?? "없음"}</td>
      <td className="ops-actions">
        {a.status === "suspended" ? (
          <button type="button" className="linkish" onClick={async () => onDone(await setAccountStatus(a.id, "active"))}>
            정지 해제
          </button>
        ) : (
          !isSelf && (
            <button type="button" className="linkish danger" onClick={async () => onDone(await setAccountStatus(a.id, "suspended"))}>
              정지
            </button>
          )
        )}
        {sessions > 0 && (
          <button type="button" className="linkish" onClick={async () => onDone(await forceLogout(a.id))}>
            세션 끊기
          </button>
        )}
        <form
          className="passwd"
          onSubmit={async (e) => {
            e.preventDefault();
            const result = await setAccountPassword(a.id, password);
            setPassword("");
            onDone(result);
          }}
        >
          <input
            type="password"
            placeholder="임시 비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit" className="linkish">발급</button>
        </form>
      </td>
    </tr>
  );
}
