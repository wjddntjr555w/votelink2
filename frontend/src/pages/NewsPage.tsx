import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { fetchNews, ApiError } from "../api/client";
import type { NewsApiResponse, NewsView } from "../api/types";
import { Sidebar } from "../components/layout/Sidebar";
import { TopBar } from "../components/layout/TopBar";
import { ComplianceGate } from "../components/compliance/ComplianceGate";

const UNKNOWN_TEXT = "—";

// `is_empty`/`nothing_collected`/`truncated`/`shown_text`/`coverage_text`/`date_range_text` 는
// 백엔드 `NewsView` 의 @property 라 model_dump()/JSON 에 없다 — 여기서 같은 규칙으로 다시 계산한다.
function isEmpty(view: NewsView) { return view.rows.length === 0; }
function nothingCollected(view: NewsView) { return view.diagnostics.shown === 0; }
function truncated(view: NewsView) { return view.matched > view.rows.length; }
function shownText(view: NewsView) {
  return truncated(view) ? `${view.matched}건 중 ${view.rows.length}건 표시` : `${view.rows.length}건`;
}
function coverageText(view: NewsView) {
  return `동·지명 직접 ${view.district_specific_count}건 / 구 단위만 ${view.sigungu_only_count}건`;
}
function dateRangeText(view: NewsView) {
  if (!view.date_from) return UNKNOWN_TEXT;
  return view.date_from === view.date_to ? view.date_from : `${view.date_from} ~ ${view.date_to}`;
}

export function NewsPage() {
  const { districtId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const sort = searchParams.get("sort") ?? "date";
  const scope = searchParams.get("scope") ?? "all";
  const q = searchParams.get("q") ?? "";

  const [queryDraft, setQueryDraft] = useState(q);
  useEffect(() => setQueryDraft(q), [q]);

  const [data, setData] = useState<NewsApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchNews(districtId, { sort, scope, q })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "알 수 없는 오류가 발생했다");
      });
    return () => {
      cancelled = true;
    };
  }, [districtId, sort, scope, q]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  };

  if (error) {
    return (
      <div className="shell">
        <div className="main">
          <div className="content">
            <div className="banner banner--blocked">
              <strong>화면을 불러오지 못했다</strong>
              <p>{error}</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="shell">
        <div className="main">
          <div className="content" style={{ color: "var(--muted)" }}>불러오는 중…</div>
        </div>
      </div>
    );
  }

  const { view } = data;

  return (
    <div className="shell">
      <Sidebar
        districtId={districtId}
        districtName={view.district_name}
        active="news"
        lens={data.lens}
        authOn={data.auth_on}
        account={data.account}
      />

      <div className="main">
        <TopBar
          electionTypes={data.election_types}
          electionType=""
          districts={data.districts}
          districtId={districtId}
          authOn={data.auth_on}
          onElectionTypeChange={() => {}}
        />

        <div className="content">
          <div className="page-head">
            <div>
              <div className="eyebrow">수집한 지역 기사</div>
              <h1>{view.district_name} 뉴스</h1>
            </div>
          </div>

          {nothingCollected(view) ? (
            <div className="banner banner--warn">
              <strong>수집된 기사가 없다</strong>
              <p className="num">uv run votelink collect naver_news --district {districtId}</p>
            </div>
          ) : (
            <>
              <dl className="news-summary">
                <div><dt>표시</dt><dd>{shownText(view)}</dd></div>
                <div><dt>지역 관련도</dt><dd>{coverageText(view)}</dd></div>
                <div><dt>기간</dt><dd>{dateRangeText(view)}</dd></div>
                <div><dt>언론사</dt><dd>{view.top_publishers.length}곳</dd></div>
              </dl>
              <p className="muted small">
                읽음 {view.diagnostics.read}건 · 선거구 밖 {view.diagnostics.outside_district}건 제외
                {view.diagnostics.duplicate > 0 && ` · 중복 ${view.diagnostics.duplicate}건`}
                {view.diagnostics.rejected > 0 && (
                  <> · <span className="warn-text">계약 위반 {view.diagnostics.rejected}건 격리</span></>
                )}
              </p>
              {truncated(view) && (
                <p className="muted small">
                  최신 {view.rows.length}건만 그린다 (스코프 적용 후 {view.matched}건). 정렬을 바꾸면
                  그 순서의 상위 {view.rows.length}건을 본다.
                </p>
              )}
              <p className="muted small">
                기사는 행정동이 아니라 구 단위({view.district_name})에 귀속한다. 본문 전문은 저장하지
                않는다 — 제목을 누르면 원문으로 나간다. 구 단위 매칭만 된 기사에는 스포츠·연예가 섞인다.
              </p>
              {view.top_places.length > 0 && (
                <p className="muted small">
                  자주 언급된 지명:{" "}
                  {view.top_places.map(([name, n]) => (
                    <span key={name} className="chip">{name} {n}</span>
                  ))}
                </p>
              )}
              {view.top_persons.length > 0 && (
                <p className="muted small">
                  자주 언급된 인물:{" "}
                  {view.top_persons.map(([name, n]) => (
                    <span key={name} className="chip">{name} {n}</span>
                  ))}
                </p>
              )}

              <form
                className="news-search"
                onSubmit={(e) => {
                  e.preventDefault();
                  setParam("q", queryDraft);
                }}
              >
                <input
                  type="search"
                  value={queryDraft}
                  onChange={(e) => setQueryDraft(e.target.value)}
                  placeholder="제목·요약·언론사·언급 지명/인물 검색"
                  aria-label="기사 검색"
                />
                <button type="submit">검색</button>
                {q && (
                  <a
                    className="news-search__clear"
                    href="?"
                    onClick={(e) => {
                      e.preventDefault();
                      setQueryDraft("");
                      setParam("q", "");
                    }}
                  >
                    지우기
                  </a>
                )}
              </form>
              {q && (
                <p className="muted small">「{q}」 검색 — {shownText(view)}</p>
              )}

              <nav className="map-metric-nav">
                {Object.entries(view.scopes).map(([key, label]) => (
                  <a
                    key={key}
                    className={scope === key ? "on" : ""}
                    href="?"
                    onClick={(e) => {
                      e.preventDefault();
                      setParam("scope", key);
                    }}
                  >
                    {label}
                  </a>
                ))}
              </nav>
              <nav className="map-metric-nav">
                {Object.entries(view.sorts).map(([key, label]) => (
                  <a
                    key={key}
                    className={sort === key ? "on" : ""}
                    href="?"
                    onClick={(e) => {
                      e.preventDefault();
                      setParam("sort", key);
                    }}
                  >
                    {label}
                  </a>
                ))}
              </nav>

              <ComplianceGate verdict={view.verdict}>
                {isEmpty(view) ? (
                  <p className="muted">
                    {q
                      ? `「${q}」 에 걸리는 기사가 없다. 검색어를 지우거나 바꿔 본다.`
                      : "이 스코프에 해당하는 기사가 없다. 스코프를 넓혀 본다."}
                  </p>
                ) : (
                  <div className="news-table-wrap">
                    <table className="news-table">
                      <thead>
                        <tr>
                          <th>발행시각</th>
                          <th>언론사</th>
                          <th>제목</th>
                          <th>지역 관련</th>
                          <th>언급 지명·인물</th>
                        </tr>
                      </thead>
                      <tbody>
                        {view.rows.map((row) => (
                          <tr key={row.url}>
                            <td className="num nowrap">{row.date_label}</td>
                            <td>{row.publisher}</td>
                            <td>
                              <a href={row.url} target="_blank" rel="noopener noreferrer nofollow">
                                {row.title}
                              </a>
                            </td>
                            <td>
                              {row.is_district_specific ? (
                                <span className="badge badge--strong">동·지명 직접</span>
                              ) : (
                                <span className="badge">구 단위</span>
                              )}
                            </td>
                            <td className="muted small">{[...row.places, ...row.persons].join(" · ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </ComplianceGate>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
