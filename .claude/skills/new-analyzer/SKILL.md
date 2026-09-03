---
name: new-analyzer
description: votelink2에 새 분석기(L2 analyzer)를 추가한다. 제안서에서 스캐폴딩을 만들고 파생 레코드 계약에 맞게 구현한 뒤 registry에 등록한다. "분석기 추가", "이 데이터로 뭔가 계산해줘", "프로파일 만들어줘", "analyzer 추가", "L2 분석 붙여줘" 같은 요청에 사용.
---

# 새 분석기 추가

## 토큰 규율 (먼저 지킬 것)

이 작업에서 읽는 파일은 **아래 3개가 전부**다.

1. `docs/30-analysis-spec.md` — 전체
2. `docs/10-data-contract.md` — §2 봉투, §4 kind 목록, 산출 kind 의 payload 스키마
3. 대상 제안서 `docs/proposals/A-XXX-*.md`

읽지 **않는다**: 다른 분석기의 구현, `collectors/`, `votelink/web/`, `docs/` 의 나머지.
기존 분석기를 참고하고 싶으면 이 스킬의 `templates/` 를 쓴다. 남의 구현을 읽지 않는다.

## 절차

### 0. 제안서 확인

제안서가 없으면 **먼저 만든다.** `docs/proposals/A-XXX-<이름>.md` 에 아래 절을 채운다
(수집기용 `TEMPLATE.md` 는 출처 중심이라 맞지 않는다). 1페이지를 넘기면 분석기를 둘로
쪼갤 신호다.

```
# A-XXX: <분석기 이름>
## 무엇을 계산하는가      한 문단. 산출 레코드 1건이 무엇 하나에 대응하는지 명시
## 입력                   어떤 kind 가 몇 건 필요한가. 지금 있는가 없는가
## 산출                   kind / geo_level / payload 주요 필드
## 왜 필요한가            최종 산출물 5종 중 무엇에 쓰이는가. 답이 없으면 만들지 않는다
## 판단이 들어가는 값      임계값·분류 기준. 왜 그 값인가
## 변별력                 단위마다 다른 값이 나오는가. 어떻게 확인했는가
## 제약과 위험            표본 크기, 결측, 해석을 틀리게 만들 수 있는 요인
```

번호 `A-XXX` 는 `docs/proposals/` 의 마지막 A 번호 + 1.

### 1. 사전 확인 — 코드를 쓰기 전에

- **입력 레코드가 실제로 있는가.** `uv run votelink registry list` 는 어떤 수집기가
  어떤 kind 를 내는지만 알려준다. **실제로 쌓였는지는 `data/records/` 를 본다** —
  파일이 없으면 그 수집기는 아직 돌지 않은 것이다. 없으면 여기서 멈추고 사용자에게
  보고한다 (수집기부터다)
- **산출 kind 의 payload 모델이 있는가.** `votelink/contract/payloads.py` 의
  `PAYLOAD_MODELS` 에 없으면 Record 생성 자체가 거부된다.
  → **계약 변경이므로 사용자 승인을 받고 진행한다** (`docs/10-data-contract.md` 도 함께 고친다)
- **표본이 결론을 지탱하는가.** 동 9개 × 선거 8회로 회귀모델을 학습하면 계수는
  데이터가 아니라 우연을 배운다. 지탱하지 못하면 그 사실을 제안서에 적고 범위를 줄인다
- **LLM 이 필요한가.** 필요하면 **별도 분석기로 분리한다.** 수치 트랙과 텍스트 트랙을
  한 분석기에 섞지 않는다 (`docs/00-overview.md §4-1`)

### 2. 스캐폴딩

`templates/` 를 `analyzers/<analyzer_id>/` 로 복사하고 채운다.

```
analyzers/<id>/__init__.py
analyzers/<id>/analyzer.py        # templates/analyzer.py.tmpl — 클래스 이름은 반드시 Analyzer
analyzers/<id>/meta.yaml          # templates/meta.yaml.tmpl
analyzers/<id>/calc.py            # (선택) 순수 계산. 레코드도 파일도 모르는 함수들
analyzers/<id>/tests/__init__.py
analyzers/<id>/tests/test_analyzer.py   # templates/test_analyzer.py.tmpl
```

`analyzer_id` 는 소문자 스네이크. **무엇을 만드는지**로 짓는다
(`voter_profile`, `issue_ranking`). 입력 이름을 따지 않는다.

### 3. load 구현

- 기본 구현으로 충분한 경우가 많다 — `meta.inputs` 의 kind 를 전부 읽고 자기 출력은 뺀다
- 참조 데이터(`data/reference/`)가 더 필요할 때만 재정의한다
- **디스크만.** 네트워크 금지
- 참조 데이터 결손은 전체 중단이다. 조용히 빈 값으로 넘어가지 않는다

### 4. compute 구현

**순수 함수다. 네트워크·LLM·난수·시계 금지.** 같은 입력이면 언제 돌려도 같은 결과여야
한다. 이게 깨지면 `derived_from` 으로 근거를 역추적해도 그 근거가 그 결론을 낳았는지
확인할 수 없다.

파생 레코드 필드에서 틀리기 쉬운 것 넷:

| 필드 | 규칙 |
|---|---|
| `collector_id` | **분석기 id** 를 넣는다. 입력을 만든 수집기가 아니다 |
| `observed_at` | **입력이 가리키는 시점.** 분석 실행 시각이 아니다 |
| `derived_from` | 계산에 **실제로 쓴** record_id 전부. 근거를 못 대는 결론은 실패다 |
| `confidence` | **1.0 을 주지 않는다.** 실측이 아니라 파생이다. 결측이 있으면 더 내린다 |

- `map_items` 로 감싼다. 9개 중 1개가 깨져도 나머지 8개가 살아남아야 한다
- 판단이 들어가는 값(임계값, 분류 기준, 창 크기)은 코드가 아니라 `meta.yaml` 의 `config`
  나 `data/reference/` 에 둔다. **값마다 왜 그 값인지 주석을 남긴다** — 숫자만 있으면
  나중에 아무도 못 건드린다
- 입력이 0건이면 `AnalyzeError` 를 던진다. 빈 산출물을 조용히 내지 않는다

### 5. 변별력 확인 — 새 지표를 만들 때마다

**모든 단위에서 같은 값이 나오지 않는지 먼저 본다** (`docs/30-analysis-spec.md §9`).

전국 공통 흐름이 섞이면 단위별 차이가 사라진다. 실제로 겪은 예: 절대 득표율 기울기로
추세를 판정하면 송파갑 9개 동이 **전부** 같은 값으로 나와 변별력이 0이었다. 상위 단위
대비 편차를 쓰자 3 / 2 / 4 로 갈렸다.

분포를 출력해 확인하고, 결과를 제안서와 `meta.yaml` 주석에 남긴다.

### 6. 검증

```bash
uv run pytest analyzers/<id>/
uv run votelink analyze <id> --dry-run     # 저장 없이 계약 검증만
uv run ruff check . && uv run ruff format .
```

- 격리율이 0이 아니면 원인을 찾는다. **5% 를 넘으면 유효분도 저장되지 않는다**
- 저장은 append 가 아니라 `upsert_records` 다. 재실행하면 **교체 N · 신규 0** 이어야 한다
  (멱등). 신규가 늘어나면 `natural_key` 가 실행마다 달라지는 것이다

### 6-1. 검증 완료 표시

실제 입력으로 통과하면 `meta.yaml` 의 `verified` 를 `true` 로 올리고, **무엇으로
검증했는지 주석으로 남긴다** (입력 건수 → 산출 건수, 격리 수, 멱등 확인, 외부 사실과
대조한 결과). 통과하지 않았다면 올리지 않는다.

### 7. 등록

```bash
uv run votelink analyze --sync    # meta.yaml 들에서 analyzers/registry.yaml 재생성
```

`registry.yaml` 을 손으로 수정하지 않는다.

### 8. 웹앱에 뜨는 방식 — 손댈 것 없음

새 산출물은 `data/reference/compliance.yaml` 정책표에 없으므로 **자동으로
`unreviewed` 가 되어 경고와 함께 표시된다.** 그게 맞는 동작이다 (fail-closed,
`docs/90-compliance.md §4`). 경고를 없애려고 정책표를 고치지 않는다 — 법률 검토를
받은 사람이 서명을 남기는 것이 그 항목의 유일한 통과 경로다.

L3 코드는 건드리지 않는다. 뷰가 새 kind 를 그리게 하는 것은 별도 작업이다.

### 9. 보고

사용자에게 이것만 보고한다: 분석기 id / 입력 건수 → 산출 건수 / 격리 건수와 사유 /
변별력 확인 결과 / 확인이 필요한 판단 지점.
코드 전문을 붙여넣지 않는다.

## 멈추고 물어야 하는 상황

- 입력 레코드가 아직 없다 (수집기부터다)
- 산출 kind 의 payload 모델이 없다 (**계약 변경 = 사용자 승인**)
- 표본이 결론을 지탱하지 못한다 (설명변수보다 관측치가 적다, 시변 변수가 없다)
- 지표가 모든 단위에서 같은 값을 낸다 (변별력 0)
- 임계값을 정할 근거가 데이터에 없다 — 임의로 정하고 넘어가지 않는다
- LLM 호출이 필요하다 (비용이 발생하는 유일한 지점이고, 별도 분석기여야 한다)
- 결론이 개인 단위로 내려가야만 의미가 있다 (**절대 규칙 3 위반. 만들지 않는다**)
