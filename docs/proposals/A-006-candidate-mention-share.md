# A-006: candidate_mention_share (후보 단위 뉴스 언급 비교)

## 무엇을 계산하는가

한 선거구(sigungu)의 등록된 후보(우리 후보 + 상대 후보)별로, 최근 `window_weeks`
주간 뉴스 기사 중 그 후보의 실명이 걸린 기사 수를 집계하고, 등록된 후보 전체
언급 합 대비 점유율(share)과 전주 대비 변화율을 계산한다. 산출 레코드 1건은
**한 선거구의 한 시점(`as_of`) — 등록된 후보 전원의 주간 언급 시계열 묶음**에
대응한다 (`local_issue`가 한 선거구의 이슈 전체를 한 레코드에 담는 것과 같은 형태).

정당 단위 집계, 감성·논조 판단은 범위 밖이다. 순수 카운팅만 한다.

## 입력

- `news_article` (kind) — `data/shared/records/naver_news.jsonl`에 164,909건
  존재. **단, 현재 저장된 레코드 전부가 `mentioned_persons: []`다.** 수집기
  (`collectors/naver_news/collector.py`)가 person_terms 매칭 로직(P-006)을
  이미 갖고 있지만, 디스크의 데이터는 그 변경 이전에 수집된 것이라 아직
  반영되지 않았다. 이 분석기를 실행하려면 **먼저 `uv run votelink collect
  naver_news --reparse`로 재파싱**해 `mentioned_persons`를 채워야 한다.
- 캠프 로스터(`votelink/camp/` 경유 `candidates.yaml`의 `ours`/`opponents`) —
  후보 실명·정당·진영을 가져온다. **현재 존재하는 유일한 캠프는 테스트용
  `test1`이고 `candidates.yaml`도 더미 값(`name: "test1"`, `opponents: []`)
  이다.** 실제 송파구 갑 후보가 로스터에 등록되기 전까지는 이 분석기를
  돌려도 의미 있는 산출물이 나오지 않는다 — 구현·검증은 실제 로스터가
  들어온 뒤로 미룬다.

## 산출

- `kind`: `candidate_mention_share` (신규 — `votelink/contract/payloads.py`의
  `PAYLOAD_MODELS`에 등록 필요. **계약 변경이므로 구현 착수 전 사용자 승인
  필요.**)
- `geo_level`: `sigungu`. `geo_code`는 `news_pulse`/`local_issue`와 동일하게
  선거구의 시군구 코드(두 시군구에 걸치면 사전순 첫 코드).
- payload 초안:

```jsonc
{
  "as_of": "2026-09",              // 가장 최근 매칭 기사의 연-월
  "window_weeks": 12,              // news_pulse 와 동일 값 사용 (비교 가능성)
  "candidates": [                  // 로스터 순서: ours 먼저, opponents 는 candidates.yaml 순
    {
      "name": "홍길동",
      "party": "국민의힘",
      "lineage": "conservative",   // ours/opponents 및 party_lineage 참고
      "is_ours": true,
      "weekly": [                  // 오래된 주 순, ISO 월요일 시작
        {
          "week_start": "2026-06-16",
          "article_count": 12,
          "share_pct": 63.2,       // 그 주 등록 후보 전체 언급 합 대비 %. 분모 0 이면 null
          "wow_change_pct": 20.0   // 전주 대비 건수 변화율 %. 전주 0 이면 null
        }
      ],
      "total_articles": 140
    }
  ],
  "total_articles": 221,           // candidates[].total_articles 합 (불변식)
  "backfill_distorted": true       // news_pulse 와 같은 플래그. 검색 API 상한으로
                                    // 최근 주가 부풀었으면 true
}
```

## 왜 필요한가

`docs/00-overview.md`의 5대 최종 산출물 중 **갭 리포트**의 핵심 입력이다.
지금 있는 `news_pulse`/`issue_ranker`는 선거구 전체를 뭉뚱그려 "이 동네에
무슨 뉴스가 많은가"만 답하고, 캠프가 실제로 던지는 첫 질문("우리 후보가
상대보다 언론에 더/덜 나오고 있나")에는 답하지 못한다. 이 분석기가 그 갭을
수치로 만든다. 부차적으로 `spike`(급증) 시점과 겹쳐 보면 게시물 배치안의
타이밍 판단에도 참고자료가 된다.

## 판단이 들어가는 값

- `window_weeks` 기본값은 `news_pulse`와 **동일하게 12주**로 둔다. 다르게
  두면 두 분석기 산출물을 나란히 비교할 수 없어진다.
- `share_pct`의 분모는 **선거구 전체 뉴스 건수가 아니라 등록된 후보 전원의
  언급 합**이다 — "언론 노출의 share of voice"를 답하려는 것이지 "뉴스에서
  후보 얘기가 차지하는 비중"을 답하려는 게 아니기 때문. 이 판단은 제안서에
  남겨 이견이 있으면 재논의한다.
- `wow_change_pct`는 건수 기준 변화율이다. 전주 건수가 0이면 분모가 0이 되어
  `null`로 둔다 (0에서 어떤 수로 가도 무한대라 의미가 없다).
- 후보 매칭은 수집기가 만든 `mentioned_persons`의 **정확 문자열 일치**만
  본다. 동명이인·약칭 처리는 하지 않는다 (아래 제약 참고).

## 변별력

로스터가 더미인 현재 상태로는 검증할 수 없다 (모든 후보가 0건이거나 `test1`
하나만 존재). **실제 후보가 로스터에 등록된 뒤, 후보별 주간 건수 분포를 찍어
서로 다른 값이 나오는지 확인하는 절차를 구현 단계에서 반드시 수행한다** —
이 확인 없이는 `meta.verified`를 올리지 않는다. 원리상으로는 후보마다 검색어
(person_terms)가 다르므로 매칭 건수가 우연히 전부 같아질 가능성은 낮지만,
`voter_profile`의 선례(§9, 절대 득표율 기울기가 9/9 동일값을 낸 사례)가
있으므로 가정만으로 넘기지 않는다.

## 제약과 위험

- **선행 조건 미충족 상태**: 위 "입력" 절의 두 가지(① `--reparse` 미실행,
  ② 실제 후보 로스터 미등록)가 해소되기 전까지는 구현하더라도 산출물이
  전부 공백이거나 무의미하다. 구현 착수 전에 반드시 재확인한다.
- **동명이인·약칭 오탐**: `mentioned_persons`는 person_terms 문자열이
  기사 본문에 등장하면 매칭되므로, 흔한 이름이면 다른 인물을 언급한 기사가
  섞여 들어갈 수 있다. 이 왜곡은 수집기 단계에서 발생해 분석기가 그대로
  물려받는다 — 후보 이름이 특이하지 않다면 결과 해석에 주의가 필요하다는
  점을 웹앱 노출 시 함께 안내해야 한다.
- **정당 단위는 범위 밖**: `news_article` payload에 정당 필드가 없어(검색어로만
  쓰이고 결과에 저장되지 않음), 정당 단위 집계를 하려면 별도의 텍스트 매칭
  로직이 필요하다. 로드맵 3단계(이슈×후보 매트릭스) 이후 별도 제안서로 다룬다.
- **`backfill_distorted`의 후보별 적용**: `news_pulse`는 선거구 전체 기준으로
  이 플래그를 계산한다. 후보별로 검색 API 페이징 상한에 걸리는 시점이 다를
  수 있어, 선거구 전체 플래그를 그대로 물려받으면 특정 후보에는 과소·과대
  적용될 수 있다. 구현 시 후보별로 판정할지, 선거구 공통값을 물려받을지
  결정하고 근거를 `meta.yaml` 주석에 남긴다.
- **표본 크기**: 상대 후보가 아직 확정되지 않은 시기(캠프 온보딩 초기)에는
  `opponents: []`가 정상 상태다. 이 경우 `candidates` 배열이 `ours` 1건뿐이어도
  실패로 처리하지 않는다 — 상대 미확정은 오류가 아니라 선거 일정상 자연스러운
  상태다.
