# P-004: 온보딩 관할 — 동 이름으로 고르기

> `P-` = 플랫폼/아키텍처 제안서.
>
> 상태: **채택 · 구현** (2026-09-09). **P-001 을 전제한다** — 관할(`Territory`)과
> `resolve_territory` 가 이미 있고, 이 문서는 그 입력 수단 하나를 더 붙인다. 스키마도
> 저장 경로도 바뀌지 않는다.
>
> **`/onboarding` · `/cycles/new` 에 동 이름 shuttle 위젯을 넣었다.** `emd_codes` textarea 는
> 남는다. 이 폼에 **처음으로 인라인 JS 가 들어갔다** — §4 가 그 결정을 적는다.

## 1. 무엇을

`/onboarding` (과 `/cycles/new`) 의 **관할** fieldset 에서, 행정동코드를 손으로 타이핑하는
대신 **동 이름 shuttle 위젯**으로 고른다.

- **왼쪽** — `districts.yaml` 의 코드가 확인된 행정동 전부. 자치구 드롭다운과 이름
  검색창으로 거른다.
- **`»` / `«`** — 왼쪽에서 체크한 동을 오른쪽으로, 오른쪽에서 체크한 동을 도로.
- **오른쪽** — 고른 동이 **자치구별로 묶여** 쌓인다. 이게 최종 관할의 미리보기다.

고른 코드는 hidden `<input name="emd_pick">` 로 제출된다. `emd_codes` textarea 는
**없애지 않는다** — 셋째 입력 수단으로 남고, `build_cycle` 이 `emd_pick + textarea` 를
합쳐 기존 경로(`resolve_territory` → `unknown` 검사 → dedupe)에 태운다. `resolve_territory`
가 프리셋·자치구·직접입력 셋을 이미 합치므로(P-001 §6) 넷째가 늘 뿐이다.

## 2. 왜 필요한가

프리셋(국회의원 선거구)으로도 자치구 전체로도 안 잡히는 관할 —
**기초의원 선거구 가·나·다** (P-001 §6) — 은 textarea 가 유일한 통로였다. 그 경우 캠프는:

1. `uv run votelink district list --emd` 를 **터미널에서** 쳐서 코드를 베껴오고
   (웹만 쓰는 캠프에게 이 단계가 벽이다),
2. 10자리 숫자를 오타 없이 옮겨야 한다. 틀리면 `build_cycle` 이
   `districts.yaml 이 모르는 행정동코드다` 로 저장을 거부한다(`forms.py`) — **틀린 코드**는
   잡히지만 **맞지만 엉뚱한 동**(`…53000` 을 `…54000` 으로)은 안 잡힌다.

두 번째가 P-001 §16 이 "가장 위험한 실패"로 지목한 자리다 — 관할이 틀리면 에러 없이 모든
분석이 조용히 다른 답을 낸다. 사람은 `1171053000` 을 보고 그게 맞는 동인지 판단할 수 없지만
**동 이름을 보면 판단할 수 있다.** 이 제안은 손입력 오타라는 실패 모드 하나를 없앤다.

## 3. 데이터는 이미 있다

`districts.yaml` 의 `Emd` 가 `name` 과 `code` 를 함께 들고 있다(`districts.py`). `_onboarding_ctx`
가 `load_districts` 를 이미 부른다. 거기서 `(sigungu, [(code, name)…])` 목록 하나를 더 뽑아
(`emd_groups`) 템플릿에 넘긴다. **새 참조 소스도 새 로더도 없다.**

`code=null` 인 미확인 동은 목록에서 빠진다 — 코드가 없으면 관할에 넣을 수 없다(백필 D-001
이 먼저다). 그 동이 필요하면 textarea 로 넣는다.

## 4. 인라인 JS — 이 폼의 첫 스크립트

이 폼은 지금까지 JS 를 안 썼다. 로스터도 상대 후보를 textarea 한 줄씩 받는다. shuttle 은
`»` 버튼·자치구 필터·오른쪽 목록이 전부 JS 를 요구하므로 그 규율을 깬다.

**깨는 범위를 좁혔다:**

- **외부 요청 0건 규칙은 그대로다.** 인라인 `<script>` 한 조각, CDN 도 라이브러리도
  빌드 체인도 없다. `webapp-spec §10` 이 겨눈 것(컴플라이언스 — 열람 맥락이 제3자에게
  새는 것)은 건드리지 않는다. topbar 의 `onchange="location.href=…"` 와 같은 급이다.
- **JS 가 없으면 위젯은 `hidden` 인 채로 남는다.** `<noscript>` 가 "코드를 직접 넣으라"고
  안내하고, textarea 경로가 그대로 동작한다. 폼은 JS 없이도 완전하다.
- **hidden `emd_pick` 이 실제 제출값이다.** 스크립트는 선택이 바뀔 때마다 hidden 을
  재생성한다. 검증 실패로 폼이 다시 열리면 서버가 `form.emd_pick` 을 hidden 으로
  다시 찍고, 스크립트가 그걸 읽어 오른쪽 목록을 복원한다 — JS 가 죽어도 이전 선택은
  hidden 으로 살아서 제출된다.

## 5. 검증은 하나도 안 바뀐다

`build_cycle` 의 방어가 그대로 유효하다:

- 체크박스가 주는 코드는 정의상 `known_emd_codes` 안이다 → `unknown` 은 체크박스
  경로에서 뜰 수 없고 textarea 경로에서만 뜬다(그쪽은 그대로 둔다).
- 프리셋으로 이미 들어온 동을 또 골라도 `resolve_territory` 가 dedupe 한다.
- 관할이 비면 여전히 `ScaffoldError`. shuttle 은 "하나 이상" 요건을 채우는 또 하나의
  방법일 뿐이다.

## 6. 제약과 위험

- **`districts.yaml` 이 커지면 왼쪽 목록이 길어진다.** 지금은 송파 중심이지만 서울
  전역(D-006)이면 ~425동이다. 왼쪽은 스크롤 박스(`max-height`)이고 자치구·이름 필터로
  좁힌다. 그래도 렌더링되는 `<li>` 는 전량이다 — 수백 개 수준은 브라우저가 감당하지만,
  수천으로 가면 자치구별 지연 렌더가 필요하다. 그 시점에 이 절을 다시 본다.
- **`/cycles/{id}/edit` 은 범위 밖.** 수정은 2단계 확인 폼이라(`webapp-spec §221`) 관할
  입력 UI 가 다르다. 온보딩·주기추가가 같은 템플릿을 쓰므로 그 둘만 얻는다.
  → **2026-09-10: P-005 §9 가 이걸 뒤집었다.** shuttle 을 `_emd_shuttle.html` partial 로
  빼고 수정 폼도 include 한다 — 미리보기가 diff 를 잡으므로 입력 수단만 같아지고 확인
  절차는 그대로다.
- **shuttle 은 JS 에 의존한다.** 첫 의존이다. §4 가 좁혔지만 "모든 화면이 서버 렌더만으로
  완전하다"는 명제에서 "이 위젯은 향상이고 폴백이 있다"로 내려왔다.

## 7. 이번 범위 아님

지도 클릭 선택 · 주소 검색 · 기초의원 선거구 프리셋 데이터화(별도 `D-` 제안) ·
`/cycles/{id}/edit` 관할 UI · 왼쪽 목록 지연 렌더

## 8. 채택 시 갱신할 문서

| 문서 | 고칠 것 | 상태 |
|---|---|---|
| `votelink/web/forms.py` | `CycleForm.emd_pick` · `build_cycle` 의 코드 합치기 | ✅ |
| `votelink/web/app.py` | `_onboarding_ctx` 가 `emd_groups` 를 넘긴다 | ✅ |
| `votelink/web/templates/onboarding.html` | shuttle 위젯 + 인라인 스크립트 | ✅ |
| `votelink/web/static/app.css` | `.shuttle*` | ✅ |
| `docs/40-webapp-spec.md` | 온보딩 관할 입력에 shuttle 한 줄 · §10 에 "인라인 JS 예외" | ✅ |
| `CLAUDE.md` | 토큰 규율 표의 캠프/온보딩 행에 P-004 추가 | ✅ |
