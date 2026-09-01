# 준비물 — 사람이 직접 해야 하는 것

코드로 대신할 수 없는 것들. 새 수집기가 늘어나면 여기에 계속 추가된다.

## 1. 행정동코드 매핑표 (필요할 때만)

내부 표준은 **행정기관코드 7자리**다 (예: 서울 송파구 풍납1동 = `3230040`).

응답에 행정기관코드가 들어 있는 출처(`mois_population` 등)는 **매핑표가 필요 없다.**
코드를 주지 않고 지역명만 주는 출처가 생기면 그때 채운다.

- 받는 곳: 행정안전부 **행정표준코드관리시스템** (https://www.code.go.kr)
  → 행정기관코드 (행정동 단위, 8자리)
- 대안: 공공데이터포털에서 "행정동코드" 검색

```bash
uv run votelink geo import ~/Downloads/행정동코드.csv --system mois
uv run votelink geo lookup 풍납1동          # 확인
```

열 이름은 자동 탐지한다. 실패하면 `--code-col` / `--name-col` 로 지정.

> 이 표를 손으로 만들지 말 것. 틀린 코드는 에러 없이 **다른 동네에 데이터를 붙인다.**

## 2. 공공데이터포털 인증키 (`DATA_GO_KR_SERVICE_KEY`)

`mois_population` 수집기가 쓴다.

1. https://www.data.go.kr 회원가입
2. 주민등록 인구 데이터셋에서 **활용신청** (개발계정은 보통 즉시 승인)
3. 마이페이지 → 오픈API → 인증키 복사
   - Encoding / Decoding 어느 쪽이어도 된다. 수집기가 `%2F` 같은 인코딩을 감지해
     자동으로 되돌린다 (그대로 쓰면 이중 인코딩으로 인증이 실패한다)
4. 엔드포인트는 `collectors/mois_population/meta.yaml` 의 `config.endpoint` 에 있다
   (현재 `https://apis.data.go.kr/1741000/admmSexdAgePpltn`)
5. `config.reference_month` 를 받으려는 기준월로 맞춘다 (예: `2026-07`)
6. 조회 범위는 `config.district: seoul_songpa_gap` 이며 행정동 목록은
   `data/reference/districts.yaml` 에 있다 (`votelink district list --emd` 로 확인)

### 응답이 예상과 다르면
`meta.yaml` 의 `config` 만 고친다. 파이썬은 건드리지 않는다.

| 증상 | 고칠 곳 |
|---|---|
| 파라미터 이름이 다르다 | `config.params`, `config.paging.*_param` |
| XML이 온다 | `config.params.type` (`JSON`/`json`/`resultType`) |
| 목록을 못 찾는다 | 로그가 알려주는 경로를 `config.data_path` 에 고정 |
| 필드명이 다르다 | `collectors/mois_population/aggregate.py` 상단 상수 |

```bash
export DATA_GO_KR_SERVICE_KEY='발급받은_디코딩_키'

uv run votelink collect mois_population --capture-fixture   # 실제 응답 받아 저장
uv run pytest collectors/mois_population/                   # 응답 형식 검증
uv run votelink collect mois_population --dry-run           # 저장 없이 계약 검증
uv run votelink collect mois_population                     # 실제 수집
```

`meta.verified: false` 인 수집기는 실제 응답으로 검증되지 않은 상태다.
테스트가 통과하면 `true` 로 올린다.

## 3. 선거구 획정 확인 (권장)

`data/reference/districts.yaml` 의 송파갑 행정동 9개는 **사용자 제공 목록**이다.
선관위 선거구 획정 자료로 대조해두는 편이 좋다 — 목록이 틀리면 옆 지역구 데이터가
섞여 들어와도 **아무 에러가 나지 않는다.** 인구도 득표도 그럴듯한 숫자가 나온다.

```bash
uv run votelink district list --emd
```

## 4. 앞으로 필요해질 것 (아직 아님)

| 무엇 | 언제 | 비고 |
|---|---|---|
| Anthropic API 키 | L2 텍스트 트랙 | 이슈 도출·메시지 생성. 비용 발생 지점 |
| 네이버 개발자 API | 뉴스 수집기 | Client ID / Secret |
| BIGKINDS 계정 | 뉴스 심화 | 기관 승인 필요 |
| 카카오/네이버 지도 API | POI·일정 최적화 | 좌표·이동시간 |

## 비밀값 관리

환경변수로만 넣는다. **코드나 meta.yaml 에 키를 쓰지 않는다.**
`.env` 는 `.gitignore` 에 있다.

```bash
# .env
DATA_GO_KR_SERVICE_KEY=...
```
