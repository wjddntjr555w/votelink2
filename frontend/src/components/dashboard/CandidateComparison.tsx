import type { CandidateComparison as CandidateComparisonData } from "../../api/types";

/** 후보자 비교 — 있는 데이터(지지율·최근 변화·지역 강세)만. 사진·인지도·호감도는
 * 수집하지 않는 값이라 만들지 않는다. 렌즈+로스터가 둘 다 있을 때만 호출된다. */
export function CandidateComparison({ cc }: { cc: CandidateComparisonData }) {
  return (
    <section className="panel">
      <h2>후보자 비교</h2>
      <div className="compare">
        <div className="side ours">
          <div className="avatar">{cc.ours_name[0]}</div>
          <div>
            <div className="name">
              {cc.ours_name} {cc.ours_party && <span className="party">({cc.ours_party})</span>}
            </div>
            <div className="metric">
              <div className="row">
                <span>지지율</span>
                <span className="num">{cc.support_ours.toFixed(1)}%</span>
              </div>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${cc.support_ours}%`, background: "var(--camp-conservative)" }} />
              </div>
            </div>
            <div className="metric">
              <div className="row">
                <span>최근 변화</span>
                <span className="num">
                  {cc.recent_change_ours.text}
                  {cc.recent_change_ours.known ? "%p" : ""}
                </span>
              </div>
            </div>
            <div className="metric">
              <div className="row">
                <span>지역 강세</span>
                <span className="num">{cc.strong_regions_ours}곳</span>
              </div>
            </div>
          </div>
        </div>

        <span className="vs">VS</span>

        <div className="side theirs">
          <div>
            <div className="name" style={{ textAlign: "right" }}>
              {cc.theirs_name}
            </div>
            <div className="metric">
              <div className="row">
                <span>지지율</span>
                <span className="num">{cc.support_theirs.toFixed(1)}%</span>
              </div>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${cc.support_theirs}%`, background: "var(--muted)" }} />
              </div>
            </div>
            <div className="metric">
              <div className="row">
                <span>최근 변화</span>
                <span className="num" style={{ color: "var(--muted)" }} title="상대는 우리 진영을 뺀 전부라 개별 진영 변화를 정확히 가를 수 없다">
                  —
                </span>
              </div>
            </div>
            <div className="metric">
              <div className="row">
                <span>지역 강세</span>
                <span className="num">{cc.strong_regions_theirs}곳</span>
              </div>
            </div>
          </div>
          <div className="avatar">{cc.theirs_name[0]}</div>
        </div>
      </div>
      <p className="footnote">
        사진·인지도·호감도는 수집하지 않는 값이라 표시하지 않는다. "상대"는 첫 로스터 등록 상대 후보 기준이다.
      </p>
    </section>
  );
}
