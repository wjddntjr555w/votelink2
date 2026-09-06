# A-002: 뉴스 펄스 (news_pulse)

> 상태: **구현 완료 · 미검증 (2026-09-06)**. `analyzers/news_pulse/`.
> 계약에 `news_pulse` payload 추가(사용자 승인). 입력 8,229 → 산출 1 · 격리 0 · 멱등.
> `verified: false` — naver 검색 API 상한이 첫 백필의 최근 주를 부풀려 spike 판정을
> 아직 신뢰할 수 없다. `backfill_distorted` 가 이를 표시하고, 증분 수집이 쌓이면 올린다.
> 접두사 `A-` = analyzer. 착수 순서 2번 (뉴스 수집기 위에 올리는 L2/L3 중 LLM 없는 것 먼저).
> 선행: A-001 과 같은 방식으로 `news_pulse` payload 모델을 계약에 추가해야 한다
> (`RecordKind` 에는 없음 — 아래 §계약 변경). **사용자 승인 필요.**

## 무엇을

선거구 하나마다 **레코드 1건**을 만든다. 그 안에 `news_article` 수집분을
**주 단위로 접은** 시계열:

- 주별 기사 수 (전체 / 동·지명 직접 언급분)
- 주별 언론사 다양성 (고유 도메인 수, 상위 언론사 집중도)
- 누적 언급 지명·인물 빈도 상위 N
- **급증 주 플래그** — 최근 주의 기사 수가 직전 8주 평균 대비 z-score ≥ 임계값

웹앱 대시보드의 "뉴스 펄스" 카드 한 장과 1:1 대응한다.

## 입력과 출력

| | kind | 출처 | 비고 |
|---|---|---|---|
| 입력 | `news_article` | `naver_news` | 선거구 시군구 코드로 필터 |
| 입력 | (참조) | `districts.yaml` | 선거구 → 시군구 코드 |
| **출력** | **`news_pulse`** | 이 분석기 | 선거구당 1건 |

**모르는 `kind` 는 무시한다** (계약 §7). 개표·인구가 들어와도 이 분석기는 바뀌지 않는다.

## 왜 필요한가

최종 산출물 5종 중 **일정표**와 **메시지**의 입력이다. "이번 주 우리 지역에서
뉴스가 얼마나, 어디서, 무엇에 대해 돌았는가"에 답한다. 급증 주는 대응이
필요한 시점을 가리킨다 — 무엇에 대응할지(=이슈 분류)는 A-003(issue_ranker)의
일이고, 이 분석기는 **양과 분포만** 센다. LLM 없이 재현 가능해야 하기 때문이다.

## 계약 변경 — `news_pulse` payload 추가

`RecordKind` 에 `NEWS_PULSE = "news_pulse"` 를 추가하고 `payloads.py` 에 모델을 넣는다.
A-001 이 `segment_profile` 로 밟은 절차와 동일하다.

```python
class NewsWeekPoint(_Payload):
    week_start: str            # ISO 월요일 "2026-09-01"
    article_count: int
    district_specific_count: int   # confidence >= 0.9 인 것
    publisher_count: int       # 고유 도메인 수
    top_publisher_share: float # 최다 언론사 비중 0~1
    spike: bool                # 이 주가 급증 주인가
    spike_z: float | None      # z-score. 히스토리 8주 미만이면 None


class NewsPulsePayload(_Payload):
    as_of: str                 # 가장 최근 기사의 연-월 "2026-09" (순수성 — now() 안 씀)
    window_weeks: int          # 접은 주 수
    weekly: list[NewsWeekPoint]  # 오래된 주 순. total_articles 는 이 합과 일치(불변식)
    total_articles: int
    top_places: list[TermCount]     # 누적 상위 (term, count)
    top_persons: list[TermCount]
    top_publishers: list[TermCount]
    backfill_distorted: bool   # 검색 API 상한으로 최근 주가 부풀었으면 True
```

**봉투 쪽:**
- `geo_level: sigungu`, `geo_code` = 선거구의 시군구 코드 (기사와 같은 레벨).
  두 시군구에 걸친 선거구(중구성동구 을)는 **첫 시군구 코드**로 대표하고
  note 에 명시 — 기사 자체가 구 단위라 더 쪼갤 수 없다
- `observed_at` = 가장 최근 기사의 `observed_at`. 분석 실행 시각이 아니다
- `derived_from` = 접은 기사 전체의 `record_id`
- `natural_key` = `news_pulse|{geo_code}|{as_of}` → 같은 날 재실행 시 같은 `record_id`
- `confidence` = 항상 0.6 고정. 파생이고, 기사 표본이 "송파"=지명 매칭이라
  노이즈(스포츠·연예)를 포함한다. 그 필터는 A-003 의 일이다

## 계산 규칙

전부 **순수 함수**. 네트워크·LLM·난수 없음. 같은 입력 → 같은 출력.
"현재 주"는 입력에서 파생한다 (`max(observed_at)` 의 주). **`datetime.now()` 를
쓰지 않는다** — 쓰면 재실행마다 급증 판정이 바뀐다.

- 주 경계 = ISO 주 (월요일 시작). 기사 `published_at` 기준
- `publisher` = `NewsArticlePayload.publisher` 그대로 (L1 이 이미 도메인→언론사명)
- `spike_z` = (그 주 기사 수 − 직전 8주 평균) / 직전 8주 표준편차.
  표준편차 0 이거나 히스토리 8주 미만이면 `None`, `spike=False`
- `spike` = `spike_z is not None and spike_z >= config.spike_z_threshold` (기본 2.0)
- `top_*` 는 상위 10, 동점은 이름 오름차순 (결정적)

## 웹앱 — 뉴스 펄스 카드 (L3, 대시보드)

`loader.load_news_pulse(settings, district_id)` → `viewmodel.build_pulse_card()` →
대시보드 상단 카드. `_output.html` 매크로 통과 (컴플라이언스). 표시:

- 주별 막대 (인라인 SVG, 급증 주는 강조색). 데이터 없는 주는 0 이 아니라 끊김
- "최근 주 N건 (직전 8주 평균 M) · 급증" 또는 "평상"
- 상위 언론사·지명 칩

`compliance.yaml` 에 `news_pulse` 항목 추가 (derived: true, distribution: internal_only,
ai_generated: false, status: unreviewed).

## 제약과 위험

- **표본이 편향돼 있다.** naver_news 검색어가 "송파" 등 지명이라 잠실운동장·
  올림픽공원발 스포츠 기사가 섞인다. 이 분석기는 그걸 안 거른다 — 양만 센다.
  거르려면 A-003. 카드에 이 한계를 명시한다
- **첫 수집이 8천 건 백필이라 첫 실행의 "주별"이 왜곡된다.** naver API 는
  검색어당 1,000건 상한이라 과거로 갈수록 성기다. `window_weeks` 를 12 정도로
  잡아 백필 꼬리를 자른다
- **행정동 귀속 불가.** 기사는 sigungu 레벨. 동별 펄스는 만들 수 없다
- 데이터량: 선거구당 1레코드. 무시할 수준
- 법적 검토: 기사 메타의 집계·인용이며 본문 저장 없음. 산출물이 외부로 나가면
  `docs/90-compliance.md` 검증 대상 (공표 금지기간 포함)
- **LLM 을 넣지 않는다.** 넣으면 재현성이 깨진다 (A-001 §마지막과 같은 이유).
  이슈 분류는 A-003 이 URL 키 캐시로 결정성을 확보해 별도로 단다
