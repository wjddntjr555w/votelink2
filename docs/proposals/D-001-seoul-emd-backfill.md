# D-001: 서울 47개 선거구 행정동코드(admmCd) 백필

> `D-` = 참조 데이터(reference data) 백필/정비 제안서. `C-`(수집기)·`A-`(분석기)와 같은
> 자리(`docs/proposals/`)에 둔다. 1페이지를 넘기지 않는다.

> 상태: **완료 (2026-09-05).** 서울 48개 선거구 전체가 `확인 완료`다. `votelink
> district backfill-codes` 로 425개 동 중 394개(368 + 26)를 자동 매칭으로 채웠고,
> 나머지는 두 종류였다: (1) 표기 차이 27건(`창1동`↔`창제1동`, `종로1·2·3·4가동`↔
> `종로1.2.3.4가동` 등) — `districts.yaml` 의 `name` 을 MOIS 표기에 맞춘 뒤 재실행해
> 채웠다. (2) `seoul_jung_seongdong_eul`(중구성동구 을)의 금호1~4가동·옥수동 4곳 —
> 이 선거구는 중구·성동구에 걸쳐 있는데 `District.sigungu` 필드가 하나뿐이라
> `backfill-codes` 의 자동 매칭이 (sigungu, name) 키로 못 찾는다. 코드값은 raw로
> 확인됐으므로 직접 기록했다(§제약과 위험에 한계로 남김). 전역 code 425개 전부 유니크,
> `uv run pytest` 통과.
>
> **후속 (해결됨):** `nec_archive`·`nec_archive_assembly`·`voter_profile` 의
> `meta.yaml` `districts:` 는 D-002(`457c847`)·D-004(`06f9bab`) 에서 서울 48개
> 선거구로 넓혔고, 후보→진영 매핑도 D-005 에서 채웠다. 그 확장이 도입한 sigungu
> 기준선 오염 버그의 수정과 48개 선거구 산출물 실측 검증은 **D-006** 에 있다.

## 무엇을

`data/reference/districts.yaml` 의 서울 48개 선거구 중 `seoul_songpa_gap` 을 뺀 47개는
`emd[].code`(행정동코드 10자리 admmCd) 가 전부 `null` 이다. 이 값을 `mois_population`
수집기의 **실제 API 응답**에서 확인된 admmCd 로만 채운다. 추정값은 넣지 않는다 — 확인
못 한 동은 그대로 `null` 로 남긴다.

## 왜 필요한가

`nec_archive` / `nec_archive_assembly` / `voter_profile`(A-001) 은 `districts.yaml` 의
`emd[].code` 를 직접 조회해 `geo_code` 를 만든다(이름을 주는 출처라서). `code` 가 비면
그 선거구의 **모든 행정동이 격리**되고 L2 산출물이 0건이 된다. 최근 다지역구 지원
(`--district`, `/d/<선거구>/`)이 데이터 레벨에서 아직 반쪽이라는 뜻 — 이 제안이 그 나머지 반이다.
답은 타깃 전략·갭 리포트 등 송파갑에서 이미 도는 파이프라인 전체를 47개 선거구로 넓히는 것.

## 어떻게

`docs/SETUP.md` §3 은 "그 선거구로 `mois_population` 을 돌리면 응답의 admmCd 가
`districts.yaml` 에 채워진다(수집기가 이름으로 매칭)"고 서술했지만 그 코드는 없었다
(송파갑 9개는 손으로 채워졌다). 그래서 명령을 만든다: `votelink district backfill-codes`.

- **입력은 `data/raw/mois_population/` 의 원본 응답**이지 `data/records/mois_population.jsonl`
  이 아니다. raw 는 `lv=3` 조회라 그 자치구의 **모든 행정동**이 각자의 admmCd 와 함께
  들어 있다(파싱이 실패해도 raw 는 이미 저장돼 있다 — fetch 가 parse 보다 먼저 쓴다).
  jsonl 은 이름이 이미 맞은 동만 있어 불일치를 진단할 수 없다.
- raw → `(시군구명, 행정동명, admmCd)` 로 펼치고, `districts.yaml` 의 `(sigungu, emd.name)`
  과 **정확히 일치**하는 것만 `code` 를 채운다.
- 절차: 47개 선거구로 `mois_population` 을 한 번씩 돌려 raw 를 쌓는다(이름 불일치로
  수집 자체가 실패해도 무방 — raw 는 남는다) → `backfill-codes --dry-run` 으로 리포트 확인
  → `backfill-codes` 로 기록 → 리포트의 "이름 불일치" 를 보고 `districts.yaml` 의
  `name` 을 MOIS 표기에 맞춘 뒤 재실행(idempotent) → `district list --emd` 로 pending 0 확인.

## 판단이 들어가는 값

**이름 매칭은 정확 일치만 자동으로 채운다.** `창신제1동`↔`창신1동`, `종로1·2·3·4가동` 같은
표기 차이를 정규화 규칙으로 흡수하지 않는다 — 근사 매칭이 옆 동 코드를 붙이면 인구·득표가
그럴듯하게 틀린 채로 전략이 나온다(`docs/SETUP.md` §3 "왜 이 대조가 필요한가"와 같은 이유).
불일치는 리포트로 드러내고 사람이 `name` 을 고친다.

## 제약과 위험

- `code` 는 `config.reference_month`(현재 2024-12) 시점 스냅샷의 admmCd. 행정동 통폐합이
  있으면 재확인이 필요하다.
- 일부 동은 응답 페이지 경계·명칭 변경으로 여전히 매칭 안 될 수 있다 — 그대로 `null` 유지,
  수집에서 pending 으로 계속 제외된다(조용히 누락되지 않는다).
- `org_code`(행정기관코드 7자리)는 이번 범위 밖. 참고용·미사용이라 `null` 로 둔다.
- **선거구가 시군구 경계를 걸치면 자동 매칭이 못 찾는다.** `District.sigungu` 는 선거구당
  하나뿐인데 `seoul_jung_seongdong_eul`(중구성동구 을)처럼 두 시군구에 걸친 선거구가
  실제로 있다 — 그 소수 동은 `backfill-codes` 가 `(sigungu, name)` 키로 찾지 못하므로
  raw 로 확인한 값을 `emd_backfill._write_codes()` 로 직접 기록했다. 이런 선거구가
  더 있으면 같은 방식(코드 확인 → 직접 기록)을 반복한다.

## 후속 (이번 범위 아님)

- **`nec_archive`/`voter_profile` 의 `meta.yaml` `districts:` 를 47개 선거구로 확장.**
  지금은 `seoul_songpa_gap` 만 등록돼 있어 `districts.yaml` 의 code 가 채워졌어도
  이 두 수집기·분석기가 실제로 그 선거구를 수집·분석하지는 못한다. `mois_population`
  이 이미 48개 선거구의 `sigungu_admm_code` 를 갖고 있었던 것과 같은 패턴이다.
- 선거구별 행정동 목록을 NEC 22대 총선 CSV 와 차집합 대조(송파갑 §3 "대조 완료"처럼
  경계 검증). 지금은 목록 자체가 그 xlsx 추출물이라 우선순위가 낮다.
- `org_code` 가 필요해지면 `votelink geo import` 로 code.go.kr 표를 받아 별도로 채운다.
