import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { fetchOpsEditCycleForm, opsPreviewCycle, opsApplyCycle, ApiError } from "../api/client";
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

/** 운영자가 캠프 대신 주기를 고친다 (P-005). **저장 경로는 캠프 쪽과 완전히 같다**
 * — 폼 → 미리보기 → 확인, 새 로직 0. 다른 것은 둘뿐이다: `campId` 를 URL 에서
 * 읽고, 저장할 때 사유를 요구한다(§2 — 거절이 사유 없으면 거부되는 것과 같은
 * 이유). 사유는 감사 로그와 갱신 이력에 남는다. */
export function OpsCycleEditPage() {
  const { campId = "", cycleId = "" } = useParams();

  const [data, setData] = useState<CycleFormApiResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<CycleFormValues>(EMPTY_FORM);
  const [view, setView] = useState<"form" | "preview">("form");
  const [change, setChange] = useState<CycleChange | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchOpsEditCycleForm(campId, cycleId)
      .then((res) => {
        setData(res);
        setForm((f) => ({ ...f, ...res.form }));
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, [campId, cycleId]);

  const submitPreview = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await opsPreviewCycle(campId, cycleId, form);
    setBusy(false);
    if (result.error) {
      setError(result.error);
      return;
    }
    if (!result.change) return;
    if (result.change.is_empty) {
      window.location.href = `/ops/camps/${campId}`;
      return;
    }
    setChange(result.change);
    setView("preview");
  };

  const confirmApply = async () => {
    if (!note.trim()) {
      setError("대신 고치는 사유를 적어야 저장한다.");
      return;
    }
    setBusy(true);
    setError(null);
    const result = await opsApplyCycle(campId, cycleId, { ...form, note });
    setBusy(false);
    if ("error" in result) {
      setError(result.error);
      return;
    }
    window.location.href = `/ops/camps/${campId}`;
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
            </div>
          )}
          {change.lineage_flipped && (
            <div className="banner banner--warn">
              <strong>진영이 바뀝니다 — 모든 화면의 우세·열세가 뒤집힙니다</strong>
              <p>{change.lineage_before} &rarr; {change.lineage_after}</p>
            </div>
          )}
          {change.closed.length > 0 && (
            <div className="banner banner--blocked">
              <strong>더 이상 볼 수 없게 되는 선거구</strong>
              <ul>{change.closed.map(([did, name]) => <li key={did}>{name} (<code>{did}</code>)</li>)}</ul>
            </div>
          )}

          <dl className="kv">
            {change.date_before !== change.date_after && (
              <><dt>선거일</dt><dd>{change.date_before ?? "미정"} &rarr; <strong>{change.date_after ?? "미정"}</strong></dd></>
            )}
            {change.type_before !== change.type_after && (
              <><dt>선거 계열</dt><dd>{change.type_before} &rarr; <strong>{change.type_after}</strong></dd></>
            )}
            {change.office_before !== change.office_after && (
              <><dt>직위</dt><dd>{change.office_before} &rarr; <strong>{change.office_after}</strong></dd></>
            )}
            {change.reviewer_before !== change.reviewer_after && (
              <><dt>법률 검토자</dt><dd>{change.reviewer_before || "미지정"} &rarr; <strong>{change.reviewer_after || "미지정"}</strong></dd></>
            )}
            {change.opened.length > 0 && (
              <><dt>열리는 선거구</dt><dd>{change.opened.map(([, name]) => name).join(" · ")}</dd></>
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
            <div className="banner banner--blocked"><strong>저장하지 않았다</strong><pre className="errdetail">{error}</pre></div>
          )}

          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, marginTop: 14 }}>
            대신 고치는 사유 <span className="muted small">— 감사 로그와 갱신 이력에 남습니다</span>
            <textarea
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              required
              style={{ padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 6, background: "var(--paper)", color: "var(--ink)" }}
            />
          </label>

          <div style={{ marginTop: 12 }}>
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
        <p className="auth-foot"><a href={`/ops/camps/${campId}`}>&larr; {campId} 캠프</a> · <code>{cycleId}</code></p>

        <div className="banner banner--warn">
          <strong>이 캠프의 설정을 운영자가 대신 고치는 중입니다</strong>
          <p>캠프가 알려준 정정만 입력하십시오 — 값을 창작하지 마십시오 (P-005). 저장할 때 사유를 적어야 하고, 그 사유는 감사 로그와 갱신 이력에 남습니다.</p>
        </div>
        <div className="banner banner--warn">
          <strong>저장하기 전에 무엇이 바뀌는지 보여드립니다</strong>
          <p>이 폼을 제출하면 곧바로 저장되지 않고 확인 화면이 뜹니다.</p>
        </div>

        {error && (
          <div className="banner banner--blocked"><strong>저장하지 않았다</strong><pre className="errdetail">{error}</pre></div>
        )}

        <form className="auth-form" onSubmit={submitPreview}>
          <CycleFormFields form={form} setForm={setForm} options={data} mode="edit" cycleId={cycleId} byOperator />
          <button type="submit" disabled={busy}>바뀌는 내용 보기</button>
        </form>
      </section>
    </div>
  );
}
