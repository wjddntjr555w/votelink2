import { useState } from "react";
import { signup } from "../api/client";

/** **신청은 가볍게 받는다.** 관할·진영·선거일은 승인 뒤 온보딩에서 받는다 —
 * 캠프가 아직 확정하지 못한 값을 신청서에 억지로 적게 하지 않는다 (P-002 §6). */
export function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [candidateName, setCandidateName] = useState("");
  const [contact, setContact] = useState("");
  const [wantedElection, setWantedElection] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await signup({
      email,
      password,
      candidate_name: candidateName,
      contact,
      wanted_election: wantedElection,
    });
    if ("error" in result) {
      setError(result.error);
      setBusy(false);
      return;
    }
    window.location.href = "/pending";
  };

  return (
    <div className="auth-page">
      <section className="auth-gate">
        <h1>가입 신청</h1>
        <p className="auth-foot">
          운영자가 확인한 뒤 캠프 공간을 엽니다. 승인 전에는 아무 데이터도 보이지 않습니다.
        </p>

        {error && (
          <div className="banner banner--blocked"><strong>{error}</strong></div>
        )}

        <form className="auth-form" onSubmit={submit}>
          <label>
            아이디 <span className="muted small">— 캠프 계정 하나를 캠프원이 함께 씁니다</span>
            <input
              type="text"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="username"
            />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
            />
          </label>
          <label>
            후보 이름
            <input type="text" value={candidateName} onChange={(e) => setCandidateName(e.target.value)} required />
          </label>
          <label>
            연락처
            <input type="text" value={contact} onChange={(e) => setContact(e.target.value)} required />
          </label>
          <label>
            희망 선거 <span className="muted small">— 정해졌다면. 예: 2028 총선 (선택)</span>
            <input type="text" value={wantedElection} onChange={(e) => setWantedElection(e.target.value)} />
          </label>
          <button type="submit" disabled={busy}>신청</button>
        </form>

        <p className="auth-foot">이미 계정이 있다면 <a href="/login">로그인</a>.</p>
      </section>
    </div>
  );
}
