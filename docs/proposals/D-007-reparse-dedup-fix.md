# D-007: `--reparse` 가 records 파일에 중복을 쌓는 버그 수정

> `D-` = 참조 데이터/파이프라인 정비 제안서. 1페이지를 넘기지 않는다.

> 상태: **완료 (2026-09-13).** A-006(candidate_mention_share) 검증 준비 중
> `naver_news --reparse`를 돌리다가 발견. `votelink/collect/runner.py`의
> reparse 저장 경로를 `upsert_records`로 교체. `data/shared/records/naver_news.jsonl`
> 은 record_id 기준 일회성 정리로 먼저 임시 해소한 뒤(`docs/proposals` 밖,
> 세션 작업), 수정된 코드로 재검증했다.

## 무엇을

`votelink/collect/runner.py::run()`은 `reparse=True`일 때 두 가지를 한다:

1. 네트워크 대신 `storage.iter_raw`로 저장된 raw만 읽는다 (의도된 동작).
2. **중복 방지 체크(`existing_record_ids`)를 건너뛴다** (`runner.py:79-81`,
   `seen = set() if (dry_run or reparse) else storage.existing_record_ids(...)`).

2번이 문제다. 저장은 여전히 `storage.append_records`(그냥 파일 끝에 덧붙이기)를
쓰는데, dedup 체크를 껐으니 raw에 있는 레코드 전부가 **기존 `records/<id>.jsonl`에
무조건 재추가**된다. `record_id`가 같아도(같은 기사, 같은 `natural_key`) 걸러지지
않는다.

## 실측 재현

`naver_news --reparse` 1회 실행(파싱 로직에 `mentioned_persons` 매칭을 추가한
직후) 결과: "저장 15,300건"이라 보고됐고, 실제로는 기존 15,300개 record_id가
**새로 추가된 게 아니라 중복으로 쌓였다** — 정리 전 `naver_news.jsonl`
183,117줄 중 고유 record_id는 167,939개, 즉 15,178개 record_id가 중복
(총 30,356줄)이었다. 정리 전 상태에서 `issue_ranker`를 돌리면 `derived_from`
중복 금지 규칙(`docs/10-data-contract.md`)에 걸려 **격리율 100%로 완전히
실패**했고, `news_pulse`는 중복을 걸러내지 않아 **기사 수를 조용히 2배로
집계**하고 있었다(둘 다 이번에 실측 확인).

`docs/11-storage.md §3`은 "`raw`(불변, 완전) → `records`(언제든 버리고 다시
만들 수 있다)"라 적고, §7은 `records/<id>.jsonl`을 지운 뒤 `--reparse`로
회복하는 것을 정상 절차로 문서화한다. 즉 **의도된 사용법은 "지우고 재생성"**
인데, CLI도 코드도 이걸 강제하거나 안내하지 않는다. 기존 파일을 지우지 않고
`--reparse`를 돌리면(파싱 로직이 안 바뀌었어도 매번) 이 중복이 재현된다.

## 어떻게 고쳤나

처음 시도한 안(파싱 시작 전 `records/<collector_id>.jsonl`을 통째로 비우고
새로 쓰기)은 **구현 직후 실사고로 폐기했다.** `docs/11-storage.md §2`가
명시하듯 `naver_news`처럼 여러 선거구가 **같은 `records/<id>.jsonl`을
공유**하는 수집기가 있다 — `--district` 없이(=`default_district`인 송파구
갑만) `--reparse`를 돌렸더니, 그 실행의 raw만 다시 읽어 파일 전체를
그 결과로 덮어써서 **다른 24개 선거구가 채운 레코드가 전부 사라졌다**
(167,939줄 → 15,359줄). 다행히 사전에 떠둔 백업으로 바로 복구했다.

**최종 채택안**: 이미 있는 `store.upsert_records()`를 그대로 쓴다 — 이번
실행의 `record_id`와 일치하는 줄만 새 값으로 갈아끼우고, 나머지 줄(다른
선거구·다른 실행이 채운 것)은 그대로 보존한다. `runner.py`는 `reparse=True`
일 때 `storage.append_records` 대신 `upsert_records`를 호출하도록
바뀌었다. 새 함수를 만들 필요가 없었다 — L2가 "같은 키, 다른 값"에 쓰던
도구가 L1의 reparse에도 정확히 맞는 문제였다.

- `rejected/<id>/<날짜>.jsonl`은 손대지 않는다(날짜별 append가 정상이고,
  reparse도 오늘 날짜로 새 격리분을 쌓는 게 맞다).
- `upsert_records`는 이미 임시 파일 → 원자적 교체 패턴을 쓴다.

## 검증 (실측, 2026-09-13)

- 회귀 테스트 4개 추가 (`tests/test_runner.py`, `FakeCollector` 기반):
  - `test_reparse_does_not_duplicate_records_on_disk` — 같은 raw로 reparse를
    반복해도 줄 수·고유 record_id 수가 늘지 않는다(멱등).
  - `test_reparse_replaces_changed_payload_without_duplicating` — 파싱 로직이
    바뀌면 같은 record_id가 한 줄로 남고 새 payload로 교체된다.
  - `test_reparse_preserves_records_this_runs_raw_does_not_cover` — **이번
    실사고를 그대로 재현하는 회귀 테스트.** 이 실행의 raw에 없는(=다른
    선거구가 채웠다고 가정한) record_id를 미리 심어두고 reparse 후에도
    살아있는지 확인.
  - 전체 `tests/test_runner.py` 14개, `uv run pytest` 전체(953개 전부 통과,
    5분 58초), `ruff check`/`ruff format --check` 통과.
- 실측: `naver_news --reparse` 재실행 전후 `naver_news.jsonl` 168,939→
  167,939줄로 **불변**(재실행해도 늘지도 줄지도 않음), 고유 record_id 수와
  총 줄 수 일치(중복 0). 이어서 `news_pulse`/`issue_ranker`를 송파구 갑으로
  재실행해 입력 167,939 · 격리 0% · 교체 1·신규 0(멱등) 확인.

## 제약과 위험

- **이 수정은 모든 L1 수집기에 영향을 준다** (`runner.py`는 공유 코드).
  다른 수집기의 `--reparse` 사용도 이제 upsert 경로를 타므로, 그 수집기들의
  기존 회귀 테스트가 있다면 함께 통과하는지 확인해뒀다(전체 `pytest` 그린).
- **처음 시도(파일 전체 교체)가 실제로 데이터를 날린 전례가 있다** — 이
  교훈을 `store.upsert_records`의 독스트링에 "한 owner_id 파일을 여러
  선거구가 공유할 때도 이게 맞다 — 파일 전체를 이 호출의 결과로 덮어쓰면
  안 된다"로 남겨, 다음에 이 함수를 건드릴 때 같은 실수를 반복하지 않게
  했다.
- 이번 수정은 **미래의 reparse가 중복을 안 쌓게** 막을 뿐, 과거에 이미
  쌓인 중복은 별도로 스캔·정리해야 한다고 적어뒀었다 — **후속으로 처리
  완료(2026-09-13)**. L1 수집기 4개(`mois_population`, `naver_news`,
  `nec_archive`, `nec_archive_assembly`)의 `records/*.jsonl`을 전수
  스캔한 결과 `mois_population`(832줄 중 406개 record_id 중복) ·
  `nec_archive`(4,125줄 중 173개 중복)에서도 같은 증상을 발견했다.
  중복 쌍은 `ingested_at`만 다르고 payload는 동일해(재수집 로직 변경
  없이 순수 append 중복) 마지막 값을 남기는 정리가 안전했다. 백업 후
  record_id 기준 정리(426줄 / 3,238줄로 축소) → `voter_profile`
  (48/48 선거구, 산출 850, 격리 0%, 재실행 시 교체 850·신규 0) ·
  `turnout_gap`·`target_priority`(각 10/10, 산출 200, 격리 0%, 재실행
  시 교체 200·신규 0) 재검증, 전체 `pytest` 그린. `naver_news`는 이미
  이번 제안서 본문에서 정리·검증했다.
