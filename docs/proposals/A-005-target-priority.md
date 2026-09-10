# A-005: 타깃 동 우선순위 (`target_priority`)

> `A-` = 분석기 제안서. 1페이지를 넘기면 둘로 쪼갤 신호다.

## 무엇을 계산하는가

행정동 하나 × 선거 계열 하나에 대해 **"선거 자원을 어디부터 쓸지"** 를 판단할 요인
점수와 선거구 내 순위를 낸다. 산출 레코드 1건 = `(행정동, election_type)` 한 쌍.

이 분석기는 **진영 중립**이다 (`party_lineage.yaml` 만이 정치 판단, 렌즈는 L3 — P-001).
"우리 동원 대상"인지 "우리 설득 대상"인지는 캠프 렌즈가 L3 에서 정한다. 여기서는
**어느 편이 봐도 같은 요인**(규모·변동성·경합도·투표율 여유)과, 그것을 섞은 중립
`attention_score` 만 낸다.

## 입력

| kind | 건수 | 있는가 |
|---|---|---|
| `segment_profile` | 행정동 × 계열당 1건 (`swing`, `trend`, `lean_series` 최신 `camp_share`, `population_total`, `gap_district`) | ✅ `data/shared/records/voter_profile.jsonl` |
| `turnout_gap` | 행정동 × 계열당 1건 (`mean_gap`, `latest_gap`, `gap_slope`, `below_baseline`) | ✅ `data/shared/records/turnout_gap.jsonl` |

**raw `population` 은 읽지 않는다** — 규모는 `segment_profile.population_total` 로 충분하고,
같은 `as_of` 라 조인이 없다. (사용자 초안은 population 을 3번째 입력으로 들었으나, 이미
segment_profile 에 실려 있어 뺀다.)

두 입력은 `geo_code + election_type` 로 조인한다. `turnout_gap` 이 없는 동은 동원 요인을
빼고 계산하고 `confidence` 를 낮춘다 (전체 실패 아님).

## 산출

- **kind**: `target_priority` — **신규. `payloads.py` + `enums.py` + 계약 §4 수정 = 사용자 승인 필요.**
- **geo_level**: `emd`
- **natural_key**: `target_priority|<election_type>|<geo_code>|<as_of>` (`voter_profile` 과 같은 축 규칙)
- **as_of**: `segment_profile.as_of` (YYYY-MM)
- **payload 주요 필드** (전부 0~100 지수, 선거구 내 정규화):

| 필드 | 뜻 |
|---|---|
| `size_index` | 선거구 내 인구 백분위 |
| `volatility_index` | `swing`(보수 시계열 최댓값−최솟값 %p)의 선거구 내 정규화 — 설득 여지 |
| `competitiveness_index` | 최신 회차 `|보수−진보| 격차`가 작을수록 높음 — 경합도 |
| `turnout_headroom` | `max(0, -mean_gap)` 정규화 — 동원 여유. `below_baseline` 일 때만 > 0 |
| `attention_score` | 위 넷의 가중 블렌드(가중치는 `meta.config`). **렌즈 무관** |
| `rank` | 선거구 내 `attention_score` 내림차순 순위 |
| `segment_note` | 중립 유형: `swing_battleground` / `mobilization_target` / `persuasion_ground` / `safe` / `low_stakes` |
| `conservative_share` · `progressive_share` · `population_total` | L3 가 렌즈를 씌울 원자료 |

## 왜 필요한가

최종 산출물 5종 중 **타깃전략**. "설득이냐 동원이냐, 어디부터냐"는 캠프의 1번 질문이고,
지금은 대시보드에 지표가 흩어져 있을 뿐 순위가 없다. `voter_profile`(누구를 찍나) +
`turnout_gap`(투표장에 가나)을 한 줄로 합쳐 **행동 가능한 목록**을 만든다.

## 판단이 들어가는 값 (`meta.config`, 이유 주석 필수)

- `weights`: `size` / `volatility` / `competitiveness` / `turnout_headroom` 의 블렌드 가중치.
  기본 `0.2 / 0.3 / 0.3 / 0.2` — 자원 배분은 "바꿀 수 있는 표(변동성·경합)"를 규모보다
  약간 무겁게. **민감도를 재서 순위가 가중치에 얼마나 흔들리는지 제안서에 남긴다.**
- `segment_note` 컷: `volatility_index >= 60 & competitiveness_index >= 60` → battleground,
  `turnout_headroom >= 60 & competitiveness_index >= 40` → mobilization_target, 등.
- 선거구 특화 값은 `districts.<id>`, 무관한 값은 `common`.

## 변별력 (검증 완료 2026-09-10, seoul_songpa_gap)

모든 입력 지수를 **선거구 내 min-max 정규화**로 만들어 전국 공통 흐름을 상쇄했다.
결과:

- `attention_score` 가 대선·총선 **두 계열 모두에서 9개 동 전부 다른 값**(9/9 distinct).
  대선 32.5~78.3, 총선 22.9~75.6.
- **1위(방이2동)와 최하위 두 동이 두 계열에서 일치.** 계열이 독립인데 순위 양끝이
  같은 것이 우연이 아니라는 근거 (`turnout_gap` 검증과 같은 논리).
- **가중치 민감도**: 기본값 대비 `equal`·`size_heavy` 에서 1~3위 순서 불변.
  `persuade_heavy`(0.1/0.4/0.4/0.1) 극단값에서만 중위권이 뒤섞임. → "어디부터"(1위)는
  가중치 논쟁과 무관, 중위권만 흔들린다.
- `swing_battleground` 는 이 선거구에서 안 붙는다 — 변동성 큰 동과 접전인 동이 갈린다.
  라벨은 다른 선거구용으로 살려둔다. 접전이지만 변동성·GOTV 여지가 지렛대가 아닌 동은
  `persuasion_ground` 로 분리했다.

## 제약과 위험

- **표본**: 선거구당 동 9개. 회귀·학습 없음. 백분위 정규화 n=9 는 거칠다 — 순위는
  대략의 3구간(상/중/하)으로 읽고, 1위와 2위 차이를 과신하지 않는다. 화면에도 그렇게.
- **`turnout_gap` 결측 동**: 동원 요인 없이 계산 → `confidence` 하향, `segment_note` 는
  `mobilization_target` 후보에서 제외.
- **가중치가 결론을 만든다**: 순위가 `weights` 에 민감하면 그 논쟁을 먼저 해야 한다.
  민감도 결과를 검증 단계에서 확인.
- **`confidence`**: 파생이므로 1.0 아님. 기본 0.55, 두 입력 다 있으면 0.65, `turnout_gap`
  결측이면 0.4.
- L3 표시: 정책표에 없으므로 자동 `unreviewed` 경고 — 정상 (fail-closed).
