"""districts.yaml 백필(D-001) — raw 응답의 admmCd 로 emd[].code 를 채운다.

정확 일치만 자동으로 채우고, 표기가 다른 동은 손대지 않은 채 리포트로만 드러내야
한다는 것과, 줄 단위로 되쓰는 게 주석·서식을 보존한다는 것이 이 테스트의 핵심이다.
"""

from __future__ import annotations

import pytest

from collectors.mois_population.aggregate import source_field
from votelink.collect.base import RawBatch
from votelink.collect.storage import write_raw
from votelink.contract.enums import Sex
from votelink.reference import districts as districts_mod
from votelink.reference import emd_backfill

AGE_STARTS = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)


@pytest.fixture(autouse=True)
def fresh_cache():
    districts_mod.reset_cache()
    yield
    districts_mod.reset_cache()


def make_row(sido: str, sigungu: str, dong: str, admm_code: str) -> dict:
    row = {
        "ctpvNm": sido,
        "sggNm": sigungu,
        "dongNm": dong,
        "admmCd": admm_code,
        "totNmprCnt": "0",
    }
    for age in AGE_STARTS:
        for sex in Sex:
            row[source_field(sex, age)] = "0"
    return row


def write_raw_batch(root, rows: list[dict], batch_key: str = "batch") -> None:
    body = {"Response": {"items": {"item": rows}}}
    batch = RawBatch(collector_id="mois_population", body=body, batch_key=batch_key)
    write_raw(batch, root=root)


def write_districts_yaml(path, body: str) -> None:
    path.write_text(
        "# 주석은 살아 있어야 한다.\nversion: test\ndistricts:\n" + body,
        encoding="utf-8",
    )


def test_fills_exact_name_match(tmp_path):
    raw_root = tmp_path / "raw"
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "청운효자동", "1111051500")],
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n',
    )

    report = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)

    assert report.ok
    assert report.filled == [("seoul_jongno", "청운효자동", "1111051500")]
    assert not report.unmatched_yaml
    text = yaml_path.read_text(encoding="utf-8")
    assert "# 주석은 살아 있어야 한다." in text
    assert '"청운효자동", code: "1111051500"' in text

    districts_mod.reset_cache()
    reloaded = districts_mod.load_districts(yaml_path, force=True)
    assert reloaded["seoul_jongno"].fully_resolved


def test_name_mismatch_reports_instead_of_guessing(tmp_path):
    raw_root = tmp_path / "raw"
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "창신1동", "1111063000")],
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "창신제1동", code: null }\n',
    )

    report = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)

    assert not report.filled
    assert report.unmatched_yaml == [("seoul_jongno", "창신제1동")]
    assert ("종로구", "창신1동", "1111063000") in report.unmatched_response
    # 파일이 그대로다 — 근사 매칭으로 조용히 틀린 코드를 붙이지 않는다.
    assert "code: null" in yaml_path.read_text(encoding="utf-8")


def test_rerun_is_idempotent(tmp_path):
    raw_root = tmp_path / "raw"
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "청운효자동", "1111051500")],
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n',
    )

    first = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)
    text_after_first = yaml_path.read_text(encoding="utf-8")
    second = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)

    assert first.filled
    assert not second.filled
    assert yaml_path.read_text(encoding="utf-8") == text_after_first


def test_dry_run_does_not_write(tmp_path):
    raw_root = tmp_path / "raw"
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "청운효자동", "1111051500")],
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n',
    )

    report = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root, dry_run=True)

    assert report.filled == [("seoul_jongno", "청운효자동", "1111051500")]
    assert "code: null" in yaml_path.read_text(encoding="utf-8")


def test_conflicting_admm_code_within_district_is_skipped(tmp_path):
    raw_root = tmp_path / "raw"
    # 같은 admmCd 가 서로 다른 동 이름으로 두 번 온다. 한 배치에 같이 넣으면
    # aggregate_rows 가 admmCd 로 묶어 하나로 합쳐버리므로 배치를 나눈다.
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "청운효자동", "1111051500")],
        batch_key="batch-1",
    )
    write_raw_batch(
        raw_root,
        [make_row("서울특별시", "종로구", "사직동", "1111051500")],
        batch_key="batch-2",
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n'
        '      - { name: "사직동", code: null }\n',
    )

    report = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)

    assert len(report.filled) == 1
    assert report.conflicts
    assert not report.ok


def test_district_id_scopes_to_one_district(tmp_path):
    raw_root = tmp_path / "raw"
    write_raw_batch(
        raw_root,
        [
            make_row("서울특별시", "종로구", "청운효자동", "1111051500"),
            make_row("서울특별시", "용산구", "후암동", "1117051000"),
        ],
    )
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n'
        "  - id: seoul_yongsan\n"
        "    name: 서울 용산구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 용산구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "후암동", code: null }\n',
    )

    report = emd_backfill.backfill(
        districts_path=yaml_path, raw_root=raw_root, district_id="seoul_jongno"
    )

    assert report.filled == [("seoul_jongno", "청운효자동", "1111051500")]
    text = yaml_path.read_text(encoding="utf-8")
    assert '"후암동", code: null' in text  # 다른 선거구는 손대지 않았다


def test_unknown_district_id_raises(tmp_path):
    raw_root = tmp_path / "raw"
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n',
    )

    with pytest.raises(districts_mod.DistrictNotFound):
        emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root, district_id="nope")


def test_missing_raw_sigungu_does_not_pollute_unmatched_yaml(tmp_path):
    """raw 가 아예 없는 자치구는 missing_raw_sigungu 로만 드러난다 (이름 불일치 아님)."""
    raw_root = tmp_path / "raw"  # 만들지 않는다 — 이 자치구로는 collect 를 한 번도 안 돌렸다
    yaml_path = tmp_path / "districts.yaml"
    write_districts_yaml(
        yaml_path,
        "  - id: seoul_jongno\n"
        "    name: 서울 종로구\n"
        "    sido: 서울특별시\n"
        "    sigungu: 종로구\n"
        "    source: test\n"
        "    emd:\n"
        '      - { name: "청운효자동", code: null }\n'
        '      - { name: "사직동", code: null }\n',
    )

    report = emd_backfill.backfill(districts_path=yaml_path, raw_root=raw_root)

    assert not report.filled
    assert not report.unmatched_yaml
    assert report.missing_raw_sigungu == ["seoul_jongno (종로구)"]
