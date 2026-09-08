# D-006: 서울 48개 선거구 검증 + sigungu 기준선 버그 수정

> `D-` = 참조 데이터/파이프라인 정비 제안서. 1페이지를 넘기지 않는다.

> 상태: **완료 (2026-09-07).** D-002/D-004/D-005 가 제안서 없이 커밋만 남겨
> 이 문서가 그 자리를 메운다. sigungu 기준선 버그 1·2 수정, 서울 48개 선거구
> `voter_profile` 실측 검증 통과, 테스트 추가.

## 무엇을

"선거·인구를 서울 47개 선거구로 확장"은 이미 코드에 있다 — `meta.yaml`
`districts:` 3개(D-002 `457c847` / D-004 `06f9bab`), `districts.yaml` admmCd
(D-001), `party_lineage.yaml` 서울 전역(D-005 `0b1af3f`). `D-001` §상태의
"후속으로 남은 것" 노트는 그래서 낡았다.

이 작업은 그 확장이 **조용히 깨뜨린 것**을 고치고, 송파갑 하나만 됐던 검증을
서울 48개 선거구로 넓힌다.

## 발견한 버그

### 버그 1 — voter_profile 이 sigungu 기준선을 자기 자치구로 안 좁혔다 (정확성)

`analyzers/voter_profile/analyzer.py::_collect_election` 는 `geo_level == sigungu`
개표 레코드를 자치구 구분 없이 전부 받아 `baselines[etype][eid][SIGUNGU]` 에
넣었다. 이 dict 는 geo_level 로만 키가 잡혀 **마지막에 처리된 자치구가 이긴다.**
`BaseAnalyzer.load()` 는 geo 필터가 없어 항상 서울 25개 자치구 기준선이 다
들어온다(`analyze --all` 도 전체 공유). 결과: 거의 모든 선거구의 `gap_sigungu`
가 `nec_archive.jsonl` 파일 순서상 마지막 자치구 대비로 계산됐다.
`_confidence` 도 "sigungu 키만 있으면 완비"로 세어 틀린 기준선에 0.9 를 줬다.

송파갑 최초 검증(2026-09-03) 때는 `nec_archive.jsonl` 에 송파구 기준선만 있어
last-wins == 송파구였다 → 우연히 맞았고, D-002 가 24개를 더하며 깨졌다.
`nec_archive_assembly` 는 `baselines:` 자체가 없어(총선 레코드 전부 emd) 무관.

### 버그 2 — sigungu geo_code 인코딩이 두 계층에서 달랐다 (잠재)

`nec_archive._baseline_geo` 는 sigungu 코드를 admmCd **앞 4자리** + `000000` 으로
만들었는데, `District.sigungu_codes`(커밋 `c7ac49d`)는 **앞 5자리** + `00000`
이다. 5번째 자리가 0이 아닌 광진(11215)·강북(11305)·금천(11545)에서만 갈리며,
`_baseline_geo` 가 존재하지 않는 절단 코드(`1121000000` 등)를 냈다. 버그 1이
geo_code 를 안 보던 동안엔 안 터졌지만, 버그 1을 자치구 필터로 고치는 순간
이 6개 선거구(광진 갑/을·강북 갑/을/병·금천)의 `gap_sigungu` 가 None 이 된다.

## 어떻게 고쳤나

- `District.primary_sigungu_code` 프로퍼티 신설(`votelink/reference/districts.py`)
  — `sigungu_codes` 와 같은 5자리 규칙, 두 자치구에 걸치면 다수 자치구. L1·L2 가
  이 하나를 공유한다(이 파일 docstring "두 계층이 각자 목록을 들면 어긋난다").
- `nec_archive._baseline_geo` 가 이 접근자를 쓴다(4자리 절단 로직 삭제).
  광진·강북·금천 sigungu 기준선 `natural_key` 가 바뀌므로 `nec_archive.jsonl`
  을 지우고 `--reparse` 로 재생성. `data/raw/` 불변(절대 규칙 1).
- `voter_profile._collect_election` 이 `geo_level == sigungu` 레코드를
  `record.geo_code == district.primary_sigungu_code` 일 때만 받는다.
  sido·nation 은 단일값이라 그대로.
- 테스트: `test_districts.py`(접근자 5자리·다수 자치구), `nec_archive`
  `test_district_generalization.py`(광진 5자리), `voter_profile`
  `test_analyzer.py::TestSigunguBaselineScoping`(옆 자치구 미끼를 넣고 자기
  자치구 것만 쓰는지, confidence 0.9 조건, 미끼만 있으면 None).

## 검증 (실측, 2026-09-07)

`nec_archive --all-districts --reparse`(48/48, 격리 0, 저장 4125 그대로) →
`voter_profile --all-districts`(48/48, 격리 0, 교체 850·신규 0) 후 단언:

- **커버리지** 48개 선거구 × 2계열 = 96 조합, 대선 프로파일 없는 선거구 0.
- **gap_sigungu 정확성** 대선 레코드 전건에서
  `camp_share.conservative - gap_sigungu` 가 그 선거구 `primary_sigungu_code`
  자치구 기준선의 보수%와 일치(오차 < 0.05%p). 불일치 0건.
- **gap_district 정의** 한 (선거구·회차) 안에서 `own_pct - gap_district` 가 모든
  동에서 같은 상수(= 그 회차 지역구 가중평균). 위반 0건.
- **총선** 레코드는 `gap_sigungu/sido/nation` 전부 None(기준선 없음), confidence 0.7.
- **광진·강북·금천** sigungu 기준선 geo_code 가 `1121500000`/`1130500000`/
  `1154500000` 로 재생성됨(버그 2 전) — 이 6개 선거구도 gap_sigungu 정상 산출.
- **스팟체크(21대 대선 동별 1위 진영)** 관악구 을 진보 10/10 · 강남구 갑 보수
  7/7 · 광진구 갑 진보 7·보수 1 · 중구성동구 을 보수 10·진보 9(접전) — 실측
  상식과 부합.
- **송파갑 회귀 없음** 9개 동, confidence 0.7(2002 서울시 기준선 결측), 2007
  전국 기준선 존재, `derived_from` 32 — A-001 §5 기록과 일치.

핵심 단언은 pytest 로도 고정(위 `TestSigunguBaselineScoping` 등).

## 관찰된 별개 문제 (이번 범위 아님)

confidence 0.9 가 관악구 을 10개 동에만 붙는다 — 이 자치구는 동명이 전면
개명돼(D-004) 최근 4회차만 개표가 매칭되고, 그 4회차가 우연히 상위 기준선을
다 갖춰 `_confidence` 의 "가용 회차 안에서 완비" 규칙이 0.9 를 준다. 8회차를
가진 다른 선거구(0.7)보다 높게 나오는 건 A-001 §계산 규칙의 상대 기준 특성이다.
버그가 아니라 규칙 설계 문제라 별도 판단이 필요하다 — 이번 수정은 gap 값의
정확성만 다룬다.

## 제약과 위험

- 총선(`nec_archive_assembly`)은 상위 단위 기준선을 아직 안 만든다 → 총선
  `voter_profile` 의 `gap_*` 는 계속 None, confidence 0.7. 이번 범위 밖(A-001 §5).
- 2002 대선은 서울시 기준선, 2007 대선은 전국 기준선이 여전히 결측(C-004) —
  해당 회차 confidence 0.7 상한은 그대로.
- 선거구가 시군구 경계를 걸치면 sigungu 기준선은 다수 자치구 하나로만 만든다
  (중구성동구 을 = 중구). 소수 자치구 동은 자기 자치구 대비 편차가 없다 —
  D-001 §제약과 같은 한계.
- 스팟체크에서 실측과 크게 어긋나는 선거구는 `verified` 범위에서 빼고 여기
  사유를 남긴다(D-004 가 회차를 뺀 방식).
