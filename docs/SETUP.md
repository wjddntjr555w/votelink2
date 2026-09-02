# 준비물 — 사람이 직접 해야 하는 것

코드로 대신할 수 없는 것들. 새 수집기가 늘어나면 여기에 계속 추가된다.

## 1. 행정동코드 매핑표 (아직 필요 없다)

내부 표준은 **행정동코드 10자리**다 (예: 서울 송파구 풍납1동 = `1171051000`).
단일 진실은 `votelink/contract/models.py` 의 `GEO_CODE_DIGITS`.

> 행안부 게시판의 **법정동코드와 다른 체계다.** 자릿수가 같아 헷갈리지만 값이 다르다
> (풍납동 법정동코드 `1171010300` ≠ 풍납1동 행정동코드 `1171051000`).
> 행정기관코드 7자리(`3230040`)도 내부 표준이 아니다 — `districts.yaml` 에
> `org_code` 로 참고용으로만 남아 있다.

**지금은 이 매핑표(`data/reference/geo_mapping.csv`)가 비어 있어도 된다.**
두 수집기가 각자 코드를 얻는 방식이 다르기 때문이다.

| 수집기 | geo_code 를 어디서 얻나 |
|---|---|
| `mois_population` | 응답에 `admmCd` 가 들어 있다 — 그대로 쓴다 |
| `nec_election_result` | 이름만 주므로 `districts.yaml` 의 `emd[].code` 를 조회한다 |

`districts.yaml` 의 코드는 `mois_population` 실제 응답에서 확인된 값이라
두 수집기의 `geo_code` 가 정의상 일치한다. 그래서 별도 매핑표 없이 조인이 된다.

매핑표는 **송파갑 밖의 지역까지 다뤄야 할 때** 채운다.

- 받는 곳: 행정안전부 **행정표준코드관리시스템** (https://www.code.go.kr)
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

### ✅ 검증 완료 (2026-09-01)

키가 정상 동작하고, 실제 응답으로 필드명·봉투 구조·에러 코드 처리·조회 전략까지
전부 확인했다. `meta.verified: true`.

핵심 발견: **행안부 게시판의 법정동코드는 이 API의 `admmCd`가 아니다.**
자릿수·구조가 비슷해 헷갈렸지만 값이 다르다 (풍납동 법정동코드 `1171010300` ≠
풍납1동 실제 admmCd `1171051000`). 그래서 조회 전략을 바꿨다:

**동별 코드를 미리 몰라도 된다.** 시군구 코드 하나(`admmCd=1171000000`, 송파구)로
`lv=3` 조회하면 산하 행정동이 **이미 동 단위로 집계된 채**, 각자의 고유 `admmCd`와
함께 한 번에 온다. 수집기가 그 응답을 `districts.yaml`의 동 **이름**으로 걸러낸다.
그래서 동별 코드가 비어 있어도(`code: null`) 수집이 된다 — `sigungu_admm_code`
하나만 맞으면 된다.

```
$ .../selectAdmmSexdAgePpltn?admmCd=1171000000&srchFrYm=202412&srchToYm=202412&lv=3&regSeCd=1&type=JSON
resultCode: 0 (NORMAL_SERVICE), totalCount: 27  ← 송파구 전체 행정동
→ dongNm/sggNm/ctpvNm/admmCd, male{N}AgeNmprCnt·feml{N}AgeNmprCnt (N=0,10,...,100), totNmprCnt
   (tong/ban 이 빈 문자열 — 이미 동 단위로 집계돼 있다는 뜻)
```

풍납1동(`1171051000`), 풍납2동(`1171052000`)은 이 응답으로 확인해
`districts.yaml`에 채웠다. 나머지 7개는 응답에 있었을 텐데 전체를 못 받아서
**아직 미확인**이다 — 다만 위 이유로 수집이 막히지는 않는다.

```bash
uv run votelink district list --emd    # 2개 확인, 7개 미확인으로 나온다
```

미확인 동이 응답에서 하나라도 안 잡히면(예: 이름이 바뀌었으면) **수집이 실패한다**
(조용히 일부만 수집하지 않는다). 9개 중 3개만 들어와도 그 3개로 그럴듯한 전략이
나오기 때문이다.

### 엔드포인트 경로

포털 REST API의 요청 URL은 보통 **3단**이다.

```
https://apis.data.go.kr/<기관코드>/<서비스명>/<오퍼레이션명>
                        1741000    admmSexdAgePpltn   ← 여기가 빠져 있다
```

서비스까지만 호출하면 이 응답이 온다:

```json
{"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
  "errMsg": "NO_OPENAPI_SERVICE_ERROR",
  "returnAuthMsg": "해당 오픈API 서비스가 없거나 폐기됨",
  "returnReasonCode": "12"}}}
```

**확인됨 (2026-09-01)** — 오퍼레이션은 `selectAdmmSexdAgePpltn` 이다:

```
https://apis.data.go.kr/1741000/admmSexdAgePpltn/selectAdmmSexdAgePpltn
  ?serviceKey=<키>
  &admmCd=1171000000     # 조회 기준 코드. lv 와 짝을 이룬다
  &srchFrYm=202412       # 조회 시작 연월 (기준월에서 자동 생성)
  &srchToYm=202412       # 조회 종료 연월
  &lv=3                  # 행정구역 레벨. 3=시군구(산하 동이 집계돼 나옴), 4=행정동 단위
  &regSeCd=1             # 등록구분 (1 = 거주자)
  &type=JSON             # 기본은 XML
  &numOfRows=100&pageNo=1
```

`meta.yaml` 에 반영되어 있다. `srchFrYm`/`srchToYm` 은 `config.reference_month`
하나에서 만들어지므로 기준월을 바꿀 때 고칠 곳은 한 군데다.

**과거 월에도 데이터가 없을 수 있다** — 발행 지연이 있다. `2026-07`처럼 아직
발행 안 된 미래월을 넣으면 `NODATA_ERROR`(resultCode 3)가 난다. 처음 시도할
땐 몇 달 전으로 넉넉히 잡는 편이 안전하다.

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

## 3. 선거구 획정 대조

### ✅ 대조 완료 (2026-09-02) — 지금은 할 일이 없다

`districts.yaml` 의 송파갑 행정동 9개가 **선관위 확정 자료와 정확히 일치**한다.
차집합이 양쪽 다 공집합이었다.

```
방이1동 방이2동 송파1동 송파2동 오륜동 잠실4동 잠실6동 풍납1동 풍납2동
```

같은 파일에서 송파구을 8개, 송파구병 10개가 따로 나오므로 **경계도 확인됐다**
(옆 지역구 동이 섞여 들어오지 않았다).

### 왜 이 대조가 필요한가

목록이 틀리면 옆 지역구 데이터가 섞여 들어와도 **아무 에러가 나지 않는다.**
인구도 득표도 그럴듯한 숫자가 나오고, 전략 전체가 틀린 모집단 위에서 만들어진다.
이 프로젝트에서 조용히 틀리는 것이 가장 위험하다.

### 어떻게 대조했나 (재현 방법)

**별도 다운로드가 필요 없다.** `nec_election_result` 용으로 이미 받은
**제22대 총선 개표결과 CSV가 곧 선관위 확정 자료**다. 그 파일의
`선거구명=송파구갑` 행에서 `법정읍면동명` 을 뽑아 `districts.yaml` 과 비교한다.

```bash
uv run python -c "
import csv, yaml
p='data/incoming/nec_election_result/중앙선거관리위원회_국회의원선거 개표결과_20240410.csv'
nec=set()
with open(p, encoding='cp949', newline='') as fh:
    for row in csv.DictReader(fh):
        if (row['선거구명'] or '').strip() == '송파구갑':
            e=(row['법정읍면동명'] or '').strip()
            if e.endswith('동'): nec.add(e)
d=yaml.safe_load(open('data/reference/districts.yaml', encoding='utf-8'))
ours={e['name'] for e in d['districts'][0]['emd']}
print('yaml에만:', sorted(ours-nec))
print('선관위에만:', sorted(nec-ours))
"
```

**양쪽 다 빈 리스트여야 한다.** 하나라도 차이가 나면 그게 곧 버그다.

> `법정읍면동명` 이라는 컬럼명에 속지 말 것. 값은 실제로 **행정동**이다
> (풍납1동/풍납2동이 따로 온다). 자세한 사정은 §4 "검증 완료" 항목.

정의된 목록은 이 명령으로도 볼 수 있다:

```bash
uv run votelink district list --emd
```

### 언제 다시 해야 하나

**새 총선이 치러져 선거구가 재획정되면.** 획정은 매 선거마다 바뀐다.
새 선거의 개표결과 CSV를 받은 뒤 위 스크립트의 파일 경로만 바꿔 다시 돌리고,
`districts.yaml` 의 `emd` 목록과 `source` 를 갱신한다.

대통령선거 CSV로는 대조할 수 없다 — **대선에는 선거구 개념이 없어**
`선거구명` 컬럼 자체가 없다. 총선 개표결과라야 한다.

## 4. 선관위 개표결과 CSV 내려받기 (`nec_election_result`)

과거 선거 개표결과를 받는 `nec_election_result` 수집기가 쓴다.
**인증키도 활용신청도 필요 없다.** 포털 파일데이터라 로그인 없이 바로 받는다.

### 4-1. 받을 파일

| 데이터셋 | 번호 | 상태 |
|---|---|---|
| 중앙선거관리위원회_국회의원선거 개표결과_20240410 | [15025527](https://www.data.go.kr/data/15025527/fileData.do) | ✅ 수집됨 |
| 중앙선거관리위원회_대통령선거 개표결과_20250603 | [15025528](https://www.data.go.kr/data/15025528/fileData.do) | ✅ 수집됨 |
| 제21대 국회의원선거 개표결과_20200415 | 포털에서 `국회의원선거 개표결과` 검색 | ⬜ 아직 |

페이지에서 **[다운로드]** 버튼만 누른다. 파란 "활용신청" 버튼은 오픈API용이라 무시한다.

> **21대(2020) 는 22대(2024) 파일 안에 없다.** 확인했다 (2026-09-02).
> 받은 파일은 엑셀이 아니라 **CSV라서 시트 개념이 없고**, 컬럼이
> `시도명 / 선거구명 / 법정읍면동명 / 투표구명 / 후보자 / 득표수` 6개뿐이라
> **선거일·연도 컬럼 자체가 없다.** 126,901행 전부 2024-04-10 한 번의 선거다.
> 선거마다 별도 데이터셋이므로 21대는 따로 받아야 한다.

> ⚠️ **비례대표는 받지 말 것.** `비례대표국회의원선거 개표결과`(15144273)는
> 컬럼 구조가 다르다. 필요한 건 **지역구** 결과다.
> 통합 엑셀(.xlsx)은 포털에서 비공개다. CSV만 받는다.

### 4-2. 넣을 자리

```
data/incoming/nec_election_result/
```

파일명은 그대로 둔다 — `meta.yaml` 의 `elections[].file_match` 가 파일명 일부로 찾는다.
이 폴더는 `.gitignore` 에 있다. 수집기가 원본을 `data/raw/` 로 옮겨 담아 불변 보관하므로
수집 후에는 지워도 된다.

### 4-3. 실행

```bash
uv run votelink collect nec_election_result --dry-run   # 저장 없이 계약 검증
uv run votelink collect nec_election_result             # 실제 수집
```

선거를 추가하려면 CSV를 넣고 `meta.yaml` 의 `config.elections` 에 한 줄 더한다.
**파이썬은 건드리지 않는다.**

```yaml
- election_id: "2020-04-15-national-assembly"
  election_type: national_assembly
  district_name: 서울 송파구 갑
  date: "2020-04-15"
  file_match: "국회의원선거 개표결과_20200415"   # 파일명에 들어 있는 문자열
  sgg_match: 송파구갑                            # 선거구명 컬럼과 정확히 일치해야 한다
```

### ✅ 검증 완료 (2026-09-01)

실제 CSV 2건으로 확인했다. `meta.verified: true`. 격리 0%, 18개 레코드
(9개 동 × 2개 선거). `geo_code` 가 `mois_population` 과 정확히 일치해 L2 조인이 된다.

**파일마다 인코딩과 컬럼명이 다르다** — 코드가 아니라 `meta.yaml` 에서 흡수한다.

| | 총선 2024 | 대선 2025 |
|---|---|---|
| 인코딩 | `cp949` | `utf-8` |
| 지역 컬럼 | `선거구명` = 송파구갑 | `구시군명` = 송파구 |
| 동 컬럼 | `법정읍면동명` | `읍면동명` |

**`법정읍면동명` 이라는 이름에 속지 말 것** — 값은 실제로 행정동이다
(풍납1동/풍납2동이 따로 온다). 법정동이었다면 9개가 4개로 무너져 인구와 조인이 안 됐다.

**선거인수·투표수·무효 투표수·기권자수는 `후보자` 컬럼에 세로로 섞여 온다.**
후보명과 같은 자리에 들어오며, 이 넷을 뺀 나머지가 실제 후보다
(`meta.yaml` 의 `aggregate_items`). 후보는 `"더불어민주당 조재희"` 처럼
정당과 이름이 한 칸에 있어 첫 공백으로 가른다.

`거소·선상투표` / `관외사전투표` / `국외부재자투표` / `잘못 투입·구분된 투표지` 는
행정동이 아니라 **필터로 버린다**(격리하지 않는다 — 격리율이 임계를 넘어 수집이 실패한다).

### 왜 오픈API를 안 쓰는가

투·개표 정보 API(15000900)를 실제로 호출해 확인했다. 문서화된 오퍼레이션은
`투표 결과 조회` 하나뿐이고 응답이 `totSunsu`/`totTusu`/`Turnout` 같은 투표율
집계뿐이다 — **후보자명·정당명·득표수·읍면동 필드가 공식 문서에 없다.**
`getXmntckSttusInfoInqire` 가 실재하긴 하나 미문서화이고, 지역 필터가
`sdName`/`wiwName` 뿐이라 읍면동을 준다는 보장이 없다.
수집 주기도 `null`(선거는 비정기)이라 API 자동화의 이득이 거의 없다.

### 응답이 예상과 다르면

| 증상 | 고칠 곳 |
|---|---|
| 컬럼명이 다르다 | `meta.yaml` 의 `config.columns` 에 후보 이름 추가 |
| 인코딩 오류 | `config.encodings` 순서 |
| `선거구명=... 인 행이 없다` | `elections[].sgg_match` (에러 메시지가 파일의 실제 값을 보여준다) |
| 집계 항목명이 다르다 | `config.aggregate_items` |
| 파일을 못 찾는다 | `elections[].file_match` |

## 5. 네이버 검색 API 키 (`naver_news`) ← **지금 필요하다**

`naver_news` 수집기는 구현됐지만 **키가 없어 아직 한 번도 실행되지 않았다**
(`verified: false`).

### ⚠️ developers.naver.com 에서는 이제 발급되지 않는다

> **"애플리케이션 설정 실패 — 신규로 등록할 수 없는 API가 선택되었습니다"**
>
> 2026년에 네이버가 검색 API를 **NAVER API HUB**(네이버클라우드플랫폼)로
> 이관했다. 구 개발자센터에서 `검색` 을 고르면 위 오류가 난다. 계정 문제가
> 아니라 창구가 바뀐 것이다. (2026-09-02 확인)

| 날짜 | 무슨 일 |
|---|---|
| 2026-06-25 | NAVER API HUB 정식 오픈 |
| 2026-07-31 | 구 developers.naver.com **신규 등록 종료**. 쇼핑·책·전문자료 검색은 완전 종료 |
| 2027-06-30 | 구 인증정보(`X-Naver-*`) 지원 종료 |

뉴스 검색은 **종료된 게 아니라 이관됐다.** HUB에서 계속 제공된다.

### 5-1. 발급 (NAVER API HUB)

1. https://www.ncloud.com → **네이버클라우드플랫폼 회원가입 / 로그인**
2. 콘솔 → **Services > AI·NAVER API > NAVER API HUB**
3. **Application 등록** → 이름은 아무거나 (예: `votelink2`)
4. 사용할 API에서 **`검색 > 뉴스`** 를 선택
5. **인증정보(Authentication information)** 에서 **Client ID / Client Secret** 확인

> **결제수단 등록을 요구할 수 있다.** 현재 검색 API는 *한시적 무료*이고
> 월 775,000회까지 제공되지만, 네이버가 유료 전환을 예고한 상태다.
> 카드 등록이 부담되면 §5-6의 대안을 보라.

### 5-2. 넣을 자리

```bash
# .env
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

환경변수 이름은 **우리가 정한 것이라 바뀌지 않는다.** 네이버 쪽 헤더 이름만
`meta.yaml` 의 `config.auth` 에서 고른다 (HUB: `X-NCP-APIGW-*`,
레거시: `X-Naver-*`). 2027-06-30 이전에 발급받은 구 키가 있다면 그 두 줄만
바꾸고 `endpoint` 를 되돌리면 그대로 동작한다.

### 5-2. 넣을 자리

```bash
# .env
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

### 5-3. 실행

```bash
uv run votelink collect naver_news --capture-fixture   # 실제 응답 1건을 fixture로
uv run pytest collectors/naver_news/                   # skip 이 풀리고 검증된다
uv run votelink collect naver_news --dry-run           # 저장 없이 계약 검증만
uv run votelink collect naver_news                     # 실제 수집
```

fixture 가 없는 동안 `test_parse.py` 4개는 **skip 된다.** 정상이다 —
합성 데이터로 대신하지 않는다는 뜻이고, "아직 미검증"이라는 정직한 신호다.

### 5-4. 알아둘 제약

| 무엇 | 값 |
|---|---|
| 호출 한도 | 월 775,000회 · 키당 50 RPS (HUB 기준. 우리는 하루 100회 미만이라 여유가 크다) |
| 요금 | **한시적 무료.** 네이버가 유료 전환을 예고했다 — 나중에 비용이 생길 수 있다 |
| 검색어당 최대 | **1,000건** (`start` 상한) — **과거 기사 소급 수집이 안 된다** |
| 기간 필터 | **없다.** `sort=date` 로 받다가 `since` 보다 오래되면 멈춘다 |
| 저장 범위 | 링크 + 메타 + 출처 스니펫까지. 본문 전문은 계약이 막는다 |

과거 기사가 필요해지면 네이버로는 안 되고 BIGKINDS를 별도 수집기로 붙여야 한다.

### 5-5. 응답이 예상과 다르면

이 수집기는 **fixture 없이 구현했다.** 특히 이관 직후라 확실하지 않은 부분이 있다.

| 항목 | 확인 상태 |
|---|---|
| 인증 헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY` | ✅ 네이버클라우드 공식 문서 |
| 엔드포인트 `https://naverapihub.apigw.ntruss.com/search/v1/news` | ⚠️ **2차 출처. 미확인** |
| 응답 필드명 (`items`/`title`/`originallink`/`pubDate` …) | ⚠️ 레거시 기준. HUB 에서 동일한지 미확인 |

| 증상 | 고칠 곳 |
|---|---|
| 404 / 경로 오류 | `meta.yaml` 의 `config.endpoint` (콘솔의 API 가이드에 실제 경로가 있다) |
| 401 / 인증 오류 | `config.auth.header_id` · `header_secret` |
| 필드명이 다르다 | `collectors/naver_news/collector.py` 상단 `F_*` 상수 |
| 발행시각 파싱 실패 | `collectors/naver_news/text.py` 의 `parse_pub_date` |
| 검색어를 바꾸고 싶다 | `meta.yaml` 의 `config.queries` (id 는 ascii여야 한다) |
| 관련 없는 기사가 많다 | `config.sigungu_terms` 를 좁힌다 |
| 언론사명이 도메인으로 나온다 | `config.publisher_names` 에 `도메인: 매체명` 추가 |

**콘솔에서 실제 경로를 확인하는 게 가장 빠르다.** HUB 콘솔의 해당 API 가이드에
요청 URL 예시가 있다. 그 값을 `config.endpoint` 에 넣으면 코드는 그대로 돈다.

### 5-6. 카드 등록이 부담되면 (대안)

네이버클라우드 가입·결제수단 등록을 하고 싶지 않다면 뉴스 출처를 바꿀 수 있다.
어느 쪽이든 `naver_news` 를 버리는 게 아니라 **별도 수집기 제안서(C-004)** 로 간다 —
공통 레코드 계약이 같아서 L2 는 바뀌지 않는다.

| 대안 | 장점 | 단점 |
|---|---|---|
| 언론사·포털 RSS | 가입 불필요, 즉시 | 매체마다 형식이 달라 수집기가 여러 개로 쪼개진다. 지역 커버리지가 얕다 |
| BIGKINDS | 메타데이터가 풍부하고 **과거 기사 백필이 된다** | 기관 승인 절차. 연구 목적 심사 |
| 송파구청 보도자료 | 지역 현안이 가장 직접적 | 관 발표라 편향. 기사 아님 |

## 6. 앞으로 필요해질 것 (아직 아님)

| 무엇 | 언제 | 비고 |
|---|---|---|
| Anthropic API 키 | L2 텍스트 트랙 | 이슈 도출·메시지 생성. 비용 발생 지점 |
| BIGKINDS 계정 | 뉴스 심화·과거 기사 백필 | 기관 승인 필요 |
| 카카오/네이버 지도 API | POI·일정 최적화 | 좌표·이동시간 |

## 비밀값 관리

환경변수로만 넣는다. **코드나 meta.yaml 에 키를 쓰지 않는다.**
`.env` 는 `.gitignore` 에 있다.

```bash
# .env
DATA_GO_KR_SERVICE_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```
