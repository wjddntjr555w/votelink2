# 웹앱(L3) 규약

> 상태: **v2(React SPA) 완료** (`frontend/`, `votelink/web/`, `uv run votelink serve`).
> 24개 화면 전부 React 로 옮겼다 — 로그인·가입·대기부터 대시보드·지도·뉴스·비교·
> 전국·마이페이지·주기(목록·추가·수정·로스터)·온보딩·운영자 콘솔까지. Jinja2 는
> `votelink/web/templates/{base,denied,districts,error}.html` 뿐이고, 이 넷은
> 화면이 아니라 그 화면들 아래에 깔리는 셸/오류 페이지다(`_icons.html` 도 그
> 셸이 쓴다). 이 문서는 여전히 그 시절 기준의 §1~§9 를 그대로 담고 있다 — 라우트
> 이름·리댁션 원칙·규칙 5 집행 지점 같은 개념은 React 로 옮긴 뒤에도 유효하고
> 실제로 §10-1 이 그 대응 관계를 하나씩 짚는다. 웹앱 화면을 만들거나 고칠 때
> 읽을 문서는 **이것(§10-1까지) + `frontend/src/`**다 — `votelink/web/app.py`·
> `ops.py` 는 이제 뷰가 아니라 JSON API 다.
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

`base.html` 의 `<head>` 가 Tailwind Play CDN·Chart.js CDN `<script>` 태그를 싣는다(§10의
화이트리스트). 나머지 화면은 여전히 `/static/app.css` + 이 두 CDN이 만드는 클래스만 쓴다.

`create_app(settings) -> FastAPI` **팩토리**로 만든다. 전역을 monkeypatch 하지 않고 테스트에서
임시 디렉터리를 주입할 수 있다. 라우트는 `Depends()` 대신 `request.app.state` 를 읽는다 —
라우트가 셋뿐이라 DI가 값을 못 하고, 기본인자 안의 함수 호출은 ruff `B008` 에 걸린다.

**선거구를 아는 법**: `analyzers/voter_profile/meta.yaml` 의 `config` 를 읽지 않는다
(L2 내부 상태다). 새 설정 파일도 만들지 않는다(값이 중복된다). 선거구는 **URL 이 정한다** —
`/d/<선거구>/` 와 `/d/<선거구>/map`. `/` 는 선거구가 하나뿐이면 그리로 302, 여럿이면
선택 화면(React, `DistrictsPage.tsx` — §10-1)을 띄운다. `--district` 나 `WebSettings.district_id` 는 `/` 가
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

선거구가 하나면 `/d/<그 선거구>/` 로 302. 여럿이면 선택 화면(React, 링크 목록 — `DistrictsPage.tsx`).
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
`GET/POST /onboarding` · `GET/POST /me`. 규약은
`docs/proposals/P-002-auth-and-camp-approval.md` §8-1·§9 이고, 여기서는 **위 세 화면
축과의 관계만** 적는다.

**`/me` 는 로그인만 했으면 누구나 연다** — 승인 대기든 온보딩 전이든 운영자든.
자기 비밀번호를 바꾸는 유일한 통로이고, `serve --auth` 가 만든 부트스트랩 운영자
(`root`/`root`)에게는 유일한 탈출구다. 바꾸면 **다른 기기의 세션이 전부 끊기고**
현재 세션만 새로 발급된다.

`/cycles` 아래도 캠프 쪽이다 — 선거 주기를 캠프가 스스로 더하고 고친다 (P-001 §7).

| 경로 | 무엇 |
|---|---|
| `GET /cycles` | 주기 목록. 지금 보는 주기를 표시한다 |
| `GET/POST /cycles/new` | 다음 주기 추가 |
| `GET/POST /cycles/{id}/edit` | 수정 폼 → **미리보기**(저장하지 않는다) |
| `POST /cycles/{id}/apply` | 확인을 거친 수정을 저장 |
| `GET/POST /cycles/{id}/roster` | 후보 로스터 |

`/onboarding`·`/cycles/new`·`/cycles/{id}/edit` 이 **같은 폼(`forms.CycleForm`)** 을 쓴다.
첫 주기와 두 번째 주기와 고친 주기가 다른 값을 받을 이유가 없고, 갈라두면 관할 검증 같은
것을 한쪽만 고치게 된다.

**관할은 프리셋·자치구·동 이름·코드 직접입력을 합쳐 받는다** (`resolve_territory` 가 dedup).
`/onboarding`·`/cycles/new` 에는 **동 이름 shuttle 위젯**이 있다 — 왼쪽에서 자치구·이름으로
걸러 체크 → `»` → 오른쪽에 자치구별로 모인다 (P-004). 코드가 확인된 동만 고를 수 있고,
미확인 동은 `emd_codes` textarea 로 넣는다. 위젯은 인라인 JS 를 쓰고, JS 가 없으면 숨어서
textarea 만 남는다.

**수정만 두 단계다.** 관할이 틀리면 에러 없이 모든 분석이 조용히 틀리므로(P-001 §16),
저장 전에 무엇이 달라지는지 보여주고 확인받는다 — 들고나는 동, 열리고 닫히는 선거구,
진영이 뒤집히는지, 폴더가 옮겨지는지. 계산은 `camp/changes.py`. 미리보기 상태를 어디에도
저장하지 않고 폼 값을 hidden 으로 다시 넘긴다.

**지금 보는 주기는 캠프가 고르지 않는다 — 선거일이 정한다.** 아직 안 지난 선거 중 가장
가까운 것(`camp/loader.py:current_cycle_id`). `/cycles` 가 무엇을 보고 있는지 표시한다.

**경로 파라미터를 파일 경로에 그대로 쓰지 않는다.** `{cycle_id}` 가 `cycle_dir()` 로
들어가므로 `list_cycles` 화이트리스트로 먼저 거른다. Starlette 가 `%2F` 를 라우팅 전에
풀어서 경로 탈출이 실제로 닿지는 않지만 그 사실에 기대지 않는다. 없는 주기는 **404**이고
설정이 깨진 주기는 500 이다 — "그런 것이 없다"와 "고칠 것이 있다"는 사람이 할 일이 다르다.

- **`/login`·`/signup`·`/healthz`·`/static/*` 에는 산출물이 없다.** 이 앱을 인터넷에 열어도
  되는 근거가 그것이다. 이 넷 중 하나에 숫자를 올리는 변경은 근거를 무너뜨린다.
- **어느 캠프의 눈으로 보는지는 세션이 정한다.** 그래서 렌즈·검토 기록·선거일이
  `app.state` 가 아니라 **`request.state`** 에 있다. 인증이 꺼져 있으면 미들웨어가 앱 전역
  값을 그대로 복사해 넣으므로 라우트의 코드 경로는 하나다.
- **`/d/<선거구>/` 는 세션의 관할로 스코프된다.** 검사는 라우트가 아니라 미들웨어에 있고
  경로 모양으로 걸린다 — `/d/` 밑에 화면을 더 붙여도 검사가 이미 따라와 있다.
  관할 밖이면 403(리다이렉트가 아니다) + 감사 로그 `denied`.

### 운영자 콘솔 — `/ops/*`

`votelink/web/ops.py` (별도 라우터). 규약은 `docs/proposals/P-003-operator-console.md`.

| 경로 | 무엇 |
|---|---|
| `GET /ops/` | 승인 큐 + 계정 목록 |
| `POST /ops/signups/{id}/approve` · `/reject` | 승인(캠프 공간 생성) · 거절(사유 필수) |
| `POST /ops/accounts/{id}/status` · `/logout` · `/passwd` | 정지·해제 · 세션 강제 종료 · 임시 비밀번호 |
| `GET /ops/camps/{camp_id}` | 그 캠프의 설정과 최근 이력 |
| `GET/POST /ops/camps/{camp_id}/cycles/{cid}/edit` | 주기 대리 수정 폼 → **미리보기** (P-005) |
| `POST /ops/camps/{camp_id}/cycles/{cid}/apply` | 확인·사유를 거친 대리 수정을 저장 |
| `GET /ops/audit` | 감사 로그 (캠프·건수 필터) |
| `GET /ops/news-parties` | 뉴스 검색용 정당명 전역 목록 + 수집 실행 |
| `GET/POST /ops/news-parties` · `PATCH`·`DELETE /ops/news-parties/{id}` | 목록 조회 · 추가 · 수정 · 삭제 (P-006) |
| `POST /ops/news-parties/collect` · `/collect/{district_id}` | naver_news 수동 수집 실행 — 전체 지역구 / 지역구 하나 (P-003 §4, 지금은 이 수집기 전용) |
| `POST /ops/news-parties/collect/{district_id}/candidates` | 위와 같은 지역구 수집이지만 지명·정당 검색어는 건너뛰고 후보·상대후보 검색어만 돈다(`NAVER_NEWS_QUERY_SCOPE=candidates`, P-006) |
| `GET /ops/news-parties/jobs` | 실행 이력과 상태(running/done/failed) — 로그 본문은 안 올린다 |

- **`role='operator'` 만 연다.** 판정은 `auth.is_ops` 접두어 검사이고 미들웨어에 있다 —
  라우터에 걸면 `include_router` 를 잊은 다음 사람이 통제까지 함께 잊는다.
- **이 화면들에도 산출물이 없다.** 계정·신청·감사 로그는 레코드가 아니다. 운영자 화면에
  캠프의 분석 숫자를 올리면 `verdict` 계산이 필요해지고 절대 규칙 5 가 걸린다 —
  캠프 상세는 설정과 메타만 낸다(관할 동 **수**, 진영, 선거일, 로스터 이름).
- **상태를 바꾸는 것은 전부 POST 다.** GET 으로 두면 링크 한 줄로 남의 캠프가 정지된다.
  POST 뒤에는 항상 리다이렉트하고(PRG) 알림은 쿼리스트링으로 넘긴다 — 한 줄 알림 때문에
  세션 저장소에 쓰기를 들이지 않는다.
- **운영자의 주기 대리 수정은 캠프의 2단계 흐름을 그대로 부른다** (P-005). `build_cycle`·
  `diff_cycle`·`scaffold` 가 같고, 다른 것은 둘뿐이다: `camp_id` 를 URL 에서 읽고, 저장 시
  **사유를 요구한다** (거절이 사유 없으면 거부되는 것과 같은 이유). 감사 액션은 캠프 자신의
  `edit_cycle` 과 구분해 `edit_cycle_by_operator` 로 남긴다 — 뭉치면 "이 캠프의 누군가"가
  고친 것처럼 보인다 (P-003 §5).
- `party_lineage.yaml` 류 참조데이터의 **구조적** 편집기는 아직 없다(P-003 §3·§7).
  `news-parties`(P-006)는 판단 근거 없는 단순 문자열 목록이라 그 제약과 무관한 일반
  CRUD다 — 예외가 아니라 다른 성격의 데이터다.
- 수집 실행은 **`naver_news` 하나로 범위를 좁혀 구현했다**(2026-09-13, P-003 §4).
  `votelink/control/jobs.py`가 CLI 를 subprocess 로 감싸고 `jobs` 테이블에 상태를
  기록한다 — 격리율 임계·`--dry-run` 같은 규칙은 CLI 에만 있고 여기서 다시 만들지
  않는다. 다른 수집기까지 받는 범용 실행 화면은 아직 없다.

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

- `static/app.css` **한 장**, 손으로 쓴다. SPA 프레임워크 없음(Jinja2 서버 렌더 유지)
- **2026-09-12 결정 — CDN을 화이트리스트로 허용한다.** 그 전까지는 차트 라이브러리·CDN이
  전혀 없었고 스파크라인·막대·지도 칸은 전부 인라인 SVG, 좌표는 뷰모델이 계산했다. 이유는
  미학이 아니라 컴플라이언스였다: 외부 요청이 0건이어야 캠프의 열람 맥락이 제3자에게
  새지 않는다. **UI/UX 품질을 위해 이 원칙을 완화하기로 결정했다** — 다음 두 CDN만 예외로
  허용한다:
  - `https://cdn.tailwindcss.com` — Tailwind Play CDN(빌드 스텝 없음). `base.html` 의
    스타일링에 쓴다
  - `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/...` (버전 고정) — 스파크라인 등
    시계열 시각화에 쓴다(`votelink/web/viewmodel.py::sparkline()` 이 좌표 대신 Chart.js
    데이터셋(`labels`/`values`)을 계산해서 넘긴다 — "템플릿은 산술을 하지 않는다"는
    원칙은 그대로다)
  - **트레이드오프를 정직하게 남긴다**: 이 두 CDN에 대한 요청이 발생하면 "이 캠프가 지금
    화면을 열람하고 있다"는 사실(접속 시각·IP)이 CDN 사업자의 서버 로그에 남을 수 있다.
    누가 어느 선거구를 보고 있는지 자체는 CDN이 알 수 없지만(요청에 그 정보가 없다),
    접속 사실 자체의 제3자 노출은 감수한 리스크다
  - **화이트리스트 밖 도메인은 여전히 금지.** 새 CDN을 추가하려면 이 목록에 먼저 적고
    이유를 남긴다 — 조용히 늘어나면 이 절이 거짓말이 된다
  - `map.html` 의 9칸 격자는 Chart.js가 표현하기 부적합한 커스텀 배치라 **인라인 SVG를
    그대로 유지**한다. `_output.html`(규칙5 매크로)의 렌더 구조·클래스명도 이번 변경과
    무관하게 그대로다
- **인라인 JS 는 여전히 허용한다** — topbar 의 `onchange` 전환, 온보딩의 동 이름 shuttle
  (P-004 §4), 이제 Chart.js 초기화 스크립트도 같은 결.
  `test_no_external_requests` 는 이제 "절대 URL 0건"이 아니라 **"위 화이트리스트 밖
  도메인 0건"** 을 데이터 화면에서 검증한다
- 경로는 `Path(__file__).resolve().parent / "templates"` (`analyze/base.py` 가 이미 쓰는 패턴)
- **`/docs`·`/redoc`·`/openapi.json` 은 여전히 끈다.** Swagger UI가 받아오는 CDN 스크립트가
  화이트리스트에 없다 — 켜려면 그 스크립트도 화이트리스트에 올려야 한다
- CSS 링크는 `url_for` 가 아니라 상대 경로다. `url_for` 는 호스트를 포함한 절대 URL을
  만드는데, 나가는 요청이 화이트리스트(같은 출처 + 위 두 CDN) 밖으로 안 나가는지 테스트로
  확인할 수 있어야 한다 (`tests/test_web.py::test_no_external_requests`)

### 10-1. React SPA (v2 완료 — 24개 화면 전부)

**2026-09-12, 화면 단위로 진행해 완료.** `/d/{district_id}/`(대시보드) ·
`/d/{district_id}/map`(지도) · `/d/{district_id}/news`(뉴스) · `/compare`(비교) ·
`/nation`(전국) · `/login`·`/signup`·`/pending`(인증 셋) · `/me`(마이페이지) ·
`/cycles`(주기 목록) · `/cycles/{id}/roster`(후보 로스터) · `/onboarding`·
`/cycles/new`(주기 생성, 동 이름 shuttle 포함) · `/cycles/{id}/edit`+
`/cycles/{id}/apply`(주기 수정 — 폼→미리보기→저장) · `/ops/`·`/ops/audit`·
`/ops/camps/{id}`·`/ops/camps/{id}/cycles/{cid}/edit`+`/apply`(운영자 콘솔) 를
전부 React 로 옮겼다. 위 §10의 CDN 화이트리스트는 이제 **적용 대상이 없다** —
CDN을 쓰던 화면(대시보드)이 가장 먼저 옮겨갔고, 그 뒤로 새로 옮긴 화면은 전부
아래 방식(런타임 외부 요청 0건)을 처음부터 썼다. §10은 그 결정의 기록으로 남겨둔다.

- **툴체인**: `frontend/`(Vite + React + TypeScript). `npm run build` →
  `frontend/dist/`. `votelink/web/app.py` 가 그 폴더를 `/assets` 로 정적 서빙하고,
  `/d/{district_id}/` 는 `dist/index.html` 을 그대로 돌려준다 — React Router 가
  URL의 `districtId` 를 클라이언트에서 읽는다(서버는 이 인자를 쓰지 않는다).
- **`/assets/...` 는 반드시 `auth.py::is_public()` 에 있어야 한다 — 화면이 아니라
  화면을 그리는 JS/CSS 다.** 이걸 빠뜨리면 로그아웃 상태(=최초 방문자 전부)의
  자산 요청이 인증 미들웨어에 걸려 `/login` 으로 303 리다이렉트되고, 브라우저는
  그 HTML 응답을 `<script type="module">` 로 실행하려다 "Expected a
  JavaScript-or-Wasm module script but the server responded with a MIME type
  of 'text/html'" 로 죽는다 — **로그인 화면 자체가 흰 화면이 된다**(로그인 폼을
  그릴 JS 도 같은 `/assets/` 에서 막히므로). 실제로 이 버그가 났었다: `/static/`
  은 처음부터 `is_public()` 에 있었지만 React 배치를 옮기며 새로 생긴
  `/assets/` 를 안 넣었다. `tests/test_web_auth.py::
  test_react_build_assets_are_public` 가 이제 이 경로를 지킨다 — 로그아웃
  상태로 `/assets/<아무 파일>` 을 불러 303 이 아님만 본다(실제 정적 서빙은
  `StaticFiles` 가 이미 검증됐다고 보고 파일 존재 여부는 안 본다).
- **데이터**: `GET /api/d/{district_id}` (JSON). `votelink/web/viewmodel.py` 의
  순수 함수(`build_view` 등)를 **한 줄도 바꾸지 않고** 그대로 쓴다 — L2/L3
  계층 무지가 이 지점에서도 이어진다. Pydantic 모델을 FastAPI가 재귀적으로
  JSON 인코딩한다.
- **런타임 외부 요청은 CDN 화이트리스트보다 더 엄격하다 — 0건이다.** Tailwind·
  Chart.js는 이제 CDN이 아니라 npm 패키지로 빌드에 번들된다. 웹폰트(IBM Plex
  Sans KR/Mono)도 Google Fonts CDN이 아니라 `@fontsource/*` npm 패키지로 번들한다
  (`frontend/src/main.tsx`). 빌드 시점에만 npm 레지스트리 접근이 필요하고, 배포된
  앱은 CDN조차 열지 않는다.
- **규칙 5는 서버가 여전히 집행한다 — 프런트를 믿지 않는다.** `_output.html`
  매크로가 하던 4분기(blocked→콘텐츠 안 그림, unreviewed→배너 먼저, cleared→조용한
  배지, notes→항상)를 프런트 `ComplianceGate` 컴포넌트가 그대로 재현하지만, **그건
  화면이 예쁘게 숨기는 것뿐이다.** 실제 데이터를 안 보내는 건 `votelink/web/app.py`
  의 `_redact_district_view`/`_redact_output` 이다 — `verdict.status == "blocked"`
  또는 판정 없음이면 그 산출물의 본문 필드를 서버가 응답 전에 지운다(`verdict` 자체는
  남겨서 프런트가 배너를 그릴 수 있게 한다). JSON API 를 df 열어 봐도 blocked 산출물의
  수치가 없어야 한다 — 네트워크 탭에서 JSON 응답을 직접 열어 봐도 마찬가지다
  (`tests/test_web.py::test_blocked_keeps_the_numbers_out_of_the_json`).
- **관할 스코핑도 API 경로까지 따라간다.** `votelink/web/auth.py::district_in_path`
  가 `/d/<선거구>/…` 뿐 아니라 `/api/d/<선거구>` 모양도 인식한다 — 화면만 막고
  API를 안 막으면 관할 밖 데이터가 API로 새 나간다(`tests/test_web_auth.py::test_the_api_route_is_scoped_to_the_camp_too`).
- **화면마다 리댁션 경계가 다를 수 있다 — 옛 Jinja 매크로 호출 자리를 그대로 옮긴다.**
  대시보드·지도는 콘텐츠 전체가 `output()` 게이트 안이라 `_redact_district_view`/
  `_redact_output` 이 전부를 지운다. 뉴스·비교는 옛 템플릿에서 게이트가 표
  (`rows`)만 감쌌다 — 뉴스는 요약 집계(건수·상위 언론사·기간), 비교는 제외된
  선거구 목록(`skipped`)이 게이트 밖이었다. 전국은 게이트가 `summary_card`·
  `cards` 만 감쌌다 — 표시 건수·인구·기준월·출처는 게이트 밖이었다. 그래서
  `_redact_news_view`/`_redact_comparison_view` 는 `rows` 만, `_redact_nation_view`
  는 `cards`·`summary_card` 만 지운다. **새 화면을 옮길 때 게이트 범위를 다시
  판단하지 말고, 지우려는 Jinja 템플릿에서 `{% call output(...) %}` 가 정확히
  무엇을 감쌌는지부터 확인한다.**
- **"지금 이 선거구"가 없는 화면(비교·전국)은 `Sidebar`/`TopBar` 에 `districtId` 를
  안 넘긴다.** 두 컴포넌트 다 `districtId` 를 선택 인자로 받고, 없으면 대시보드·
  지도·뉴스 링크와 선거구 전환 select 를 안 그린다 — 옛 `base.html` 의
  `{% if district_id %}` 와 같은 판단이다.
- **카드 컴포넌트는 화면 사이에 재사용한다.** `EmdDetailCard`(옛 `_card.html`)는
  대시보드의 상세 아코디언과 전국 화면이 그대로 같이 쓴다 — `EmdCard.gaps` 에
  실제로 들어 있는 단위(대시보드는 4단계, 전국은 `nation` 하나)만 렌더링되므로
  `levels` 인자를 따로 넘길 필요가 없다. `NationSummaryCard`(옛 `_agg.html`)는
  전국 종합 카드 전용 — 대시보드의 `TrendChart`는 같은 `AggregateCard` 데이터를
  차트 형태로 보여줄 뿐 다른 컴포넌트다.
- **인증 셋(로그인·가입·대기)은 폼이 아니라 fetch 로 POST 한다.** 나머지 화면은
  전부 GET(조회)이라 문제되지 않았지만, 로그인·가입은 서버 리다이렉트로는 성공·
  실패를 구분해 클라이언트에 돌려줄 수 없다(리다이렉트를 fetch 가 따라가면 최종
  응답이 SPA 셸 HTML이라 성공 여부를 알 수 없다). 그래서 `POST /api/login`·
  `POST /api/signup` 은 JSON 바디를 받고 JSON({"ok": true} 또는 {"error": "..."})
  을 낸다 — 세션 쿠키는 여전히 `_with_session` 이 `Set-Cookie` 로 붙인다(JSON
  응답이어도 브라우저는 쿠키를 그대로 저장한다). `POST /logout` 은 그대로 폼/
  리다이렉트다 — 성공·실패를 가릴 필요가 없어서(항상 로그아웃된다) 바꿀 이유가
  없었다.
- **화면 하나가 열리려면 미들웨어의 경로 집합에도 `/api/...` 짝을 넣어야 한다.**
  `auth.py::PUBLIC_PATHS` 에 `/api/login`·`/api/signup`, `PENDING_PATHS` 에
  `/api/pending` 을 추가했다 — 화면(`/login` 등)만 열고 그 데이터 경로를 안 열면
  React 컴포넌트가 뜨자마자 리다이렉트에 걸린다(대시보드가 `district_in_path` 로
  `/api/d/<선거구>` 를 인식하게 만든 것과 같은 종류의 실수를 여기서도 피한다).
- **`Sidebar` 가 로그인 상태를 안다.** `authOn` 이 참이면 계정 유무에 따라 "내
  계정"+로그아웃 또는 "로그인" 링크를 푸터에 그린다(`rail__account`) — 옛
  `base.html` 사이드바 푸터와 같은 자리다. 로그아웃은 `fetch("/logout", {method:
  "POST"})` 뒤 `/login` 으로 직접 이동한다(폼 제출이 아니다, 그래도 GET이 아니라서
  규칙은 지킨다).
- **`/me` 도 로그인·가입과 같은 이유로 fetch JSON 이다** — 비밀번호 변경 성공·
  실패를 리다이렉트로는 구분할 수 없다. 옛 PRG(POST 뒤 리다이렉트로 조회) 패턴은
  통째로 없앴다: `POST /api/me` 가 `{"ok": true}` 를 직접 돌려주면 `MePage` 가
  그 자리에서 성공 배너를 보여주고 세션 수를 다시 불러온다 — 새로고침도, 쿼리
  파라미터(`?ok=1`)도 필요 없다. `/api/me` 는 `auth.py::SELF_PATHS` 에 있다(`/me`
  와 짝) — 로그인만 했으면 계정 상태와 무관하게 열린다.
- **화면 하나가 폼을 공유하면 그 화면들은 같은 배치에서 옮긴다.** `/onboarding`·
  `/cycles/new`·`/cycles/{id}/edit` 는 전부 같은 `CycleForm`(+동 이름 shuttle,
  P-004)을 쓴다 — 하나만 옮기면 그 폼 컴포넌트를 두 번 만들거나 Jinja/React 를
  오가는 이상한 화면이 된다. 셋을 한 배치로 묶었다. 반대로 `/cycles`(목록) ·
  `/cycles/{id}/roster`(로스터)는 이 폼이 전혀 없어서 먼저 옮길 수 있었다.
- **폼 컴포넌트는 `mode` 로 갈라 재사용한다, 라우트로 가르지 않는다.**
  `CycleFormFields`(공유 필드셋) + `EmdShuttle`(관할 위젯)을 온보딩·주기 추가·
  주기 수정이 전부 같이 쓴다. `CycleFormPage` 하나가 `/onboarding`과 `/cycles/new`
  둘 다를 맡고(`useLocation().pathname`으로 어느 쪽인지 판단, `mode="create"`),
  `CycleEditPage`가 `/cycles/{id}/edit`을 맡는다(`mode="edit"`) — 필드는 같고
  문구·후보 정당/현직 필드 유무만 다르다. **화면 두 개를 하나로 합치려는 유혹은
  없다**: 수정은 폼→미리보기→저장의 2단계 흐름(`view` state 전환, URL 불변)이
  create 흐름과 근본적으로 다르다.
- **주기 수정의 "확인" 단계는 URL을 안 바꾼다.** 옛 Jinja는 POST 뒤 다른 템플릿
  (`cycle_preview.html`)을 같은 요청·응답에서 그렸다. React 로는 그 방식이 없다
  — 대신 `CycleEditPage` 가 `view: "form" | "preview"` 로컬 state로 같은 페이지
  안에서 전환한다. `POST /api/cycles/{id}/edit` 는 **저장하지 않고** `change`
  (`camp/changes.py::CycleChange` 를 JSON으로 그대로 낸 것, `_change_to_json`)
  만 돌려준다 — `change.is_empty` 가 참이면 프런트가 확인 화면 없이 `/cycles` 로
  바로 돌아간다(옛 라우트의 리다이렉트와 같은 판단). 실제 저장은 사용자가
  "이대로 저장"을 눌러야 `POST /api/cycles/{id}/apply` 가 한다.
- **운영자 콘솔(`ops.py`)도 마지막 배치에서 옮겼다.** `router`(`/ops`)는 SPA 셸만
  돌려주고, 새 `api_router`(`/api/ops`)가 JSON을 낸다 — 계산은 그대로
  `votelink/control/` 을 그대로 부른다(승인·거절·정지·세션 종료·비밀번호 발급은
  새 로직 0). 캠프 대신 주기 수정(P-005)도 캠프 쪽과 **완전히 같은 계산**
  (`_cycle_form_options`/`_prefill_cycle_form`/`_change_to_json`/`build_cycle`/
  `diff_cycle`/`scaffold`, 전부 `app.py` 의 것을 그대로 부른다)을 쓴다 — 다른 건
  `campId` 를 URL에서 읽는 것과 저장 시 사유(`note`)를 요구하는 것뿐이다.
  `cycle_edit.html`·`cycle_preview.html`·`_emd_shuttle.html`·`_ops.html`·
  `ops_camps.html`·`ops_camp.html`·`ops_audit.html` 을 전부 지웠다 — 이제 아무도
  렌더링하지 않는다. 더 이상 아무도 쓰지 않게 된 `_onboarding_ctx`/`_edit_ctx`
  (Jinja 컨텍스트 조립)·`_auth_ctx`도 같이 지웠다. **마지막까지 `_output.html`
  매크로(+ `_card.html`/`_agg.html`)를 쓰던 화면이 바로 운영자 콘솔이었다** —
  옮기고 나니 그 셋도 죽은 코드가 됐다(같이 삭제, 회귀 테스트는
  `ComplianceGate.test.tsx` 로 완전히 넘어갔다).
- **`is_ops()` 도 `/api/ops/...` 짝을 인식해야 한다.** `auth.py::authorize()` 의
  `is_ops(path) and not (account and account.is_operator)` 검사가 실제 접근
  통제 지점이다(`gate()` 는 그 뒤 대부분의 경로를 그냥 통과시킨다) — `/ops/...`
  접두어만 보고 `/api/ops/...` 를 안 보면, 캠프 계정이 콘솔 화면은 못 열어도 그
  데이터 API 는 직접 불러 **다른 캠프의 설정·감사 로그를 볼 수 있었다.** 같은
  이유로 `gate()` 의 운영자 리다이렉트 조건에도 `/api/cycles`·`/api/onboarding`
  (캠프 전용 화면을 `/ops/` 로 되돌리는 목록)을 짝으로 넣었다 — 운영자가 그
  API 를 직접 불러 camp_id 없이 500 을 만들 수 있었다. `PUBLIC_PATHS`/
  `PENDING_PATHS`/`ONBOARDING_PATHS`/`SELF_PATHS` 를 늘릴 때마다 반복된 패턴이다:
  **화면 경로를 막는 집합에 새 화면을 넣을 때는 그 데이터 경로도 같이 넣는다.**
- **FastAPI 함정 — `Body()` 파라미터가 하나뿐이면 JSON 객체로 안 온다.**
  `POST /api/ops/signups/{id}/reject` 가 `note: Annotated[str, Body()]` 하나만
  받게 짰더니, `{"note": "..."}` 로 보낸 요청이 422 로 죽었다 — FastAPI는 본문
  파라미터가 **둘 이상**일 때만 자동으로 객체로 묶고, 하나뿐이면 본문 자체가 그
  값이어야 한다(`"..."`, 객체가 아니라). 실제로 이 버그가 났었다(`reject`·
  `set_status`·`set_password` 셋 다) — `tests/test_web_ops.py` 를 돌리기 전까진
  안 보였다. 고치는 법은 `Body(embed=True)`: 파라미터가 하나뿐이어도 강제로
  `{"key": 값}` 모양을 받는다. **본문 파라미터를 한 개만 받는 POST 라우트를
  새로 만들 때마다 이 함정을 먼저 확인한다** — 필드가 둘 이상이면 자동으로
  괜찮으므로 이 규칙은 단일 필드 라우트에만 해당한다.
- **컴포넌트**: `frontend/src/components/{layout,compliance,dashboard,map,nation,cycle}/`,
  `frontend/src/pages/{DashboardPage,MapPage,NewsPage,ComparePage,NationPage,
  LoginPage,SignupPage,PendingPage,MePage,CyclesPage,RosterPage,CycleFormPage,
  CycleEditPage,OpsConsolePage,OpsCampPage,OpsCycleEditPage,OpsAuditPage}.tsx`.
  디자인 토큰은 `frontend/src/design-system/{tokens.css,components.css}` —
  색·spacing·타이포를 Jinja 시절과 별개로 새로 정의했다(진영 4색·컴플라이언스
  3색은 의미만 유지). 인증 화면·로스터·주기 폼·운영자 대리 수정은
  `.auth-page`/`.auth-gate`(콘솔 셸 없이 가운데 카드 하나) 전용 스타일을 쓴다.
- **테스트**: 프런트는 Vitest + React Testing Library
  (`frontend/src/**/*.test.tsx`) — `ComplianceGate` 가 가장 두껍게 테스트된
  컴포넌트다(절대 규칙 5). 백엔드 회귀는 `tests/test_web.py`·`test_web_lens.py`·
  `test_web_pulse.py`·`test_web_issues.py`·`test_web_news.py`·`test_web_compare.py`·
  `test_web_nation.py`·`test_web_auth.py`·`test_web_me.py`·`test_web_cycles.py`·
  `test_web_cycle_edit.py`·`test_web_ops.py` 가 `/api/d/{id}`·`/api/d/{id}/map`·
  `/api/d/{id}/news`·`/api/compare`·`/api/nation`·`/api/login`·`/api/signup`·
  `/api/pending`·`/api/me`·`/api/onboarding`·`/api/cycles`·`/api/cycles/new`·
  `/api/cycles/{id}/edit`·`/api/cycles/{id}/apply`·`/api/cycles/{id}/roster`·
  `/api/ops/console`·`/api/ops/camps/{id}`·`/api/ops/camps/{id}/cycles/{cid}/edit`·
  `/apply`·`/api/ops/audit` JSON을 본다 — HTML 문자열 검사(구 Jinja 테스트)는
  전부 걷어냈다. `test_web_ops.py` 는 `OPS_PATHS`(`/ops/...`)와
  `API_OPS_PATHS`(`/api/ops/...`) 둘 다에 대해 캠프 계정 403 을 확인한다 — 위
  `is_ops()` 회귀를 이 파라미터화 테스트가 잡는다.
- **아직 안 옮긴 것**: 없다. `/` 의 선거구 선택 화면(`DistrictsPage.tsx`)도 이제
  React다 — `/api/districts` 가 JSON을 낸다. `votelink/web/templates/` 에 남은 건
  `base.html`·`denied.html`·`error.html`·`_icons.html` 뿐이다 — 화면이 아니라 그
  화면들 아래에 깔리는 셸/오류 페이지다. 다음 확장은 새 화면 자체를 더하는
  일이지, 남은 화면을 옮기는 일이 아니다.

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
- **`--auth` 는 운영자가 없으면 `root`/`root` 를 만든다.** 서버를 띄우기 전에 명령을
  하나 더 기억하지 않아도 되게 한다. 이미 운영자가 있으면 손대지 않는다 (P-002 §8-1).
- **`127.0.0.1` 밖으로 열려면 조건이 둘이다** — `--auth` 가 켜져 있을 것, 그리고
  운영자가 배포 기본 비밀번호를 **이미 바꿨을 것**. 아는 비밀번호가 서버에 있으면
  인증이 없는 것과 같다. `/me` 에서 바꾼 뒤에 열린다.
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
