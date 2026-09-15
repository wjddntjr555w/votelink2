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

### 2단계 — L2 신규 분석기: 후보/정당별 언급 비교 (`candidate_mention_share`) — **구현 완료, 실 로스터 대기**
- **무엇**: `news_pulse`와 같은 주 단위 집계 프레임을 재사용하되, `mentioned_persons`/후보 로스터(ours/opponents)로 그룹핑 — 후보별 주간 언급 건수, 언급 점유율, 전주 대비 변화율을 산출. 범위는 후보 단위로 한정, 정당 단위는 3단계 이후 별도 과제로 분리.
- **왜**: 지금 있는 두 분석기는 선거구 전체를 뭉뚱그린다. 캠프가 가장 먼저 묻는 질문은 "우리 후보가 상대보다 더/덜 언급되고 있나"이며, 이는 감성분석 없이 순수 카운팅만으로 답할 수 있어 수치 트랙에 맞고 구현 비용이 가장 낮다.
- **입력**: `news_article` (kind), 캠프 로스터(`votelink/camp/` 경유 candidates.yaml).
- **출력**: 파생 레코드 kind `candidate_mention_share` — `RecordKind.CANDIDATE_MENTION_SHARE` + `CandidateMentionSharePayload` 등록 완료(`votelink/contract/enums.py`, `payloads.py`, `docs/10-data-contract.md §5.7`).
- **제안서**: `docs/proposals/A-006-candidate-mention-share.md`.
- **진행 상태 (2026-09-14 기준)**:
  1. 계약 변경 승인받아 반영 완료. `is_ours`는 "정확히 1명"이 아니라 "최소 1명"으로 검증한다 — 한 district를 여러 캠프가 관할할 수 있어서(P-001).
  2. `analyzers/candidate_mention_share/` 스캐폴딩·구현 완료(analyzer.py/calc.py/meta.yaml/tests). 단위테스트 10개(손으로 검산한 주간 카운트·share_pct·wow_change_pct 포함) 전부 통과.
  3. 강남구 갑 **테스트 전용 캠프**(`data/camps/gangnam-gap-test/`, 서명옥·김태형·김성곤)로 실행: 격리 0%, 재실행 시 멱등(교체 1·신규 0), 후보별 `total_articles`(299/119/8) 전부 다른 값으로 변별력 확인. 실행 중 기존 더미 캠프 `test1`의 관할이 실제로 강남구 갑과 겹치는 걸 발견해 — 위 "최소 1명 ours" 완화가 이론이 아니라 실측으로 필요했던 상황임이 확인됐다.
  4. `meta.yaml`의 `verified`는 여전히 `false` — 강남구 갑은 검증용 데이터이고 송파구 갑 실제 로스터가 없다. 커밋(`d442773`) 완료.
- **다음**: 송파구 갑 후보 확정 시 `candidates.yaml`에 실제 로스터 등록 → `--district seoul_songpa_gap`으로 재실행 → 실측 통과하면 `verified: true`로 승격.

### 3단계 — L2 신규 분석기: 이슈 × 후보 매트릭스
- **무엇**: `issue_ranker`가 만드는 `local_issue`와 후보 언급을 교차 — 어떤 이슈 기사에 어떤 후보/정당이 함께 언급되는지 매트릭스로.
- **왜**: 2단계(누가 더 언급되나)의 자연스러운 다음 질문은 "무슨 이슈로 언급되나"다. `issue_ranker` 산출물을 그대로 입력으로 재사용할 수 있어 구현 비용이 낮고, 갭 리포트(`docs/00-overview.md`의 5대 산출물 중 하나)의 핵심 입력이 된다.
- **선행조건**: 1단계(issue_ranker 검증)와 2단계(후보 매핑) 완료 후 착수.

### 4단계 — L3: 뉴스 화면에 후보 비교 뷰 추가 — **구체적인 콘텐츠 카탈로그로 확정 (2026-09-15)**
- **무엇**: `/d/{district}/news`에 2·3단계 산출물을 얹어 후보별 언급 추이 차트, 이슈×후보 히트맵 표시. 기존 페이지 확장이므로 새 라우트 불필요.
- **담당 파일**: `frontend/src/pages/NewsPage.tsx` + `votelink/web/app.py`(또는 해당 API 모듈) + `docs/40-webapp-spec.md §10-1`.
- **선행조건 정정**: `verified` 상태가 필수는 아니다. 절대 규칙 5는 "경고 **없이** 표시하지 않는다"이지 "미검증이면 아예 표시 못 한다"가 아니다 — `ComplianceGate`가 미검증 산출물에 자동으로 "미검토" 배지를 붙이는 게 정상 동작이므로, `news_pulse`/`issue_ranker`/`candidate_mention_share` 셋 다 `verified: false`인 지금도 화면 제작에 바로 착수할 수 있다. 아래 콘텐츠 카탈로그는 이 전제로 짰다.
- **콘텐츠 카탈로그**: 아래 "## L3 콘텐츠 기획" 절 참고.

### 5단계 (별도 결정 필요) — 텍스트 트랙 착수 여부
- `docs/00-overview.md`가 명시한 텍스트 트랙(Claude API로 세그먼트별 언어 분석 → 메시지 자산 초안: 캐치프레이즈·현수막 문구·공보물)은 이번 로드맵에서 의도적으로 뒤로 미룸.
- 착수 전 확인 필요: API 비용 예산, `docs/90-compliance.md` 기준 메시지 자산 산출물의 선거법 경고 처리 방식.

## L3 콘텐츠 기획 (2026-09-15)

> **정정 (2026-09-15)**: `news_pulse`·`local_issue` 둘 다 최초 조사(grep)의 판단과 달리
> **이미 대시보드(`/d/{district}/`)에 카드로 붙어 있었다** — `IssueBoardPanel.tsx`(이슈
> 랭킹·추세 화살표 ↑↓→·대표 헤드라인·미분류율 경고), `PulsePanel.tsx`(주간 막대·급증
> 표시·`backfill_distorted` 배너). 다만 두 컴포넌트 다 **백엔드가 이미 계산해 내려주는
> 필드를 프런트가 빠뜨린 부분**이 있었다: `IssueBoardPanel`은 `top_places` 칩이 없었고
> (추가 완료), `PulsePanel`은 `top_publishers`/`top_places`/`top_persons`가 아예
> 없고 `IssueBoardPanel`은 자기 `backfill_distorted`를 표시 안 한다(둘 다 티어 1의
> 5·7번으로 남겨둠). `candidate_mention_share`는 이 정정 작성 당시엔 화면에 전혀
> 없었으나, 같은 세션에서 `CandidateMentionPanel.tsx`로 바로 구현했다(티어 1의
> 1·3번, 아래 참고) — 이제 세 kind 모두 대시보드에 카드로 올라와 있다. 남은 건
> 위에서 짚은 진짜 갭들(2·5·6·7·8·9번)과 티어 2다.

`candidate_mention_share`를 새로 만들고 보니, 이 데이터를 대시보드 콘텐츠로 끌어올리되
이미 화면에 있는 개표·투표율·유권자 성향 데이터, 그리고 이미 있는 `news_pulse`/
`local_issue` 카드와 조합해 "미디어에서 보이는 그림"과 "실제 표심·전략 우선순위"를 나란히
비교할 수 있게 하는 게 목표다 — `docs/00-overview.md` 5대 산출물 중 **갭 리포트**로 가는
다리다.

### 티어 1 — 지금 바로 (프런트엔드만, 조합 불필요)

1. ~~**후보 언급 점유율 타임라인**~~ — **완료 (2026-09-15).** `CandidateMentionPanel.tsx`(대시보드) 신규 — `candidate_mention_share.candidates[].weekly[]`를 후보별 진영색 스파크라인 막대로, 이번 주 건수·점유율을 함께 표시.
2. ~~**주간 점유율 100% 스택 바**~~ — **완료 (2026-09-15).** `WeeklyShareStack`(`CandidateMentionPanel.tsx` 안, 신규 함수) — 주마다 후보들의 `share_pct`를 100% 기준 가로 스택 바로. 1번(후보별 개별 막대)이 "누가 얼마나 나왔나"라면 이건 "그 주 노출을 누가 나눠 가졌나". 백엔드 변경 없음(share_pct는 이미 계산돼 있다).
3. ~~**급변 하이라이트 카드**~~ — **완료 (2026-09-15).** `CandidateMentionPanel.tsx`에 통합 — 카드 전체에서 `|wow_change_pct|` 최댓값을 자동으로 뽑아 "이번 주 특이사항" 배너로 표시(`build_candidate_mention_card`의 `highlight` 필드). 강남구 갑 실데이터로 확인: 서명옥 550% 급증을 정확히 집어냄.
4. ~~**이슈 랭킹 카드 목록**~~ — **완료.** `IssueBoardPanel.tsx`(대시보드)가 이미 랭킹·`trend` 화살표·`sample_headlines`를 보여주고 있었다. 빠져 있던 `top_places` 칩만 추가(`b.places` 렌더링, `votelink/web/viewmodel.py::build_issue_board`가 이미 계산해 내려주던 값이라 프런트만 고치면 됐다).
5. ~~**언론사 분포 카드**~~ — **완료 (2026-09-15).** `PulsePanel.tsx`에 `top_publishers`/`top_places`/`top_persons` 칩 추가(`PulseCard`가 이미 갖고 있던 필드). 쏠림 경고는 `top_publisher_share`(주 단위 필드)가 카드에 없어서, 대신 창 전체 기준 `top_publishers[0]/total_articles`를 화면단에서 계산해 30% 이상이면 경고 문구를 띄운다(`IssueBoardPanel`의 `unclassified_pct>=50`과 같은 성격의 표시 임계값). 송파구 갑 실데이터로 확인: 1위 언론사 비중 4.5%로 정상 범위, 경고 안 뜸.
6. ~~**주간 브리핑 요약 카드**~~ — **완료 (2026-09-15).** `WeeklyDigestCard.tsx`(대시보드, 세 패널 위) 신규 — 백엔드 변경 없이 이미 fetch 된 `pulse`/`issue_board`/`candidate_mentions` 세 카드의 값만 골라 한 줄 요약(뉴스량·급증·우리 vs 상대 점유율·급변 하이라이트·최상위 이슈 2개·상위 언론사 수). 컴플라이언스 처리: 세 소스가 서로 다른 `verdict`를 가질 수 있어 이 카드 자체엔 `ComplianceGate` 배너를 씌우지 않고, 대신 각 소스가 `blocked`면 그 값만 조용히 생략한다(`shows(verdict)` 헬퍼) — 아래 개별 패널이 이미 자기 배너를 보여준다.
7. ~~**백필 왜곡 배너 (공용 컴포넌트)**~~ — **완료 (2026-09-15).** `BackfillBanner.tsx` 신규 — `distorted`/`trustNote`(무엇을 못 믿는지, 패널마다 다름)만 받는 공용 컴포넌트로 세 패널(`PulsePanel`="급증 판정", `IssueBoardPanel`="최근성·추세 판정", `CandidateMentionPanel`="이번 주 변화율")을 통일. `IssueBoardPanel`이 갖고 있던 진짜 구멍(자기 `backfill_distorted` 미표시)을 이번에 메웠다.
8. ~~**표본 편향 고지 카드**~~ — **이미 있었다.** 위 7번 작업 중 확인 — `IssueBoardPanel.tsx`가 이미 `unclassified_pct`로 "표본은 지명 검색분이라 스포츠·행사·타지역 국가뉴스가 섞인다({pct}%가 분류 불가)" 고지와, 하단에 `unclassified_count`/"어휘집 보강 신호"(≥50%) 경고까지 갖고 있었다. 별도 구현 불필요.
9. ~~**`/compare`에 뉴스량 열 추가**~~ — **완료 (2026-09-15).** `load_all_news_pulse`(loader.py, 신규) + `build_comparison`의 `news_pulse_by_district` 인자(viewmodel.py) + `ComparisonRow.news_total_articles`. `news_pulse`가 `blocked`면 그 칸만 `None`(개별 gate가 없어 "0건"으로 새지 않게 직접 거름). 실측: 강남 갑/을/병 4,924건, 강동 갑/을 1,791건 — 같은 시군구 선거구가 정확히 같은 값을 보였다(뉴스는 sigungu 단위라 의도된 동작). 백엔드 테스트 3개 신규, 프런트 lint/test/build 통과.

### 티어 2 — 조합 필요 (새 분석기 없이 기존 kind 2개 이상을 한 화면에) — **완료 (10·11·13번 구현, 12번 파일럿 후 드롭)**

10. ~~**뉴스량 대비 후보 노출 비율 오버레이**~~ — **완료 (2026-09-15).** `NewsVolumeOverlayCard.tsx` 신규 — `pulse.bars[].count`(선거구 전체, 배경 회색 막대)와 `candidate_mentions`의 우리 후보 `bars[].count`(전경, 진영색)를 같은 `peak` 기준·같은 시간축에 겹친다. 두 분석기의 week 그리드가 이론상 완전히 같다는 보장은 없어 `week_start` 문자열로 맞춰 읽는다(코드 주석에 근거 남김). 백엔드 변경 없음.
11. ~~**미디어 노출 vs 표심 갭 카드**~~ — **완료 (2026-09-15).** `MediaElectoralGapCard.tsx` 신규 — `candidate_mentions`의 최신 `share_pct`(우리 vs 상대)와 `view.summary_card.camp_bar`(진영별 득표 근사 집계, `BarSlice.ours`로 우리 진영 판정)를 나란히 놓고 갭 문구(예: "언론 노출이 표심보다 X%p 앞서 있다")를 만든다. 백엔드 변경 없음 — `summary_card`는 이미 대시보드가 fetch 하던 값이다. **로그인한 캠프 렌즈가 있을 때만 렌더** — CandidateComparison과 같은 전제("우리"는 렌즈가 정한다). 두 소스가 다른 verdict를 가질 수 있어 WeeklyDigestCard와 같은 `shows()` 패턴으로 개별 배너 없이 값만 거른다.
12. ~~**동별 이슈-우선순위 오버레이 (지도 확장)**~~ — **드롭 (2026-09-15), 파일럿 완료.** `docs/proposals/D-008-place-name-geo-mapping.md`에서 파일럿까지 마쳤다. 구 단위 term·동명 중복·랜드마크·선거구 밖 지명은 애초에 매핑 불가였고, 최선의 경우인 "EMD 정확 명칭"(오륜동 등, `districts.yaml`과 바로 join 가능)조차 실제로 세어보니 news_pulse/local_issue가 쓰는 최근 12주 창에서 표본이 0~2건대로 극히 적고, 그 몇 건마저 동명이동(전국에 같은 이름의 행정동이 있어 다른 도시 기사가 섞임) 오염이 확인됐다. 매핑 인프라를 만들 가치가 없다는 결론 — 재검토 조건은 D-008 참고.
13. ~~**진영색 일관 스타일링**~~ — **완료 (2026-09-15).** `frontend/src/design-system/campColor.ts` 신규(`CAMP_COLOR` 맵 + `campColor()` 헬퍼) — `CandidateMentionPanel.tsx`가 이미 세 번째로 복붙하려던 참이라 이번에 뽑아냈다. `CandidateMentionPanel`·`MediaElectoralGapCard`·`NewsVolumeOverlayCard` 셋이 이걸 쓴다.

### 티어 3 — 후속 (새 분석기 또는 텍스트 트랙 필요, 설계만)

14. **이슈 × 후보 매트릭스** — 3단계 그대로. 티어2의 12번은 근사치일 뿐, 정확히 조인하려면 새 분석기가 필요.
15. **자동 주간 브리핑 문장 (텍스트 트랙)** — 6번의 숫자 요약을 자연어로. Claude API 비용 발생 지점, 5단계와 함께 별도 승인 필요.
16. **다음 액션 추천 카드** — "상대 언급 3주 연속 상승 — 대응 검토" 같은 제안형 카드는 `docs/90-compliance.md`의 중위험(해석 산출물) 범주. 법률 검토 경로 확인 전엔 만들지 않는다.

### 권장 우선순위

1. 이슈 랭킹 카드(4) — 구현 비용 최저, `local_issue` 단독.
2. 후보 언급 타임라인(1) + 급변 하이라이트(3) — `candidate_mention_share`를 처음 화면에 태운다.
3. 미디어 노출 vs 표심 갭 카드(11) — "뉴스 × 개표율" 요청에 가장 직접 답한다.
4. 나머지는 여유에 따라.

~~공통 선행 작업: 백필 배너(7)·표본 편향 고지(8)는 어느 카드를 먼저 만들든 같이 붙인다~~
— **완료.** **티어 1 전 항목(1~9번) 완료 (2026-09-15).**

## 다음 액션
2단계(`candidate_mention_share`)는 송파구 갑 후보 확정 대기 중. 1단계(기존 분석기 검증)는 시간 경과·소스 개선 대기 중. 4단계(L3 콘텐츠)는 위 우선순위 순서대로 다음 대화에서 바로 착수 가능 — 프런트엔드 작업이므로 커밋 전 `npm run lint && npm test && npm run build` 필요.
