import type { ReactNode } from "react";
import type { Verdict } from "../../api/types";

/**
 * 절대 규칙 5의 집행 지점 — React 버전.
 *
 * `votelink/web/templates/_output.html` 매크로와 **정확히 같은 4분기**를 재현한다:
 * - `blocked` → children 을 그리지 않는다. 자리에 차단 사유만.
 * - `unreviewed` → 경고 배너를 **children 위에**. 옆·아래가 아니다.
 * - `cleared` → 조용한 배지 + 검토자·검토일.
 * - `notes` → 상태와 무관하게 항상 표시.
 * - `verdict` 가 `null`/`undefined` → **`blocked` 와 같게 다룬다.** 판정 없음은
 *   "안전"이 아니라 "모름"이다 (docs/90-compliance.md §9, P-002 §10).
 *
 * **경고 없이 children 만 그릴 수 있는 경로가 이 컴포넌트에 존재하지 않는다** —
 * `_output.html` 이 지켜온 것과 같은 불변식이다. 이 컴포넌트를 거치지 않고
 * 산출물을 그리는 곳이 생기면 규칙 5가 조용히 비껴간다.
 */
export function ComplianceGate({
  verdict,
  children,
}: {
  verdict: Verdict | null | undefined;
  children: ReactNode;
}) {
  if (!verdict) {
    return (
      <section className="output output--blocked" data-testid="compliance-gate">
        <div className="banner banner--blocked">
          <strong>검증 판정이 없어 표시하지 않는다</strong>
          <p>이 산출물의 선거법 검증 결과를 계산하지 못했다. 판정 없는 산출물은 그리지 않는다.</p>
        </div>
      </section>
    );
  }

  const showsContent = verdict.status !== "blocked";

  return (
    <section className={`output output--${verdict.status}`} data-testid="compliance-gate">
      {verdict.status === "blocked" && (
        <div className="banner banner--blocked">
          <strong>표시가 차단된 산출물이다</strong>
          <ul>
            {verdict.reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {verdict.status === "unreviewed" && (
        <div className="banner banner--warn">
          <strong>선거법 검토를 받지 않은 산출물이다</strong>
          <ul>
            {verdict.reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {verdict.status === "cleared" && (
        <p className="badge badge--cleared">
          검토 완료
          {verdict.reviewed_by && <> · {verdict.reviewed_by}</>}
          {verdict.reviewed_at && <> ({verdict.reviewed_at})</>}
        </p>
      )}

      {verdict.notes.length > 0 && (
        <ul className="notes">
          {verdict.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}

      {showsContent && children}
    </section>
  );
}
