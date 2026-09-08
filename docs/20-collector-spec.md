# 수집기(L1) 공통 규약

> 이 문서 + `docs/10-data-contract.md` 두 장이면 수집기 하나를 만들 수 있다.
> 다른 문서는 읽지 않는다.

## 1. fetch / parse 2단 분리 — 가장 중요한 규칙

수집기는 **반드시 두 단계**로 나뉜다.

```
fetch(네트워크)  →  data/shared/raw/ 에 원본 그대로 저장  →  parse(순수 함수)  →  Record
```

| 단계 | 성격 | 규칙 |
|---|---|---|
| `fetch` | 네트워크 I/O | 응답을 **가공 없이** 저장한다. 파싱하지 않는다 |
| `parse` | 순수 함수 | 네트워크를 타지 않는다. 같은 입력 → 항상 같은 출력 |

**왜 이렇게 하는가.** 6개월 뒤 파서 버그를 발견했을 때,
`--reparse`로 저장된 원본에서 전부 다시 만들 수 있다. 재크롤링이 불필요하고
(출처가 이미 데이터를 내렸어도 복구 가능), parse는 고정 fixture로 오프라인 테스트가 된다.

이 분리를 어기면(fetch 안에서 파싱하면) 위 셋이 전부 불가능해진다.

## 2. 디렉터리 구조

수집기 하나 = 폴더 하나. 다른 곳에 코드를 흘리지 않는다.

```
collectors/<collector_id>/
├── __init__.py
├── collector.py          # fetch() 와 parse() 만 있다
├── meta.yaml             # 메타데이터 (registry가 읽는다)
└── tests/
    ├── fixtures/sample_raw.json   # 실제 응답 1건을 저장
    └── test_parse.py              # fixture → Record 검증
```

## 3. 인터페이스

```python
from votelink.collect.base import BaseCollector, RawBatch
from votelink.contract.models import Record


class Collector(BaseCollector):
    def fetch(self, since: datetime | None) -> Iterator[RawBatch]:
        """네트워크에서 원본을 가져온다. 가공하지 않는다."""

    def parse(self, raw: RawBatch) -> Iterator[Record]:
        """원본 → 공통 레코드. 순수 함수. 네트워크 금지."""
```

`since`는 증분 수집용이다. `None`이면 전체 수집.
증분이 불가능한 출처는 `meta.yaml`에 `incremental: false`로 명시하고 `since`를 무시한다.

## 4. meta.yaml

```yaml
id: nec_election_result
name: 중앙선관위 선거통계 개표결과
kinds: [election_result]
source_name: 중앙선거관리위원회
source_url: https://info.nec.go.kr
source_license: public_open      # public_open|api_tos|crawl_public|restricted
access: api                      # api|rss|crawl|file
schedule: "0 4 * * 1"            # cron. null이면 수동 실행만
incremental: false
geo_level: emd
requires_secrets: [NEC_API_KEY]  # 없으면 []
rate_limit_rps: 1
proposal: docs/proposals/C-001-nec-election-result.md
verified: false                  # 실제 응답 fixture로 검증됐는가
config:                          # 수집기별 설정. 비밀값은 넣지 않는다
  endpoint: "https://..."
  per_page: 1000
```

**선거구에 종속적인 수집기**(대상 행정동을 좁히거나 지역명으로 조회하는 등)는 `config` 를
세 갈래로 둔다. 코드는 `self.meta.config` 가 아니라 `self.config[...]` / `self.cfg(...)` 로
읽는다 — `--district` (없으면 `default_district`)로 해석된 평평한 dict 다.

```yaml
config:
  default_district: seoul_songpa_gap   # --district 없이 실행하면 이걸 쓴다
  common:                              # 선거구 무관 값
    endpoint: "https://..."
  districts:                           # 선거구별로 달라지는 값
    seoul_songpa_gap: { sigungu_admm_code: "1171000000" }
```

`common`/`districts` 키가 없는 평평한 `config` 도 그대로 동작한다(`votelink.districtcfg`).
없는 선거구를 `--district` 로 요구하면 실행이 한 줄 오류로 끝난다.

`proposal` 경로가 실제로 없으면 등록이 거부된다. 제안서 없이 만든 수집기를 막는 장치다.

`verified: false` 인 수집기는 실행할 때마다 경고가 뜬다. 실제 응답 fixture로
테스트를 통과시킨 뒤에만 `true` 로 올린다.

`registry.yaml`은 이 파일들을 모아 자동 생성한다. 손으로 쓰지 않는다.

## 5. 수집 예절 (crawl 방식일 때 필수)

- `robots.txt`를 확인하고 따른다. 확인 없이 크롤링하지 않는다.
- User-Agent에 프로젝트명과 연락 수단을 넣는다.
- `rate_limit_rps`를 지킨다. 기본값 1 req/s.
- 429/503 → 지수 백오프(2s, 4s, 8s, 16s), 4회 후 중단.
- 공식 API가 있으면 크롤링하지 않는다. API 우선.
- 로그인·유료장벽 뒤의 데이터는 수집하지 않는다.
- 뉴스 본문 전문은 저장하지 않는다. 링크 + 메타 + 요약까지.

## 6. 실패 처리

| 상황 | 처리 |
|---|---|
| fetch 실패 (네트워크·인증) | 실행 중단. raw 미저장. 종료코드 1 |
| fetch 성공, 일부 응답 깨짐 | raw는 **그대로 저장**. parse 단계에서 판정 |
| parse 중 개별 레코드 계약 위반 | `data/shared/rejected/<collector>/` 로 사유와 함께 격리 (`map_items` 가 처리) |
| 격리 비율 > 5% | 실행을 실패로 처리. 유효분도 커밋하지 않는다 |
| `geo_code` 매핑 실패 | 계약 위반으로 간주 → 격리 |

부분 성공을 조용히 넘기지 않는 이유: 5%가 조용히 누락되면 그 5%가
어느 동네인지 아무도 모르고, 그 동네가 통째로 전략에서 빠진다.

## 7. 테스트 의무

수집기마다 최소 1개:

```python
def test_parse_produces_valid_records():
    raw = load_fixture("sample_raw.json")
    records = list(Collector().parse(raw))
    assert records
    for r in records:  # Pydantic 검증
        Record.model_validate(r.model_dump())
        assert r.geo_code is not None
        assert r.observed_at <= r.ingested_at
```

fixture는 실제 응답 1건을 그대로 저장한다. 손으로 만든 가짜 데이터는 쓰지 않는다 —
빈 문자열, 콤마 섞인 숫자, 예상 못 한 필드명 같은 실제 출처의 지저분함이
테스트에 반영되지 않기 때문이다.

```bash
uv run votelink collect <id> --capture-fixture
```

**fixture가 없으면 parse 테스트는 skip 되어야 한다.** 합성 데이터로 대신하지 않는다.
skip 은 "이 수집기는 아직 미검증"이라는 정직한 신호다.

산수(재집계·환산)처럼 응답 형식과 무관한 로직은 별도 순수 함수로 빼서
합성 데이터로 검증해도 된다 (예: `collectors/mois_population/aggregate.py`).

## 7-1. 실행

```bash
uv run votelink collect <id>              # 수집 + 저장
uv run votelink collect <id> --dry-run    # 저장 없이 계약 검증만
uv run votelink collect <id> --reparse    # 네트워크 없이 저장된 raw 재파싱
uv run votelink collect <id> --since 2026-08-01
uv run votelink collect <id> --capture-fixture   # 실제 응답을 fixture로 저장
uv run votelink registry sync             # registry.yaml 재생성
```

실행 후 요약에 **격리 건수와 상위 사유 5개**가 나온다. 격리가 0이 아니면 원인을 본다.

## 8. 새 수집기를 추가하는 절차

직접 하지 말고 **스킬 `new-collector`** 를 호출한다.
절차: 제안서 작성 → 스킬이 스캐폴딩 → fetch/parse 구현 → fixture 저장 → 테스트 통과.
