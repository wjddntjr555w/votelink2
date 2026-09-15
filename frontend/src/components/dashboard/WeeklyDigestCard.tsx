import type { CandidateMentionCard, IssueBoardCard, PulseCard, Verdict } from "../../api/types";

/** 이미 각자 게이트를 통과한 세 카드(pulse/issue_board/candidate_mentions)의
 * 숫자만 한 줄로 모은다. LLM 을 쓰지 않는다 — 필드를 고르고 배치만 한다.
 *
 * 개별 카드의 `verdict`가 `blocked`면 그 값은 이미 백엔드(`_redact_output`)가
 * 0/빈 값으로 지워서 내려온다. 그래도 "0건"을 "실제로 0건"처럼 보여주면
 * 오해를 부르므로, blocked 인 소스는 여기서도 한 번 더 걸러 아예 빼고 조용히
 * 생략한다 — 개별 패널은 자기 배너를 따로 갖고 있으니 이 요약 카드에서
 * ComplianceGate 배너를 세 번 겹쳐 그리지 않는다(취지: `docs/90-compliance.md`
 * 절대 규칙 5 — 차단된 값을 실제 값처럼 보여주지 않는다는 정신은 지키되,
 * 배너 자체는 아래 개별 패널이 이미 보여준다).
 */
function shows(verdict: Verdict | null | undefined): boolean {
  return !!verdict && verdict.status !== "blocked";
}

export function WeeklyDigestCard({
  pulse,
  issueBoard,
  candidateMentions,
}: {
  pulse: PulseCard | null;
  issueBoard: IssueBoardCard | null;
  candidateMentions: CandidateMentionCard | null;
}) {
  const pulseOk = pulse && shows(pulse.verdict);
  const issueOk = issueBoard && shows(issueBoard.verdict);
  const mentionsOk = candidateMentions && shows(candidateMentions.verdict);

  if (!pulseOk && !issueOk && !mentionsOk) {
    return null;
  }

  const ours = mentionsOk ? candidateMentions.candidates.find((c) => c.is_ours) : undefined;
  const oursShare = ours?.latest_share_pct ?? null;
  const theirsShare = oursShare !== null ? Math.max(0, 100 - oursShare) : null;

  return (
    <section className="panel">
      <h2>이번 주 요약</h2>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: 13, lineHeight: 1.8 }}>
        {pulseOk && (
          <li>
            뉴스 <strong className="num">{pulse.latest_count}건</strong>
            {pulse.latest_spike && (
              <span className="status-pill watch" style={{ marginLeft: 6 }}>
                급증 {pulse.latest_z_text}
              </span>
            )}
            <span style={{ color: "var(--muted)" }}> · 창 합계 {pulse.total_articles}건</span>
          </li>
        )}
        {mentionsOk && ours && oursShare !== null && theirsShare !== null && (
          <li>
            언론 노출 우리 <strong className="num">{oursShare.toFixed(0)}%</strong> vs 상대{" "}
            <strong className="num">{theirsShare.toFixed(0)}%</strong>
            {candidateMentions.highlight && (
              <span style={{ color: "var(--signal-behind)" }}> · {candidateMentions.highlight.text}</span>
            )}
          </li>
        )}
        {issueOk && issueBoard.bars.length > 0 && (
          <li>
            최상위 이슈{" "}
            {issueBoard.bars.slice(0, 2).map((b, i) => (
              <span key={b.category}>
                {i > 0 && " · "}
                <strong>{b.label}</strong> {b.trend_label}
              </span>
            ))}
          </li>
        )}
        {pulseOk && pulse.top_publishers.length > 0 && (
          <li style={{ color: "var(--muted)" }}>상위 언론사 {pulse.top_publishers.length}곳</li>
        )}
      </ul>
    </section>
  );
}
