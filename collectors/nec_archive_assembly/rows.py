"""셀 격자 -> 지역구 하나의 행정동 단위 개표 행. 순수 함수.

대선(nec_archive)과 다른 점: 지역구 300곳마다 **후보 수가 다르다.** 그래서 후보
열 경계(`total`)는 고정 인덱스가 아니라 헤더 행에서 `계` 라는 텍스트를 찾아
동적으로 정한다(사용자 승인, 2026-09-03). `candidate_from`·구조적 열(읍면동명 등)은
파일 안에서 안 바뀌므로 여전히 설정값이다.

이 모듈은 응답 형식과 무관한 산수·문자열 처리만 하므로 합성 데이터로 검증한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

Grid = list[list[str]]

# '풍납제1동' -> '풍납1동'. nec_archive(대선)와 같은 규칙이지만 이 폴더는
# 코드를 공유하지 않으므로 별도로 둔다.
_JE_DONG_RE = re.compile(r"제(\d+)동$")

# 가운뎃점(·, 선관위 원본 표기)과 마침표(., mois_population 실제 admmCd 표기)가
# 같은 동을 다르게 쓴다 — 예: '종로1·2·3·4가동' vs '종로1.2.3.4가동' (D-001,
# districts.yaml 을 admmCd 백필 과정에서 MOIS 표기로 정정했다).
_DOT_RE = re.compile(r"[·.]")

DEFAULT_TOTAL_MARKERS = ("소계",)

AGGREGATE_LABELS = frozenset(
    {"계", "합계", "소계", "유효투표수", "무효투표수", "무표투표수", "기권수", "투표수", "선거인수"}
)


def normalize_emd(name: str) -> str:
    """양쪽(파일 · districts.yaml) 모두에 적용해서 비교한다 — 어느 쪽이 '표준'인지
    가정하지 않는다. 한쪽만 정규화하면 그 가정이 always 맞지는 않는다(D-001)."""
    text = _JE_DONG_RE.sub(r"\1동", (name or "").strip())
    return _DOT_RE.sub(".", text)


def to_int(value: str) -> int:
    text = str(value).replace(",", "").strip()
    if not text:
        return 0
    return int(float(text))


def cell(row: list[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) else ""


@dataclass(frozen=True)
class Layout:
    """지역구 하나의 개표 격자 배치.

    `district_col` 이 있으면(22대처럼 전국 단일 파일) 그 열 값으로 대상 지역구
    행만 골라낸다. 없으면(18~21대처럼 시트/파일이 이미 그 지역구 하나다) grid
    전체를 그대로 쓴다.
    """

    emd: int
    precinct: int  # 투표구명(또는 투표타입) 열. '소계' 여부로 동 단위 행을 가른다
    eligible: int
    votes: int
    candidate_from: int
    label_row: int  # `total_label` 을 찾는 행. district_col 모드에선 파일 전체의
    # 고정 헤더 행(예: 22대는 최대 후보 수에 맞춘 공용 폭이라 지역구와 무관하게 같다)
    data_from: int
    district_col: int | None = None
    district_name_col: int | None = None  # district_col 매칭에 쓰는 값이 다른 열이면
    candidate_name_row_offset: int | None = None  # None 이면 이름 행이 '정당\n후보' 병합.
    # 아니면 이름 행 = (이름을 읽는 기준 행) + 이 오프셋 (18대: 정당행 다음 줄)
    candidate_from_block_start: bool = False
    # True 면 후보 이름을 label_row 가 아니라 **그 지역구 블록이 시작하는 행**에서
    # 읽는다. 22대처럼 후보 열 경계(`계`)는 파일 전체가 공유하는 고정 위치인데,
    # 실제로 뛴 후보(정당\n후보 병합 셀)는 지역구 블록의 첫 행에만 있기 때문이다.
    total_label: str = "계"
    invalid_offset: int = 1  # total_col + 이 값 = 무효 열


@dataclass(frozen=True)
class DistrictRow:
    """행정동 하나의 개표 결과. 아직 계약 레코드가 아니다."""

    emd_name: str
    eligible_voters: int
    total_votes: int
    counted_votes: int
    invalid_votes: int
    results: list[tuple[str, str]] = field(default_factory=list)
    votes: list[int] = field(default_factory=list)


def find_total_column(row: list[str], start: int, label: str) -> int:
    """헤더 행에서 `label` 텍스트가 나오는 열을 찾는다. 후보 열의 끝 경계다.

    지역구마다 후보 수가 달라 고정 인덱스를 쓸 수 없다. 지역구 하나를 고른 뒤
    **그 안에서 한 번만** 찾으면 된다 — 같은 지역구 안에서는 후보 수가 고정이다.
    """
    for i in range(start, len(row)):
        if cell(row, i) == label:
            return i
    raise ValueError(
        f"헤더 행 {start}열부터 '{label}' 라벨을 못 찾았다. "
        "layout.label_row 나 candidate_from 이 이 파일과 안 맞는다"
    )


def candidate_columns(
    grid: Grid, layout: Layout, total_col: int, name_row: int
) -> list[tuple[str, str]]:
    """(정당, 후보) 목록. `candidate_from` ~ `total_col` 직전까지.

    `name_row` 에서 후보 이름을 읽는다 — 보통 `label_row` 지만,
    `candidate_from_block_start` 인 파일(22대)은 지역구 블록의 첫 행이다.

    빈 칸은 건너뛴다 — 전국 공용 헤더를 쓰는 파일(22대)은 최대 후보 수에 맞춰
    열을 넉넉히 잡아 두고 실제 후보가 적은 지역구는 나머지를 비워 둔다.
    """
    out: list[tuple[str, str]] = []
    for column in range(layout.candidate_from, total_col):
        label = cell(grid[name_row], column)
        if not label:
            continue  # 패딩된 빈 후보 슬롯

        if layout.candidate_name_row_offset is not None:
            party = label
            name = cell(grid[name_row + layout.candidate_name_row_offset], column)
        elif "\n" in label:
            party, name = label.split("\n", 1)
        else:
            party, name = "", label

        name = name.strip()
        if not name or "".join(name.split()) in AGGREGATE_LABELS:
            raise ValueError(
                f"후보 열 {column} 이 이름이 없거나 집계 항목이다: {label!r}. "
                "candidate_from/label_row 가 이 지역구와 안 맞는다"
            )
        out.append((party.strip(), name))
    return out


def iter_district_rows(
    grid: Grid,
    layout: Layout,
    *,
    district_name: str | None = None,
    emd_names: set[str],
    total_markers: tuple[str, ...] = DEFAULT_TOTAL_MARKERS,
) -> Iterator[DistrictRow]:
    """대상 지역구의 행정동 합계 행만 돌려준다.

    `district_col` 이 설정돼 있으면 병합셀 전방채움 후 그 값이 `district_name`
    과 같은 구간만 본다(22대). 아니면 grid 전체가 이미 그 지역구다(18~21대).
    """
    total_col = find_total_column(grid[layout.label_row], layout.candidate_from, layout.total_label)

    # 후보 이름을 읽을 행. 보통 label_row 지만, block_start 모드(22대)는 지역구
    # 블록의 첫 행에만 그 지역구가 실제로 낸 후보 이름이 있다 — label_row 는
    # 파일 전체가 공유하는 폭 넓은 헤더일 뿐이라 이름이 없다.
    name_row = layout.label_row
    candidates: list[tuple[str, str]] | None = None
    span_labels: list[bool] | None = None  # 열별로 실제 후보가 있었는지 (패딩된 빈 슬롯 제외용)
    if not layout.candidate_from_block_start:
        candidates = candidate_columns(grid, layout, total_col, name_row)
        span_labels = [
            bool(cell(grid[name_row], c)) for c in range(layout.candidate_from, total_col)
        ]

    district = ""
    in_target = layout.district_col is None
    for row_index, row in enumerate(grid[layout.data_from :], layout.data_from):
        if layout.district_col is not None:
            name_col = layout.district_name_col or layout.district_col
            if cell(row, layout.district_col):
                district = cell(row, name_col)
                if district == district_name and layout.candidate_from_block_start:
                    # 이 행이 지역구 블록의 첫 행 — 후보 이름이 여기 있다
                    candidates = candidate_columns(grid, layout, total_col, row_index)
                    span_labels = [
                        bool(cell(row, c)) for c in range(layout.candidate_from, total_col)
                    ]
            in_target = district == district_name

        if not in_target:
            continue
        if candidates is None:
            continue  # district_name 행을 아직 못 만났다 (블록 밖 잡음 행)

        name = normalize_emd(cell(row, layout.emd))
        if name not in emd_names:
            continue
        if cell(row, layout.precinct) not in total_markers:
            continue

        span = range(layout.candidate_from, total_col)
        votes = [to_int(cell(row, c)) for c, has in zip(span, span_labels, strict=True) if has]

        yield DistrictRow(
            emd_name=name,
            eligible_voters=to_int(cell(row, layout.eligible)),
            total_votes=to_int(cell(row, layout.votes)),
            counted_votes=to_int(cell(row, total_col)),
            invalid_votes=to_int(cell(row, total_col + layout.invalid_offset)),
            results=candidates,
            votes=votes,
        )


def check_arithmetic(row: DistrictRow) -> None:
    summed = sum(row.votes)
    if summed != row.counted_votes:
        raise ValueError(
            f"{row.emd_name}: 득표 합({summed})이 출처의 '계'({row.counted_votes})와 다르다. "
            "layout 의 candidate_from/label_row 가 어긋났을 가능성이 높다"
        )
    if row.counted_votes + row.invalid_votes != row.total_votes:
        raise ValueError(
            f"{row.emd_name}: 계({row.counted_votes}) + 무효({row.invalid_votes}) 가 "
            f"투표수({row.total_votes})와 맞지 않는다"
        )
    if row.total_votes > row.eligible_voters:
        raise ValueError(
            f"{row.emd_name}: 투표수({row.total_votes})가 선거인수({row.eligible_voters})보다 많다"
        )
