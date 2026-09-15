# A-007: issue_candidate_matrix (이슈 × 후보 교차표)

## 무엇을 계산하는가

한 선거구(sigungu)에서, 이슈 카테고리별로 그 카테고리 기사에 어떤 등록 후보(우리
후보 + 상대)가 함께 언급됐는지 교차 집계한다. 산출 레코드 1건은 **한 선거구의 한
시점(`as_of`) — 카테고리별 후보 언급 교차표 전체**에 대응한다(`local_issue`가
선거구 이슈 전체를 한 레코드에 담는 것과 같은 형태).

정당 단위·감성/유불리 판정은 범위 밖. 순수 카운팅만 한다.

## 사전 확인 — 기존 산출물로 근사할 수 있는가

**안 된다.** `local_issue`(카테고리별 집계)와 `candidate_mention_share`(후보별 집계)는
둘 다 `news_article`을 각자 다른 축으로 집계한 뒤 버린 결과라, "이 기사가 어느
카테고리이면서 동시에 어느 후보를 언급했는가"라는 **기사 단위 연결 정보가 남아있지
않다.** `local_issue.issues[].sample_headlines`는 대표 헤드라인 최대 3개일 뿐 전체
기사 목록이 아니고, `candidate_mention_share`의 `derived_from`도 후보별로 나뉘지
않은 레코드 전체 근거 목록이다. 따라서 이 분석기는 `news_article`을 **다시 읽어**
이슈 어휘집과 후보 로스터를 같은 기사 집합에 동시 적용해야 한다.

## 입력

- `news_article` (kind) — `issue_ranker`/`candidate_mention_share`와 같은 방식으로
  district의 `sigungu_codes`로 필터링.
- 참조 데이터 `data/shared/reference/issue_lexicon.yaml` — `issue_ranker`가 쓰는
  것과 **같은 파일**(title+summary에 keyword가 substring으로 등장하면 그 카테고리).
  분석기 폴더 독립 원칙(`docs/30-analysis-spec.md §3`) 때문에 `issue_ranker`의
  코드는 재사용하지 않고 매칭 로직만 이 분석기의 `calc.py`에 다시 구현한다 — 파일은
  공유해도 코드는 공유하지 않는다.
- 캠프 로스터(`votelink/camp/` 경유 `candidates.yaml`) — `candidate_mention_share`와
  같은 소스지만 마찬가지로 로스터 병합 로직은 그쪽 `calc.py`를 import하지 않고
  이 분석기 안에 다시 둔다(같은 이유).
- **둘 다 지금 있다.** `issue_lexicon.yaml`은 이미 서비스 중이고 로스터는 강남구 갑
  테스트 캠프로 확인 가능하다.

## 산출

- `kind`: `issue_candidate_matrix` (신규 — `PAYLOAD_MODELS` 등록 필요. **계약
  변경이므로 구현 착수 전 사용자 승인 필요.**)
- `geo_level`: `sigungu`. `geo_code`는 `local_issue`/`candidate_mention_share`와
  동일 규칙(두 시군구에 걸치면 사전순 첫 코드).
- payload 초안:

```jsonc
{
  "as_of": "2026-09",              // 가장 최근 매칭 기사의 연-월
  "window_weeks": 12,              // news_pulse 계열과 동일 값 (비교 가능성)
  "lexicon_version": "draft-2026-09-06",  // issue_ranker와 같은 값이면 같은 어휘집 버전
  "total_articles": 512,           // window 안 · sigungu-scoped 전체 기사 수
  "categories": [                  // 후보 언급이 1건이라도 있는 카테고리만. article_count 내림차순
    {
      "category": "redevelopment",
      "label": "재건축·재개발",
      "article_count": 180,        // local_issue와 같은 정의: 이 카테고리로 분류된 기사 수
      "candidates": [              // count 내림차순
        {"name": "홍길동", "is_ours": true, "count": 12, "share_of_category": 6.7},
        {"name": "김철수", "is_ours": false, "count": 3, "share_of_category": 1.7}
      ]
    }
  ]
}
```
`share_of_category = count / article_count * 100`. 카테고리 안 후보 언급 합이
`article_count`를 넘을 수 있다(한 기사에 후보가 여럿 언급될 수 있음 — 비배타적).

## 왜 필요한가

로드맵(`docs/roadmap-news-content.md`) 티어3 14번. `docs/00-overview.md` 5대
산출물 중 **갭 리포트**의 재료 — "우리 후보가 어느 이슈에서 노출되고 있는지"와
"상대는 어느 이슈에서 노출되고 있는지"를 나란히 보면, 메시지를 어느 이슈에 집중할지
판단 근거가 된다.

## 판단이 들어가는 값

- `window_weeks` 기본 12 — `news_pulse`/`candidate_mention_share`와 맞춘다.
- 카테고리는 후보 언급이 1건 이상 있는 것만 남긴다 — 후보와 전혀 안 엮인 카테고리는
  이 매트릭스의 목적(이슈-후보 연결)에 정보가 없다.
- 후보 매칭은 `mentioned_persons`의 정확 문자열 일치, 이슈 매칭은 어휘집 substring
  일치 — 둘 다 이미 있는 두 분석기와 같은 규칙을 그대로 가져온다. 새 임계값 없음.

## 변별력

카테고리별로 후보 간 `count`가 다르게 나오는지, 같은 후보라도 카테고리마다
`count`가 다르게 나오는지 확인한다. 손으로 만든 축소판 입력(후보 2명 × 카테고리
2개, 기사 조합을 손으로 배치)으로 계산이 맞는지 먼저 검증하고, 실제 데이터는
강남구 갑 테스트 캠프로 실행해본다.

**단, `issue_lexicon.yaml`은 송파구 갑 지명·거리명 위주 키워드다** (가락시영,
잠실주공, 탄천, 성내천, 위례신사선 등) — 강남구 갑 기사에는 거의 매칭되지 않을
가능성이 높다. 실데이터 실행에서 카테고리가 0~1개만 나와도 이 분석기의 결함이
아니라 어휘집의 지리적 특이성 때문이라는 걸 미리 적어둔다.

## 제약과 위험

- **이중으로 막혀 있다.** ① `candidate_mention_share`와 같은 이유로 송파구 갑
  실제 후보 로스터가 없다. ② `issue_ranker`와 같은 이유로 어휘집이 초안이고
  표본이 스포츠·행사 위주로 오염돼 있다(현재 미분류 ~82%). 두 선행 분석기가 둘 다
  `verified: false`인 상태라, 이 분석기는 그 위에 쌓이는 만큼 실측 검증이 더 멀다
  — 스캐폴딩·단위테스트·구조 검증까지만 이번에 하고, `verified` 승격은 두 선행
  조건이 풀린 뒤로 미룬다.
- 한 기사가 여러 카테고리·여러 후보에 동시에 걸릴 수 있어 `count`들의 합이 어느
  분모와도 깔끔하게 안 맞는다 — 등식이 아니라 각 셀의 절대값만 신뢰한다.
- 후보 매칭·이슈 매칭 둘 다 오탐 위험(동명이인, 국가뉴스 혼입)을 이미 알려진 채로
  물려받는다 — 두 위험이 곱해지므로 이 매트릭스의 개별 셀은 두 선행 산출물 중
  어느 것보다도 신뢰도가 낮다고 본다(`confidence` 값에 반영).
