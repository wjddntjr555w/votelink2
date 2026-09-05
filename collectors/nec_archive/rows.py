"""셀 격자 -> 행정동 단위 개표 행. 순수 함수.

선관위 개표자료는 33년치가 서로 다른 레이아웃이다. 그 차이를 **코드가 아니라
`Layout` 값**으로 흡수한다. 새 선거를 붙이는 것이 설정 변경이어야 한다.

이 모듈은 응답 형식과 무관한 산수·문자열 처리만 하므로 합성 데이터로 검증한다
(docs/20-collector-spec.md §7).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

Grid = list[list[str]]

# 1992년은 '풍납제1동', 지금은 '풍납1동'. 33년치를 한 이름 체계로 맞추는 유일한 규칙이다.
_JE_DONG_RE = re.compile(r"제(\d+)동$")

# 가운뎃점(·, districts.yaml 의 원 출처 표기)과 마침표(., mois_population 실제
# admmCd 표기) 가 같은 동을 다르게 쓴다 — 예: '종로1·2·3·4가동' vs '종로1.2.3.4가동'
# (D-001, districts.yaml 을 admmCd 백필 과정에서 MOIS 표기로 정정했다). 이 파일은
# districts.yaml 을 직접 조회하므로(§_emd_names) 이 차이를 흡수해야 한다.
_DOT_RE = re.compile(r"[·.]")

# 동 단위 합계 행의 투표구명. 선거마다 다르다 —
# 16·17대는 '소계', 19대는 '합계', 18·20·21대는 빈칸이다.
DEFAULT_TOTAL_MARKERS = ("", "소계", "합계")

# 후보명 자리에 오면 안 되는 집계 항목. layout 의 열 경계가 어긋났다는 신호다.
# 빈 이름만 막으면 '계' 열이 '계'라는 이름의 후보로 조용히 들어온다 —
# 그러면 득표가 두 배가 되는데 숫자는 그럴듯해서 눈치채기 어렵다.
AGGREGATE_LABELS = frozenset(
    {"계", "합계", "소계", "유효투표수", "무효투표수", "무표투표수", "기권수", "투표수", "선거인수"}
)


def normalize_emd(name: str) -> str:
    """'풍납제1동' -> '풍납1동', '·' -> '.'. 대조하는 양쪽 모두에 적용해야 한다.

    districts.yaml 의 표기가 출처마다(선관위 원본 vs MOIS 백필) 다를 수 있으므로
    이 함수를 파일 쪽과 districts.yaml 쪽 양쪽에 똑같이 적용해서 비교한다
    (한쪽만 정규화하면 어느 쪽이 '표준'인지 가정하게 되는데 그 가정이 always
    맞지는 않는다 — D-001 로 실제로 어긋난 사례가 나왔다).
    """
    text = _JE_DONG_RE.sub(r"\1동", (name or "").strip())
    return _DOT_RE.sub(".", text)


# 시군구명이 전국에서 겹치면(중구·강서구 등 여러 시도에 같은 이름) 원본이 '중구(서울)'
# 처럼 시도명을 괄호로 붙여 구분한다. 송파구처럼 전국에 하나뿐인 이름에는 안 붙어서
# 지금까지(송파구 하나만 쓸 때) 드러나지 않았다 — 47개 선거구로 넓히며 발견했다
# (D-002, 2002년 중구 기준선).
_DISAMBIGUATION_RE = re.compile(r"\([^)]*\)$")


def strip_disambiguation(sgg: str) -> str:
    return _DISAMBIGUATION_RE.sub("", sgg).strip()


def to_int(value: str) -> int:
    """'17,729' / '17729.0' / '' -> int. 출처마다 표기가 다르다."""
    text = str(value).replace(",", "").strip()
    if not text:
        return 0
    return int(float(text))


@dataclass(frozen=True)
class Layout:
    """한 선거 파일의 열·행 배치. meta.yaml 의 `elections[].layout` 이 그대로 들어온다."""

    sgg: int  # 구시군명(또는 위원회명) 열
    emd: int  # 읍면동명 열
    eligible: int  # 선거인수 열
    votes: int  # 투표수 열
    candidate_from: int  # 첫 후보 득표 열
    total: int  # 후보 득표 합계('계') 열 — 후보 열의 끝 경계이기도 하다
    invalid: int  # 무효투표수 열
    candidate_row: int  # 후보명이 있는 행
    data_from: int  # 데이터가 시작하는 행
    party_row: int | None = None  # 정당명 행. candidate_row 와 같으면 '정당\n후보' 한 칸
    precinct: int | None = None  # 투표구명 열. None 이면 그 파일에 투표구 개념이 없다
    sido: int | None = None  # 시도명 열. 16·17대는 이 열이 없다


@dataclass(frozen=True)
class EmdRow:
    """행정동 하나의 개표 결과. 아직 계약 레코드가 아니다."""

    emd_name: str
    eligible_voters: int
    total_votes: int
    counted_votes: int  # 출처가 준 '계'
    invalid_votes: int
    results: list[tuple[str, str]] = field(default_factory=list)  # (정당, 후보)
    votes: list[int] = field(default_factory=list)


def cell(row: list[str], index: int) -> str:
    """격자가 들쭉날쭉하다. 없는 칸은 빈 문자열로 본다."""
    return row[index].strip() if 0 <= index < len(row) else ""


def candidate_columns(grid: Grid, layout: Layout) -> list[tuple[str, str]]:
    """(정당, 후보) 목록. 후보 열은 `candidate_from` 부터 `total` 직전까지다.

    정당명 정규화는 하지 않는다 — 원문 그대로 보존한다. 진영 비교는 L2 의 일이다.
    """
    out: list[tuple[str, str]] = []
    for column in range(layout.candidate_from, layout.total):
        name = cell(grid[layout.candidate_row], column)
        party = ""
        if layout.party_row is not None:
            party = cell(grid[layout.party_row], column)
        # 신형 파일은 '더불어민주당\n이재명' 처럼 한 칸에 둘이 들어 있다.
        if layout.party_row == layout.candidate_row and "\n" in name:
            party, name = name.split("\n", 1)
        if not name.strip():
            raise ValueError(
                f"후보 열 {column} 의 이름이 비어 있다. "
                "layout 의 candidate_from/total/candidate_row 가 어긋났다"
            )
        if "".join(name.split()) in AGGREGATE_LABELS:
            raise ValueError(
                f"후보 열 {column} 에 집계 항목 '{name.strip()}' 이 들어왔다. "
                "layout 의 candidate_from/total 이 어긋났다"
            )
        out.append((party.strip(), name.strip()))
    return out


def iter_emd_rows(
    grid: Grid,
    layout: Layout,
    *,
    sigungu_match: str | tuple[str, ...],
    emd_names: set[str],
    total_markers: tuple[str, ...] = DEFAULT_TOTAL_MARKERS,
) -> Iterator[EmdRow]:
    """대상 시군구의 행정동 합계 행만 돌려준다.

    `sigungu_match` 는 보통 문자열 하나지만, 선거구가 두 자치구에 걸치면
    (예: 중구성동구 을 — 중구 15동 + 성동구 4동, D-002) 튜플로 여러 개를 준다.

    버리는 것(격리가 아니라 필터):
    - 대상이 아닌 시군구
    - `거소·선상투표` `관외사전투표` `재외투표` `부재자` 등 — 행정동이 아니다.
      emd_names 에 없으면 그냥 걸러진다. 오류가 아니라 대상이 아닐 뿐이고,
      격리하면 격리율 임계(5%)를 넘겨 수집 전체가 실패한다 (C-002 와 같은 판단)
    - 투표구 단위 행 — 인구와 조인되는 단위는 동이고, 투표구는 선거마다 재편돼
      시계열이 되지 않는다
    """
    matches = (sigungu_match,) if isinstance(sigungu_match, str) else sigungu_match
    candidates = candidate_columns(grid, layout)
    sigungu = ""
    for row in grid[layout.data_from :]:
        # 신형 파일은 구시군명이 블록 첫 행에만 있다(병합셀). 앞의 값을 이어 쓴다.
        if cell(row, layout.sgg):
            sigungu = strip_disambiguation(cell(row, layout.sgg).strip("[]"))
        if not any(m in sigungu for m in matches):
            continue
        name = normalize_emd(cell(row, layout.emd))
        if name not in emd_names:
            continue
        if layout.precinct is not None and cell(row, layout.precinct) not in total_markers:
            continue
        yield EmdRow(
            emd_name=name,
            eligible_voters=to_int(cell(row, layout.eligible)),
            total_votes=to_int(cell(row, layout.votes)),
            counted_votes=to_int(cell(row, layout.total)),
            invalid_votes=to_int(cell(row, layout.invalid)),
            results=candidates,
            votes=[to_int(cell(row, c)) for c in range(layout.candidate_from, layout.total)],
        )


# --- 기준선(상위 행정단위) 합계 ------------------------------------------------
#
# 동별 득표율은 그 자체로 의미가 없다. "송파갑 평균 대비", "서울 평균 대비" 처럼
# 비교 대상이 있어야 지표가 된다. 원본 격자에는 전국이 이미 들어 있고 현재 파서가
# 송파구만 걸러낼 뿐이므로, **재수집 없이** 총계 행만 더 읽으면 된다.
#
# 33년치의 총계 표기가 제각각이라 조건을 코드에 박지 않고 meta.yaml 의
# `elections[].baselines` 규칙으로 둔다. 규칙 하나가 여러 행에 맞으면 **합산**한다
# (1992년 송파구는 '송파구갑'+'송파구을' 로만 존재한다).


@dataclass(frozen=True)
class BaselineRule:
    """어느 행들을 모아 한 단위의 합계로 삼을지."""

    level: str  # nation / sido / sigungu
    sido: str | None = None  # 시도열 완전일치
    sido_prefix: str | None = None  # 시도열 접두사 ('서울' 이 '서울특별시'를 잡는다)
    sgg: str | None = None  # 시군구열 완전일치
    sgg_prefix: str | None = None  # 시군구열 접두사 ('송파구' 가 '송파구갑'을 잡는다)
    emd: tuple[str, ...] = ()  # 읍면동열이 이 중 하나 (빈 튜플이면 조건 없음)

    # 잡힐 것으로 기대하는 행 수. **이 안전장치가 없으면 결함이 조용히 지나간다.**
    # 18대는 송파구에 '소계' 행이 둘이다 — 구 전체(545,369)와 재외·부재자를 뺀
    # 관내분(527,457). 둘 다 산술이 맞아서 합쳐도 불변식에 걸리지 않고,
    # 투표율도 그럴듯하게 나온다. 오직 행 수로만 드러난다.
    expect: int | None = None

    # 여러 행이 잡혔을 때 첫 행만 쓴다. 선관위 파일은 블록 첫 행이 그 단위의
    # 전체 합계이고 뒤따르는 소계는 부분집합이다.
    take_first: bool = False

    def matches(self, sido: str, sgg: str, emd: str) -> bool:
        if self.sido is not None and sido != self.sido:
            return False
        if self.sido_prefix is not None and not sido.startswith(self.sido_prefix):
            return False
        if self.sgg is not None and sgg != self.sgg:
            return False
        if self.sgg_prefix is not None and not sgg.startswith(self.sgg_prefix):
            return False
        return not (self.emd and emd not in self.emd)


@dataclass(frozen=True)
class BaselineRow:
    """상위 행정단위 하나의 개표 합계. EmdRow 와 같은 모양이지만 이름이 없다."""

    level: str
    eligible_voters: int
    total_votes: int
    counted_votes: int
    invalid_votes: int
    results: list[tuple[str, str]] = field(default_factory=list)
    votes: list[int] = field(default_factory=list)
    matched_rows: int = 0


def iter_baseline_rows(
    grid: Grid, layout: Layout, rules: list[BaselineRule]
) -> Iterator[BaselineRow]:
    """규칙마다 맞는 행을 모아 합산한 결과를 돌려준다.

    맞는 행이 하나도 없으면 그 규칙은 **조용히 건너뛰지 않고** 예외를 던진다.
    기준선이 소리 없이 빠지면 분석기의 gap 이 None 이 되는데, 그게 '아직 없어서'인지
    '규칙이 틀려서'인지 구분할 수 없기 때문이다.
    """
    candidates = candidate_columns(grid, layout)
    span = range(layout.candidate_from, layout.total)

    for rule in rules:
        hits: list[list[str]] = []
        sido = sgg = ""

        for row in grid[layout.data_from :]:
            # 병합셀은 블록 첫 행에만 값이 있다. 앞의 값을 이어 쓴다.
            if layout.sido is not None and cell(row, layout.sido):
                sido = cell(row, layout.sido)
            if cell(row, layout.sgg):
                sgg = strip_disambiguation(cell(row, layout.sgg).strip("[]"))
            if rule.matches(sido, sgg, cell(row, layout.emd)):
                hits.append(row)

        if not hits:
            raise ValueError(
                f"기준선 규칙 '{rule.level}' 에 맞는 행이 없다: {rule}. "
                "meta.yaml 의 baselines 조건이 이 선거 파일의 표기와 맞지 않는다"
            )
        if rule.expect is not None and len(hits) != rule.expect:
            raise ValueError(
                f"기준선 규칙 '{rule.level}' 이 {len(hits)}개 행을 잡았는데 "
                f"{rule.expect}개를 기대했다: {rule}. 파일 구조가 달라졌거나 조건이 "
                "상위/하위 단위를 함께 잡고 있다 — 합산하면 득표가 부풀지만 "
                "산술 불변식으로는 드러나지 않는다"
            )

        used = hits[:1] if rule.take_first else hits
        acc = [0] * len(span)
        eligible = votes = counted = invalid = 0
        for row in used:
            eligible += to_int(cell(row, layout.eligible))
            votes += to_int(cell(row, layout.votes))
            counted += to_int(cell(row, layout.total))
            invalid += to_int(cell(row, layout.invalid))
            for i, column in enumerate(span):
                acc[i] += to_int(cell(row, column))

        yield BaselineRow(
            level=rule.level,
            eligible_voters=eligible,
            total_votes=votes,
            counted_votes=counted,
            invalid_votes=invalid,
            results=candidates,
            votes=acc,
            matched_rows=len(used),
        )


def merge_baseline_rows(rows: list[BaselineRow], *, level: str) -> BaselineRow:
    """여러 `BaselineRow` 를 하나로 합산한다.

    17대(2007)는 시도별 16개 파일로 쪼개져 있어 전국 총계 행 자체가 없다.
    각 파일의 자체 총계(구 합계의 합)를 구한 뒤 16개를 더해야 전국이 나온다.
    같은 선거의 같은 후보 순서를 전제한다 — 파일마다 후보 열 순서가 다르면
    득표가 엉뚱한 후보에게 더해지는데 겉으로는 드러나지 않는다.
    """
    if not rows:
        raise ValueError(f"합산할 행이 없다: level={level}")

    width = len(rows[0].votes)
    for row in rows:
        if len(row.votes) != width:
            raise ValueError(
                f"'{level}' 합산 중 후보 수가 다른 행을 만났다: "
                f"{width} vs {len(row.votes)}. 시도 파일마다 레이아웃이 다를 수 없다"
            )

    return BaselineRow(
        level=level,
        eligible_voters=sum(r.eligible_voters for r in rows),
        total_votes=sum(r.total_votes for r in rows),
        counted_votes=sum(r.counted_votes for r in rows),
        invalid_votes=sum(r.invalid_votes for r in rows),
        results=rows[0].results,
        votes=[sum(r.votes[i] for r in rows) for i in range(width)],
        matched_rows=sum(r.matched_rows for r in rows),
    )


def check_baseline_arithmetic(row: BaselineRow) -> None:
    """동 단위와 같은 산술 불변식을 기준선에도 건다.

    합산은 조용히 틀리기 쉽다 — 투표구 행이 섞여 들어오면 득표가 배로 뛰는데
    숫자는 그럴듯하다. 출처가 준 '계'와 대조하면 그게 드러난다.
    """
    summed = sum(row.votes)
    if summed != row.counted_votes:
        raise ValueError(
            f"{row.level}: 득표 합({summed})이 출처의 '계'({row.counted_votes})와 다르다. "
            f"baselines 규칙이 {row.matched_rows}개 행을 잡았는데 그중 상위/하위 단위가 "
            "섞였을 가능성이 높다"
        )
    if row.counted_votes + row.invalid_votes != row.total_votes:
        raise ValueError(
            f"{row.level}: 계({row.counted_votes}) + 무효({row.invalid_votes}) 가 "
            f"투표수({row.total_votes})와 맞지 않는다"
        )
    if row.total_votes > row.eligible_voters:
        raise ValueError(
            f"{row.level}: 투표수({row.total_votes})가 선거인수({row.eligible_voters})보다 많다"
        )


def check_arithmetic(row: EmdRow) -> None:
    """출처가 스스로 준 '계' 와 우리가 더한 값이 맞는지 본다.

    계약도 `득표합 + 무효 == 투표수` 를 강제하지만, 그것만으로는 열 인덱스가
    통째로 밀린 경우를 못 잡는다. 출처의 '계' 와 대조해야 layout 오류가 드러난다.
    """
    summed = sum(row.votes)
    if summed != row.counted_votes:
        raise ValueError(
            f"{row.emd_name}: 득표 합({summed})이 출처의 '계'({row.counted_votes})와 다르다. "
            "layout 의 candidate_from/total 열이 어긋났을 가능성이 높다"
        )
    if row.counted_votes + row.invalid_votes != row.total_votes:
        raise ValueError(
            f"{row.emd_name}: 계({row.counted_votes}) + 무효({row.invalid_votes}) 가 "
            f"투표수({row.total_votes})와 맞지 않는다"
        )
