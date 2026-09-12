import { Icon } from "../layout/Icon";
import type { IssueBoardCard } from "../../api/types";

export function IssueBoardPanel({
  issueBoard,
  districtName,
  districtId,
}: {
  issueBoard: IssueBoardCard;
  districtName: string;
  districtId: string;
}) {
  return (
    <section className="panel">
      <h2>
        이슈 보드{" "}
        <span style={{ fontSize: 12, color: "var(--muted)", fontWeight: 400 }}>
          · {issueBoard.as_of} 기준 · 최근 {issueBoard.window_weeks}주 · 어휘집 {issueBoard.lexicon_version}
        </span>
      </h2>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        창 합계 {issueBoard.total_articles}건 · 무엇에 대해 뉴스가 돌았는가 (감성·유불리 판정 아님)
      </p>
      <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
        표본은 '{districtName}' 지명 검색분이라 스포츠·행사·타지역 국가뉴스가 많이 섞인다
        ({issueBoard.unclassified_pct.toFixed(0)}%가 분류 불가). 카테고리 랭킹·추세는 방향 참고용이다.
      </p>

      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {issueBoard.bars.map((b) => (
          <li key={b.category} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 3 }}>
              <Icon name="news" size={14} />
              <span style={{ fontWeight: 600 }}>{b.label}</span>
              <span style={{ fontSize: 12 }}>{b.trend_label}</span>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>
                {b.article_count}건 · {b.share.toFixed(0)}%
              </span>
            </div>
            <svg viewBox="0 0 100 6" preserveAspectRatio="none" style={{ display: "block", width: "100%", height: 6 }} role="img" aria-label={b.title}>
              <rect x="0" y="0" width={b.width_pct} height={6} fill="var(--accent)" />
            </svg>
            {b.headlines.length > 0 && (
              <ul style={{ margin: "4px 0 0", paddingLeft: 16, fontSize: 12, color: "var(--muted)" }}>
                {b.headlines.map((h, i) => (
                  <li key={i}>{h}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        분류 안 됨 <strong>{issueBoard.unclassified_count}건</strong> ({issueBoard.unclassified_pct.toFixed(0)}%)
        {issueBoard.unclassified_pct >= 50 && <span style={{ color: "var(--signal-behind)" }}> — 어휘집 보강 신호</span>}
      </p>
      <p style={{ fontSize: 12 }}>
        <a href={`/d/${districtId}/news`}>원문 목록 보기 →</a>
      </p>
    </section>
  );
}
