import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import {
  fetchOnboardingForm,
  fetchNewCycleForm,
  saveOnboarding,
  saveNewCycle,
  ApiError,
} from "../api/client";
import type { CycleFormApiResponse, CycleFormValues } from "../api/types";
import { CycleFormFields } from "../components/cycle/CycleFormFields";

const EMPTY_FORM: CycleFormValues = {
  election_type: "",
  office: "",
  election_date: "",
  lineage: "",
  party: "",
  incumbent: "",
  preset: "",
  sigungu: "",
  emd_pick: [],
  emd_codes: "",
  legal_reviewer: "",
};

/** 한 폼이 두 곳에서 쓰인다: 승인 직후의 첫 설정(`/onboarding`)과 다음 선거 주기
 * 추가(`/cycles/new`). 받는 값이 같아서 나누지 않았다 — 관할도 진영도 당적도
 * 주기마다 다시 정한다 (P-001 §7). **관할이 이 폼의 심장이다.** 관할이 틀리면
 * 에러가 나지 않고 그냥 다른 답이 나온다 — P-001 §16 이 가장 위험한 실패로
 * 지목한 자리다. */
export function CycleFormPage() {
  const isOnboarding = useLocation().pathname === "/onboarding";

  const [data, setData] = useState<CycleFormApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<CycleFormValues>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const fetcher = isOnboarding ? fetchOnboardingForm : fetchNewCycleForm;
    fetcher()
      .then((res) => {
        setData(res);
        setForm((f) => ({ ...f, ...res.form }));
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, [isOnboarding]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const save = isOnboarding ? saveOnboarding : saveNewCycle;
    const result = await save(form);
    setBusy(false);
    if ("error" in result) {
      setError(result.error);
      return;
    }
    window.location.href = isOnboarding ? "/" : "/cycles";
  };

  if (loadError) {
    return (
      <div className="auth-page">
        <section className="auth-gate"><div className="banner banner--blocked"><strong>{loadError}</strong></div></section>
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
      <section className="auth-gate" style={{ maxWidth: 640 }}>
        {isOnboarding ? (
          <>
            <h1>캠프 설정</h1>
            <p className="auth-foot">
              한 번만 채우면 됩니다. 다음 선거 때는 주기를 새로 추가합니다 — 캠프는 남고 선거가
              그 안에서 바뀝니다.
            </p>
          </>
        ) : (
          <>
            <h1>선거 주기 추가</h1>
            <p className="auth-foot"><a href="/cycles">&larr; 주기 목록</a></p>
            <p className="auth-foot">
              관할도 진영도 당적도 다시 정합니다. 구청장에 나갔다가 다음엔 시의원에 나갈 수 있고
              당적도 바뀝니다 — 그래서 이 값들이 캠프가 아니라 주기에 붙어 있습니다.{" "}
              <strong>기존 주기는 그대로 남습니다.</strong>
            </p>
          </>
        )}

        {error && (
          <div className="banner banner--blocked">
            <strong>저장하지 않았다</strong>
            <pre className="errdetail">{error}</pre>
          </div>
        )}

        <form className="auth-form" onSubmit={submit}>
          <CycleFormFields form={form} setForm={setForm} options={data} mode="create" />
          <button type="submit" disabled={busy}>{isOnboarding ? "저장하고 시작" : "주기 추가"}</button>
        </form>
      </section>
    </div>
  );
}
