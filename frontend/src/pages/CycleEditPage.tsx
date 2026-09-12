import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchEditCycleForm, previewCycle, applyCycle, ApiError } from "../api/client";
import type { CycleChange, CycleFormApiResponse, CycleFormValues } from "../api/types";
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

/** 주기 수정. **여기서 바로 저장하지 않는다** — 관할이 틀리면 에러 없이 모든 분석이
 * 조용히 틀리므로(P-001 §16), 폼 → 미리보기(확인) → 저장 두 단계를 거친다. 미리보기는
 * 아무것도 저장하지 않고, URL 도 안 바꾼다 — 한 페이지 안에서 `view` 상태로 전환한다. */
export function CycleEditPage() {
  const { cycleId = "" } = useParams();

  const [data, setData] = useState<CycleFormApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<CycleFormValues>(EMPTY_FORM);
  const [view, setView] = useState<"form" | "preview">("form");
  const [change, setChange] = useState<CycleChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchEditCycleForm(cycleId)
      .then((res) => {
        setData(res);
        setForm((f) => ({ ...f, ...res.form }));
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, [cycleId]);

  const submitPreview = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await previewCycle(cycleId, form);
    setBusy(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    if (!result.change) return;
    if (result.change.is_empty) {
      // 바뀌는 것이 없으면 확인을 물을 이유가 없다 — 옛 Jinja 라우트의 리다이렉트와 같은 판단.
      window.location.href = "/cycles";
      return;
    }
    setChange(result.change);
    setView("preview");
  };

  const confirmApply = async () => {
    setBusy(true);
    setError(null);
    const result = await applyCycle(cycleId, form);
    setBusy(false);
    if ("error" in result) {
      setError(result.error);
      setView("form");
      return;
    }
    window.location.href = "/cycles";
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

  if (view === "preview" && change) {
    return (
      <div className="auth-page">
        <section className="auth-gate" style={{ maxWidth: 640 }}>
          <h1>이대로 저장할까요?</h1>
          <p className="auth-foot"><code>{cycleId}</code> · 아직 아무것도 바뀌지 않았습니다.</p>

          {change.moved && (
            <div className="banner banner--warn">
              <strong>주기 폴더가 옮겨집니다</strong>
              <p><code>{change.cycle_id_before}</code> &rarr; <code>{change.cycle_id_after}</code></p>
              <p style={{ fontSize: 12 }}>
                폴더 이름은 선거일과 계열에서 나온 값이라 함께 바뀝니다. 법률 검토 기록과 이 주기의
                레코드가 폴더를 따라 함께 옮겨갑니다 — 검토는 그 선거에 대한 것이지 폴더 이름에
                대한 것이 아닙니다.
              </p>
            </div>
          )}

          {change.lineage_flipped && (
            <div className="banner banner--warn">
              <strong>진영이 바뀝니다 — 모든 화면의 우세·열세가 뒤집힙니다</strong>
              <p>{change.lineage_before} &rarr; {change.lineage_after}</p>
              <p style={{ fontSize: 12 }}>
                숫자 자체는 그대로입니다. 공용 데이터는 진영 단위로 중립 계산되고, 이 값은 그것을
                "우리 / 상대"로 읽는 방식만 정합니다.
              </p>
            </div>
          )}

          {change.closed.length > 0 && (
            <div className="banner banner--blocked">
              <strong>더 이상 볼 수 없게 되는 선거구</strong>
              <ul>
                {change.closed.map(([did, name]) => (
                  <li key={did}>{name} (<code>{did}</code>)</li>
                ))}
              </ul>
              <p style={{ fontSize: 12 }}>관할 밖이 되므로 저장 뒤에는 이 화면들이 403 으로 막힙니다.</p>
            </div>
          )}

          <dl className="kv">
            {change.date_before !== change.date_after && (
              <>
                <dt>선거일</dt>
                <dd>
                  {change.date_before ?? "미정"} &rarr; <strong>{change.date_after ?? "미정"}</strong>
                  {!change.date_after && (
                    <>
                      <br />
                      <span className="warn-text">
                        미정으로 되돌리면 공표 금지기간(§108) 같은 기간 판정을 계산할 수 없어 그
                        산출물들이 전부 미검토로 떨어집니다.
                      </span>
                    </>
                  )}
                </dd>
              </>
            )}
            {change.type_before !== change.type_after && (
              <>
                <dt>선거 계열</dt>
                <dd>{change.type_before} &rarr; <strong>{change.type_after}</strong></dd>
              </>
            )}
            {change.office_before !== change.office_after && (
              <>
                <dt>직위</dt>
                <dd>{change.office_before} &rarr; <strong>{change.office_after}</strong></dd>
              </>
            )}
            {change.reviewer_before !== change.reviewer_after && (
              <>
                <dt>법률 검토자</dt>
                <dd>{change.reviewer_before || "미지정"} &rarr; <strong>{change.reviewer_after || "미지정"}</strong></dd>
              </>
            )}
            {change.opened.length > 0 && (
              <>
                <dt>열리는 선거구</dt>
                <dd>{change.opened.map(([, name]) => name).join(" · ")}</dd>
              </>
            )}
          </dl>

          {change.territory_changed ? (
            <>
              <h2 style={{ fontSize: 15, margin: "18px 0 8px" }}>
                관할 {change.kept + change.added.length}개 동{" "}
                <span className="muted">(그대로 {change.kept} · 추가 {change.added.length} · 제외 {change.removed.length})</span>
              </h2>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
                {change.added.length > 0 && (
                  <div>
                    <h3 style={{ fontSize: 13, color: "var(--signal-ahead)", margin: "0 0 6px" }}>추가되는 동 {change.added.length}개</h3>
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, maxHeight: 260, overflowY: "auto" }}>
                      {change.added.map((e) => <li key={e.code}>{e.label}</li>)}
                    </ul>
                  </div>
                )}
                {change.removed.length > 0 && (
                  <div>
                    <h3 style={{ fontSize: 13, color: "var(--signal-behind)", margin: "0 0 6px" }}>빠지는 동 {change.removed.length}개</h3>
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, maxHeight: 260, overflowY: "auto" }}>
                      {change.removed.map((e) => <li key={e.code}>{e.label}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            </>
          ) : (
            <p className="muted">관할은 그대로입니다 ({change.kept}개 동).</p>
          )}

          {error && (
            <div className="banner banner--blocked">
              <strong>저장하지 않았다</strong>
              <pre className="errdetail">{error}</pre>
            </div>
          )}

          <div style={{ marginTop: 16 }}>
            <button type="button" onClick={confirmApply} disabled={busy}>이대로 저장</button>
          </div>
          <p className="auth-foot">
            <a href="#" onClick={(e) => { e.preventDefault(); setView("form"); }}>&larr; 돌아가서 고치기</a>
          </p>
        </section>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <section className="auth-gate" style={{ maxWidth: 640 }}>
        <h1>주기 수정</h1>
        <p className="auth-foot"><a href="/cycles">&larr; 주기 목록</a> · <code>{cycleId}</code></p>

        <div className="banner banner--warn">
          <strong>저장하기 전에 무엇이 바뀌는지 보여드립니다</strong>
          <p>
            이 폼을 제출하면 곧바로 저장되지 않고 확인 화면이 뜹니다 — 들고나는 동, 열리고 닫히는
            선거구, 우세·열세가 뒤집히는지를 먼저 보십시오.
          </p>
        </div>

        {error && (
          <div className="banner banner--blocked">
            <strong>저장하지 않았다</strong>
            <pre className="errdetail">{error}</pre>
          </div>
        )}

        <form className="auth-form" onSubmit={submitPreview}>
          <CycleFormFields form={form} setForm={setForm} options={data} mode="edit" cycleId={cycleId} />
          <button type="submit" disabled={busy}>바뀌는 내용 보기</button>
        </form>

        <p className="muted small">
          저장하면 <code>election.yaml</code> 을 다시 씁니다. 표준 주석은 그대로 다시 깔리지만{" "}
          <strong>파일에 손으로 적어둔 메모는 남지 않습니다.</strong>
        </p>
      </section>
    </div>
  );
}
