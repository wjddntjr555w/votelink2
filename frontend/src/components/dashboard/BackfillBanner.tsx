/** news_pulse/local_issue/candidate_mention_share 셋 다 갖고 있는
 * `backfill_distorted` 플래그의 공용 배너. 세 패널이 각자 문구를 조금씩
 * 다르게 썼던 걸 하나로 합친다 — 무엇을 못 믿는지(trustNote)만 패널마다 다르다. */
export function BackfillBanner({
  distorted,
  trustNote,
}: {
  distorted: boolean;
  trustNote: string;
}) {
  if (!distorted) {
    return null;
  }
  return (
    <p style={{ fontSize: 12, color: "var(--signal-behind)" }}>
      첫 백필의 검색 API 상한(검색어당 1,000건) 때문에 최근으로 갈수록 기사량이 부풀어 있다.
      증분 수집이 여러 주 쌓이기 전까지 {trustNote}을 신뢰하지 않는다.
    </p>
  );
}
