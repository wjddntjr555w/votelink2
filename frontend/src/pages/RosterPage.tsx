import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchRoster, saveRoster, ApiError } from "../api/client";
import type { RosterApiResponse } from "../api/types";

/** 후보 로스터 — 관할과 달리 **틀려도 분석을 바꾸지 않는다**(화면 표기에만 쓰이고
 * 진영별 집계는 party_lineage.yaml 이 한다), 그래서 확인 단계가 없다. */
export function RosterPage() {
  const { cycleId = "" } = useParams();

  const [data, setData] = useState<RosterApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [oursName, setOursName] = useState("");
  const [oursParty, setOursParty] = useState("");
  const [oursLineage, setOursLineage] = useState("");
  const [oursIncumbent, setOursIncumbent] = useState(false);
  const [opponents, setOpponents] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchRoster(cycleId)
      .then((res) => {
        setData(res);
        setOursName(res.form.ours_name);
        setOursParty(res.form.ours_party);
        setOursLineage(res.form.ours_lineage);
        setOursIncumbent(res.form.ours_incumbent);
        setOpponents(res.form.opponents);
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, [cycleId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    const result = await saveRoster(cycleId, {
      ours_name: oursName,
      ours_party: oursParty,
      ours_lineage: oursLineage,
      ours_incumbent: oursIncumbent,
      opponents,
    });
    setBusy(false);
    if ("error" in result) {
      setFormError(result.error);
      return;
    }
    window.location.href = "/cycles";
  };

  if (loadError) {
    return (
      <div className="auth-page">
        <section className="auth-gate">
          <div className="banner banner--blocked"><strong>{loadError}</strong></div>
        </section>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="auth-page">
        <section className="auth-gate" style={{ color: "var(--muted)" }}>불러오는 중…</section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="auth-gate" style={{ maxWidth: 560 }}>
        <h1>후보 로스터</h1>
        <p className="auth-foot">
          <a href="/cycles">&larr; 주기 목록</a> · <code>{cycleId}</code>
        </p>

        <div className="banner banner--warn">
          <strong>공개 출처 필드만 적습니다</strong>
          <p>
            선관위 후보자정보·언론 보도로 확인 가능한 것에 한합니다. 사적 정보와 미확인
            소문은 어떤 경우에도 넣지 않습니다. 후보는 공인이고 공개된 공적 기록에 한해
            허용됩니다 — 유권자 개인 정보와는 다른 축입니다.
          </p>
        </div>

        {formError && (
          <div className="banner banner--blocked">
            <strong>저장하지 않았다</strong>
            <pre className="errdetail">{formError}</pre>
          </div>
        )}

        <form className="auth-form" onSubmit={submit}>
          <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
            <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>우리 후보</legend>
            <label>
              이름
              <input type="text" value={oursName} onChange={(e) => setOursName(e.target.value)} required />
            </label>
            <label>
              정당
              <input type="text" value={oursParty} onChange={(e) => setOursParty(e.target.value)} required />
            </label>
            <label>
              진영
              <select value={oursLineage} onChange={(e) => setOursLineage(e.target.value)} required>
                <option value="" disabled>선택</option>
                {data.lineage_options.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input
                type="checkbox"
                checked={oursIncumbent}
                onChange={(e) => setOursIncumbent(e.target.checked)}
                style={{ width: "auto" }}
              />
              현직입니다
            </label>
          </fieldset>

          <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
            <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>상대 후보</legend>
            <label>
              한 줄에 한 명
              <textarea
                rows={8}
                value={opponents}
                onChange={(e) => setOpponents(e.target.value)}
                placeholder={
                  "김철수 | 국민의힘 | 보수 | 현직\n이영희 | 무소속 | 중도 | | 경선 불복 탈당. 계보는 보수이나 중도 표방."
                }
                style={{ resize: "vertical", fontFamily: "var(--font-mono)", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 6, background: "var(--paper)", color: "var(--ink)" }}
              />
              <span className="muted small">
                형식: <code>이름 | 정당 | 진영 | 현직 | 비고</code> — 뒤 둘은 생략할 수 있습니다. 진영은{" "}
                <code>진보 · 보수 · 중도 · 기타</code> (영문 값도 됩니다). 빈 줄과 <code>#</code> 로
                시작하는 줄은 건너뜁니다. <strong>후보 확정 전이면 비워 두어도 됩니다.</strong>
              </span>
            </label>
            <p className="muted small">
              무소속·신당은 진영이 자명하지 않습니다. <strong>근거를 비고에 적고 손으로
              정하십시오.</strong> 미기입을 기타로 자동 강등하지 않습니다 — 조용히 떨어뜨리면
              '분류 누락'과 '실제 군소후보'를 구분할 수 없게 됩니다.
            </p>
          </fieldset>

          <button type="submit" disabled={busy}>저장</button>
        </form>
      </section>
    </div>
  );
}
