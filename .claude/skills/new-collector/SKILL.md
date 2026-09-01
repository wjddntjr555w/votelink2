---
name: new-collector
description: votelink2에 새 데이터 수집기(L1 collector)를 추가한다. 제안서에서 스캐폴딩을 만들고 공통 데이터 계약에 맞게 구현한 뒤 registry에 등록한다. "수집기 추가", "크롤러 만들어줘", "이 API에서 데이터 가져오게 해줘", "collector 추가" 같은 요청에 사용.
---

# 새 수집기 추가

## 토큰 규율 (먼저 지킬 것)

이 작업에서 읽는 파일은 **아래 3개가 전부**다.

1. `docs/10-data-contract.md` — §2 봉투, §3 지리, §4 kind 목록
2. `docs/20-collector-spec.md` — 전체
3. 대상 제안서 `docs/proposals/C-XXX-*.md`

읽지 **않는다**: 다른 수집기의 구현, `docs/` 의 나머지, `analyzers/`, `votelink/web/`.
기존 수집기를 참고하고 싶으면 이 스킬의 `templates/` 를 쓴다. 남의 구현을 읽지 않는다.

## 절차

### 0. 제안서 확인
제안서가 없으면 **먼저 만든다.** `docs/proposals/TEMPLATE.md` 를 복사해
사용자와 대화하며 채운다. 특히 "왜 필요한가"에 답이 안 나오면 **거기서 멈추고**
사용자에게 되묻는다. 쓰이지 않을 데이터를 수집하는 수집기는 만들지 않는다.

번호 `C-XXX` 는 `docs/proposals/` 의 마지막 번호 + 1.

### 1. 사전 확인 — 코드를 쓰기 전에
- 공식 API가 있는데 크롤링하려는 것은 아닌가 → API 우선
- `access: crawl` 이면 robots.txt를 실제로 가져와 확인하고 결과를 제안서에 적는다
- 출처의 지역 코드를 행안부 행정동코드로 바꿀 수 있는가
  → **불가능하면 여기서 멈추고 사용자에게 보고한다.** 매핑 없는 데이터는 쓸 수 없다
- 개인 식별 정보가 섞여 있는가 → 있으면 수집 범위에서 제외하고 그 사실을 명시

### 2. 스캐폴딩
`templates/` 를 `collectors/<collector_id>/` 로 복사하고 채운다.

```
collectors/<id>/__init__.py
collectors/<id>/collector.py     # templates/collector.py.tmpl
collectors/<id>/meta.yaml        # templates/meta.yaml.tmpl
collectors/<id>/tests/test_parse.py   # templates/test_parse.py.tmpl
```

`collector_id` 는 소문자 스네이크. 출처 + 데이터 종류 (`nec_election_result`,
`mois_population`, `naver_news`).

### 3. fetch 구현
- 네트워크만. **파싱 금지.** 응답을 가공 없이 `RawBatch` 에 담는다
- HTTP는 `votelink.collect.http.politeClient` 를 쓴다 (rate limit·백오프·UA 내장).
  `requests`/`httpx` 를 직접 부르지 않는다
- 비밀값은 `meta.yaml` 의 `requires_secrets` 에 선언하고 환경변수로 읽는다.
  **코드에 키를 쓰지 않는다**

### 4. 실제 응답 1건을 fixture로 저장
```bash
uv run votelink collect <id> --capture-fixture
```
손으로 만든 가짜 데이터를 쓰지 않는다.

**API 키가 없거나 출처에 접근할 수 없으면 여기서 멈춘다.** 응답 형식을 추측해
fixture를 지어내지 않는다. 대신:
- `meta.verified: false` 로 두고
- parse 테스트는 fixture 부재 시 skip 되게 하고
- 응답 필드명을 한 곳(모듈 상단 상수)에 모아 고치기 쉽게 만들고
- 사용자에게 **무엇을 발급받아야 하는지** 알리고 `docs/SETUP.md` 에 적는다

### 5. parse 구현
- 순수 함수. 네트워크 금지
- 봉투 15필드를 전부 채운다. `observed_at`(데이터 시점)과 `ingested_at`(수집 시각)을 혼동하지 않는다
- `geo_code` 는 `votelink.collect.geo.to_emd_code()` 로 변환. 실패 시 예외를 던진다 (null 금지)
- **해석하지 않는다.** 감성·분류·추정은 여기서 하지 않는다

### 6. 검증
```bash
uv run pytest collectors/<id>/
uv run votelink collect <id> --dry-run     # 저장 없이 계약 검증만
uv run ruff check . && uv run ruff format .
```
`--dry-run` 에서 격리율이 0이 아니면 원인을 찾고, 5% 넘으면 넘어가지 않는다.

### 6-1. 검증 완료 표시
fixture로 테스트가 통과하면 `meta.yaml` 의 `verified` 를 `true` 로 올린다.
통과하지 않았다면 올리지 않는다.

### 7. 등록
```bash
uv run votelink registry sync    # meta.yaml 들에서 registry.yaml 재생성
```
`registry.yaml` 을 손으로 수정하지 않는다.

### 8. 보고
사용자에게 이것만 보고한다: 수집기 id / kind / 수집된 레코드 수 /
격리 건수와 사유 / 확인이 필요한 판단 지점.
코드 전문을 붙여넣지 않는다.

## 멈추고 물어야 하는 상황

- 행정동코드 매핑이 불가능하다
- robots.txt 가 금지하거나 이용약관이 불명확하다
- 개인 식별 정보를 빼면 데이터가 쓸모없어진다
- 제안서의 "왜 필요한가"가 최종 산출물과 연결되지 않는다
- 기존 `kind` 에 안 맞아 새 `kind` 가 필요하다 (데이터 계약 변경이므로 사용자 승인 필요)
- API 키·계정 발급이 필요하다 (사용자만 할 수 있다 → `docs/SETUP.md` 에 적고 알린다)
