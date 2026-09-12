import type { Insight, Lens, Situation } from "../../api/types";

function deltaNode(recentChange: Situation["recent_change"]) {
  if (!recentChange.known) {
    return (
      <span className="gap gap--unknown" title={recentChange.title}>
        {recentChange.text}
      </span>
    );
  }
  const v = recentChange.value ?? 0;
  const cls = v > 0 ? "up" : v < 0 ? "down" : "";
  const arrow = v > 0 ? "↑" : v < 0 ? "↓" : "";
  return (
    <b className={cls}>
      {recentChange.text}%p {arrow}
    </b>
  );
}

/** "현재 판세" Hero — 목업의 콘솔 다크 카드 + 게이지를 그대로 React 컴포넌트로.
 * 큰 숫자만 강조하는 게 아니라 "지금 선거가 어떤 상태인가"를 한 장에 담는다. */
export function SituationHero({
  situation,
  lens,
  insights,
}: {
  situation: Situation;
  lens: Lens | null;
  insights: Insight[];
}) {
  const pct = parseFloat(situation.leading_pct_text);

  return (
    <section className="hero">
      <div>
        <div className="hero__label">현재 판세</div>
        <div className="hero__state">{situation.leading_label}</div>
        <div className="hero__number num">{situation.leading_lead_text}</div>
        <div className="hero__delta">
          최근 조사 대비 {deltaNode(situation.recent_change)} · 최근 조사 기준 진영 간 지지율 격차
        </div>

        {insights.length > 0 && (
          <ul className="hero__points">
            {insights.slice(0, 3).map((insight, i) => (
              <li key={i}>{insight.title}</li>
            ))}
          </ul>
        )}

        {lens && (
          <div className="hero__candidate">
            <div>
              <span>후보</span>
              <b>{lens.label}</b>
            </div>
            <div>
              <span>지지율</span>
              <b className="num">{situation.leading_pct_text}</b>
            </div>
          </div>
        )}
      </div>

      <div className="gauge">
        <div
          className="gauge__ring"
          style={{
            background: `conic-gradient(var(--accent) 0% ${pct}%, var(--console-line) ${pct}% 100%)`,
          }}
        />
        <div className="gauge__hole">
          <strong className="num">{situation.leading_pct_text}</strong>
          {lens && <span>{lens.candidate_name}</span>}
        </div>
      </div>
    </section>
  );
}
