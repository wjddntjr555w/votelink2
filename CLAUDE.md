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
| 저장 경로·무엇을 지워도 되는지 | `docs/11-storage.md` + `votelink/store.py` |
| 새 분석기 추가 | 스킬 `new-analyzer` 를 호출 |
| 분석 로직 수정 | `analyzers/<id>/` + `docs/30-analysis-spec.md` |
| 웹앱 화면 작업 | `votelink/web/` + `docs/40-webapp-spec.md` |
| 산출물이 선거법에 걸리는지 | `docs/90-compliance.md` |
| 프로젝트 전체 파악 | `docs/00-overview.md` (이것만) |
| API 키·계정이 필요한지 | `docs/SETUP.md` |
| 선거구에 어느 동이 속하는지 | `data/shared/reference/districts.yaml` (코드에 박지 말 것) |
| 선거구 행정동코드(admmCd) 채우기 | `docs/proposals/D-001-seoul-emd-backfill.md` + `votelink/reference/emd_backfill.py` |
| 캠프 공간·온보딩·관할·선거 주기 | `votelink/camp/` + `docs/proposals/P-001-camp-data-isolation.md` |
| 로그인·세션·계정·권한 | `votelink/control/` + `votelink/web/auth.py` + `docs/proposals/P-002-auth-and-camp-approval.md` |
| 운영자 화면 (`/ops/*`) | `votelink/web/ops.py` + `docs/proposals/P-003-operator-console.md` |
| 운영자가 캠프 주기를 대신 수정 | `votelink/web/ops.py` + `docs/proposals/P-005-operator-edits-camp-cycle.md` |

수집기가 20개가 되어도 한 개를 고치는 비용은 그대로여야 한다.
전체 목록이 필요하면 `collectors/registry.yaml` 한 파일만 본다.

## 절대 규칙

1. **`data/shared/raw/` 는 읽기 전용.** 어떤 경우에도 수정·삭제하지 않는다.
2. **수집기는 해석하지 않는다.** 감성분석·분류·추정은 전부 L2의 파생 레코드로.
3. **개인 단위 데이터 없음.** 최소 집계 단위는 행정동. 개인 식별 정보는 수집하지 않는다.
4. **`geo_code` 매핑 실패는 에러다.** null로 넘어가지 않는다.
5. **선거법 검증을 통과하지 않은 산출물은 웹앱에 경고 없이 표시하지 않는다.**
6. 스키마의 단일 진실은 `votelink/contract/models.py`. 문서가 아니라 코드가 기준.

## 명령어

```bash
uv sync                          # 의존성
uv run votelink collect <id>     # 수집기 실행
uv run votelink collect <id> --district <선거구>  # 이 선거구로 수집 (생략 시 meta 의 default_district)
uv run votelink collect <id> --all-districts      # meta 의 config.districts 에 등록된 모든 선거구를 차례로 수집
uv run votelink collect <id> --reparse   # 재수집 없이 저장된 raw만 재파싱
uv run votelink collect <id> --dry-run   # 저장 없이 계약 검증만
uv run votelink registry sync            # registry.yaml 재생성
uv run votelink geo import <csv>         # 행정동코드 매핑표 적재 (출처가 코드를 안 줄 때만)
uv run votelink district list --emd      # 선거구 정의 확인
uv run votelink collect <id> --capture-fixture  # 실제 응답을 fixture로 저장
uv run votelink analyze          # 등록된 분석기 목록
uv run votelink analyze <id>     # 분석기 실행
uv run votelink analyze <id> --district <선거구>  # 이 선거구로 분석 (생략 시 default_district)
uv run votelink analyze <id> --all-districts      # meta 의 config.districts 에 등록된 모든 선거구를 차례로 분석
uv run votelink analyze --all             # 등록된 모든 분석기 × 각자의 config.districts 전체. 입력 kind 는 1회만 읽어 공유
uv run votelink analyze <id> --dry-run   # 저장 없이 계약 검증만
uv run votelink analyze --sync           # analyzers/registry.yaml 재생성
uv run votelink camp new <id> --candidate <이름> --party <정당> --type <계열> --office <직위> \
    --lineage <진영> [--date YYYY-MM-DD] [--preset <선거구>|--sigungu <자치구>|--emd <코드>]
                                 # 캠프 온보딩. 관할은 프리셋·자치구·직접지정을 합칠 수 있다
uv run votelink camp list        # 캠프와 선거 주기 목록
uv run votelink camp show <캠프> [<주기>]  # 한 주기의 설정 (관할 검증 포함)
uv run votelink account create-operator <email> <pw>  # 운영자 추가. 웹에 운영자 가입 폼은 없다
                                         # (첫 운영자는 serve --auth 가 root/root 로 만든다)
uv run votelink account list             # 계정과 활성 세션 수
uv run votelink account signups          # 승인 대기 큐
uv run votelink account approve <신청id> --operator <운영자id> [--camp-id <id>]  # 승인 → 캠프 공간 생성
uv run votelink account reject <신청id> --operator <운영자id> --note <사유>      # 거절 (사유 필수)
uv run votelink account logout <계정id>  # 세션 전부 끊기 (비밀번호 유출 시 즉시 대응)
uv run votelink account passwd <계정id> <pw>  # 임시 비밀번호 발급 (기존 세션도 끊는다)
uv run votelink serve            # 로컬 웹앱 (기본 8420). `/` 선거구 선택 · `/d/<선거구>/`[/map] · `/compare` · `/nation`. `?election_type=` 로 계열 재필터
uv run votelink serve --district <선거구>  # `/` 를 이 선거구로 바로 보낸다
uv run votelink serve --camp <캠프>       # 이 캠프의 렌즈로 본다 (단일 캠프 로컬 사용)
uv run votelink serve --auth              # 로그인을 요구한다. 멀티캠프는 이것이 필수이고,
                                          # 운영자가 없으면 root/root 로 만든다. --camp 와 못 섞는다.
                                          # 127.0.0.1 밖으로 열려면 --auth + 기본 비밀번호 변경이 둘 다 필요
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
