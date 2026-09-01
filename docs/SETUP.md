# 준비물 — 사람이 직접 해야 하는 것

코드로 대신할 수 없는 것들. 새 수집기가 늘어나면 여기에 계속 추가된다.

## 1. 행정동코드 매핑표 ⚠️ 가장 먼저

**이게 없으면 어떤 수집기도 동작하지 않는다.** 모든 레코드는 행정동에 고정되는데,
기관마다 코드 체계가 달라 변환표가 필요하다.

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
2. 데이터셋 **"행정안전부_행정동별(통반단위) 성/연령별 주민등록 인구수"**
   (https://www.data.go.kr/data/15108072/openapi.do) 에서 **활용신청**
   - 개발계정은 보통 즉시 승인된다
3. 마이페이지 → 오픈API → 인증키에서 **일반 인증키(Decoding)** 복사
4. 같은 데이터셋 페이지의 **요청 URL 전체**(`uddi:` UUID 포함)를 복사
   → `collectors/mois_population/meta.yaml` 의 `config.endpoint` 에 붙여넣기
   - 자동변환 API는 데이터셋 개정마다 UUID가 바뀌므로 코드에 박지 않는다
5. `config.reference_month` 를 받으려는 기준월로 맞춘다 (예: `2026-07`)

```bash
export DATA_GO_KR_SERVICE_KEY='발급받은_디코딩_키'

uv run votelink collect mois_population --capture-fixture   # 실제 응답 받아 저장
uv run pytest collectors/mois_population/                   # 응답 형식 검증
uv run votelink collect mois_population --dry-run           # 저장 없이 계약 검증
uv run votelink collect mois_population                     # 실제 수집
```

`meta.verified: false` 인 수집기는 실제 응답으로 검증되지 않은 상태다.
테스트가 통과하면 `true` 로 올린다.

## 3. 앞으로 필요해질 것 (아직 아님)

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
