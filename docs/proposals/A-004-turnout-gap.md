# A-004: 투표율 편차 (turnout_gap)

> 접두사 `A-` = analyzer. 1페이지를 넘기지 않는다.
>
> 상태: **제안** (2026-09-08). `## 계약 변경` 에 **사용자 승인이 필요하다.**
>
> `docs/new_process.md §4` 가 "다음 하나" 4순위로 꼽은 항목 — **새 수집기가 필요 없는
> 순수 분석 확장**이다. 입력(`election_result`)이 이미 다 쌓여 있다.

## 무엇을

행정동마다 **그 선거구 평균 대비 투표율이 얼마나 낮은가**를 선거 계열별로 계산한다.
산출 레코드 1건 = 행정동 1개 × 선거 계열 1개, 그 안에 회차별 시계열이 들어간다
(`voter_profile` 과 같은 모양).

"누구에게 투표할 것인가"보다 **"투표를 하는가"가 더 큰 지렛대인 동**을 찾는 것이 목적이다.

## 입력과 출력

| | |
|---|---|
| 입력 kind | `election_result` (emd 단위) |
| 입력 건수 | **4,453건 · 13개 회차** (실측 2026-09-08). 대선 8회 + 총선 5회 |
| 산출 kind | `turnout_gap` (**신규 — 계약 변경**) |
| geo_level | `emd` |
| 산출 건수 | 행정동 × 선거 계열. 송파갑 기준 9개 동 × 2계열 = 18건 |

`ElectionResultPayload` 가 `eligible_voters` 와 `total_votes` 를 이미 들고 있어
투표율은 그대로 계산된다. 새 필드도 새 수집기도 필요 없다.

## 왜 필요한가

`docs/00-overview.md §2` 의 5개 산출물 중 **타깃 전략**과 **갭 리포트**에 직접 들어간다.
`voter_profile` 이 "이 동은 어느 진영인가"를 답한다면 이건 "이 동은 애초에 투표장에
가는가"를 답한다. 성향이 우리 쪽인데 투표율이 낮은 동은 설득 대상이 아니라 **동원 대상**이고,
둘은 전혀 다른 자원을 쓴다.

## 계약 변경 — `turnout_gap` payload 추가

**사용자 승인 필요.** `RecordKind` 에 `TURNOUT_GAP` 을 더하고 아래 모델을
`votelink/contract/payloads.py` 의 `PAYLOAD_MODELS` 에 등록한다.
`docs/10-data-contract.md` 도 함께 고친다.

```python
class TurnoutPoint(_Payload):
    election_id: str
    turnout: float = Field(ge=0, le=1)  # 이 동의 투표율
    baseline: float = Field(ge=0, le=1)  # 같은 선거의 선거구 전체 투표율
    gap: float  # turnout - baseline. 음수면 평균보다 낮다
    eligible_voters: int = Field(ge=0)
    total_votes: int = Field(ge=0)


class TurnoutGapPayload(_Payload):
    election_type: ElectionType
    emd_name: str
    points: list[TurnoutPoint] = Field(min_length=1)  # 오래된 순, 같은 계열만
    latest_gap: float  # 최근 회차의 편차
    mean_gap: float  # 전 회차 평균 편차
    gap_slope: float  # 회차당 편차 변화량. 양수면 격차가 벌어지는 중
    below_baseline: bool  # mean_gap < 0
    elections_used: int
    as_of: str  # 최근 회차 선거일 "2025-06-03"
```

`Trend` enum 을 재사용하지 않는다 — 그건 진영 이동(`conservative_shift` 등) 전용이라
투표율에 의미가 없다. 새 enum 도 만들지 않고 `gap_slope` 를 float 로 그대로 낸다(아래).

## 계산 규칙

1. `election_result` 를 `(election_type, election_id)` 로 묶는다.
2. 회차마다 **선거구 전체 투표율**을 기준선으로 잡는다 —
   `sum(total_votes) / sum(eligible_voters)`. 동별 단순 평균이 아니라 **가중 합**이다.
   인구가 다른 동을 같은 무게로 세면 작은 동이 기준선을 흔든다.
3. 동별 `gap = 그 동 투표율 − 기준선`.
4. `mean_gap` = 전 회차 평균, `latest_gap` = 최근 회차,
   `gap_slope` = 회차 순번에 대한 gap 의 최소제곱 기울기.
5. `below_baseline = mean_gap < 0`.

**임계값을 두지 않는다.** GOTV 우선순위는 `below_baseline` 이 참인 동을
`mean_gap` 크기로 정렬하면 나온다 — 어디까지 갈지는 캠프의 자원 문제지 분석기가
정할 값이 아니다. 근거 없는 컷오프를 만들지 않는다.

`natural_key` 는 `turnout_gap|<election_type>|<geo_code>|<as_of>`
(`voter_profile` 이 계열 축을 키에 더한 것과 같은 이유).
`observed_at` 은 최근 회차의 선거일이다 — 분석 실행 시각이 아니다.

## 변별력 — 실측 (2026-09-08, 송파갑 9개 동)

`voter_profile` 이 겪은 함정("절대값을 쓰면 9개 동이 전부 같은 값")이 **여기엔 없었다.**
한 선거 안에서 동별 투표율이 이미 갈린다:

| 회차 | 선거구 투표율 | 동별 폭 |
|---|---|---|
| 1992 대선 | 81.8% | 3.4%p |
| 2002 대선 | 73.3% | 13.1%p |
| 2007 대선 | 65.5% | 17.4%p |
| 2008 총선 | 42.3% | 18.7%p |

그래도 **기준선 편차를 쓴다.** 절대 투표율은 회차별 전국 효과(1992년 81.8% vs 2008년
42.3%)가 지배해서 시계열로 비교할 수 없기 때문이다. 편차로 바꾸면 그 효과가 상쇄된다.

편차는 안정적이면서 뚜렷하다 — 오륜동은 7회 연속 `+1.9 → +3.3 → +6.8 → +9.7 → +8.4`,
방이2동은 `-1.5 → -2.4 → -6.3 → -7.7 → -7.7`. 순위가 뒤집히지 않는다.

**부수적 발견: 격차가 벌어지고 있다.** 1992년 ±2%p 였던 폭이 2007~2012년에는 ±8~11%p 다.
`gap_slope` 를 payload 에 넣는 이유가 이것이다.

## 이번 범위 아님

- **사전투표 비중.** `docs/new_process.md §3.2` 는 이 분석기에 "사전투표 비중 추이"도
  적어뒀지만 **`ElectionResultPayload` 에 사전/당일 구분 필드가 없다.** 수집기가 그
  데이터를 받지 않는다. 넣으려면 `nec_archive` 부터 고쳐야 하므로 별도 제안서다.
- 투표율 **예측**. 이 분석기는 과거를 기술할 뿐 다음 선거를 추정하지 않는다.
- 웹 화면(GOTV 지도). L3 는 자동으로 `unreviewed` 경고와 함께 뜬다 —
  뷰를 새로 그리는 것은 별도 작업이다.

## 제약과 위험

- **총선과 대선을 한 시계열에 섞지 않는다.** 투표율 수준이 근본적으로 다르다
  (2008 총선 42% vs 1992 대선 82%). `election_type` 이 키에 들어가는 이유다.
- **행정동 경계 변경.** 동이 분할·통합되면 같은 `geo_code` 의 과거 값이 다른 지역을
  가리킨다. `districts.yaml` 이 현재 획정만 담으므로 이 분석기는 그것을 알지 못한다.
- **총선은 선거구가 곧 기준선이라 상위 단위가 없다.** 대선은 시군구·시도 기준선도
  가능하지만 이번엔 선거구 기준선 하나만 쓴다.
- `confidence` 는 회차 수에 따라 낮춘다. 3회 미만이면 `gap_slope` 를 신뢰하지 않는다.
- 투표율이 낮은 동이 곧 우리 지지층인 것은 **아니다.** 이 분석기는 성향을 말하지 않는다 —
  `voter_profile` 과 함께 읽어야 의미가 생긴다. 화면에서 이 둘을 붙여 놓아야 한다.
