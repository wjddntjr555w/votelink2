import type { CandidateMentionCard, PulseCard, Verdict } from "../../api/types";
import { campColor } from "../../design-system/campColor";

function shows(verdict: Verdict | null | undefined): boolean {
  return !!verdict && verdict.status !== "blocked";
}

/** news_pulse 의 선거구 전체 주간 기사량(배경) 위에 candidate_mention_share
 * 우리 후보의 주간 언급 건수(전경)를 같은 축·같은 최댓값 기준으로 겹친다 —
 * "뉴스 자체가 늘어난 건지, 우리 노출만 늘어난 건지"를 가른다.
 *
 * 두 분석기의 window(주 그리드)가 각자의 "가장 최근 기사" 기준으로 따로
 * 계산되므로 완전히 같은 주 집합이라는 보장이 없다 — week_start 문자열로
 * 맞춰 읽고, 어느 한쪽에 없는 주는 0으로 둔다(그 주에 해당 집계가 없다는
 * 뜻이지 실제 0건이라는 뜻은 아닐 수 있어 막대에 표시하지 않는 대신
 * 옅게 표시한다는 수준까지는 이번에 하지 않는다 — 두 분석기 모두 같은
 * naver_news 원천·같은 sigungu 라 실제로는 거의 항상 같은 그리드가 나온다).
 */
export function NewsVolumeOverlayCard({
  pulse,
  candidateMentions,
}: {
  pulse: PulseCard | null;
  candidateMentions: CandidateMentionCard | null;
}) {
  if (!pulse || !candidateMentions) {
    return null;
  }
  if (!shows(pulse.verdict) || !shows(candidateMentions.verdict)) {
    return null;
  }
  const ours = candidateMentions.candidates.find((c) => c.is_ours);
  if (!ours) {
    return null;
  }

  const oursByWeek = new Map(ours.bars.map((b) => [b.week_start, b.count]));
  const peak = Math.max(1, ...pulse.bars.map((b) => b.count));
  const oursColor = campColor(ours.lineage);

  return (
    <section className="panel">
      <h2>선거구 뉴스량 대비 {ours.name} 노출</h2>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        선거구 전체 뉴스량(회색) 위에 {ours.name} 언급 건수(진영색)를 같은 축에 겹친다.
      </p>
      <div style={{ display: "flex", gap: 3, height: 64, alignItems: "flex-end" }}>
        {pulse.bars.map((b) => {
          const oursCount = oursByWeek.get(b.week_start) ?? 0;
          return (
            <div
              key={b.week_start}
              title={`${b.week_start} — 선거구 전체 ${b.count}건 · ${ours.name} ${oursCount}건`}
              style={{ flex: 1, display: "flex", gap: 1, height: "100%", alignItems: "flex-end" }}
            >
              <span
                style={{
                  flex: 1,
                  minHeight: 1,
                  height: `${(b.count / peak) * 100}%`,
                  background: "var(--muted)",
                  opacity: 0.35,
                  borderRadius: "1px 1px 0 0",
                }}
              />
              <span
                style={{
                  flex: 1,
                  minHeight: 1,
                  height: `${(oursCount / peak) * 100}%`,
                  background: oursColor,
                  borderRadius: "1px 1px 0 0",
                }}
              />
            </div>
          );
        })}
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "6px 0 0" }}>
        <span
          style={{
            display: "inline-block",
            width: 10,
            height: 10,
            background: "var(--muted)",
            opacity: 0.35,
            marginRight: 4,
            verticalAlign: "middle",
          }}
        />
        선거구 전체 뉴스
        <span
          style={{
            display: "inline-block",
            width: 10,
            height: 10,
            background: oursColor,
            marginLeft: 12,
            marginRight: 4,
            verticalAlign: "middle",
          }}
        />
        {ours.name} 언급
      </p>
    </section>
  );
}
