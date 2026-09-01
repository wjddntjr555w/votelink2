# votelink2

서울 송파구 갑 지역구 후보를 위한 선거 전략 지원 시스템.
공개 데이터 수집(L1) → 분석·학습(L2) → 로컬 웹앱(L3)의 3계층.

## 토큰 규율 — 먼저 읽을 것

이 저장소는 **작업 종류별로 읽어야 할 파일이 고정**되어 있다.
아래 표에 없는 파일은 읽지 않는다. `docs/`를 통째로 읽지 않는다.

| 하려는 작업 | 읽을 파일 (이게 전부다) |
|---|---|
| 새 수집기 추가 | 스킬 `new-collector` 를 호출 (직접 하지 말 것) |
| 기존 수집기 수정 | `collectors/<id>/` + `docs/20-collector-spec.md` |
| 데이터 스키마 변경 | `docs/10-data-contract.md` + `votelink/contract/models.py` |
| 새 분석기 추가 | 스킬 `new-analyzer` 를 호출 |
| 분석 로직 수정 | `analyzers/<id>/` + `docs/30-analysis-spec.md` |
| 웹앱 화면 작업 | `votelink/web/` + `docs/40-webapp-spec.md` |
| 산출물이 선거법에 걸리는지 | `docs/90-compliance.md` |
| 프로젝트 전체 파악 | `docs/00-overview.md` (이것만) |
| API 키·계정이 필요한지 | `docs/SETUP.md` |
| 선거구에 어느 동이 속하는지 | `data/reference/districts.yaml` (코드에 박지 말 것) |

수집기가 20개가 되어도 한 개를 고치는 비용은 그대로여야 한다.
전체 목록이 필요하면 `collectors/registry.yaml` 한 파일만 본다.

## 절대 규칙

1. **`data/raw/` 는 읽기 전용.** 어떤 경우에도 수정·삭제하지 않는다.
2. **수집기는 해석하지 않는다.** 감성분석·분류·추정은 전부 L2의 파생 레코드로.
3. **개인 단위 데이터 없음.** 최소 집계 단위는 행정동. 개인 식별 정보는 수집하지 않는다.
4. **`geo_code` 매핑 실패는 에러다.** null로 넘어가지 않는다.
5. **선거법 검증을 통과하지 않은 산출물은 웹앱에 경고 없이 표시하지 않는다.**
6. 스키마의 단일 진실은 `votelink/contract/models.py`. 문서가 아니라 코드가 기준.

## 명령어

```bash
uv sync                          # 의존성
uv run votelink collect <id>     # 수집기 실행
uv run votelink collect <id> --reparse   # 재수집 없이 저장된 raw만 재파싱
uv run votelink collect <id> --dry-run   # 저장 없이 계약 검증만
uv run votelink registry sync            # registry.yaml 재생성
uv run votelink geo import <csv>         # 행정동코드 매핑표 적재 (출처가 코드를 안 줄 때만)
uv run votelink district list --emd      # 선거구 정의 확인
uv run votelink collect <id> --capture-fixture  # 실제 응답을 fixture로 저장
uv run votelink analyze <id>     # 분석기 실행
uv run votelink serve            # 로컬 웹앱 (기본 8420)
uv run pytest                    # 테스트
uv run ruff check . && uv run ruff format .
```

## 커밋 전 필수

```bash
uv run ruff check . && uv run pytest
```

## 확장 방식

새 수집기·분석기는 코드가 아니라 `docs/proposals/` 의 제안서 1장에서 시작한다.
제안서 → 스킬이 스캐폴딩 → 구현 → registry 등록.
