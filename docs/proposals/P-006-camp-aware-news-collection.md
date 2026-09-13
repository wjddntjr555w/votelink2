# P-006: 뉴스 수집에 후보·상대후보·정당 검색어를 자동으로 반영한다

## 1. 무엇을

`collectors/naver_news/`는 지역명 검색어(`config.districts.<id>.queries`)만 쓴다.
후보·상대후보 이름은 검색어에도, 결과를 지역과 연관짓는 매칭 사전(`person_terms`)에도
들어가지 않는다 — 스키마 자리(`person_terms`)만 있고 모든 지역구에서 빈 배열이다.
그래서 지명이 없이 후보 실명만 나오는 기사(전국 정치 뉴스에 흔하다)가 통째로 안 잡힌다.

이 제안은 두 축을 새로 연결한다.

1. **캠프 로스터(`candidates.yaml`의 `ours`/`opponents`)** → 그 캠프가 관할하는 district의
   뉴스 수집 검색어(queries)와 매칭 사전(person_terms)에 자동 병합
2. **정당명 전역 목록**(운영자가 개수 제한 없이 추가·수정·삭제) → "정당명+지역명",
   "정당명 단독" 두 종류의 검색어로 모든 district에 자동 병합

## 2. P-001 §5·§16과의 관계 — 캠프별 분리 수집이 아니다

`docs/proposals/P-001-camp-data-isolation.md` §5는 이미 이 아이디어의 위험한 버전을
검토하고 기각했다:

> 상대 후보 로스터가 생기면 뉴스 수집에 `person_terms` 를 넣고 싶어진다. **넣지 않는다.**
> 로스터는 수집 파라미터가 아니라 **읽기 시점 필터·주석**으로 적용한다... 수집을 캠프별로
> 쪼개면 (1) 네이버·data.go.kr 호출이 캠프 수만큼 곱해지고, (2) 같은 선거구의 두 캠프가
> 사실상 같은 기사를 두 벌 저장하게 된다.

같은 문서 §16은 정확히 이 제안의 모양을 후속 과제로 미리 승인해두었다:

> 후속으로 "전 캠프 로스터의 합집합"을 운영자가 수집하는 방법이 있다(후보 이름은
> 공개 정보이므로 여전히 공용이다). 이번 범위는 아니다.

**이 제안이 구현하는 것은 §16의 그 후속 과제다.** 수집 자체는 여전히 district 단위
공용·1회다(`votelink collect naver_news --district <id>` 그대로). `--camp` 인자를
naver_news에 추가하지 않는다. 대신 fetch 시점에 그 district를 관할하는 **모든** 캠프의
로스터를 합집합으로 모아 검색어·매칭사전에 반영한다 — API 호출은 district 수에 비례하지
캠프 수에 비례하지 않고, 같은 기사가 캠프마다 중복 저장되지도 않는다(공용 코퍼스 그대로).

## 3. 후보명 → 검색어(queries)

- id: `cand-{sha256(name)[:8]}` — ascii 슬러그, 결정적(재수집 때마다 같음), raw 파일명
  제약(`docs/20-collector-spec.md`)을 만족한다.
- q: `"{name} {party}"` — 정당명을 한정어로 붙여 동명이인 노이즈를 줄인다. 이름 단독
  쿼리는 추가하지 않는다 — 흔한 이름에서 노이즈가 개선 목적 자체를 무력화한다.

## 4. 후보명 → 매칭 사전(person_terms)

- ours + opponents 전원의 이름을 그대로 합집합(중복 제거)에 넣는다.
- confidence는 신설 상수 `CONFIDENCE_PERSON = 0.9`로 `district_terms`(동/지명 직접 언급)와
  같은 등급을 준다. 근거: `sigungu_terms`(0.7)는 "송파구"처럼 흔해 스포츠·부동산 기사가
  섞이지만, 후보 실명은 지리적 모호성이 없다(동명이인 노이즈는 있어도 그건 별개 축이다).
- **스코프 필터 확장이 반드시 필요하다.** 현재 `_mentions_region`은 `district_terms`/
  `sigungu_terms`만 보고 폐기 여부를 정한다. 후보명만 언급되고 지명이 없는 기사(예:
  "OOO 의원, 국회서 OO법 발의")는 이 필터에서 폐기되어, person 쿼리로 찾아놓고도 버려진다.
  `_mentions_region`을 `_in_scope`로 확장해 person_terms 매칭도 "범위 안" 근거로 인정한다.
  이 수정 없이는 이번 기능 전체가 사실상 무의미하다.
- 절대규칙 3(개인 단위 데이터 없음)과의 정합성: `candidates.yaml`의 기존 논리
  ("절대규칙 3은 유권자 개인을 겨냥하며, 후보는 공인이라 공개 출처 필드에 한해 예외" —
  P-001 §14)를 그대로 따른다. 이 변경은 화이트리스트의 **출처**를 "손으로 meta.yaml에
  적은 빈 배열"에서 "candidates.yaml에서 자동 파생"으로 바꿀 뿐, 새 예외를 만들지 않는다.

## 5. 정당명 목록 — 전역·운영자 CRUD

정당명은 캠프 로스터와 성격이 다르다: 특정 캠프가 아니라 "이 선거구에 어떤 정당이
출마했는지" 자체가 공개 정보이고, 캠프 존재 여부와 무관하게 유용하다(캠프가 아직 없는
지역구도 정당 뉴스는 미리 쌓아둘 수 있다). 그래서 **캠프 단위가 아니라 전역 단일 목록**
(`data/shared/reference/news_parties.yaml`)으로 관리하고, 운영자 콘솔에 CRUD 화면을 둔다.

`docs/proposals/P-003-operator-console.md` §3은 `party_lineage.yaml`류 참조데이터에
대해 "폼 편집기를 만들지 말고 원문 텍스트+git 커밋으로 관리하라"고 못박았다 — 그 파일은
판단 근거·주석이 1032줄 대부분을 차지하고, 폼 왕복이 그걸 지운다. `news_parties.yaml`은
정당명 문자열 목록일 뿐 판단 근거가 없으므로 이 제약과 무관하다. 일반 폼 CRUD로 관리한다.

검색어는 두 종류를 만든다(정당명 단독 검색은 전국 뉴스가 섞일 수 있으나, 어차피
`_in_scope` 필터를 통과해야 저장되므로 지역 무관 기사가 쌓이지는 않는다):

- `{id: "{party_id}-region", q: "{정당명} {district.geo_name}"}`
- `{id: party_id, q: "{정당명}"}`

## 6. 계약 변경 없음

payload 스키마(`NewsArticlePayload`)는 바꾸지 않는다. `mentioned_persons`는 이미 있는
필드고, 정당명은 어떤 새 필드에도 담기지 않는다(검색어로만 쓰이고, 매칭 결과는 기존
`mentioned_places`/`mentioned_persons`로 충분히 복원된다 — C-003이 "어떤 검색어에
걸렸는지는 저장하지 않는다"고 이미 정한 것과 같은 판단).

## 7. 이번 범위 아님

- 캠프별 독립 수집·별도 저장(P-001 §5가 이미 기각)
- 정당명 목록의 district별 오버라이드(전역 하나로 충분하다는 판단, 필요해지면 후속 제안)
- 정당-진영 매핑(그건 `party_lineage.yaml`의 일이고 이 목록과 무관하다)

> **2026-09-13 추가 — 수집 실행 버튼.** `/ops/news-parties`에 "전체 지역구 수집"·
> "이 지역구만 수집" 버튼과 실행 이력(상태·종료 코드)을 추가했다. `docs/proposals/
> P-003-operator-console.md` §4가 설계해두고 미구현이던 것을 `naver_news` 하나로
> 범위를 좁혀 구현했다 — CLI를 subprocess로 감싸는 `votelink/control/jobs.py`,
> `jobs` 테이블, 재시작 시 고아 정리(`reap_orphans`)까지 §4 설계 그대로다. 지금은
> 수동 트리거이고, cron 자동화는 후속(§8 표에 추가 안 함 — 이 문서의 범위가
> 검색어 로직이라 실행 트리거 상세는 P-003 §4에 남긴다).
>
> **2026-09-13 추가 — 후보 검색어만 재수집.** "이 지역구 후보 뉴스만 재수집" 버튼을
> 더했다. 캠프가 로스터(`candidates.yaml`)를 막 갱신했을 때 지명·정당 검색어까지
> 전부 다시 돌리지 않고 §3·§4가 만든 후보·상대후보 검색어만 빠르게 재실행한다.
> CLI 인자를 늘리지 않고 `NAVER_NEWS_QUERY_SCOPE=candidates` 환경변수로 범위를
> 좁힌다 — `collect` 서브커맨드는 모든 수집기가 공유하는 generic 인터페이스라
> naver_news 하나만의 관심사를 거기 얹지 않는다. `NAVER_CLIENT_ID`처럼 이미
> 환경변수가 여닫는 값이 있으니 같은 통로다(`collectors/naver_news/collector.py::
> _queries`). 이 범위로 받은 기사도 스코프 판정·`mentioned_persons` 계산은
> 평소와 동일하다 — 매칭 사전은 범위와 무관하게 항상 전부 채운다.

## 8. 채택 시 갱신할 문서

| 문서 | 고칠 것 |
|---|---|
| `docs/proposals/P-001-camp-data-isolation.md` | §5에 "district 단위 합집합(P-006)은 이 제약 밖" 정정, §18 표에 이번 변경 문서 추가 |
| `docs/proposals/P-003-operator-console.md` | §3 근처에 "news_parties.yaml은 이 제약과 무관" 구분 문단 |
| `docs/proposals/C-003-naver-news.md` | 캠프 로스터·정당목록 통합 상태 갱신 |
| `docs/90-compliance.md` | §10 표에 후보 실명 수집 출처 근거 한 줄 |
| `docs/40-webapp-spec.md` | 운영자 콘솔 라우트 표에 `/api/ops/news-parties` 추가 |
