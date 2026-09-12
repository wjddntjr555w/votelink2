import type { Insight } from "../../api/types";

/** 이미 계산된 숫자를 문장으로. "AI 분석"이 아니라 규칙 기반 자동 요약이라고
 * 정직하게 표기한다 — LLM이 생성하지 않는다. */
export function CampaignInsights({ insights }: { insights: Insight[] }) {
  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Campaign Insights</h2>
        <span
          className="insight-badge"
          title="이미 계산된 숫자를 규칙으로 문장화한다. LLM이 생성하지 않는다."
        >
          규칙 기반 자동 요약
        </span>
      </div>
      {insights.length > 0 ? (
        <ul className="insight-list">
          {insights.map((insight, i) => (
            <li key={i}>
              <span className={`glyph ${insight.tone === "warn" ? "g-flag" : "g-up"}`}>
                {insight.icon}
              </span>
              <div>
                <h4>{insight.title}</h4>
                <p>{insight.detail}</p>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ marginTop: 14, color: "var(--muted)" }}>지금은 특별히 강조할 변화가 없다.</p>
      )}
    </div>
  );
}
