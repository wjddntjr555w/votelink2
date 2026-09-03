# 저장 레이아웃

> 상태: v1 (2026-09-03) · 경로 상수의 진실은 `votelink/collect/storage.py` 와 `votelink/store.py`
> 저장 관련 작업을 할 때 읽을 문서는 **이것 + 그 두 파일 뿐**이다.

## 1. 다섯 디렉터리

```
data/
  raw/        fetch 원본. **불변.** 절대 규칙 1
  incoming/   사람이 손으로 넣는 원본 (access: file 수집기의 입력)
  records/    계약을 통과한 공통 레코드. 원천도 파생도 같은 형식
  rejected/   계약을 위반해 격리된 항목 (사유 포함)
  reference/  참조 데이터. **여기만 git 이 추적한다**
```

나머지 넷은 `.gitignore` 대상이다. 이유는 용량이 아니라 **재현 가능성**이다 —
`records/` 는 `raw/` 에서 다시 만들 수 있고, `raw/` 는 저장소가 아니라 출처가 원본을 갖는다.
반대로 `reference/` 는 **사람의 판단**이 들어 있어 어디서도 다시 만들 수 없다
(선거구 획정, 진영 분류, 법률 검토 기록). 그래서 그것만 추적한다.

## 2. 경로 규칙

| 무엇 | 경로 | 누가 쓰나 |
|---|---|---|
| fetch 원본 | `raw/<collector_id>/<YYYY-MM-DD>/<batch_key>.json.gz` | `storage.write_raw` |
| 공통 레코드 | `records/<owner_id>.jsonl` | `store.append_records` (L1) · `store.upsert_records` (L2) |
| 격리 항목 | `rejected/<owner_id>/<YYYY-MM-DD>.jsonl` | `store.append_rejected` |
| 수동 입력 | `incoming/<collector_id>/` | 사람 |

`owner_id` 는 **수집기 id 이거나 분석기 id** 다. 파생 레코드도 원천과 같은 계약을 쓰므로
파일 형식이 같고, 그래서 디렉터리도 나누지 않는다. 어느 파일이 파생인지는 경로가 아니라
레코드의 `derived_from` 이 말한다.

같은 날 같은 `batch_key` 가 또 오면 파일명 뒤에 `HHMMSS` 를 붙인다 — **덮어쓰지 않는다.**
날짜 디렉터리는 "언제 가져왔나"이지 "언제의 데이터인가"가 아니다. 후자는 레코드의
`observed_at` 이다.

## 3. `raw/` 가 불변인 이유

절대 규칙 1은 보존이 목적이 아니라 **재파싱이 목적**이다.

```
raw (불변, 완전)  --parse-->  records (언제든 버리고 다시 만들 수 있다)
```

파싱 버그를 고쳤을 때 출처를 다시 때리지 않고 고칠 수 있어야 한다. 그래서
`uv run votelink collect <id> --reparse` 가 있다 — 네트워크 없이 저장된 raw 만 다시 읽는다.
raw 를 고치면 이 되돌리기가 불가능해지고, 그 순간 `records/` 의 숫자가 어디서 왔는지
말할 수 없게 된다.

**따라서 비대칭이 있다**: `records/<id>.jsonl` 을 지우는 것은 회복 가능하고(재파싱),
`raw/<id>/` 를 지우는 것은 회복 불가능하다(재수집이 되면 다행이고, 과거 시점 데이터면
영영 못 구한다). 은퇴한 수집기의 raw 를 남겨두는 것도 같은 이유다 —
`data/raw/nec_election_result/` 는 그 수집기가 `collectors/_retired/` 로 간 뒤에도 남아 있고,
`records/nec_election_result.jsonl` 만 지워졌다.

## 4. append(L1) vs upsert(L2)

레코드 파일 형식은 같지만 **쓰는 방식이 다르다.** 이게 두 계층의 유일한 저장 차이다.

| | L1 수집 | L2 분석 |
|---|---|---|
| 함수 | `append_records` | `upsert_records` |
| 같은 `record_id` | 중복으로 보고 버린다 | **새 값으로 교체한다** |

분석기가 append 면 안 되는 이유: 원본은 불변이지만 분석 결과는 로직이나 참조 데이터
(`party_lineage.yaml` 등)를 고치면 같은 키에서 다른 값이 나온다. append 만 하면 그 갱신이
'중복'으로 조용히 버려져서, 매핑을 고치고 재실행해도 산출물이 그대로인 상태가 된다.

`upsert_records` 는 임시 파일에 쓴 뒤 원자적으로 교체한다. 중간에 죽어도 반쪽 파일이
남지 않는다.

**다른 `as_of` 의 과거 분석은 `record_id` 가 다르므로 그대로 남는다.** 의도된 보존이다.
같은 동의 레코드가 여러 장이 될 수 있고, **그중 무엇을 보여줄지 고르는 것은 L3의 일**이다
(`docs/40-webapp-spec.md §6`).

## 5. `incoming/` 과 `raw/` 의 경계

`access: file` 수집기는 네트워크를 타지 않고 사람이 놓아둔 파일을 읽는다.
그 입력은 `incoming/<collector_id>/` 에 둔다 — 안내문(`여기에_CSV를_넣으세요.txt`)을
함께 두면 다음 사람이 헤매지 않는다.

**알려진 예외**: `nec_archive` 와 `nec_archive_assembly` 는 선관위 개표자료 아카이브
(9,584 파일 / 651MB)를 `data/raw/nec_archive/01_대통령선거(대선)/` 처럼 `raw/` 아래에서
읽는다 (`meta.yaml` 의 `config.archive_dir`). 규약대로면 `incoming/` 이다.

지금 문제를 일으키지 않는 이유는 `storage.iter_raw` 가 `*.json.gz` 만 훑기 때문이다 —
Excel 원본은 raw 리더에게 보이지 않고, `fetch` 가 만든 `<날짜>/*.json.gz` 배치와 섞이지
않는다. 정리하려면 `archive_dir` 두 줄과 651MB 이동이 필요하다. **옮길 때까지는 이
문서가 그 사실을 안다는 것이 안전장치다** — `raw/` 아래 모든 것이 fetch 산출물이라고
가정하는 코드를 새로 쓰지 않는다.

## 6. SQLite 는 아직 없다

`docs/00-overview.md §4-1` 이 "원본 JSONL(불변) + SQLite" 를 예고하고 `.gitignore` 도
`data/*.db` 를 막아두었지만, **v0.1 에서는 만들지 않았다.**

레코드가 158건이다 (원천 149 + 파생 9). L2 분석기도 L3 웹앱도 전량을 메모리에 올리며,
그게 가장 단순하다
(`store.load_records` 독스트링: "읍면동 단위 집계라 규모가 작다").

**필요해지는 시점**은 건수가 자릿수로 커질 때다 — `foot_traffic`(시간대별 유동인구)처럼
행이 동 × 시간대 × 날짜로 곱해지는 kind 가 들어오면 JSONL 전량 로드가 먼저 무너진다.
그때 이 절을 고치고 `store.py` 뒤에 질의 계층을 넣는다. **`store` 의 함수 시그니처가
경계**이므로 호출하는 쪽(분석기·웹앱)은 바뀌지 않아야 한다.

## 7. 무엇을 지워도 되는가

| 대상 | 지워도 되나 | 회복 방법 |
|---|---|---|
| `raw/` | **안 된다** (절대 규칙 1) | 없음 |
| `incoming/` | 안 된다 | 사람이 다시 내려받아야 한다 |
| `records/<id>.jsonl` | 된다 | `collect <id> --reparse` 또는 `analyze <id>` |
| `rejected/` | 된다 | 재실행하면 다시 쌓인다. 다만 **지우기 전에 읽어라** — 격리는 고칠 거리다 |
| `reference/` | **안 된다** | git 에 있지만, 되돌리면 사람의 판단이 되돌아간다 |

테스트는 이 디렉터리들을 건드릴 수 없다. 저장소 루트 `conftest.py` 의 `data_root` 픽스처가
`autouse` 로 세 경로 상수를 임시 디렉터리로 돌린다 (`reference/` 는 읽기 전용이라 제외).
