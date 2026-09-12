import { useEffect, useState } from "react";
import { fetchPending, ApiError } from "../api/client";
import type { PendingApiResponse } from "../api/types";

/** 미승인 계정이 볼 수 있는 유일한 화면. **공용 데이터도 보여주지 않는다** —
 * "아무것도 보여주지 않는다"가 사용자가 고른 미승인 공개범위다 (P-002 §6). */
export function PendingPage() {
  const [data, setData] = useState<PendingApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPending()
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
  }, []);

  return (
    <div className="auth-page">
      <section className="auth-gate">
        <h1>승인 대기 중</h1>

        {error && (
          <div className="banner banner--blocked"><strong>{error}</strong></div>
        )}

        <div className="banner banner--warn">
          <strong>운영자가 신청을 확인하고 있습니다</strong>
          <p>승인되면 이 화면 대신 캠프 설정(온보딩) 화면이 열립니다.</p>
        </div>

        {data?.request && (
          <dl className="news-summary" style={{ flexDirection: "column", gap: 8 }}>
            <div><dt>후보</dt><dd>{data.request.candidate_name}</dd></div>
            <div><dt>연락처</dt><dd>{data.request.contact}</dd></div>
            {data.request.wanted_election && (
              <div><dt>희망 선거</dt><dd>{data.request.wanted_election}</dd></div>
            )}
            <div><dt>신청 시각</dt><dd>{data.request.requested_at}</dd></div>
          </dl>
        )}

        <p className="auth-foot">
          승인 여부는 운영자가 연락처로 알립니다. 이 화면은 새로고침해도 됩니다.
        </p>
      </section>
    </div>
  );
}
