# 웹앱(L3) 규약

> 상태: v1 구현됨 (`votelink/web/`, `uv run votelink serve`)
> 웹앱 화면을 만들거나 고칠 때 읽을 문서는 **이것 + `votelink/web/` 뿐**이다.
> 검증 배지의 근거는 `docs/90-compliance.md`, 렌더할 데이터의 형태는 `votelink/contract/`.

## 1. 웹앱이란 무엇인가

저장된 레코드를 **읽어서 화면으로 만드는 것**. 그게 전부다.

```
data/shared/records/*.jsonl  →  로더  →  뷰모델  →  템플릿  →  HTML
     (파생 레코드)      디스크만   순수 함수
```

**L3는 쓰지 않는다.** `votelink/web/` 는 `store.append_records` / `upsert_records` /
`append_rejected` 를 import 하지 않는다. 웹앱이 데이터를 만들기 시작하면 `derived_from`
추적이 끊기고, 어떤 화면의 숫자가 어디서 왔는지 말할 수 없게 된다.

## 2. L1·L2와의 대칭 — 그리고 대칭이 끝나는 지점

구조가 같으면 새로 배울 게 없다. `docs/30-analysis-spec.md §2` 와 같은 의도다.

| L1 (수집) | L2 (분석) | **L3 (표현)** | 왜 |
|---|---|---|---|
| `fetch()` 네트워크만 | `load()` 디스크만 | **`loader.py`** 디스크만 | 부작용을 한 곳에 가둔다 |
| `parse()` 순수 함수 | `compute()` 순수 함수 | **`viewmodel.py`** 순수 함수 | 같은 레코드 → 같은 화면 |
| `map_items` 항목 격리 | 동일 | 동일 | 동 1개가 깨져도 8장은 그린다 |
| `runner.py` | `runner.py` | `app.py` (라우팅) | |
| `registry.yaml` | `registry.yaml` | **없다 — 앱은 하나다** | 대칭을 맹목적으로 복제하지 않는다 |

마지막 행이 중요하다. 등록부는 "같은 모양의 것이 N개"일 때 값을 한다. 웹앱은 하나뿐이라
`registry.py`·`meta.py` 를 만들지 않는다.

같은 이유로 `__init__.py` 는 상수만 들고 있고 `create_app` 을 재수출하지 않는다. 재수출하면
웹 의존성이 없는 환경에서 `votelink.web` 을 건드리는 순간 죽고, 그러면 `cmd_serve` 의 늦은
import 가 무의미해진다. CLI는 `from votelink.web.app import create_app` 을 함수 안에서 부른다.

## 3. L2 ↔ L3 계약 — Record를 읽되, 뷰모델로 한 번 옮긴다

`00-overview.md §3`: "L2와 L3도 산출물 JSON 스키마로만 연결된다."
그 스키마가 바로 `Record` + `SegmentProfilePayload` 다. **계약을 읽는 것은 계층 무지를 지키는
방법이지 어기는 방법이 아니다** — L2가 L1을 정확히 그렇게 읽는다.

그런데도 뷰모델을 두는 이유는 셋이다.

1. **`record.payload` 는 `dict[str, Any]` 다.** `Record._check_payload` 는 검증만 하고 결과를
   버리므로 타입이 남지 않는다. 템플릿에서 `payload["lean_series"][-1]["camp_share"]["conservative"]`
   를 쓰면 오타가 런타임에만 드러나고 계약이 바뀌어도 아무 데서도 안 걸린다.
   로더가 `SegmentProfilePayload.model_validate()` 를 한 번 더 부르는 것이 타입 있는 뷰를 얻는
   정당한 경로다 (이미 검증된 값이라 실패하지 않는다).
2. **표현 판단은 계약에 넣을 수 없다.** "None을 `—` 로 그린다", "발산 색 스케일의 중심은 0이다",
   "정렬 기본값은 `geo_code`" — 전부 L3의 결정이고 payload에 들어가면 안 된다.
3. **템플릿이 산술을 하면 안 된다.** 스파크라인 좌표, 누적 막대 폭, 색 값은 순수 함수로 계산하고
   테스트해야 한다. 템플릿 안의 계산은 테스트할 방법이 없다.

## 4. 폴더 구조

```
votelink/web/
  __init__.py     DEFAULT_HOST / DEFAULT_PORT 뿐. fastapi 를 import 하지 않는다
  settings.py     WebSettings — district_id, records_root, policy_path
  loader.py       디스크만. _dedup_newest(공용) · load_profiles · load_comparison · load_all_emd
  viewmodel.py    순수 함수. build_card / build_view / aggregate_profiles / build_comparison / build_nation_view
  shapes.py       배치 좌표 공급자 (격자 ↔ 훗날 GeoJSON)
  app.py          create_app() 팩토리 + 라우트 (/, /d/<선거구>/[map], /compare, /nation, /healthz)
  templates/      base.html dashboard.html map.html compare.html nation.html _card.html _agg.html _output.html
  static/app.css
```

`create_app(settings) -> FastAPI` **팩토리**로 만든다. 전역을 monkeypatch 하지 않고 테스트에서
임시 디렉터리를 주입할 수 있다. 라우트는 `Depends()` 대신 `request.app.state` 를 읽는다 —
라우트가 셋뿐이라 DI가 값을 못 하고, 기본인자 안의 함수 호출은 ruff `B008` 에 걸린다.

**선거구를 아는 법**: `analyzers/voter_profile/meta.yaml` 의 `config` 를 읽지 않는다
(L2 내부 상태다). 새 설정 파일도 만들지 않는다(값이 중복된다). 선거구는 **URL 이 정한다** —
`/d/<선거구>/` 와 `/d/<선거구>/map`. `/` 는 선거구가 하나뿐이면 그리로 302, 여럿이면
선택 화면(`districts.html`)을 띄운다. `--district` 나 `WebSettings.district_id` 는 `/` 가
바로 보낼 **기본 선거구**를 정할 뿐, 요청 URL 이 항상 이긴다. 조용히 첫 번째를 고르지 않는다.
`districts.yaml` 에 선거구가 여럿이어도 서버는 뜬다.

## 5. 무엇을 읽는가 — 화이트리스트

로더는 네 겹으로 거른다. 전부 **fail-closed** 다. (`loader._dedup_newest`)

| # | 필터 | 왜 |
|---|---|---|
| 1 | `iter_records(kinds=[...])` — **kind를 반드시 준다** | 인자 없이 부르면 `data/shared/records/` 전체를 먹는다 |
| 2 | `District.contains(geo_code)` | 위생 조치가 아니라 **원래 맞는 동작**이다. 한 화면은 선거구 하나만 보여준다 — `data/shared/records/` 한 파일에 여러 선거구 레코드가 섞여 있어도 이 필터가 갈라낸다 |
| 3 | `payload.election_type == 요청값` (기본 `presidential`) | 한 동에 대선·총선·지선 레코드가 별도로 있다. 계열을 섞으면 편차의 의미가 무너진다 (A-001) |
| 4 | `(profile_type, election_type, geo_code)` 별 **최신 `as_of` 하나** | §6 참조 |

**`/compare` 는 필터 2를 선거구마다 반복한다** (`load_comparison` 이 각 선거구로 `load_profiles`). **`/nation` 은 필터 2를 의도적으로 건너뛴다** — 전국은 선거구 하나가 아니다. 구멍이 아니라 문서화된 결정이다.

`exclude_owners=["fake_collector"]` 같은 **블랙리스트는 쓰지 않는다.** 시험 산출물 이름을
프로덕션 코드에 굽는 것이고, 다음 주에는 다른 이름일 것이다. 화이트리스트가 이미 가능하다.

**읽은 건수와 숨긴 건수를 화면에 표시한다.** 9가 10이 되면 눈에 보여야 한다.

## 6. 같은 동이 여러 장이 될 수 있다

`analyzers/voter_profile/analyzer.py` 의 `natural_key` 는
`f"{PROFILE_TYPE}|{election_type}|{code}|{reference_month}"` 이고, `store.upsert_records` 는 다른 키를 보존한다.
**다음 달 인구로 재분석하면 같은 (동, 계열) 의 레코드가 둘이 된다.**

이건 분석기의 버그가 아니다. 과거 분석을 남기는 것은 의도된 설계다
(`store.upsert_records` 독스트링: "다른 `as_of` 의 과거 분석은 record_id 가 다르므로 그대로 남는다").

**고르는 것은 L3의 일이다.** 로더가 `(profile_type, election_type, geo_code)` 별로 `as_of` 가 가장 큰
하나만 남기고, **몇 건을 숨겼는지 보고한다.** 카드가 18장이 되는 화면은 틀린 화면이고, 아무 말 없이
9장이 되는 화면도 틀린 화면이다.

## 7. 화면

화면 축은 셋이다:

- **선거구** — `GET /d/<선거구>/`(대시보드) + `GET /d/<선거구>/map`(지도)
- **선거구 비교** — `GET /compare` (모든 선거구를 근사 집계해 한 표로)
- **전국 동** — `GET /nation` (선거구 소속 필터를 건너뛴 전체 동)

각 화면은 `?election_type=`(기본 `presidential`)로 계열을 재필터한다 — `?sort=`·`?metric=` 과 같은
층위다. 선거구는 여전히 **경로 축**(`/d/<선거구>/`), 집계는 그 위의 뷰다.

### `GET /` — 선거구 라우팅

선거구가 하나면 `/d/<그 선거구>/` 로 302. 여럿이면 선택 화면(`districts.html`, 링크 목록).
`WebSettings.district_id`(= `serve --district`)가 있으면 그리로 바로 302.
내비게이션에는 선거구가 둘 이상일 때만 전환 `<select>` 가 뜬다 (`onchange` 한 줄, 외부 요청 없음).

### `GET /d/{district_id}/` 대시보드

**지역구 헤더**

| 요소 | 출처 |
|---|---|
| 선거구명 | `districts.yaml` → `District.name` |
| **동 수 "9 / 9"** | 로드된 레코드 수 / `len(district.emd_codes)`. **둘 다 보여준다** — 다르면 결측이다 |
| 총 인구 | Σ `payload.population_total` |
| 인구 기준월 | `payload.population_month` (전부 같아야 한다. 다르면 경고 줄) |
| 분석 기준월 | `payload.as_of` |
| 최근 선거 | `lean_series[-1].election_id` / `.election_date` |
| 출처 | `record.source_name`, `record.source_license` |
| 검증 배지 | `review()` 결과 (`docs/90-compliance.md §8`) |
| 진단 줄 | 읽은 파일·건수, **숨긴 건수** (구 `as_of`, 선거구 밖) |

**선거구 종합 카드 1장** — `viewmodel.aggregate_profiles` 가 동 카드들을 하나로 묶는다.
`camp_share`·`turnout` 은 **인구·투표율 가중 근사**다 (원시 득표수가 파생 레코드에 없다) →
`approx` 배지로 표시한다. `age_mix`·`sex_ratio`·인구 합은 정확하다. 추세는 단일 값 대신
멤버 동들의 **분포**(`trend_mix`)로 — 단일 추세로 뭉개려면 L2 임계값을 화면에서 읽어야 한다.

**동 카드 × 9** — 제안서 A-001이 "`segment_profile` 레코드 1건 = 동 카드 한 장"으로 설계했다.

| 요소 | 출처 |
|---|---|
| 동명 / 코드 | `record.geo_name` / `record.geo_code` |
| 진영 구성 (4색 누적 100%) | `lean_series[-1].camp_share` — 계약 `_check_shares` 가 4개 키를 보장한다 |
| 투표율 | `lean_series[-1].turnout` |
| 스윙 | `payload.swing` (%p) |
| 추세 | `payload.trend` → 한국어 라벨. **설명문은 `enums.Trend` 독스트링에서만** |
| 편차 4종 | `gap_district` / `gap_sigungu` / `gap_sido` / `gap_nation` (§8) |
| 보수 시계열 스파크라인 | `[p.camp_share["conservative"] for p in lean_series]` |
| 편차 시계열 스파크라인 | `[p.gap_district for p in lean_series]` — None은 선을 끊는다 |
| 연령 구조 | `payload.age_mix` (9밴드) |
| 성비 | `payload.sex_ratio` — **`%` 를 붙이지 않는다.** 이 payload의 유일한 비-퍼센트 값이다 |
| 신뢰도 | `record.confidence` |
| 근거 | `len(record.derived_from)` + `<details>` 로 record_id 목록 |

`?sort=code|swing|gap|turnout` (기본 `code`), `?election_type=`(기본 `presidential`).
서버 렌더라 JS가 필요 없다.

**`meta.yaml` 의 `config` 값(`trend_threshold` 등)을 화면에 쓰지 않는다.** L2 내부 값이다.

### `GET /d/{district_id}/map` 지도

- 9칸 + `?metric=gap_district|swing|conservative|turnout` (기본 `gap_district`), `?election_type=`
- **발산 스케일**(gap·conservative, 중심 0) vs **순차 스케일**(swing·turnout)
- 범례에 **실제 min/max 수치와 분모**를 표기
- **값 없음은 색이 아니라 해칭 + 별도 범례 항목** (§8)

### `GET /compare` — 선거구 비교

정의된 모든 선거구를 훑어 각각 `aggregate_profiles` 로 한 행을 만든다. 행: 선거구명(링크) ·
진영 구성 mini bar · 투표율 · 스윙 · **전국 대비 편차**(선거구마다 시/도·시군구가 달라
전국만 공통 축) · 인구 · 동 `loaded/expected` · 검토 상태. `?sort=name|conservative|gap_nation|turnout|swing`.

프로파일이 0건인 선거구는 **`skipped` 목록**에 사유와 조치 커맨드를 남긴다 — 조용히 빠지지
않는다. 행이 근사 집계이므로 헤더에 그 사실을 적고, `worst_verdict` 로 규칙 5를 게이팅한다.

### `GET /nation` — 전국 전체 동

`load_all_emd` 이 `District.contains` 를 건너뛰고 모든 `segment_profile` EMD 레코드를 로드한다
(계열 필터·최신 `as_of` dedup 은 그대로). 편차는 **전국 대비만** 유효하다 (`_card.html` 에
`levels=('nation',)`). 분모가 없으므로 "표시 N곳"만 적는다. `?sort=`·`?election_type=`.

### `GET /healthz`

기동 확인과 TestClient 스모크용.

### 인증 화면 넷 — `--auth` 일 때만 의미가 있다

`GET/POST /login` · `POST /logout` · `GET/POST /signup` · `GET /pending` ·
`GET/POST /onboarding`. 규약은 `docs/proposals/P-002-auth-and-camp-approval.md` §9 이고,
여기서는 **위 세 화면 축과의 관계만** 적는다.

- **`/login`·`/signup`·`/healthz`·`/static/*` 에는 산출물이 없다.** 이 앱을 인터넷에 열어도
  되는 근거가 그것이다. 이 넷 중 하나에 숫자를 올리는 변경은 근거를 무너뜨린다.
- **어느 캠프의 눈으로 보는지는 세션이 정한다.** 그래서 렌즈·검토 기록·선거일이
  `app.state` 가 아니라 **`request.state`** 에 있다. 인증이 꺼져 있으면 미들웨어가 앱 전역
  값을 그대로 복사해 넣으므로 라우트의 코드 경로는 하나다.
- **`/d/<선거구>/` 는 세션의 관할로 스코프된다.** 검사는 라우트가 아니라 미들웨어에 있고
  경로 모양으로 걸린다 — `/d/` 밑에 화면을 더 붙여도 검사가 이미 따라와 있다.
  관할 밖이면 403(리다이렉트가 아니다) + 감사 로그 `denied`.

### 만들지 않는 것

**동 상세 페이지 `/emd/{code}` 를 만들지 않는다.** 제안서가 "레코드 1건 = 카드 한 장"이라
했으니 시계열까지 카드 안에 넣는다.

**전국 지도 `/nation/map` 은 국가 경계 파일이 들어오기 전까지 만들지 않는다.** 격자 폴백이
수백 칸을 만들지만 지리적 의미가 0이다. 경계 파일이 들어오면 `build_map` 재사용 한 줄이다.

## 8. `gap_* = None` 을 0으로 만들지 않는다

계약이 못 박았다 (`payloads.LeanPoint`):

> None 을 0.0 으로 채우지 않는다 — '차이가 없다'와 '모른다'는 다르다.

UI가 이걸 무너뜨리는 경로가 넷이고, 넷 다 막는다.

| 무너지는 지점 | 규칙 |
|---|---|
| **숫자 자리** | `—` (em dash) + `title="상위 단위 기준선 레코드가 없어 계산할 수 없다"`. 빈칸은 렌더 버그와 구분이 안 되고, `0.0` 은 거짓말이다 |
| **색** | 칠하지 않는다. 발산 스케일에서 None이 중립색이 되면 화면상 0.0과 **완전히 같아진다.** **해칭(사선)** 으로 — 색과 무늬는 다른 채널이라 색각 접근성에도 맞다 |
| **집계** | 평균·최대·최소에 넣지 않고 **분모를 노출한다**: "평균 편차 −4.2%p (8회 중 7회 기준)" |
| **선 그래프** | 점을 찍지 않고 **선을 끊는다.** 앞뒤를 이으면 없는 데이터를 보간한 게 된다 |
| **집계 카드 (근사)** | `aggregate_profiles` 의 `camp_share`·`turnout` 은 인구·투표율 가중 근사다 → `approx` 배지. gap 롤업은 `GapSummary`(멤버 동들의 편차, 분모 노출). trend 는 `trend_mix` 분포 |

**타입으로 강제한다.** 뷰모델이 `float | None` 을 템플릿에 넘기지 않고
`GapCell(value, text, known, css_class)` 를 넘긴다.
**템플릿에 None을 0으로 포맷할 수 있는 경로가 존재하지 않는다.**

**최근 회차만 보여주면 과거의 결측이 화면에서 사라진다.** 구현하며 실제로 겪었다 —
유일한 결측인 2002년 시도 기준선이 최근 선거의 편차 4종에 끼지 않아 어디에도 안 보였다.
그래서 `EmdCard.gap_coverage` 가 단위별로 **시계열 전체의 분모**를 들고 있고, 비어 있는
단위에만 "8회 중 7회"를 편차 옆에 적는다. 결측이 그것이 속한 자리에서 보여야 한다.

**confidence 와 이어 붙인다.** 현재 `nec_archive` 의 `confidence: 0.7` 은 정확히 이 결측
(2002 서울시·2007 전국) 때문이다. 카드가 "신뢰도 0.7 · 기준선 N건 결측"을 한 줄로 보여주면
두 신호가 일관되고 사용자가 왜 낮은지 추론할 수 있다.
단 **결측의 *이유*(2002년 파일에 시도 열이 없다)는 레코드에 없다.** L3는 "몇 건 없다"까지만
말하고 원인을 지어내지 않는다.

## 9. 검증 배지 — 규칙 5의 집행

정의와 판정 규칙은 `docs/90-compliance.md`. 여기서는 **렌더 규칙**만 정한다.

> 산출물 블록은 `_output.html` 매크로를 통해서만 그린다. 매크로는 `verdict` 를 **필수 인자**로
> 받는다. **경고 없이 콘텐츠만 그릴 수 있는 경로가 템플릿에 존재하지 않는다.**

- `blocked` → 콘텐츠를 렌더하지 않는다. 자리에 차단 사유만
- `unreviewed` → 경고 배너를 **콘텐츠 위에** (옆·아래가 아니다)
- `cleared` → 조용한 배지 + 검토자·검토일
- `notes[]` → 상태와 무관하게 항상
- `None` → **`blocked` 와 같게 다룬다.** 판정 없음은 "안전"이 아니라 "모름"이고, 모르면
  안 그린다. 예전에는 `None` 이면 콘텐츠를 그냥 그렸다 — 화면들이 각자 "산출물이 0건이면
  매크로를 부르지 않는다"를 지켜서 누출은 없었지만, 그 규칙이 매크로가 아니라 **호출자**에
  있었다 (P-002 §10 이 막은 구멍)

## 10. 템플릿과 정적 자산

**Jinja2를 쓴다.** FastAPI가 `Jinja2Templates` 로 지원하고 autoescape가 기본 on이다.
표준 라이브러리 `string.Template` 은 반복·조건이 없어서 9칸 루프와 3상태 분기를 파이썬 문자열
조립으로 만들게 되고, 그러면 마크업이 로직 파일로 들어오고 이스케이프가 우리 책임이 된다.

`00-overview.md §4-1` 의 "별도 프론트 빌드 체인을 두지 않는다"는 **npm/webpack을 겨냥한 말**이다.
Jinja2는 "FastAPI + 서버 렌더"의 서버 렌더 쪽 절반이다.

- `static/app.css` **한 장**, 손으로 쓴다. JS 프레임워크 없음
- **차트 라이브러리 없음, CDN 없음.** 스파크라인·막대·지도 칸은 전부 **인라인 SVG** 이고
  좌표는 뷰모델이 계산한다
- 이유는 미학이 아니라 **컴플라이언스**다: 외부 요청이 0건이어야 캠프의 열람 맥락이 제3자에게
  새지 않는다. 이것이 "로컬 웹앱" 원칙의 실질이다
- 경로는 `Path(__file__).resolve().parent / "templates"` (`analyze/base.py` 가 이미 쓰는 패턴)
- **`/docs`·`/redoc`·`/openapi.json` 을 끈다.** Swagger UI 가 CDN 에서 스크립트를 받아온다
- CSS 링크는 `url_for` 가 아니라 상대 경로다. `url_for` 는 호스트를 포함한 절대 URL을
  만드는데, 나가는 요청이 전부 같은 출처임을 테스트로 확인할 수 있어야 한다
  (`tests/test_web.py::test_no_external_requests` 가 절대 URL 이 하나도 없음을 본다)

## 11. 지도 배치 — 지금은 격자, 나중에 경계

실제 행정동 경계 GeoJSON이 저장소에 없다. **출처·라이선스 확정이 이 작업 단위 안에서 끝나지
않는다** (행안부·통계청 SGIS·국토지리정보원이 각각 이용 조건이 다르다). 외부 타일 서비스는
로컬 원칙 위반이고, 타일 요청이 "누가 송파갑을 들여다보는가"를 제3자에게 흘린다.

동이 9개뿐이고, 이 화면이 답할 질문은 "경계가 정확히 어디인가"가 아니라 **"어느 동이 약한가"** 다.
9칸 색칠 격자가 그 질문에는 실제 경계와 동등하게 답한다.

`shapes.py` 를 **공급자 인터페이스**로 만든다:

```
EmdShape(geo_code, geo_name, svg_path, label_xy)
shapes_for(codes) -> list[EmdShape]
```

`data/shared/reference/emd_boundaries.geojson` 이 **있으면** 그걸 쓰고, 없으면 격자를 만든다.
템플릿과 라우트는 둘 다 `svg_path` 만 본다 →
**나중에 파일 한 장 떨구고 로더만 붙이면 화면 코드가 안 바뀐다.**

선례가 있다. A-001 §기준선: *"이 작업은 분석기보다 먼저일 필요가 없다. gap은 기준선 레코드가
없으면 None이고, 나중에 들어온 뒤 재실행하면 코드 변경 없이 채워진다."* 실제로 분석기 코드는
한 줄도 바뀌지 않았다.

**정직성 장치 둘:**

1. 경계 파일이 없을 때만 화면에 **"실제 행정동 경계가 아니다 — 격자 배치"** 고지를 띄운다.
   파일이 들어오면 자동으로 사라진다.
2. **칸을 손으로 배치하지 않는다.** `geo_code` 오름차순 고정. 대충 실제 위치처럼 놓는 것은
   근거 없는 지리를 지어내는 것이고, 배치가 판단이 되는 순간 그건 `data/shared/reference/` 에 있어야 할
   데이터가 된다. 지금은 그 판단을 **하지 않는 쪽**을 택한다.

## 12. 실행

```bash
uv run votelink serve [--host 127.0.0.1] [--port 8420] [--district <id>] [--camp <id>] [--auth]
```

- **`--auth` 가 단일 캠프와 멀티캠프를 가르는 스위치다.** 기본은 꺼짐이고, 그 상태의 앱은
  지금까지의 1인 로컬 사용과 같다. 켜면 로그인을 요구하고 캠프는 세션이 정한다 —
  그래서 `--camp` 와 함께 쓸 수 없다(캠프를 두 곳에서 정하면 화면이 어느 쪽을 따르는지
  알 수 없다). 켜기 전에 `votelink account create-operator` 로 운영자가 있어야 한다.
- **`--auth` 없이는 `127.0.0.1` 밖으로 열지 못한다** (아래 호스트 항목 참조).
- `--district` 는 **선택**이다. 주면 `/` 가 그 선거구로 바로 이동하고, 안 주면 `/` 가
  선택 화면을 띄운다(선거구가 하나뿐이면 그리로 이동). 기동 전 점검은 `--district` 를
  줬으면 그 하나만, 안 줬으면 정의된 선거구 전부를 `loaded/expected` 로 요약한다 —
  선거구가 여럿이어도 죽이지 않는다.
- **기본 호스트는 `127.0.0.1`.** `0.0.0.0` 이 아니다. 편의가 아니라 컴플라이언스에 인접한
  결정이다 — 미검토 산출물이 경고와 함께 뜨는 화면을 LAN에 열어두면 그게 의도치 않은 공표가 된다.
  **근거가 바뀌었다** (P-002 §2): 예전에는 비노출 자체가 인증을 대신했고, 이제는 인증·세션·감사가
  그 일을 한다. 그래서 노출을 허용하되 조건을 붙인다 — **`--auth` 없이 `127.0.0.1` 밖으로
  바인딩하면 기동을 거부한다**(fail-closed, `tests/test_cli.py`)
- `fastapi`·`uvicorn` 을 **모듈 최상단에서 import 하지 않는다.** `cmd_serve` 안에서 하고
  `ImportError` 를 `uv sync` 안내로 바꾼다 — 환경이 오래됐을 때 `collect`·`analyze` 까지 같이
  죽지 않도록 (`cmd_collect` 가 `FetchError` 를 트레이스백 없이 처리하는 것과 같은 패턴)
- **레코드가 0건이어도 서버를 띄운다.** 분석 러너가 입력 0건을 실패로 치는 것과 다른 판단인데,
  이유가 있다: 서버가 안 뜨면 *왜* 비었는지 볼 화면조차 없다. CLI 경고 + 빈 상태 화면이
  `uv run votelink analyze voter_profile` 을 안내한다
- **`--reload` 를 넣지 않는다.** Jinja2 `FileSystemLoader` 의 `auto_reload` 가 기본 참이라
  템플릿·CSS 수정은 새로고침만으로 반영된다. 파이썬 수정만 재시작이 필요하고, 그 정도로
  리로더 서브프로세스를 들일 이유가 없다

**의존성** (런타임 코어에 넣는다 — `serve` 가 `CLAUDE.md` 명령어 목록의 1급 명령이다):
`fastapi` · `uvicorn` (**`[standard]` 를 쓰지 않는다** — `uvloop` 는 Windows에서 안 깔리고
`httptools`·`watchfiles` 가 필요 없다) · `jinja2`.
테스트 의존성은 추가하지 않는다 — `fastapi.testclient.TestClient` 는 이미 있는 `httpx` 를 쓴다.

## 13. 저장은 아직 JSONL이다

`00-overview.md §4-1` 이 SQLite를 예고하지만 v0.1에서는 쓰지 않는다. 레코드가 9건이고
`docs/11-storage.md` 는 아직 없다. 전량을 메모리에 올리는 것으로 충분하며, 필요해지는 시점은
`foot_traffic` 처럼 건수가 자릿수로 커지는 데이터가 들어올 때다.

`/nation` 이 카드 수가 데이터에 비례하는 첫 화면이다 — 선거구 코드가 전부 채워지고 계열이
셋으로 늘면 수백~수천 장이 된다. `load_comparison` 도 N선거구 × 전체 스캔이라 O(N·R) 이다.
지금은 무의미하지만, 여기가 SQLite 트리거 지점이다.
