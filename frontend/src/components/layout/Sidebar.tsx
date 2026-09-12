import { Icon } from "./Icon";
import { logout } from "../../api/client";
import type { Lens } from "../../api/types";

interface Props {
  districtId?: string;
  districtName?: string;
  electionTypeLabel?: string;
  active: "dashboard" | "map" | "news" | "compare" | "nation" | "cycles" | "me" | "ops" | "audit";
  lens: Lens | null;
  authOn: boolean;
  account: { email: string; is_operator: boolean } | null;
}

/** 좌측 콘솔 레일. Jinja2 시절 base.html 의 사이드바와 같은 항목·같은 판단 —
 * 실제 라우트가 없는 메뉴("후보 비교"·"여론조사"·"리포트"·"설정")는 추가하지 않는다.
 * `districtId` 가 없으면(비교·전국처럼 "지금 이 선거구"가 없는 화면) 대시보드·지도·
 * 뉴스 링크를 안 그린다 — 옛 base.html 의 `{% if district_id %}` 와 같은 판단이다. */
export function Sidebar({ districtId, districtName, electionTypeLabel, active, lens, authOn, account }: Props) {
  const navVisible = !authOn || lens || account?.is_operator;

  return (
    <aside className="rail">
      <div className="rail__brand">
        <b>VOTELINK</b>
        <span>WAR ROOM</span>
      </div>
      {districtName && (
        <div className="rail__district">
          <div className="name">{districtName}</div>
          {electionTypeLabel && <div className="meta">{electionTypeLabel}</div>}
        </div>
      )}

      {navVisible && (
        <nav className="rail__nav">
          {districtId && (
            <>
              <a className={active === "dashboard" ? "on" : ""} href={`/d/${districtId}/`}>
                <Icon name="dashboard" />
                대시보드
              </a>
              <a className={active === "map" ? "on" : ""} href={`/d/${districtId}/map`}>
                <Icon name="map" />
                지역분석
              </a>
              <a className={active === "news" ? "on" : ""} href={`/d/${districtId}/news`}>
                <Icon name="news" />
                뉴스
              </a>
            </>
          )}
          <div className="rail__navlabel">전국</div>
          <a className={active === "compare" ? "on" : ""} href="/compare">
            <Icon name="compare" />
            선거구 비교
          </a>
          <a className={active === "nation" ? "on" : ""} href="/nation">
            <Icon name="nation" />
            전국 동
          </a>
          {lens && (
            <a className={active === "cycles" ? "on" : ""} href="/cycles">
              <Icon name="cycle" />
              선거 주기
            </a>
          )}
          {account?.is_operator && (
            <>
              <a className={active === "ops" ? "on" : ""} href="/ops/">
                <Icon name="ops" />
                캠프 관리
              </a>
              <a className={active === "audit" ? "on" : ""} href="/ops/audit">
                <Icon name="audit" />
                감사 로그
              </a>
            </>
          )}
        </nav>
      )}

      <div className="rail__foot">
        {lens ? (
          <div className="who">
            <b>{lens.label}</b>
            캠프 · 내부 열람
          </div>
        ) : account?.is_operator ? (
          <div className="who">
            <b>{account.email}</b>
            운영자 · 전 캠프 열람
          </div>
        ) : !authOn ? (
          <div className="who">진영 중립 보기 · 캠프 내부 열람</div>
        ) : null}
        {authOn && (
          <div className="rail__account">
            {account ? (
              <>
                <a href="/me" className={active === "me" ? "on" : ""}>내 계정</a>
                {/* POST 만 받는다 — GET 이면 남의 페이지에 심은 이미지 한 장으로 로그아웃된다. */}
                <button
                  type="button"
                  className="linkish"
                  onClick={async () => {
                    await logout();
                    window.location.href = "/login";
                  }}
                >
                  로그아웃
                </button>
              </>
            ) : (
              <a href="/login">로그인</a>
            )}
          </div>
        )}
        <div className="rail__status">
          <i />
          시스템 정상 운영
        </div>
      </div>
    </aside>
  );
}
