import type { CycleFormOptions, CycleFormValues } from "../../api/types";
import { EmdShuttle } from "./EmdShuttle";

interface Props {
  form: CycleFormValues;
  setForm: (updater: (f: CycleFormValues) => CycleFormValues) => void;
  options: CycleFormOptions;
  mode: "create" | "edit";
  cycleId?: string;
  byOperator?: boolean;
}

/** 주기 폼의 공유 필드셋 — 옛 `onboarding.html`/`cycle_edit.html` 이 거의 같은
 * 마크업이었던 것을 한 컴포넌트로 합쳤다. `mode` 가 다른 건 문구와(생성만 있는)
 * 후보 정당/현직 필드 유무뿐 — 값과 검증은 `CycleForm`(백엔드) 하나가 정한다.
 * `byOperator` 는 운영자 대리 수정(P-005)일 때 참이다 — 캠프 세션이 없는 운영자는
 * `/cycles/{id}/roster` 를 열 수 없으므로 그 자리에 링크 대신 평문을 둔다. */
export function CycleFormFields({ form, setForm, options, mode, cycleId, byOperator }: Props) {
  const set = <K extends keyof CycleFormValues>(key: K, value: CycleFormValues[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  return (
    <>
      <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
        <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>선거</legend>
        <label>
          선거 계열
          <select value={form.election_type} onChange={(e) => set("election_type", e.target.value)} required>
            {options.type_options.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          직위
          <select value={form.office} onChange={(e) => set("office", e.target.value)} required>
            {options.office_options.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          선거일
          <input type="date" value={form.election_date} onChange={(e) => set("election_date", e.target.value)} />
          <span className="muted small">
            {mode === "create" ? (
              <>모르면 비워 둡니다. 임의 날짜로 채우지 않습니다 — 공표 금지기간(§108)처럼 기간에
              의존하는 판정은 이 값 없이 계산할 수 없고, 그런 산출물은 전부 미검토로 떨어집니다.</>
            ) : (
              <>
                <strong>선거일이나 계열을 바꾸면 주기 폴더 이름도 함께 바뀝니다</strong>
                (<code>{cycleId}</code> 는 선거일과 계열에서 나온 이름입니다). 법률 검토 기록과
                이 주기의 레코드가 폴더를 따라 함께 옮겨갑니다.
              </>
            )}
          </span>
        </label>
      </fieldset>

      <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
        <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>
          {mode === "create" ? "우리 후보" : "진영"}
        </legend>
        <label>
          {mode === "create" ? "진영" : "우리 진영"}
          <select value={form.lineage} onChange={(e) => set("lineage", e.target.value)} required>
            {options.lineage_options.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <span className="muted small">
            {mode === "create" ? (
              <>이 한 줄이 렌즈입니다. 공용 데이터의 동별 진영 구성이 그 즉시 우세·열세로 읽힙니다 —
              숫자는 어느 캠프가 보든 같고 읽는 방식만 달라집니다.</>
            ) : (
              <>
                바꾸면 <strong>모든 화면의 우세·열세가 통째로 뒤집힙니다</strong> — 숫자는 그대로이고
                읽는 방식만 달라집니다. 정당은 여기가 아니라{" "}
                {cycleId && !byOperator ? (
                  <a href={`/cycles/${cycleId}/roster`}>후보 로스터</a>
                ) : (
                  "후보 로스터"
                )}에 있습니다.
              </>
            )}
          </span>
        </label>
        {mode === "create" && (
          <>
            <label>
              정당
              <input type="text" value={form.party} onChange={(e) => set("party", e.target.value)} required />
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input
                type="checkbox"
                checked={form.incumbent === "1"}
                onChange={(e) => set("incumbent", e.target.checked ? "1" : "")}
                style={{ width: "auto" }}
              />
              현직입니다
            </label>
          </>
        )}
      </fieldset>

      <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
        <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>관할</legend>
        <p className="muted small">
          {mode === "create" ? (
            <>셋을 함께 쓸 수 있습니다. 프리셋으로 채운 뒤 몇 개를 더 붙이는 식입니다. 기초의원
            선거구(가·나·다)처럼 프리셋이 없는 경우는 직접 입력만으로 만듭니다.</>
          ) : (
            <>지금 저장된 관할이 아래 <strong>선택된 관할</strong>에 그대로 들어 있습니다. 동을
            빼려면 오른쪽에서 체크 해제 → 제거. 프리셋·자치구를 새로 고르거나 코드를 직접 넣으면{" "}
            <strong>선택된 것에 더해집니다</strong> (P-005 §9).</>
          )}
        </p>
        <label>
          선거구 프리셋
          <select value={form.preset} onChange={(e) => set("preset", e.target.value)}>
            <option value="">(쓰지 않음)</option>
            {options.presets.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          {mode === "edit" && form.preset && (
            <span className="muted small">
              프리셋이 걸려 있으면 그 프리셋의 동은 저장할 때 다시 들어옵니다 — 개별로만 관리하려면{" "}
              <strong>(쓰지 않음)</strong>으로 바꾸십시오.
            </span>
          )}
        </label>
        <label>
          자치구 전체
          <select value={form.sigungu} onChange={(e) => set("sigungu", e.target.value)}>
            <option value="">(쓰지 않음)</option>
            {options.sigungus.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          {mode === "create" && <span className="muted small">구청장처럼 선거구 여럿을 아우르는 경우입니다.</span>}
        </label>

        <EmdShuttle
          emdGroups={options.emd_groups}
          selected={form.emd_pick}
          onChange={(codes) => set("emd_pick", codes)}
        />

        <label>
          행정동코드 직접 입력
          <textarea
            rows={4}
            value={form.emd_codes}
            onChange={(e) => set("emd_codes", e.target.value)}
            placeholder="1171051000 1171052000 …"
            style={{ resize: "vertical", fontFamily: "var(--font-mono)", padding: "8px 10px", border: "1px solid var(--line)", borderRadius: 6, background: "var(--paper)", color: "var(--ink)" }}
          />
          <span className="muted small">
            줄바꿈·쉼표·공백 아무거나로 구분합니다. <code>uv run votelink district list --emd</code> 의
            코드와 같아야 합니다. 위 목록에 없는 동(코드 미확인)은 여기에 넣습니다.
          </span>
        </label>
      </fieldset>

      <fieldset style={{ border: "1px solid var(--line)", borderRadius: 6, padding: "12px 14px" }}>
        <legend style={{ padding: "0 6px", fontSize: 12, color: "var(--muted)" }}>법률 검토</legend>
        <label>
          검토자 {mode === "create" && <span className="muted small">(선택)</span>}
          <input
            type="text"
            value={form.legal_reviewer}
            onChange={(e) => set("legal_reviewer", e.target.value)}
          />
          <span className="muted small">
            산출물 검토 서명의 주체가 됩니다. <strong>시스템은 이 서명을 보증하지 않습니다</strong> —
            캠프당 계정이 하나라 그 이름이 그 사람인지 확인할 수 없습니다. 최종 판단자는 캠프의
            법률 검토입니다.
          </span>
        </label>
      </fieldset>
    </>
  );
}
