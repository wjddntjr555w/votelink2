"""CLI — 실제로 손에 쥐는 명령들."""

import pytest

from votelink import cli
from votelink.collect import geo


def test_geo_import_autodetects_korean_headers(tmp_path, monkeypatch, capsys):
    src = tmp_path / "official.csv"
    src.write_text(
        "행정기관코드,행정기관명\n"
        "1111054000,서울특별시 시험구 가나동\n"
        "1111055000,서울특별시 시험구 다라동\n",
        encoding="utf-8",
    )
    target = tmp_path / "geo_mapping.csv"
    monkeypatch.setattr(geo, "REFERENCE_CSV", target)
    geo.reset_table()

    assert cli.main(["geo", "import", str(src)]) == 0
    assert "2건" in capsys.readouterr().out
    assert geo.to_emd_code("가나동") == "1111054000"
    geo.reset_table()


def test_geo_import_rejects_non_emd_file(tmp_path, monkeypatch):
    src = tmp_path / "sigungu.csv"
    src.write_text("행정기관코드,행정기관명\n11710,시험구\n", encoding="utf-8")
    monkeypatch.setattr(geo, "REFERENCE_CSV", tmp_path / "out.csv")
    with pytest.raises(SystemExit, match="10자리"):
        cli.main(["geo", "import", str(src)])


def test_geo_import_reports_available_columns(tmp_path, monkeypatch):
    src = tmp_path / "weird.csv"
    src.write_text("foo,bar\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(geo, "REFERENCE_CSV", tmp_path / "out.csv")
    with pytest.raises(SystemExit, match="foo, bar"):
        cli.main(["geo", "import", str(src)])


def test_geo_lookup_failure_returns_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(geo, "REFERENCE_CSV", tmp_path / "empty.csv")
    geo.reset_table()
    assert cli.main(["geo", "lookup", "없는동"]) == 1
    geo.reset_table()


def test_registry_list_on_empty_project(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["registry", "list"]) == 0
    assert "new-collector" in capsys.readouterr().out


def test_unimplemented_commands_say_so(capsys):
    assert cli.main(["serve"]) == 2
    assert "아직 구현되지 않았다" in capsys.readouterr().out


def test_collect_reports_missing_config_without_traceback(monkeypatch, capsys):
    """설정 누락은 사용자가 고칠 일이다. 트레이스백 대신 안내를 보여준다."""
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)
    assert cli.main(["collect", "mois_population"]) == 1
    captured = capsys.readouterr()
    assert "DATA_GO_KR_SERVICE_KEY" in captured.err
    assert "Traceback" not in captured.err
    assert "검증되지 않았다" in captured.out
