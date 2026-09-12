import type { Situation } from "../../api/types";

export function KpiGrid({ situation }: { situation: Situation }) {
  return (
    <section className="kpi-strip">
      <div className="kpi">
        <div className="k-label">투표 의향</div>
        <div className="k-value num">{situation.turnout_text}</div>
      </div>
      <div className="kpi">
        <div className="k-label">최근 변화</div>
        <div className="k-value num">
          {situation.recent_change.text}
          {situation.recent_change.known ? "%p" : ""}
        </div>
      </div>
      <div className="kpi">
        <div className="k-label">주의 지역</div>
        <div className="k-value num">{situation.watch_count}곳</div>
      </div>
      <div className="kpi">
        <div className="k-label">분석 신뢰도</div>
        <div className="k-value num">{situation.avg_confidence_text}</div>
      </div>
    </section>
  );
}
