"""뷰모델 — 레코드에서 화면 조각으로. **전부 순수 함수라 의존성 없이 돌아간다.**

여기서 지키는 핵심 계약: **`gap_* = None` 은 화면 어디에서도 0이 되지 않는다.**
계약 주석("'차이가 없다'와 '모른다'는 다르다")을 UI가 무너뜨릴 수 있는 경로가 넷이고,
그 넷을 각각 테스트로 막는다 — 숫자·색·집계·선 그래프.

도형(`shapes.py`)도 표현이므로 여기서 함께 본다.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import make_record
from votelink.contract.enums import AgeBand, Camp, Trend
from votelink.contract.payloads import SegmentProfilePayload
from votelink.reference.compliance import OutputPolicy, Policy, ReviewStatus, Verdict
from votelink.reference.districts import District, Emd
from votelink.web import shapes as shapes_mod
from votelink.web.loader import DistrictProfiles, EmdProfile, LoadDiagnostics
from votelink.web.viewmodel import (
    METRICS,
    UNKNOWN_FILL,
    UNKNOWN_TEXT,
    GapCell,
    GapSummary,
    build_card,
    build_map,
    build_view,
    camp_bar,
    divergent_fill,
    fmt,
    sort_cards,
    sparkline,
    worst_verdict,
)

CODES = ["1171051000", "1171052000", "1171056100"]


def lean(date: str, con: float, **gaps) -> dict:
    return {
        "election_id": f"{date}-presidential",
        "election_date": date,
        "election_type": "presidential",
        "camp_share": {
            "conservative": con,
            "progressive": 100.0 - con,
            "centrist": 0.0,
            "other": 0.0,
        },
        "turnout": gaps.pop("turnout", 70.0),
        "gap_district": gaps.get("gap_district"),
        "gap_sigungu": gaps.get("gap_sigungu"),
        "gap_sido": gaps.get("gap_sido"),
        "gap_nation": gaps.get("gap_nation"),
    }


def payload_dict(series: list[dict]) -> dict:
    con = [p["camp_share"]["conservative"] for p in series]
    return {
        "profile_type": "voter_profile",
        "as_of": "2024-12",
        "lean_series": series,
        "swing": max(con) - min(con),
        "trend": "stable",
        "age_mix": {band.value: 100.0 / len(AgeBand) for band in AgeBand},
        "sex_ratio": 0.97,
        "population_total": 1000,
        "population_month": "2024-12",
    }


def make_profile(code: str = CODES[0], series: list[dict] | None = None, **over) -> EmdProfile:
    series = series or [lean("2020-04-15", 40.0), lean("2025-06-03", 50.0)]
    record = make_record(
        kind="segment_profile",
        geo_code=code,
        geo_name=f"동{code[-4:]}",
        payload=payload_dict(series),
        natural_key=f"voter_profile|{code}|2024-12",
        **over,
    )
    return EmdProfile(record=record, payload=SegmentProfilePayload.model_validate(record.payload))


def make_district() -> District:
    return District(
        id="test_gap",
        name="시험 지역구 갑",
        sido="시험시",
        sigungu="시험구",
        emd=[Emd(name=f"동{c[-4:]}", code=c) for c in CODES],
    )


def cleared_policy() -> Policy:
    return Policy(
        outputs=[
            OutputPolicy(kind="segment_profile", risk="low", status="cleared", reviewed_by="검토자")
        ]
    )


# --- gap = None: 숫자 자리 ---------------------------------------------------------


def test_unknown_gap_is_not_zero():
    """`—` 와 `0.0` 은 글자도 클래스도 달라야 한다.

    이게 무너지면 '모른다'가 '차이가 없다'로 읽힌다. 계약이 None 을 0.0 으로 채우지
    않는 이유가 화면에서 통째로 사라진다.
    """
    unknown = GapCell.of(None)
    zero = GapCell.of(0.0)

    assert unknown.text == UNKNOWN_TEXT
    assert zero.text == "+0.0"
    assert unknown.text != zero.text
    assert unknown.css_class != zero.css_class
    assert unknown.known is False
    assert zero.known is True


def test_unknown_gap_says_why():
    assert "기준선" in GapCell.of(None, "서울시").title
    assert "서울시" in GapCell.of(None, "서울시").title


def test_gap_sign_classes_differ():
    assert GapCell.of(1.0).css_class != GapCell.of(-1.0).css_class
    assert GapCell.of(0.0).css_class != GapCell.of(1.0).css_class


# --- gap = None: 집계 --------------------------------------------------------------


def test_unknown_gaps_do_not_drag_the_mean_toward_zero():
    """None 을 0으로 세면 평균이 0 쪽으로 끌린다. 빼고 계산하고 분모를 밝힌다."""
    summary = GapSummary.of([10.0, 10.0, None, None])
    assert summary.mean == 10.0  # 5.0 이 아니다
    assert summary.known == 2
    assert summary.total == 4
    assert "4회 중 2회" in summary.text


def test_all_unknown_summary_has_no_mean():
    summary = GapSummary.of([None, None])
    assert summary.mean is None
    assert summary.text.startswith(UNKNOWN_TEXT)
    assert "2회 중 0회" in summary.text


# --- gap = None: 선 그래프 ----------------------------------------------------------


def test_sparkline_breaks_the_line_at_unknown():
    """앞뒤를 이으면 없는 데이터를 보간한 게 된다."""
    spark = sparkline([1.0, 2.0, None, 4.0, 5.0], ["a", "b", "c", "d", "e"])
    assert len(spark.segments) == 2  # 끊겼다
    assert len(spark.dots) == 4  # None 자리에는 점도 없다
    assert spark.breaks == 1


def test_sparkline_without_gaps_is_one_segment():
    spark = sparkline([1.0, 2.0, 3.0], ["a", "b", "c"])
    assert len(spark.segments) == 1
    assert spark.breaks == 0


def test_sparkline_of_all_unknown_draws_nothing():
    spark = sparkline([None, None], ["a", "b"])
    assert spark.segments == []
    assert spark.is_empty


# --- gap = None: 색 ----------------------------------------------------------------


def test_unknown_map_cell_is_hatched_not_colored(tmp_path):
    """발산 스케일에서 None 이 중립색이 되면 0.0 과 화면상 완전히 같아진다."""
    blind = [lean("2020-04-15", 40.0), lean("2025-06-03", 50.0, gap_district=None)]
    seeing = [lean("2020-04-15", 40.0), lean("2025-06-03", 50.0, gap_district=3.0)]
    profiles = _profiles([make_profile(CODES[0], blind), make_profile(CODES[1], seeing)])
    view = build_view(profiles, cleared_policy())
    shape_set = shapes_mod.shapes_for(
        [(c.geo_code, c.geo_name) for c in view.cards], path=tmp_path / "없다.geojson"
    )
    map_view = build_map(view, shape_set, metric_key="gap_district")

    unknown = [c for c in map_view.cells if c.value is None]
    assert len(unknown) == 1
    assert unknown[0].fill == UNKNOWN_FILL  # 색이 아니라 무늬
    assert unknown[0].text == UNKNOWN_TEXT
    assert "unknown" in unknown[0].css_class
    assert map_view.has_unknown
    # 값 없음은 색 눈금에 끼워 넣지 않고 별도 항목으로 둔다
    assert any(stop.fill == UNKNOWN_FILL for stop in map_view.legend)


def test_zero_gap_still_gets_a_color(tmp_path):
    """0.0 은 아는 값이다. 해칭으로 빠지면 안 된다."""
    series = [lean("2020-04-15", 40.0), lean("2025-06-03", 50.0, gap_district=0.0)]
    view = build_view(_profiles([make_profile(CODES[0], series)]), cleared_policy())
    shape_set = shapes_mod.shapes_for(
        [(c.geo_code, c.geo_name) for c in view.cards], path=tmp_path / "없다.geojson"
    )
    cell = build_map(view, shape_set, metric_key="gap_district").cells[0]
    assert cell.fill != UNKNOWN_FILL
    assert cell.fill.startswith("hsl(")


# --- 카드 -----------------------------------------------------------------------


def _profiles(items: list[EmdProfile]) -> DistrictProfiles:
    return DistrictProfiles(
        district=make_district(),
        profiles=items,
        diagnostics=LoadDiagnostics(loaded=len(items), expected=len(CODES)),
    )


def test_camp_bar_stacks_to_100():
    card = build_card(make_profile(), make_district(), cleared_policy())
    assert [s.camp for s in card.camp_bar] == list(
        (Camp.PROGRESSIVE, Camp.CENTRIST, Camp.CONSERVATIVE, Camp.OTHER)
    )
    last = card.camp_bar[-1]
    assert last.offset + last.pct == pytest.approx(100.0, abs=0.01)


def test_camp_bar_keeps_zero_camps():
    """계약이 4개 키를 보장한다. 0%라고 빼면 막대 색 순서가 카드마다 달라진다."""
    assert len(camp_bar(make_profile().payload.lean_series[-1])) == 4


def test_sex_ratio_has_no_percent_sign():
    """이 payload 의 유일한 비-퍼센트 값이다."""
    card = build_card(make_profile(), make_district(), cleared_policy())
    assert card.sex_ratio_text == "0.97"
    assert "%" not in card.sex_ratio_text


def test_card_counts_missing_gaps():
    series = [lean("2020-04-15", 40.0), lean("2025-06-03", 50.0, gap_district=1.0)]
    card = build_card(make_profile(CODES[0], series), make_district(), cleared_policy())
    # 2회 × 4단위 = 8칸, 그중 채워진 것은 gap_district 하나뿐이다
    assert card.missing_gaps == 7


def test_card_uses_the_real_upper_unit_names():
    """편차 기준 이름을 코드에 박지 않는다."""
    card = build_card(make_profile(), make_district(), cleared_policy())
    assert "시험구" in card.gaps["sigungu"].title
    assert "시험시" in card.gaps["sido"].title


def test_trend_note_comes_from_the_contract():
    """설명문의 유일한 출처는 `enums.Trend` 독스트링이다. meta.yaml 값이 아니다."""
    view = build_view(_profiles([make_profile()]), cleared_policy())
    assert view.trend_note
    assert view.trend_note == (Trend.__doc__ or "").strip()


# --- 결정성 ---------------------------------------------------------------------


def test_view_is_deterministic():
    """같은 입력이면 같은 화면. 시계도 난수도 쓰지 않는다."""
    profiles = _profiles([make_profile(CODES[0]), make_profile(CODES[1])])
    policy = cleared_policy()
    assert build_view(profiles, policy) == build_view(profiles, policy)


# --- 정렬 -----------------------------------------------------------------------


def test_gap_sort_puts_unknown_last():
    """값 없음이 0.0 과 섞이면 '모른다'가 중간 성적처럼 보인다."""
    known = make_profile(CODES[0], [lean("2025-06-03", 50.0, gap_district=-5.0)])
    unknown = make_profile(CODES[1], [lean("2025-06-03", 50.0, gap_district=None)])
    high = make_profile(CODES[2], [lean("2025-06-03", 50.0, gap_district=9.0)])
    district, policy = make_district(), cleared_policy()
    cards = [build_card(p, district, policy) for p in (known, unknown, high)]

    ordered = sort_cards(cards, "gap")
    assert [c.gaps["district"].value for c in ordered] == [9.0, -5.0, None]


def test_unknown_sort_key_falls_back_to_code():
    cards = [
        build_card(make_profile(c), make_district(), cleared_policy()) for c in (CODES[2], CODES[0])
    ]
    assert [c.geo_code for c in sort_cards(cards, "말도안되는키")] == [CODES[0], CODES[2]]


# --- 지표 표기 -------------------------------------------------------------------


def test_only_deviations_get_a_sign():
    """투표율 82%를 `+82%` 로 쓰면 틀린 표기다."""
    assert fmt(82.0, METRICS["turnout"]) == "82.0"
    assert fmt(-6.7, METRICS["gap_district"]) == "-6.7"
    assert fmt(11.5, METRICS["gap_district"]) == "+11.5"


def test_divergent_fill_is_symmetric_and_deterministic():
    assert divergent_fill(5.0, 10.0) == divergent_fill(5.0, 10.0)
    assert divergent_fill(5.0, 10.0) != divergent_fill(-5.0, 10.0)  # 진영이 다르면 색이 다르다
    assert divergent_fill(0.0, 0.0).startswith("hsl(")  # 전부 같은 값이어도 죽지 않는다


# --- 판정 집계 -------------------------------------------------------------------


def test_worst_verdict_wins():
    """하나라도 blocked 면 헤더도 blocked 다. 헤더가 실상을 축소해 말하지 않게."""
    verdicts = [
        Verdict(status=ReviewStatus.CLEARED),
        Verdict(status=ReviewStatus.BLOCKED),
        Verdict(status=ReviewStatus.UNREVIEWED),
    ]
    assert worst_verdict(verdicts).status is ReviewStatus.BLOCKED
    assert worst_verdict([]) is None


# --- 도형 -----------------------------------------------------------------------


def test_grid_is_used_when_no_boundary_file(tmp_path):
    shape_set = shapes_mod.shapes_for(
        [(c, f"동{c[-4:]}") for c in CODES], path=tmp_path / "없다.geojson"
    )
    assert shape_set.is_real_boundary is False  # 화면이 고지를 띄우는 근거
    assert len(shape_set.shapes) == 3
    assert all(s.svg_path.startswith("M ") for s in shape_set.shapes)


def test_grid_order_is_geo_code_not_input_order(tmp_path):
    """칸을 손으로 배치하지 않는다. 배치가 판단이 되면 참조 데이터가 돼야 한다."""
    reversed_input = [(c, f"동{c[-4:]}") for c in reversed(CODES)]
    shape_set = shapes_mod.shapes_for(reversed_input, path=tmp_path / "없다.geojson")
    assert [s.geo_code for s in shape_set.shapes] == CODES


def test_real_boundary_is_used_when_the_file_exists(tmp_path):
    """파일이 들어오면 화면 코드를 안 고치고 실제 경계로 바뀐다 — 이 이음매가 요점이다."""
    path = tmp_path / "emd_boundaries.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"adm_cd": code},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[127.1 + i, 37.5], [127.2 + i, 37.5], [127.2 + i, 37.6]]
                            ],
                        },
                    }
                    for i, code in enumerate(CODES)
                ],
            }
        ),
        encoding="utf-8",
    )
    shape_set = shapes_mod.shapes_for([(c, f"동{c[-4:]}") for c in CODES], path=path)
    assert shape_set.is_real_boundary is True
    assert len(shape_set.shapes) == 3
    assert "L " in shape_set.shapes[0].svg_path  # 사각형이 아니라 폴리곤


def test_boundary_file_missing_a_code_fails_loudly(tmp_path):
    """격자로 조용히 후퇴하지 않는다. 파일을 놓아둔 사람은 그게 쓰이기를 기대한다."""
    path = tmp_path / "emd_boundaries.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"adm_cd": CODES[0]},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[127.1, 37.5], [127.2, 37.5], [127.2, 37.6]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(shapes_mod.ShapeError, match="없는 행정동코드"):
        shapes_mod.shapes_for([(c, "x") for c in CODES], path=path)


def test_unrecognised_code_property_names_the_keys_it_tried(tmp_path):
    path = tmp_path / "b.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"이상한이름": "1"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[127.1, 37.5], [127.2, 37.5], [127.2, 37.6]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(shapes_mod.ShapeError, match="_CODE_KEYS"):
        shapes_mod.shapes_for([(CODES[0], "x")], path=path)
