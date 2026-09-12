import { Icon } from "./Icon";

interface Props {
  electionTypes: [string, string][];
  electionType: string;
  districts: [string, string][];
  districtId?: string;
  authOn: boolean;
  onElectionTypeChange: (value: string) => void;
}

/** 계열/선거구 전환 + 알림(장식). et-switch/district-switch 는 Jinja 시절과 같은
 * 목적 — 서버 재요청(location 이동)으로 화면을 바꾼다. `districtId` 가 없으면(비교·
 * 전국처럼 "지금 이 선거구"가 없는 화면) 선거구 전환 select 를 안 그린다 —
 * 옛 base.html 의 `{% if district_id and districts|length > 1 %}` 와 같은 판단. */
export function TopBar({
  electionTypes,
  electionType,
  districts,
  districtId,
  authOn,
  onElectionTypeChange,
}: Props) {
  return (
    <div className="topbar">
      {electionTypes.length > 0 && (
        <select
          className="pill-select"
          aria-label="선거 계열 선택"
          value={electionType}
          onChange={(e) => onElectionTypeChange(e.target.value)}
        >
          {electionTypes.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      )}
      {districtId && districts.length > 1 && (
        <select
          className="pill-select"
          aria-label="선거구 선택"
          value={districtId}
          onChange={(e) => {
            if (e.target.value) window.location.href = `/d/${e.target.value}/`;
          }}
        >
          {districts.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      )}
      <span className="spacer" />
      {authOn && (
        <span className="bell" title="알림 기능 준비 중">
          <Icon name="bell" size={18} />
        </span>
      )}
    </div>
  );
}
