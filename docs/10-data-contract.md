# 공통 데이터 계약 (v1)

> 상태: v1 구현됨 (`votelink/contract/models.py`, 테스트 23개)
> **단일 진실은 코드다.** 이 문서와 모델이 어긋나면 모델이 옳다.
> 이 문서가 L1(수집)과 L2(분석)를 잇는 유일한 접점이다.
> 수집기를 몇 개로 늘리든 이 계약만 지키면 분석기 코드는 바뀌지 않는다.

## 1. 구조: 봉투 + 본문

뉴스 기사와 인구통계표를 하나의 스키마에 넣는 것은 불가능하다.
그래서 **봉투(envelope)는 모든 레코드가 동일**하고, **본문(payload)은 `kind`별로 다르다.**

```
Record = Envelope(공통 15필드) + Payload(kind별)
```

- 수집기 작성자는 봉투 채우는 법만 알면 된다.
- 분석기는 `kind`로 분기하고, 모르는 `kind`는 무시한다.
- 새 `kind` 추가는 기존 코드를 건드리지 않는다.

**단일 진실은 Pydantic 모델**(`votelink/contract/models.py`)이다.
이 문서는 그 모델의 의도를 설명한다. JSON Schema는 Pydantic에서 생성한다.

## 2. 봉투 (Envelope)

| 필드 | 타입 | 필수 | 설명 |
|---|---|:--:|---|
| `record_id` | str(16) | ✓ | `sha256(kind\|collector_id\|natural_key)[:16]`. 재수집해도 같은 값 → 멱등성 |
| `schema_version` | str | ✓ | `"1.0"`. 계약이 깨지는 변경 시 올린다 |
| `kind` | enum | ✓ | 본문 종류. §4 참조 |
| `collector_id` | str | ✓ | 이 레코드를 만든 수집기 (`nec_election_result` 등) |
| `source_name` | str | ✓ | 원 출처 기관·매체명 (`중앙선거관리위원회`) |
| `source_url` | str \| null | ✓ | 원본 URL. 없으면 null |
| `source_license` | enum | ✓ | `public_open` / `api_tos` / `crawl_public` / `restricted` |
| `observed_at` | datetime | ✓ | **데이터가 가리키는 시점**. 기사 발행일, 통계 기준일 |
| `observed_precision` | enum | ✓ | `year`/`month`/`day`/`minute`. 통계는 보통 `month` |
| `ingested_at` | datetime | ✓ | 수집한 시각 |
| `geo_level` | enum | ✓ | `nation`/`sido`/`sigungu`/`emd`/`point`/`none` |
| `geo_code` | str \| null | ✓ | 행정동코드. §3 참조 |
| `geo_name` | str \| null | ✓ | 사람이 읽는 지역명 |
| `confidence` | float | ✓ | 0.0~1.0. 실측=1.0, 추정·표본=근거에 따라 |
| `derived_from` | list[str] | ✓ | 파생 레코드면 근거 `record_id` 목록. 원천이면 `[]` |
| `payload` | object | ✓ | `kind`별 본문 |

### `natural_key` — 봉투에 없지만 반드시 필요한 것
`record_id`는 자동 계산이고, 수집기는 대신 **`natural_key`** 를 넘긴다.
출처 안에서 그 데이터를 유일하게 가리키는 문자열이다 (기사 URL, `선거ID|투표구코드`,
`기준월|행정동코드`). 저장되지 않으며 오직 `record_id` 계산에만 쓰인다.

`natural_key`를 잘못 잡으면(예: 수집 시각을 섞으면) 재수집할 때마다 다른 `record_id`가
나오고 중복이 쌓인다. 수집기에서 가장 흔한 실수 지점이다.

**모든 datetime은 KST(+09:00) ISO 8601.** UTC로 저장하지 않는다 — 이 시스템의 모든
의미(유세 시간대, 통계 기준일, 선거법 기간)가 한국 현지시각 기준이기 때문이다.

### 왜 `observed_at`과 `ingested_at`을 나누는가
어제 수집한 2020년 총선 결과는 `observed_at=2020-04-15`, `ingested_at=어제`다.
이 둘을 섞으면 시계열 분석이 전부 망가진다.

### 왜 `derived_from`이 필요한가
"이 동네 40대 남성을 공략하라"는 결론이 **어느 데이터에서 나왔는지** 웹앱에서
역추적할 수 있어야 한다. 근거 없는 전략은 이 프로젝트에서 실패로 간주한다.
파생 레코드도 원천 레코드와 같은 계약을 쓰고, `derived_from`으로만 구분된다.

## 3. 지리 앵커 — 이 프로젝트의 최대 함정

모든 레코드는 행정구역에 고정된다. 지리가 없는 데이터(`geo_level: none`)는
전략에 쓸 수 없다.

문제는 **한국의 행정구역 코드 체계가 기관마다 다르다**는 것이다.

| 기관 | 코드 체계 |
|---|---|
| 행정안전부 | 법정동코드 10자리 / 행정동코드 |
| 통계청(KOSIS) | 통계용 행정구역 코드 |
| 중앙선관위 | 자체 선거구·투표구 코드 |

**결정: 내부 표준은 행정안전부 행정표준코드의 `행정기관코드` 7자리로 통일한다.**
(예: 서울 송파구 풍납1동 = `3230040`)
각 수집기는 자기 출처의 코드를 내부 표준으로 변환할 책임이 있고,
변환표는 `data/reference/geo_mapping.csv`에 둔다. 매핑 실패는 조용히 넘기지 않고
수집 실패로 처리한다.

### 코드 자릿수 규약

| geo_level | geo_code | 비고 |
|---|---|---|
| `nation` | 없음 (null) | |
| `sido` / `sigungu` / `emd` | 숫자 **7자리** | 행정기관코드는 계층과 무관하게 7자리다 |
| `point` | 숫자 7자리 | **지점도 '포함하는 행정동' 코드를 갖는다.** 좌표는 payload에 |
| `none` | 없음 (null) | 전략에 쓸 수 없는 데이터 |

자릿수가 계층을 구분하지 못하므로 **자릿수 검증은 약한 방어선**이다.
진짜 검증은 "그 코드가 출처/매핑표에 실재하는가"이며, 그건 수집기가 책임진다.

법정동코드(10자리)와 통계청 행정구역코드(8자리)는 **내부 표준이 아니다.**
매핑표의 `source_code` 로만 존재하며 `geo_code` 에 그대로 들어가면 거부된다.

`point`가 행정동 코드를 갖는 이유: 좌표만 있으면 인구·선거결과와 조인할 수 없다.
전통시장 하나가 어느 동에 속하는지 모르면 일정표를 짤 수 없다.

**선거구 ↔ 행정동 매핑도 데이터다.** 코드에 하드코딩하지 않는다.
선거구 획정은 매 선거마다 바뀌므로, 선관위 수집기가 가져와 레코드로 저장한다.

## 4. kind 목록

MVP(v0.1)에서 구현하는 것은 ✓ 표시.

| kind | 설명 | 주 출처 | MVP |
|---|---|---|:--:|
| `election_result` | 과거 선거 개표 결과 (투표구 단위) | 선관위 선거통계시스템 | ✓ |
| `population` | 주민등록 인구 (동×연령×성별) | 행안부 / KOSIS | ✓ |
| `news_article` | 뉴스 기사 메타 + 요약 | 네이버 뉴스 API, RSS, BIGKINDS | ✓ |
| `poll` | 여론조사 결과 | 중앙선거여론조사심의위 | |
| `poi` | 지점 (전통시장, 역, 아파트단지, 학교) | 지도 API, 공공데이터 | |
| `foot_traffic` | 시간대별 유동인구 | 통신사·카드사 공공데이터 | |
| `candidate` | 후보자 정보·공약·전과·재산 | 선관위 후보자정보 | |
| `local_issue` | 지역 현안 (파생) | 뉴스·민원에서 추출 | |
| `segment_profile` | 유권자 세그먼트 프로파일 (파생) | 분석 산출 | ✓ |

## 5. MVP 3종 payload

### 5.1 `election_result`
```jsonc
{
  "election_id": "2024-04-10-national-assembly",  // 선거 식별자
  "election_type": "national_assembly",           // enum
  "district_name": "서울 송파구 갑",
  "precinct": "풍납1동 제1투표소",                 // 투표구. null이면 동 전체 집계
  "eligible_voters": 12345,
  "total_votes": 8901,
  "results": [
    {"party": "A당", "candidate": "홍길동", "votes": 4200},
    {"party": "B당", "candidate": "김철수", "votes": 4100}
  ],
  "invalid_votes": 601
}
```

### 5.2 `population`
```jsonc
{
  "reference_month": "2026-08",
  "breakdown": [                 // 동 × 연령대 × 성별
    {"age_band": "20-29", "sex": "M", "count": 1820},
    {"age_band": "20-29", "sex": "F", "count": 1910}
  ],
  "total": 24500,
  "households": 10200
}
```
`age_band`는 10년 단위 고정(`0-9` … `80+`). 출처마다 5세/10세 단위가 다르므로
수집기가 10년 단위로 재집계한다.

### 5.3 `news_article`
```jsonc
{
  "title": "...",
  "publisher": "...",
  "published_at": "2026-08-30T14:20:00+09:00",
  "url": "...",
  "summary": "3문장 이내 요약",   // 원문 전문은 저장하지 않는다 (저작권)
  "full_text_stored": false,
  "mentioned_places": ["풍납동", "올림픽공원"],
  "mentioned_persons": [],
  "topics": ["재건축", "교통"],
  "sentiment": null                // L2가 채우는 파생 필드는 여기 두지 않고
}                                  // 별도 파생 레코드로 만든다
```

`full_text_stored`는 `source_license`가 `public_open`일 때만 `true`가 될 수 있다.
그 외 출처에서 전문을 저장하려 하면 계약 위반으로 거부된다 (모델이 강제).

**원칙: 수집기는 판단하지 않는다.** 감성분석·이슈분류 같은 해석은 전부 L2의
파생 레코드로 만든다. 수집기가 해석을 섞기 시작하면 재분석이 불가능해진다.

## 6. 레코드 수명

```
원본 파일(불변)              공통 레코드                질의용
data/raw/{collector}/     →  data/records/*.jsonl  →  data/votelink.db
{YYYY-MM-DD}/*.jsonl.gz                                (SQLite)
```

`data/raw/`는 절대 수정하지 않는다. 파싱 로직이 틀렸다는 걸 6개월 뒤에 알아도
원본에서 다시 만들 수 있어야 한다. 상세는 `docs/11-storage.md`.

## 7. 계약 위반 처리

- 봉투 필드 누락 / 타입 불일치 → **수집 실패**. 부분 저장하지 않는다.
- `geo_code` 매핑 실패 → 수집 실패 (조용히 null로 두지 않는다).
- 알 수 없는 `kind` → 분석기는 무시하고 로그만 남긴다 (전방 호환).
- `schema_version` 상위 버전 → 분석기는 처리 거부.
