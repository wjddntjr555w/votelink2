import type { CandidateMentionCard, CandidateMentionSeries } from "../../api/types";
import { BackfillBanner } from "./BackfillBanner";
import { campColor } from "../../design-system/campColor";

function ChangeBadge({ pct }: { pct: number | null }) {
  if (pct === null) {
    return <span style={{ color: "var(--muted)" }}>—</span>;
  }
  const up = pct > 0;
  return (
    <span className={`status-pill ${up ? "watch" : "stable"}`}>
      {up ? "▲" : pct < 0 ? "▼" : "—"} {Math.abs(pct).toFixed(0)}%
    </span>
  );
}

/** 주간 점유율을 100% 기준 스택 바로 — 후보별 개별 막대(CandidateRow)는 각자
 * "얼마나 많이 나왔나"를 보여주고, 이건 "그 주 언론 노출을 누가 나눠 가졌나"를
 * 보여준다. 같은 주 후보들의 share_pct 는 분모가 같아 합이 100에 수렴한다
 * (분석기 쪽 계산, `analyzers/candidate_mention_share/calc.py::share_pct`). */
function WeeklyShareStack({ card }: { card: CandidateMentionCard }) {
  const weeks = card.candidates[0]?.bars.map((b) => b.week_start) ?? [];
  if (weeks.length === 0) {
    return null;
  }
  return (
    <div style={{ margin: "8px 0 12px" }}>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 6px" }}>
        주간 언급 점유율 (100% 기준)
      </p>
      {weeks.map((weekStart, i) => {
        const segments = card.candidates
          .map((c) => ({ name: c.name, color: campColor(c.lineage), pct: c.bars[i]?.share_pct ?? null }))
          .filter((s): s is { name: string; color: string; pct: number } => s.pct !== null && s.pct > 0);
        return (
          <div key={weekStart} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 11, color: "var(--muted)", width: 76, flexShrink: 0 }}>{weekStart}</span>
            {segments.length > 0 ? (
              <div style={{ display: "flex", flex: 1, height: 12, borderRadius: 2, overflow: "hidden" }}>
                {segments.map((s) => (
                  <span
                    key={s.name}
                    title={`${s.name} ${s.pct.toFixed(0)}%`}
                    style={{ width: `${s.pct}%`, background: s.color }}
                  />
                ))}
              </div>
            ) : (
              <span style={{ fontSize: 11, color: "var(--muted)" }}>데이터 없음</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CandidateRow({ series }: { series: CandidateMentionSeries }) {
  const color = campColor(series.lineage);
  return (
    <li style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
        <span style={{ fontWeight: 600 }}>{series.name}</span>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>({series.party})</span>
        {series.is_ours && <span className="badge badge--strong">우리</span>}
        <span style={{ fontSize: 12, color: "var(--muted)" }}>
          이번 주 {series.latest_count}건
          {series.latest_share_pct !== null && ` · 점유 ${series.latest_share_pct.toFixed(0)}%`}
        </span>
        <ChangeBadge pct={series.latest_wow_change_pct} />
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 36 }}>
        {series.bars.map((b) => (
          <span
            key={b.week_start}
            title={b.title}
            style={{
              flex: 1,
              minHeight: 1,
              height: `${b.height_pct}%`,
              background: color,
              opacity: b.count === 0 ? 0.15 : 1,
              borderRadius: "1px 1px 0 0",
            }}
          />
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "2px 0 0" }}>
        창 합계 {series.total_articles}건
      </p>
    </li>
  );
}

export function CandidateMentionPanel({
  card,
  districtId,
}: {
  card: CandidateMentionCard;
  districtId: string;
}) {
  return (
    <section className="panel">
      <h2>
        후보 언급 비교{" "}
        <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
          · {card.as_of} 기준 · 최근 {card.window_weeks}주
        </span>
      </h2>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        창 합계 {card.total_articles}건 · 뉴스에 이름이 얼마나 나오는가 (감성·유불리 판정 아님)
      </p>

      <BackfillBanner distorted={card.backfill_distorted} trustNote="이번 주 변화율" />

      {card.highlight && (
        <p className="banner banner--warn" style={{ fontSize: 13 }}>
          이번 주 특이사항: {card.highlight.text}
        </p>
      )}

      <WeeklyShareStack card={card} />

      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {card.candidates.map((series) => (
          <CandidateRow key={series.name} series={series} />
        ))}
      </ul>

      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        이름의 정확 일치만 본다 — 동명이인·약칭은 걸러내지 않는다. 후보 이름이 흔하면 다른
        인물을 언급한 기사가 섞였을 수 있다.
      </p>
      <p style={{ fontSize: 12 }}>
        <a href={`/d/${districtId}/news`}>원문 목록 보기 →</a>
      </p>
    </section>
  );
}
