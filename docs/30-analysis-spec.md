# 분석기(L2) 공통 규약

> 상태: v1 구현됨 (`votelink/analyze/`, `analyzers/voter_profile/`)
> 분석기를 만들거나 고칠 때 읽을 문서는 **이것 + 해당 `analyzers/<id>/` 뿐**이다.
> 다른 분석기의 구현을 참고하러 읽지 않는다.

## 1. 분석기란 무엇인가

공통 레코드를 읽어 **파생 레코드**를 만드는 것. 그게 전부다.

```
data/shared/records/*.jsonl  →  분석기  →  data/shared/records/<analyzer_id>.jsonl
   (원천 + 다른 파생)              (파생. 형식은 원천과 동일)
```

파생도 원천과 **같은 계약**(`docs/10-data-contract.md`)을 쓴다. 다른 점은
`derived_from` 이 비어 있지 않다는 것 하나뿐이다.

## 2. 수집기와의 대칭

구조가 같으면 새로 배울 게 없다. 이 대칭은 의도된 것이다.

| L1 (수집) | L2 (분석) | 왜 |
|---|---|---|
| `fetch()` 네트워크만 | `load()` **디스크만** | 부작용을 한 곳에 가둔다 |
| `parse()` 순수 함수 | `compute()` **순수 함수** | 재실행하면 같은 결과 |
| `map_items` 항목 격리 | 동일 | 9개 중 1개 실패가 8개를 죽이지 않게 |
| `data/shared/rejected/` | 동일 | 조용한 누락을 만들지 않는다 |
| `collectors/<id>/` | `analyzers/<id>/` | 하나 고치는 비용이 개수와 무관하게 |
| `collect <id>` | `analyze <id>` | |
| `registry.yaml` | 동일 | 전체 목록은 파일 하나만 본다 |

**L1과 L2는 서로의 코드를 import 하지 않는다** (`docs/00-overview.md §3`).
공통으로 쓰는 레코드 입출력은 `votelink/store.py` 에 있다.

## 3. 폴더 구조

```
analyzers/<id>/
  analyzer.py     Analyzer 클래스 (이 이름이어야 registry 가 찾는다)
  meta.yaml       id, inputs, outputs, geo_level, config
  calc.py         (선택) 순수 계산. 레코드도 파일도 모르는 함수들
  tests/
```

폴더 밖으로 코드를 흘리지 않는다.

## 4. `load()` — 입력

기본 구현으로 충분한 경우가 많다. `meta.inputs` 에 적은 kind 를 전부 읽어온다.

```python
store.load_records(self.meta.inputs, exclude_owners=[self.id])
```

- **모르는 `kind` 와 상위 `schema_version` 은 조용히 건너뛴다** (계약 §7).
  새 수집기가 붙어도 기존 분석기가 죽지 않는다.
- **자기 출력은 제외한다.** 자기 결론을 입력으로 다시 먹으면 재실행마다 결과가 흘러간다.
- 네트워크 금지.

## 5. `compute()` — 계산

**순수 함수다.** 네트워크 금지, LLM 금지, 난수 금지, 시계 금지.
같은 입력이면 언제 돌려도 같은 결과가 나와야 한다.

이게 깨지면 `derived_from` 으로 근거를 역추적해도 *그 근거가 그 결론을 낳았는지*
확인할 수 없다. 근거를 못 대는 전략은 이 프로젝트에서 실패로 간주한다.

**LLM 을 쓰는 분석은 별도 분석기로 분리한다.** 수치 트랙과 텍스트 트랙을 섞으면
"왜 이런 결론인지"를 설명할 수 없게 된다 (`docs/00-overview.md §4-1`).

### 파생 레코드를 만들 때

| 필드 | 규칙 |
|---|---|
| `collector_id` | 분석기 id 를 넣는다 (레코드를 만든 주체) |
| `source_name` | 분석기임이 드러나게. 원 출처는 `derived_from` 이 가리킨다 |
| `observed_at` | **입력이 가리키는 시점.** 분석 실행 시각이 아니다 — 실행할 때마다 값이 바뀌면 시계열이 망가진다 |
| `derived_from` | 계산에 실제로 쓴 모든 `record_id`. 중복 불가 |
| `confidence` | **1.0 을 주지 않는다.** 실측이 아니라 파생이다 |
| `natural_key` | `<profile_type>\|<geo_code>\|<as_of>` 꼴. 같은 입력이면 같은 `record_id`. 한 분석기가 같은 동에 여러 축(예: 선거 계열)으로 레코드를 내면 그 축을 키에 더한다 — `voter_profile` 은 `<profile_type>\|<election_type>\|<geo_code>\|<as_of>` |

새 `kind` 를 내려면 `votelink/contract/payloads.py` 에 모델을 등록해야 한다.
**이건 계약 변경이며 사용자 승인이 필요하다.**

## 6. 실패 처리

수집기와 같은 철학이다: **조용한 누락을 만들지 않는다.**

| 상황 | 처리 |
|---|---|
| 개별 항목 실패 (동 하나) | `Rejected` 로 격리, 나머지는 계속 |
| 격리율 > **5%** | 유효분도 저장하지 않는다 |
| 입력 0건 | **실패다.** '분석이 돌았는데 결과가 없다'와 '수집이 안 됐다'를 구분할 수 없다 |
| 참조 데이터 결손 | `AnalyzeError` → 전체 중단. 부분 저장하지 않는다 |

**진영 매핑처럼 "빠지면 나머지 비율이 전부 틀리는" 결손은 항목 격리가 아니라 전체
실패로 처리한다.** 한 후보의 득표가 조용히 빠지면 숫자는 그럴듯하게 나오는데 전부
틀리기 때문이다.

## 7. 저장 — append 가 아니라 upsert

**수집기와 다른 유일한 지점이다.**

수집기는 원본이 불변이라 append 로 충분하다. 분석 결과는 참조 데이터나 계산을
고치면 **같은 키에서 다른 값**이 나온다. append 만 하면 그 갱신이 '중복'으로
조용히 버려져서, 매핑을 고치고 재실행해도 산출물이 그대로인 상태가 된다.

`store.upsert_records()` 가 같은 `record_id` 를 교체하고 나머지 줄은 보존한다.
다른 `as_of` 의 과거 분석은 `record_id` 가 달라 그대로 남는다.

## 8. 참조 데이터는 코드에 박지 않는다

판단이 들어가는 값은 `data/shared/reference/` 에 두고 분석기는 읽기만 한다.

| 파일 | 무엇 | 왜 데이터인가 |
|---|---|---|
| `districts.yaml` | 선거구 ↔ 행정동 | 획정이 매 선거마다 바뀐다 |
| `party_lineage.yaml` | 후보 → 진영 | **정치적 판단이다.** 눈에 보여야 하고, 이견이 있으면 파일만 고쳐 재분석할 수 있어야 한다 |

임계값도 마찬가지다. `meta.yaml` 의 `config` 에 두고 이유를 주석으로 남긴다.

선거구는 `config` 를 `default_district` / `common` / `districts.<id>` 세 갈래로 두고,
분석기는 `self.meta.config` 가 아니라 `self.config[...]` / `self.cfg(...)` 로 읽는다 —
`uv run votelink analyze <id> --district <선거구>` (없으면 `default_district`)로
해석된 평평한 dict 다. 평평한 `config` 도 그대로 동작한다(`votelink.districtcfg`).
지역 특화 임계값(예: `voter_profile` 의 `trend_threshold`)은 `districts.<id>` 에,
선거구 무관 값은 `common` 에 둔다.

## 9. 지표를 설계할 때 — 변별력을 먼저 확인하라

`voter_profile` 에서 실제로 겪은 함정이다.

`trend` 를 **절대** 득표율의 기울기로 정의했더니 송파갑 9개 동이 **전부**
`conservative_shift` 로 나왔다. 최근 3회가 2017(탄핵 직후 보수 저점) → 2022 → 2025라
어느 동이든 보수가 오르기 때문이다. 동별 차이를 말해야 하는 지표가 9/9 같은 값이면
정보량이 0이고, 웹앱에 "보수 이동"이라 표시되면 오해만 부른다.

**상위 단위 평균을 뺀 편차**로 바꾸자 3/2/4 로 갈렸다. 공통 흐름이 상쇄되고 그
지역만의 이동이 남는다.

> 새 지표를 만들면 **모든 단위에서 같은 값이 나오지 않는지 먼저 확인한다.**
> 그리고 분류 임계값이 결과를 바꾸는지 민감도를 재본다 — 바꾸지 않으면 그 논쟁은
> 할 필요가 없다.

## 10. 새 분석기 추가

코드가 아니라 **제안서 1장**에서 시작한다 (`docs/proposals/A-XXX-*.md`).
접두사 `A-` = analyzer, `C-` = collector.

```
docs/proposals/A-002-....md   (사람이 작성)
        ↓
analyzers/<id>/ 스캐폴딩 + meta.yaml
        ↓
구현 → 실제 입력으로 검증 → meta.verified: true
        ↓
uv run votelink analyze --sync
```

`verified: false` 인 분석기는 실행 시 경고가 뜬다. 산출물을 신뢰하지 않는다는 뜻이다.

## 11. 명령어

```bash
uv run votelink analyze                  # 등록된 분석기 목록
uv run votelink analyze <id>             # 실행
uv run votelink analyze <id> --dry-run   # 저장 없이 계약 검증만
uv run votelink analyze --sync           # analyzers/registry.yaml 재생성
```
