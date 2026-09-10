# P-005: 운영자가 캠프의 선거 주기를 고친다

> `P-` = 플랫폼/아키텍처 제안서.
>
> 상태: **채택 · 구현** (2026-09-10). **P-003 §2 의 결정을 좁게 개정한다** — 그 문서는
> "운영자는 `/ops/camps/<id>` 에서 결과를 읽기만 한다"고 적었다. 이 문서는 거기에
> **교정용 쓰기 하나**를 연다. P-001 → P-002 → P-003 을 전제한다.
>
> 스키마도 저장 경로도 안 바뀐다. 캠프가 이미 쓰는 2단계 수정 흐름
> (`/cycles/{id}/edit` → 미리보기 → `apply`)을 `/ops/*` 아래에서 운영자 권한으로
> 다시 부를 뿐이다.

## 1. 무엇을

`/ops/camps/<camp_id>` 의 각 선거 주기에 **[수정] 링크**를 붙인다. 운영자가 그 캠프의
`CycleForm` 전체(후보명·정당·진영·직위·선거일·관할·incumbent·법률검토자)를 고친다.
저장 경로는 캠프 쪽과 **완전히 같다**:

```
GET  /ops/camps/{camp_id}/cycles/{cycle_id}/edit    폼
POST /ops/camps/{camp_id}/cycles/{cycle_id}/edit    미리보기 (저장 안 함)
POST /ops/camps/{camp_id}/cycles/{cycle_id}/apply   확인한 수정을 저장
```

미리보기·확인·폴더 이동·`diff_cycle` 계산이 그대로다. 다른 것은 **딱 둘**:

- `camp_id` 를 세션 계정이 아니라 **URL 경로**에서 읽는다 (§4).
- 저장 시 **사유(note)를 요구한다** — 거절이 사유 없으면 거부되는 것과 같은 이유
  (P-003 §2). 사유는 감사 로그와 P-001 §11 갱신 이력에 들어간다.

## 2. 왜 P-003 §2 를 뒤집나

P-003 은 "운영자가 대신 입력하면 관할을 캠프보다 운영자가 더 잘 안다는 전제가 된다"고
막았다. 그 우려는 **일상 입력**에 대한 것이고, 이 제안이 여는 것은 아니다:

1. **캠프가 스스로 못 고치는 상태.** 로그인 불가·정지·온보딩 미완 상태에서 주기가
   잘못 저장돼 있으면 캠프의 `/cycles/{id}/edit` 는 닿지 않는다. 지금 유일한 통로는
   운영자가 서버에 붙어 YAML 을 손으로 고치는 것이고, 그건 감사 로그도 미리보기도
   없는 경로다.
2. **명백한 오류 교정.** `1171053000` 대신 `1171054000` 이 들어간 관할, 진영 오분류.
   P-004 가 손입력 오타를 줄였지만 이미 저장된 것은 못 되돌린다.

두 경우 모두 **운영자가 값을 창작하지 않는다** — 캠프가 알려준 정정을 대신 친다.
그리고 캠프가 받는 안전장치를 운영자도 똑같이 받는다: `diff_cycle` 이 들고나는 동,
열리고 닫히는 선거구, 뒤집히는 진영, 옮겨지는 폴더를 저장 **전에** 보여준다
(P-001 §16). 감사 로그가 운영자 이름과 사유를 남긴다.

## 3. 재사용하는 것 — 새 로직 0

| 이미 있는 것 | 위치 | 이 제안에서 |
|---|---|---|
| `CycleForm` · `build_cycle` | `web/forms.py` | 그대로 |
| 2단계 미리보기 (`diff_cycle`) | `camp/changes.py` | 그대로 |
| `cycle_edit.html` · `cycle_preview.html` | `web/templates/` | 그대로 (action 만 `/ops/...`) |
| `rename_cycle` · `write_election` | `camp/scaffold.py` | 그대로 |
| 접근 통제 | `web/auth.py` 미들웨어의 `/ops` 판정 | 그대로 — 새 라우트가 접두어 안이라 공짜 |

**로직을 이중화하지 않는다.** ops.py 가 CLI 를 감싸기만 하는 것과 같은 원칙
(P-003 서두). 캠프 흐름이 바뀌면 운영자 흐름도 같이 바뀌어야 하므로 함수를 공유한다.

## 4. `camp_id` 출처만 바꾼다

지금 `_own_cycle` · `_edit_ctx` 는 `request.state.account.camp_id` 를 읽는다. camp_id 를
**인자로 받도록** 뺀다:

- `_cycle_in_camp(settings, camp_id, cycle_id)` — 모듈 레벨 화이트리스트 검사. 캠프
  라우트의 `_own_cycle` 은 이걸 `account.camp_id` 로 부르는 두 줄 래퍼로 남고, 운영자
  라우트(`ops._target_cycle`)는 경로값으로 부른다.
- `_edit_ctx(..., edit_base, list_href, list_label, by_operator)` — 폼 action 과 배너를
  가른다. 기본값은 캠프용(`/cycles`)이라 캠프 라우트는 한 글자도 안 바뀐다.
- `{camp_id}` 도 `list_camps` 화이트리스트로 먼저 거른다 — `{cycle_id}` 를
  `list_cycles` 로 거르는 것과 같은 이유 (경로 탈출·모르는 캠프에 404).
- 운영자 라우트의 감사 로그는 `action="edit_cycle_by_operator"` 로 **구분한다**.
  같은 `edit_cycle` 로 뭉치면 "이 캠프의 누군가"가 고친 것처럼 보인다 — P-003 §5 가
  경고한 과신이 여기서 생긴다. `account_id` 는 운영자, `camp_id` 는 대상 캠프,
  `detail.note` 는 사유.

캠프 쪽 라우트·템플릿·URL 은 **한 글자도 안 바뀐다**. 운영자 템플릿은 폼 `action` 과
"이 캠프를 대신 고치는 중" 배너만 다르면 되므로 `cycle_edit.html` 을 `ops_edit` 플래그로
분기하거나 얇은 래퍼 템플릿을 둔다 (구현 시 결정).

## 5. 검증·감사 — 캠프와 동일 + 사유

- `build_cycle` 의 방어가 그대로다 — 모르는 `admmCd`, 빈 관할, 형식 오류 전부 저장을
  거부한다.
- **사유가 비면 미리보기에서 막는다.** 미리보기 화면에 사유 입력란을 두고, `apply` 가
  비어 있으면 400 으로 되돌린다.
- 감사 로그 `detail` 에 캠프 쪽과 같은 필드(`from`·`added`·`removed`·`lineage`·`moved`)
  + `note`.

## 6. 제약과 위험

- **운영자가 캠프의 진영을 뒤집을 수 있게 된다.** 경쟁 캠프를 함께 받는 구조에서
  운영자는 이미 단일 신뢰 지점이다 (P-003 §6). 이 제안은 그 신뢰의 표면을 넓힌다 —
  줄이는 장치는 미리보기 + 사유 필수 + 구분된 감사 액션뿐이고, 그 이상은 운영자 수를
  최소로 두는 것 말고 없다.
- **`camp_id` 는 이 화면에서 안 바꾼다.** 관할·진영은 폴더를 옮겨도 `rename_cycle` 이
  주기 폴더 하나만 다룬다. `data/camps/<camp_id>/` 자체를 바꾸는 건 계정 테이블과
  디스크를 함께 건드려야 해서 별개다 (필요하면 별도 `P-`).
- **로스터(`/cycles/{id}/roster`)는 범위 밖.** 틀려도 분석을 안 바꾸므로(확인 단계도
  없다) 운영자가 대신 고칠 이유가 약하다. 필요해지면 같은 패턴으로 나중에.
- **동시 수정.** 운영자가 미리보기를 띄운 사이 캠프가 같은 주기를 고치면 마지막
  저장이 이긴다. 지금 캠프 쪽도 그렇다 — 이 제안이 새로 들이는 위험은 아니고, 락은
  범위 밖.

## 7. 이번 범위 아님

`camp_id` 변경 · 로스터 대리 수정 · 캠프 계정 없이 캠프 공간만 만드는 흐름 ·
운영자 역할 세분화 · 수정 이력 롤백 UI · 동시 수정 락

## 9. 관할을 동 이름으로 고른다 (2026-09-10 추가)

P-004 §7 이 "이번 범위 아님"으로 두었던 **`/cycles/{id}/edit` 관할 UI** 를 여기서 채운다 —
운영자 대리 수정 폼도 같은 템플릿을 쓰므로 함께 얻는다.

- onboarding 의 shuttle 위젯·스크립트를 `templates/_emd_shuttle.html` **partial** 로 빼고
  `/onboarding`·`/cycles/new`·`/cycles/{id}/edit`·`/ops/.../edit` 이 모두 include 한다.
  중복 0. 스크립트도 partial 안에 있다.
- 수정 폼은 **현재 관할이 shuttle 오른쪽(선택됨)에 미리 채워진다**. `_edit_ctx` 가
  `cycle.territory.emd_codes` 중 `districts.yaml` 이 아는 코드를 `emd_pick` 으로,
  미확인 코드는 `emd_codes` textarea 로 내린다. 위젯 스크립트가 hidden `emd_pick` 을
  seed 로 읽어 오른쪽을 복원하므로(P-004 §4) 추가 JS 는 없다.
- **프리셋과의 관계는 안 바꾼다.** 프리셋이 걸린 채로 shuttle 에서 동을 빼면 저장 시
  `resolve_territory` 가 프리셋에서 다시 넣는다 — 기존 textarea 경고와 같다. 폼이 그
  사실을 한 줄로 알린다("개별로만 관리하려면 프리셋을 (쓰지 않음)으로").
- P-004 §6 의 우려("수정은 2단계 확인 폼이라 UI 가 다르다")는 그대로 유효하지만 —
  미리보기가 diff 를 보여주므로 **틀리게 고를 위험은 미리보기가 잡는다**. 입력 수단만
  onboarding 과 같아졌고 확인 절차는 그대로다.

## 8. 채택 시 갱신할 문서

| 문서 | 고칠 것 | 상태 |
|---|---|---|
| `votelink/web/app.py` | `_cycle_in_camp` 를 모듈 레벨로 빼고 `_edit_ctx` 에 `edit_base`·`list_href`·`by_operator` 인자화 | ✅ |
| `votelink/web/ops.py` | `/ops/camps/{id}/cycles/{cid}/edit`·`/apply` 3개 라우트, `_OpsCycleForm(note)` | ✅ |
| `votelink/web/templates/ops_camp.html` | 주기별 "대신 수정" 링크 | ✅ |
| `votelink/web/templates/cycle_edit.html`·`cycle_preview.html` | `by_operator` 분기 + 사유 입력란 + 폼 action 파라미터화 | ✅ |
| `votelink/web/templates/cycle_preview.html` | hidden 루프가 리스트값(`emd_pick`)을 항목마다 렌더 — 캠프 미리보기→저장 왕복도 함께 고쳐졌다 | ✅ |
| 감사 액션 | `ops.py` 호출부에서 `edit_cycle_by_operator` (`audit.py` 는 액션 문자열을 자유로 받으므로 무변경) | ✅ |
| `tests/test_web_ops.py` | 2단계 대리 수정 · 사유 필수 · 감사 액션 구분 · 모르는 캠프/주기 404 · 접근 통제 경로 추가 | ✅ |
| `docs/40-webapp-spec.md` | `/ops/*` 표에 대리 수정 2줄 + 설명 | ✅ |
| `docs/proposals/P-003-operator-console.md` | §2 "읽기만 한다"에 P-005 예외 블록 | ✅ |
| `CLAUDE.md` | 토큰 규율 표에 대리 수정 행 | ✅ |
| `votelink/web/templates/_emd_shuttle.html` (신규) · `onboarding.html`·`cycle_edit.html` | shuttle 을 partial 로 빼고 세 폼이 include (§9) | ✅ |
| `votelink/web/app.py` `_edit_ctx` | 현재 관할을 `emd_pick` 으로 prefill (§9) | ✅ |
