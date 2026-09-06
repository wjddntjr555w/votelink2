# A-003: 이슈 랭커 (issue_ranker)

> 상태: **구현 완료 · 미검증 (2026-09-06)**. `analyzers/issue_ranker/` + L3 이슈 보드
> 카드. 접두사 `A-` = analyzer, 착수 순서 3번 (`docs/new_process.md §4`).
> 계약에 `IssueTrend`(enums) + `LocalIssuePayload`·`IssueRank`(payloads) 추가
> (사용자 승인, 2026-09-06). `RecordKind.LOCAL_ISSUE` 는 이미 있었다.
> 실측: 입력 8,229 → 산출 1 · 격리 0 · 재실행 시 교체 1·신규 0(멱등). 불변식 성립
> (분류합 2,289 + 미분류 3,460 ≥ 총 5,516). trend 분포 3 falling / 4 rising / 3 flat
> (변별력 있음 — 아래 §계산 규칙).
> **`verified: false`** — 표본이 약하다. `naver_news` 의 "송파" 검색분은 스포츠·행사·
> 금융사 인사·부고가 70%+ 이고, 키워드를 좁게 조여도 미분류가 **83%** 이며 분류분
> 상위(`local_politics`·`greenbelt`·`redevelopment`)에도 "송파를 스쳐 언급한 국가
> 뉴스"(선관위 특검, 강남 재건축 비교)가 섞인다. substring 매칭으로는 못 가른다.
> 분석기 자체는 정상(순수·멱등·불변식·trend 변별력 5/5). 제대로 된 이슈 보드는
> 깨끗한 지역 뉴스 수집기(향후 C- 제안) 나 문맥을 읽는 LLM 분류가 있어야 나온다.
> `issue_lexicon.yaml` 은 `version: draft-2026-09-06` 로 두고, 카드에 표본 편향
> 경고를 상시 노출한다.
> 새 수집기 불필요 — `naver_news` 실측 완료분(8,229건)을 그대로 읽는다.

## 무엇을

선거구 하나마다 **레코드 1건**을 만든다. 그 안에 `news_article` 수집분을
이슈 카테고리로 분류해 **언급 빈도·최근성으로 랭킹한** 목록:

- 카테고리별 기사 수 · 전체 대비 비중
- **최근성 가중 점수** — 최근 주에 무게를 준 지수감쇠 합
- 카테고리별 추세 (rising / flat / falling) — 최근 절반 vs 이전 절반
- 카테고리별 누적 언급 지명 상위 N, 대표 헤드라인 최대 3개
- 어느 카테고리에도 안 걸린 기사 수 (`unclassified_count` — 투명성 지표)

웹앱 대시보드의 "이슈 보드" 카드 한 장과 1:1 대응한다. `news_pulse`(A-002)가
"뉴스가 **얼마나**"를 답한다면 이 분석기는 "**무엇에 대해**"를 답한다.

## 입력과 출력

| | kind | 출처 | 비고 |
|---|---|---|---|
| 입력 | `news_article` | `naver_news` | 선거구 시군구 코드로 필터, `confidence >= config` |
| 입력 | (참조) | `districts.yaml` | 선거구 → 시군구 코드 |
| 입력 | (참조) | `issue_lexicon.yaml` | 이슈 카테고리 ↔ 키워드 (신규) |
| **출력** | **`local_issue`** | 이 분석기 | 선거구당 1건 |

**모르는 `kind` 는 무시한다** (계약 §7). 개표·인구가 들어와도 이 분석기는 바뀌지 않는다.

## 왜 필요한가

최종 산출물 5종 중 **메시지**와 **갭 리포트**의 입력이다. `00-overview.md §4`가
"분석 2종" 중 하나로 못박아 뒀는데 아직 없다 — `voter_profile`이 "누구"를,
`news_pulse`가 "얼마나"를 답하고 나면 남은 축이 "무엇을"이다. 이슈 보드 없이는
"이 세그먼트에 무슨 말을 할 것인가"(메시지 단계)를 근거로 시작할 수 없다.

**이 분석기는 여론의 방향을 판정하지 않는다.** 감성(우리에게 유리한가)은
`news_article.sentiment` 를 채우는 별도 분석기의 일이고(`docs/new_process.md §3.2`
sentiment_trend), 여기서는 **무엇이 얼마나 자주, 최근에 언급됐는가**만 센다.

## 계약 변경 — `local_issue` payload 추가

`RecordKind.LOCAL_ISSUE` 는 `enums.py` 에 이미 있다. `enums.py` 에 `IssueTrend`
StrEnum 을 더하고 `payloads.py` 에 모델을 넣는다. A-001·A-002 가 밟은 절차와
동일하다. `TermCount` 는 A-002 것을 재사용한다.

```python
class IssueRank(_Payload):
    category: str  # issue_lexicon.yaml 의 키
    label: str  # 사람이 읽는 이름 ("재건축·재개발")
    article_count: int  # 이 카테고리로 분류된 기사 수 (window 안)
    share: float  # 분류된 기사 중 비중 (%). 비배타 분류라 합 > 100 가능 (le 제약 없음)
    recency_score: float  # 최근성 가중 합 (§계산 규칙)
    trend: IssueTrend  # rising / flat / falling (StrEnum, voter_profile 의 Trend 선례)
    top_places: list[TermCount]  # 이 카테고리 기사들의 mentioned_places 누적 상위
    sample_headlines: list[str]  # 대표 헤드라인 최대 3 (published_at 내림차순, 원문 title)


class LocalIssuePayload(_Payload):
    as_of: str  # 가장 최근 기사의 연-월 "2026-09" (순수성 — now() 안 씀)
    window_weeks: int  # 접은 주 수 (백필 꼬리 자름, 기본 12 — A-002 와 동일)
    total_articles: int  # window 안 · confidence 임계 이상의 분류 대상 기사 수
    issues: list[IssueRank]  # recency_score 내림차순. 동점은 category 오름차순
    unclassified_count: int  # 어느 카테고리에도 안 걸린 기사 수
    lexicon_version: str  # 사용한 issue_lexicon.yaml 의 version 필드 (재현성)
    backfill_distorted: bool  # 검색 API 상한으로 최근 주가 부풀었으면 True (A-002 와 동일)
```

**봉투 쪽:**
- `geo_level: sigungu`, `geo_code` = 선거구의 시군구 코드 (기사와 같은 레벨).
  두 시군구에 걸친 선거구는 사전순 첫 코드로 대표하고 note 에 명시 — 기사가
  구 단위라 더 쪼갤 수 없다 (A-002 와 동일한 제약)
- `observed_at` = 가장 최근 기사의 `observed_at`. 분석 실행 시각이 아니다
- `derived_from` = window 안 · 임계 이상의 **본 기사 전체**의 `record_id`
  (unclassified 도 포함 — 분류 실패도 "이 표본을 봤다"는 근거다)
- `natural_key` = `local_issue|{geo_code}|{as_of}` → 같은 달 재실행 시 같은 `record_id`
- `confidence` = **0.5 고정**. 파생이고(`news_pulse` 0.6보다 낮다), 어휘집 매칭이라는
  거친 분류가 한 단계 더 들어갔으며, 표본이 "송파"=지명 매칭이라 스포츠·연예
  노이즈를 포함한다

## 어휘집 — `data/reference/issue_lexicon.yaml` (신규)

이슈 카테고리와 그 키워드는 **지역적·정치적 판단**이다. `party_lineage.yaml`·
`districts.yaml` 과 같은 원칙으로 코드에 박지 않고 파일로 노출한다
(`docs/30-analysis-spec.md §8`). 이견이 있으면 파일만 고쳐 재분석한다.

```yaml
version: "2026-09-06"          # payload.lexicon_version 에 박힌다
categories:
  - key: redevelopment
    label: 재건축·재개발
    keywords: [재건축, 재개발, 정비사업, 리모델링, 주공, 가락시영, 조합, 안전진단]
  - key: transit
    label: 교통
    keywords: [위례신사선, 9호선, 지하철, GTX, 트램, 교통체증, 주차, 버스노선]
  # 교육 / 생활환경 / 안전 / 복지·의료 / 상권·경제 / 행정·의회 …
```

위는 **예시**다. 실제 카테고리·키워드는 구현 단계에서 사람이 송파갑 현안에 맞춰
채운다. 선거구별로 다르면 `districts.<id>` 아래로 분기한다.

## 계산 규칙

전부 **순수 함수**. 네트워크·LLM·난수·시계 없음. 같은 입력 → 같은 출력.
"현재 주"는 입력에서 파생한다 (`max(observed_at)` 의 주). **`datetime.now()` 를
쓰지 않는다** — 쓰면 재실행마다 최근성·추세가 바뀐다 (A-001·A-002 와 같은 이유).

- 입력 필터: 봉투 `confidence >= config.min_confidence` (기본 **0.7** — 구 단위 이상).
  0.9만 쓰면 표본이 절반 이하로 줄어 카테고리별 수가 무의미해진다
- 주 경계 = ISO 주 (월요일 시작). 기사 `published_at` 기준. `window_weeks` 밖은 버린다
- **분류**: 기사 `title + summary` 문자열에 카테고리 `keywords` 중 하나라도
  substring 으로 등장하면 그 카테고리로 카운트. `naver_news/text.py:match_terms`
  와 같은 방식 — 형태소 분석도 NER 도 아니다. **한 기사가 여러 카테고리에 걸리면
  전부 카운트**한다 (재건축+교통 기사는 둘 다). 그래서 `share` 합 > 100 가능
- `recency_score` = Σ (그 카테고리 주별 기사 수 × `0.5 ** (주차_역순 / half_life_weeks)`).
  `half_life_weeks` 기본 **4** (config). 최근 4주가 8주 전의 2배 무게
- `trend` = 이 카테고리가 **분류된 기사 중 차지하는 비중**이 최근 절반에서 이전
  절반보다 얼마나 커졌나. `recent_share / prior_share` 가 `>= 1.3` → rising,
  `<= 0.77` → falling, 그 사이 → flat. **절대량이 아니라 비중을 쓰는 이유**: 첫
  백필은 모든 카테고리의 절대량을 함께 부풀려서, 절대 기울기로 재면 10개 중 9개가
  rising 으로 나온다(실측). 비중으로 바꾸자 3 falling / 4 rising / 3 flat 로 갈렸다 —
  `voter_profile` 이 절대 기울기 → 지역구 편차로 바꾼 것과 같은 교훈
  (`docs/30-analysis-spec.md §9`). 임계값은 config
- `issues` 정렬: `recency_score` 내림차순, 동점은 `category` 오름차순 (결정적)
- `top_places` 상위 5, `sample_headlines` 는 `published_at` 내림차순 상위 3
  (동점은 정규화 url 오름차순). 전부 결정적
- 불변식: `sum(issue.article_count) + unclassified_count >= total_articles`
  (중복 분류 때문에 등호가 아니라 `>=`)

## 실패 처리 (`docs/30-analysis-spec.md §6`)

- 입력 0건 → **실패**. "분석이 돌았는데 이슈가 없다"와 "뉴스 수집이 안 됐다"를
  구분할 수 없다
- `issue_lexicon.yaml` 결손·파싱 실패 → `AnalyzeError`, 전체 중단
- 개별 기사 분류 중 예외(깨진 payload 등) → `Rejected` 격리, 격리율 > 5% 면 저장 안 함

## 웹앱 — 이슈 보드 카드 (L3, 대시보드)

`loader.load_local_issue(settings, district_id)` → `viewmodel.build_issue_board()` →
대시보드에서 "뉴스 펄스" 카드 옆. `_output.html` 매크로 통과 (컴플라이언스). 표시:

- 상위 5개 카테고리 가로 막대 (recency_score), 추세 화살표 (↑ rising / → flat / ↓ falling)
- 카테고리별 대표 헤드라인 1~3줄, 언급 지명 칩
- "분류 안 됨 N건" 을 숨기지 않고 표시 — 이게 크면 어휘집 보강 신호

`compliance.yaml` 에 `local_issue` 항목 추가 (derived: true, distribution:
internal_only, ai_generated: false, status: unreviewed) — 단 **레코드가 실제로
생긴 뒤**(web 커밋)에 넣는다. 파일 27–31줄이 "아직 없는 kind 를 미리 적지 않는다"
라고 못박고 있고, fail-closed 라 안 적어도 `unreviewed` 로 보호된다. 위험도 **저** —
공개 뉴스의 재정리, 해석이 거의 없다 (`docs/new_process.md §5`).

## 왜 LLM 을 쓰지 않는가 — A-002 예고와의 차이

A-002 는 "이슈 분류는 A-003 이 **URL 키 캐시로 결정성을 확보**해 별도로 단다"고
적었다. 즉 LLM 분류 + 기사 URL 로 캐싱하는 그림이었다. **v1 은 캐시 없는 순수
substring 어휘집 매칭으로 한다** (news_pulse 도 캐시를 안 쓴다):

1. `docs/30-analysis-spec.md §5` — "LLM 을 쓰는 분석은 별도 분석기로 분리한다".
   `compute()` 안에 LLM 을 넣으면(캐시가 있어도) 첫 실행의 비결정성이 근거
   추적을 무의미하게 만든다
2. `docs/SETUP.md §6` — Anthropic API 키는 "아직 아님 · 비용 발생 지점"으로 못박혀
   있다 (현행 §5 는 네이버 뉴스 설정이다). 어휘집은 키 없이, 오프라인으로 돈다
3. 재현성 — `voter_profile` 이 겪은 교훈(순수 함수라야 근거를 댈 수 있다)이 그대로 적용된다

어휘집으로 **변별력이 안 나오면**(카테고리가 뭉개지거나 unclassified 가 과반)
그때 LLM 기반 세밀 분류를 `sentiment_trend` 계열의 별도 분석기로 분리해 단다.
이 분석기(issue_ranker)의 순수성은 유지한다.

**실측 결과**: 초기 어휘집은 미분류 62.7%, `environment` 가 분류분의 49.5% 를
삼켰다(`쓰레기`·`석촌호수` 키워드가 송파구 폐기물 보도·석촌호수 행사 기사를 싹쓸이).
키워드를 고유명·복합어 위주로 좁히자 미분류 83%, `environment` 6.7% 로 정상화됐지만,
그만큼 표본에 실제 지역 현안이 적다는 뜻이다. 분류분 상위는 여전히 `local_politics`
(선관위 특검=국가), `greenbelt`·`redevelopment`(강남 혼입)가 차지한다. **어휘집 튜닝의
한계** — 근본 원인은 표본이지 매칭 방식이 아니다. trend 는 비중 기반으로 바꾼 덕에
백필 왜곡 속에서도 변별력이 나왔다(5 falling / 5 rising).

## 제약과 위험

- **어휘집이 곧 편집 판단이다.** 어떤 카테고리를 두고 어떤 키워드를 넣느냐가
  결과를 정한다. `lexicon_version` 을 payload 에 박아 재현 가능하게 한다
- **표본 편향** (A-002 와 동일). naver 검색어가 "송파" 등 지명이라 잠실운동장·
  올림픽공원발 스포츠·연예 기사가 섞인다. 이 분석기의 어휘집이 정치·생활 이슈
  키워드라 스포츠 기사는 대부분 `unclassified` 로 떨어진다 — 그 수를 카드에 노출한다
- **배타 분류가 아니다.** `share` 합이 100 을 넘을 수 있다. 의도된 것 —
  한 현안이 여러 축에 걸치는 것이 실제 모습이다
- **백필 왜곡** (A-002 와 동일). 검색 API 는 검색어당 1,000건 상한이라 과거로
  갈수록 성기다. `window_weeks` 12 로 꼬리를 자르고 `backfill_distorted` 로 표시
- **행정동 귀속 불가.** 기사는 sigungu 레벨. `top_places` 는 사전 매칭된 지명
  참고용일 뿐 "동별 이슈 지도"는 만들 수 없다. `docs/new_process.md §3.1` 이
  "동·이슈별"이라 했으나 sigungu 가 한계다
- 데이터량: 선거구당 1레코드. 무시할 수준
- 법적 검토: 기사 메타의 집계·인용. `sample_headlines` 는 원문 제목 최대 3개
  (이미 `news_article` 에 저장된 값). 본문 없음. 산출물이 외부로 나가면
  `docs/90-compliance.md` 검증 대상 (공표 금지기간 포함)
