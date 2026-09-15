import type { CandidateMentionCard, DistrictView, Verdict } from "../../api/types";
import { campColor } from "../../design-system/campColor";

function shows(verdict: Verdict | null | undefined): boolean {
  return !!verdict && verdict.status !== "blocked";
}

/** 이번 주 뉴스 언급 점유율(candidate_mention_share)과 과거 득표 기반 진영
 * 구성(voter_profile 근사 집계, `view.summary_card`)을 나란히 놓는다 —
 * "언론에서 밀리는 것"과 "표심에서 밀리는 것"은 다른 문제라는 걸 보여준다.
 *
 * 로그인한 캠프 렌즈가 있을 때만 의미가 있다("우리"가 누군지는 렌즈가
 * 정한다) — CandidateComparison과 같은 전제다. 두 소스가 서로 다른 verdict를
 * 가질 수 있어 WeeklyDigestCard와 같은 방식으로 개별 gate 없이 shows()로만
 * 거른다(각 패널이 이미 자기 배너를 보여준다). */
export function MediaElectoralGapCard({
  view,
  candidateMentions,
}: {
  view: DistrictView;
  candidateMentions: CandidateMentionCard | null;
}) {
  if (!view.lens || !view.summary_card || !candidateMentions) {
    return null;
  }
  if (!shows(view.verdict) || !shows(candidateMentions.verdict)) {
    return null;
  }

  // 여러 캠프가 한 district를 관할하면 is_ours 가 둘 이상일 수 있다(P-001) —
  // 그 드문 경우엔 첫 번째만 쓴다. 지금 렌즈의 후보와 정확히 안 맞을 수 있지만,
  // 별도 매칭 키(캠프 id)가 candidate_mention_share 쪽에 없어 이름으로 짐작하지 않는다.
  const ours = candidateMentions.candidates.find((c) => c.is_ours);
  if (!ours || ours.latest_share_pct === null) {
    return null;
  }

  const mediaOurs = ours.latest_share_pct;
  const mediaTheirs = Math.max(0, 100 - mediaOurs);

  const electoralOurs = view.summary_card.camp_bar
    .filter((s) => s.ours)
    .reduce((sum, s) => sum + s.pct, 0);
  const electoralTheirs = Math.max(0, 100 - electoralOurs);

  const gap = mediaOurs - electoralOurs;
  const gapText =
    gap > 3
      ? `언론 노출이 표심보다 ${gap.toFixed(0)}%p 앞서 있다.`
      : gap < -3
        ? `표심이 언론 노출보다 ${Math.abs(gap).toFixed(0)}%p 앞서 있다.`
        : "언론 노출과 표심이 비슷한 수준이다.";

  const oursColor = campColor(view.lens.lineage);

  return (
    <section className="panel">
      <h2>미디어 노출 vs 표심</h2>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        이번 주 뉴스 언급 점유율과 과거 득표 기반 진영 구성(근사 집계)을 나란히 놓는다.
      </p>

      <div style={{ margin: "10px 0" }}>
        <p style={{ fontSize: 12, margin: "0 0 3px" }}>언론 노출 (이번 주)</p>
        <div className="camp-bar" style={{ width: "100%" }} title="이번 주 언급 점유율">
          <span style={{ width: `${mediaOurs}%`, background: oursColor }} />
          <span style={{ width: `${mediaTheirs}%`, background: "var(--muted)" }} />
        </div>
        <p className="num" style={{ fontSize: 12, margin: "3px 0 0" }}>
          우리 {mediaOurs.toFixed(0)}% · 상대 {mediaTheirs.toFixed(0)}%
        </p>
      </div>

      <div style={{ margin: "10px 0" }}>
        <p style={{ fontSize: 12, margin: "0 0 3px" }}>표심 (과거 득표 근사 집계)</p>
        <div className="camp-bar" style={{ width: "100%" }} title="진영별 득표 구성">
          <span style={{ width: `${electoralOurs}%`, background: oursColor }} />
          <span style={{ width: `${electoralTheirs}%`, background: "var(--muted)" }} />
        </div>
        <p className="num" style={{ fontSize: 12, margin: "3px 0 0" }}>
          우리 {electoralOurs.toFixed(0)}% · 상대 {electoralTheirs.toFixed(0)}%
        </p>
      </div>

      <p style={{ fontSize: 13, fontWeight: 600 }}>{gapText}</p>
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        둘 다 근사 집계다 — 언론 노출은 이름의 정확 일치만 세고, 표심은 인구 가중 근사다.
        노출이 많다고 유리하다는 뜻이 아니고, 적다고 불리하다는 뜻도 아니다.
      </p>
    </section>
  );
}
