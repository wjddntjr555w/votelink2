import { useEffect, useState } from "react";
import { fetchMe, changePassword, ApiError } from "../api/client";
import type { MeApiResponse } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";

/** 로그인만 했으면 누구나 여는 화면 — 승인 대기든 온보딩 전이든 운영자든.
 * 자기 비밀번호를 바꾸는 일은 계정 상태와 무관하다. **산출물은 없다** —
 * 계정 정보뿐이라 참조 데이터도 읽지 않는다(대시보드용 districtId 를 안 넘긴다). */
export function MePage() {
  const [data, setData] = useState<MeApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => {
    fetchMe()
      .then((res) => setData(res))
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  };

  useEffect(load, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    setOk(false);
    const result = await changePassword(current, next, confirm);
    setBusy(false);
    if ("error" in result) {
      setFormError(result.error);
      return;
    }
    setCurrent("");
    setNext("");
    setConfirm("");
    setOk(true);
    load(); // 세션 수(다른 기기 로그아웃됨)를 새로 반영한다.
  };

  if (loadError) {
    return (
      <div className="shell">
        <div className="main">
          <div className="content">
            <div className="banner banner--blocked">
              <strong>화면을 불러오지 못했다</strong>
              <p>{loadError}</p>
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

  const { account } = data;

  return (
    <div className="shell">
      <Sidebar active="me" lens={null} authOn={data.auth_on} account={{ email: account.email, is_operator: account.is_operator }} />

      <div className="main">
        <TopBar electionTypes={[]} electionType="" districts={[]} authOn={data.auth_on} onElectionTypeChange={() => {}} />

        <div className="content">
          <div className="page-head">
            <div><h1>내 계정</h1></div>
          </div>

          {data.bootstrap && account.is_operator && (
            <div className="banner banner--blocked">
              <strong>배포 기본 비밀번호를 그대로 쓰고 있습니다</strong>
              <p>
                아는 비밀번호가 서버에 있으면 인증이 없는 것과 같습니다. 바꾸기 전까지 이
                서버는 <code>127.0.0.1</code> 밖으로 열리지 않습니다.
              </p>
            </div>
          )}

          {ok && (
            <div className="banner banner--note">
              <strong>비밀번호를 바꿨습니다</strong>
              <p>다른 기기의 로그인은 전부 끊겼습니다. 이 창은 그대로 쓰시면 됩니다.</p>
            </div>
          )}

          {formError && (
            <div className="banner banner--blocked"><strong>{formError}</strong></div>
          )}

          <dl className="news-summary" style={{ flexDirection: "column", gap: 8 }}>
            <div><dt>아이디</dt><dd>{account.email}</dd></div>
            <div><dt>역할</dt><dd>{account.is_operator ? "운영자" : "캠프"}</dd></div>
            {account.camp_id && (
              <div><dt>캠프</dt><dd className="num">{account.camp_id}</dd></div>
            )}
            <div><dt>가입</dt><dd>{account.created_at}</dd></div>
            <div><dt>마지막 로그인</dt><dd>{account.last_login_at ?? "없음"}</dd></div>
            <div><dt>지금 열린 로그인</dt><dd>{data.sessions}개</dd></div>
          </dl>

          <h2 style={{ fontSize: 16, margin: "20px 0 10px" }}>비밀번호 변경</h2>
          <form className="auth-form" onSubmit={submit} style={{ maxWidth: 360 }}>
            <label>
              지금 쓰는 비밀번호
              <input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
                autoComplete="current-password"
              />
            </label>
            <label>
              새 비밀번호
              <input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
                autoComplete="new-password"
              />
            </label>
            <label>
              새 비밀번호 확인
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
              />
            </label>
            <button type="submit" disabled={busy}>바꾸기</button>
          </form>

          <p className="muted small">
            바꾸면 <strong>다른 기기의 로그인이 전부 끊깁니다.</strong> 비밀번호를 바꾸는
            이유가 유출일 수 있고, 그때 남은 세션을 살려두면 바꾼 의미가 없습니다. 지금
            보고 계신 이 창은 끊기지 않습니다.
          </p>
          {!account.is_operator && (
            <p className="muted small">
              비밀번호를 잊으면 운영자가 임시 비밀번호를 발급합니다 — 메일 발송을 두지 않아
              자가 재설정 통로가 없습니다.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
