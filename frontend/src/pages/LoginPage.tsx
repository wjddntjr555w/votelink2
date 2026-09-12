import { useState } from "react";
import { login } from "../api/client";

/** 공개 화면. **산출물이 없다** — 그래서 이 앱을 인터넷에 열어도 그 자체가
 * 의도치 않은 공표가 되지 않는다 (P-002 §2). 여기에 숫자를 하나라도 올리면
 * 그 근거가 무너진다. */
export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await login(email, password);
    if ("error" in result) {
      setError(result.error);
      setBusy(false);
      return;
    }
    window.location.href = "/";
  };

  return (
    <div className="auth-page">
      <section className="auth-gate">
        <h1>votelink 로그인</h1>

        {error && (
          <div className="banner banner--blocked"><strong>{error}</strong></div>
        )}

        <form className="auth-form" onSubmit={submit}>
          <label>
            {/* type="email" 이 아니다. 운영자 계정의 아이디는 root 처럼 이메일이 아닐 수
                있고, 그러면 브라우저가 제출 자체를 막는다. */}
            이메일 또는 아이디
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
              autoComplete="current-password"
            />
          </label>
          <button type="submit" disabled={busy}>로그인</button>
        </form>

        <p className="auth-foot">
          계정이 없다면 <a href="/signup">가입 신청</a>을 먼저 한다. 운영자 승인 뒤에 캠프
          공간이 열린다.
        </p>
        <p className="auth-foot">
          비밀번호를 잊었다면 운영자에게 임시 비밀번호를 요청한다 — 메일 발송을 두지 않아
          자가 재설정 통로가 없다.
        </p>
      </section>
    </div>
  );
}
