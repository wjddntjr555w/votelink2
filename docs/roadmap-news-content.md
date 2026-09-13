# 정당·후보 태깅 뉴스 활용 콘텐츠 로드맵

> 이 문서는 `docs/proposals/`의 A-/C-/D-/P- 제안서와 성격이 다르다 — 단일
> 기능 제안이 아니라 여러 단계를 묶는 진행 중인 계획 문서다. 각 단계의
> 실제 결정·구현 상세는 해당 제안서(A-006, D-007 등)가 단일 진실이고,
> 이 문서는 단계 간 순서와 현재 진행 상태를 추적한다.

## Context

`naver_news` 수집기가 최근 P-006으로 캠프 로스터(후보 실명)와 정당명 전역 목록을 검색어에 병합해, 이제 지명뿐 아니라 **후보/정당 단위로 태깅된 뉴스**(`mentioned_persons`, `mentioned_places`, `topics`)를 안정적으로 모은다. L1은 이 점에서 사실상 완료 상태다.

반면 이 데이터를 소비하는 L2는 `issue_ranker`(이슈 랭킹)와 `news_pulse`(주간 기사량·언론사 분포·급증 탐지) 두 분석기뿐이고 **둘 다 `verified: false`** — 즉 아직 신뢰 검증을 통과하지 못해 웹앱에 경고 없이 노출할 수 없는 상태다(`docs/00-overview.md` 5대 원칙). 둘 다 후보/정당 단위 구분 없이 선거구 전체를 뭉뚱그려 집계한다. L3의 `/d/{district}/news` 화면도 이 집계만 보여줄 뿐, 후보별·정당별 비교 뷰는 없다.

방향: **① 수치 트랙(통계 기반 L2 분석기)을 텍스트 트랙(Claude API 해석)보다 먼저**, **② 후보 단위로 시작하고 정당 단위는 후속 과제로 분리**.

## 전체 아이디어 브레인스토밍 (참고용, 전부 로드맵에 들어가지 않음)

- 후보/정당별 언급량·점유율 추이 (mention share)
- 이슈 × 후보 교차표 — 어떤 이슈에 어떤 후보가 연루되는지
- 경쟁 후보 대비 우리 후보 노출 갭 (news 기반 gap report 입력)
- 언론사 분포의 후보별 편차 (특정 매체 쏠림)
- 뉴스 타임라인 뷰 (후보별, 이슈별)
- 세그먼트별 언어 분석 → 메시지 자산 초안 (텍스트 트랙, v0.2)
- 캐치프레이즈·현수막 문구·공보물 초안 생성 (텍스트 트랙, 최종 산출물)
- 급증(spike) 발생 시 후보 대응 타이밍 추천

이 중 우선순위에 오른 것은 아래 로드맵의 항목뿐이며, 나머지는 텍스트 트랙 단계나 후속 대화에서 재검토한다.

## 로드맵

### 1단계 — L2: `news_pulse`/`issue_ranker` 검증 완료 (선행 정리) — **재확인함, 둘 다 여전히 미검증**
- 두 분석기가 `verified: false`인 한, 이후 만드는 후보 비교 분석기도 신뢰 체인상 막힌다. `docs/30-analysis-spec.md`의 검증 기준에 맞춰 두 분석기를 검증 통과시키는 작업을 먼저 마무리한다.
- 담당 파일: `analyzers/issue_ranker/`, `analyzers/news_pulse/`, `analyzers/registry.yaml`.
- **진행 상태 (2026-09-13)**:
  1. **예상 밖 버그 발견·수정 (D-007, 완료)**: `naver_news --reparse`가 `votelink/collect/runner.py`의 `--reparse` 저장 경로(append 방식 + 중복 방지 체크 스킵) 때문에 `naver_news.jsonl`에 record_id 15,178개(30,356줄)를 중복 저장했다. `issue_ranker`는 `derived_from` 중복 검증에 걸려 격리율 100%로 실패했고, `news_pulse`는 중복을 걸러내지 않아 기사 수를 조용히 이중 집계하고 있었다. 제안서 `docs/proposals/D-007-reparse-dedup-fix.md`를 쓰고 구현까지 진행: `runner.py`의 reparse 저장 경로를 `store.upsert_records`로 교체(record_id 일치분만 교체, 나머지 보존). **구현 중 실사고**: 처음엔 파일 전체를 그 실행 결과로 덮어쓰는 안으로 만들었다가, `naver_news`처럼 여러 선거구가 같은 records 파일을 공유하는 구조(`docs/11-storage.md §2`)에서 `--district` 없이 reparse하면 다른 24개 선거구 기여분이 전부 사라지는 것을 직접 겪었다(167,939→15,359줄). 백업에서 즉시 복구하고 `upsert_records` 방식으로 다시 구현, 이 사고를 그대로 재현하는 회귀 테스트(`test_reparse_preserves_records_this_runs_raw_does_not_cover`)를 추가했다. 실측 검증: 재실행해도 167,939줄 불변·중복 0. 전체 `pytest` 953개 전부 통과, `ruff check`/`ruff format --check` 통과 — D-007 완전히 마무리.
  2. 정리 후 두 분석기 모두 격리 0%·멱등(교체 1·신규 0) 확인 — 계약·코드 자체는 정상.
  3. 다만 **원래 `verified: false`의 사유는 둘 다 그대로 재현됐다**: `news_pulse`는 최근 2주(08-31, 09-07)가 직전 주 대비 3~11배로 여전히 `backfill_distorted=true` (검색 API 1,000건 상한 백필 왜곡, 증분 수집이 더 쌓여야 해소). `issue_ranker`는 `unclassified_count` 82.3% (2026-09-06 시점 83%와 사실상 동일) — naver_news "송파" 검색 소스 자체의 구조적 표본 편향, 어휘집 보강이나 더 정제된 지역 뉴스 수집기가 있어야 해소된다.
  4. 두 분석기 `meta.yaml`에 2026-09-13 재확인 결과와 근거 수치를 주석으로 남겨뒀다.
- **막힌 이유 요약**: 코드 결함이 아니라 **데이터/시간 문제** — (a) `news_pulse`는 증분 수집이 여러 주 더 쌓여야 하고, (b) `issue_ranker`는 naver 검색 API의 태생적 노이즈(스포츠·부고·전국뉴스 오염)를 줄일 더 정제된 소스나 어휘집 개선이 필요하다. 시간 경과·별도 수집기 개선이 선행돼야 한다.
- **D-007 후속: 전체 수집기 전수 스캔 (완료, 2026-09-13)**: D-007이 "과거에 이미 쌓인 중복은 범위 밖"이라 남긴 것을 처리. `collectors/`의 L1 수집기 4개 전부(`mois_population`, `naver_news`, `nec_archive`, `nec_archive_assembly`) 스캔 결과:

  | 수집기 | 정리 전 | 고유 record_id | 중복 record_id | 중복 줄 수 |
  |---|---|---|---|---|
  | `mois_population` | 832줄 | 426 | 406개 | 812줄 |
  | `naver_news` | 183,117줄 | 167,939 | 15,178개 | 30,356줄 |
  | `nec_archive` | 4,125줄 | 3,238 | 173개 | 1,060줄 |
  | `nec_archive_assembly` | 1,427줄 | 1,427 | 0개 | 깨끗 |

  `nec_archive_assembly`만 원래 문제없었고, 나머지 3개는 전부 같은 D-007 증상. 중복 쌍은 `ingested_at`만 다르고 payload는 동일해(순수 append 중복) 마지막 값을 남기는 정리가 안전했다. 백업 후 record_id 기준 정리 → `voter_profile`(48/48 선거구, 산출 850, 격리 0%, 재실행 시 교체 850·신규 0) · `turnout_gap`/`target_priority`(각 10/10, 격리 0%, 재실행 시 멱등) 재검증, 전체 `pytest` 953개 재확인 통과. `docs/proposals/D-007-reparse-dedup-fix.md`에 반영하고 커밋(`4b40038`)·푸시 완료. **지금은 모든 수집기의 records 파일이 중복 없이 깨끗하다.**

### 2단계 — L2 신규 분석기: 후보/정당별 언급 비교 (`candidate_mention_share`) — **진행 중**
- **무엇**: `news_pulse`와 같은 주 단위 집계 프레임을 재사용하되, `mentioned_persons`/후보 로스터(ours/opponents)로 그룹핑 — 후보별 주간 언급 건수, 언급 점유율, 전주 대비 변화율을 산출. 범위는 후보 단위로 한정, 정당 단위는 3단계 이후 별도 과제로 분리.
- **왜**: 지금 있는 두 분석기는 선거구 전체를 뭉뚱그린다. 캠프가 가장 먼저 묻는 질문은 "우리 후보가 상대보다 더/덜 언급되고 있나"이며, 이는 감성분석 없이 순수 카운팅만으로 답할 수 있어 수치 트랙에 맞고 구현 비용이 가장 낮다.
- **입력**: `news_article` (kind), 캠프 로스터(`votelink/camp/` 경유 candidates.yaml).
- **출력**: 새 파생 레코드 kind `candidate_mention_share` — `docs/10-data-contract.md` + `votelink/contract/payloads.py`에 추가 필요 (계약 변경, 착수 전 사용자 승인 필요).
- **제안서**: `docs/proposals/A-006-candidate-mention-share.md` — 작성 완료.
- **진행 상태 (2026-09-13 기준)**:
  1. 제안서 작성 완료. 신규 kind `candidate_mention_share`을 payload 계약에 추가하는 건은 아직 승인 대기.
  2. 선행 조건 ①(`mentioned_persons` 필드 미반영) 해소 — `uv run votelink collect naver_news --reparse` 실행 완료.
  3. 선행 조건 ②(실제 후보 로스터 부재)는 송파구 갑 후보 미확정으로 **미정 유지**. 대신 분석기의 변별력(모든 후보가 같은 값을 내지 않는지)을 미리 확인하려고, 실제 인물(서명옥/국민의힘, 김태형·김성곤/더불어민주당)로 강남구 갑에 **테스트 전용 캠프**(`data/camps/gangnam-gap-test/`)를 만들어 `NAVER_NEWS_QUERY_SCOPE=candidates`로 후보 쿼리를 수집했다. 결과: `mentioned_persons` 언급 건수가 서명옥 930 / 김태형 985 / 김성곤 995로 **서로 다른 값**이 나와 변별력 0 위험은 없는 것으로 확인. 단 이 캠프는 검증용이며 송파구 갑 실제 로스터가 아니다 — 실제 후보 확정 전까지 이 분석기의 스캐폴딩·구현은 보류.
- **다음**: 송파구 갑 후보 확정 시 실제 로스터 등록 → 계약 변경 승인 → `new-analyzer` 스킬로 스캐폴딩·구현.

### 3단계 — L2 신규 분석기: 이슈 × 후보 매트릭스
- **무엇**: `issue_ranker`가 만드는 `local_issue`와 후보 언급을 교차 — 어떤 이슈 기사에 어떤 후보/정당이 함께 언급되는지 매트릭스로.
- **왜**: 2단계(누가 더 언급되나)의 자연스러운 다음 질문은 "무슨 이슈로 언급되나"다. `issue_ranker` 산출물을 그대로 입력으로 재사용할 수 있어 구현 비용이 낮고, 갭 리포트(`docs/00-overview.md`의 5대 산출물 중 하나)의 핵심 입력이 된다.
- **선행조건**: 1단계(issue_ranker 검증)와 2단계(후보 매핑) 완료 후 착수.

### 4단계 — L3: 뉴스 화면에 후보 비교 뷰 추가
- **무엇**: `/d/{district}/news`에 2·3단계 산출물을 얹어 후보별 언급 추이 차트, 이슈×후보 히트맵 표시. 기존 페이지 확장이므로 새 라우트 불필요.
- **담당 파일**: `frontend/src/pages/NewsPage.tsx`(정확한 경로는 착수 시 재확인) + `votelink/web/app.py`(또는 해당 API 모듈) + `docs/40-webapp-spec.md §10-1`.
- **선행조건**: 2·3단계 산출물이 검증(verified) 상태여야 웹앱에 경고 없이 노출 가능 (절대 규칙 5).

### 5단계 (별도 결정 필요) — 텍스트 트랙 착수 여부
- `docs/00-overview.md`가 명시한 텍스트 트랙(Claude API로 세그먼트별 언어 분석 → 메시지 자산 초안: 캐치프레이즈·현수막 문구·공보물)은 이번 로드맵에서 의도적으로 뒤로 미룸.
- 착수 전 확인 필요: API 비용 예산, `docs/90-compliance.md` 기준 메시지 자산 산출물의 선거법 경고 처리 방식.

## 다음 액션
2단계(`candidate_mention_share`)는 송파구 갑 후보 확정 대기 중. 1단계(기존 분석기 검증)는 시간 경과·소스 개선 대기 중. 둘 다 당장 진행 가능한 항목이 아니면, 이 문서를 다시 열어 우선순위를 재점검한다.
