"""CLI — 실제로 손에 쥐는 명령들."""

import pytest

from votelink import cli, store
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


def test_serve_binds_loopback_by_default(monkeypatch, capsys):
    """기본 호스트가 127.0.0.1 이다. 편의가 아니라 컴플라이언스에 인접한 결정이다 —
    미검토 산출물이 경고와 함께 뜨는 화면을 LAN 에 열면 의도치 않은 공표가 된다.

    서버를 실제로 띄우지 않고 uvicorn.run 에 넘어간 인자만 본다.
    """
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))

    assert cli.main(["serve"]) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8420
    assert "http://127.0.0.1:8420" in capsys.readouterr().out


def test_serve_honours_host_and_port(monkeypatch):
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))

    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9000"]) == 0
    assert (calls["host"], calls["port"]) == ("0.0.0.0", 9000)


def test_serve_warns_but_still_starts_with_no_records(monkeypatch, tmp_path, capsys):
    """서버가 안 뜨면 *왜* 비었는지 볼 화면조차 없다. 경고하고 띄운다."""
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    monkeypatch.setattr(store, "RECORDS_DIR", tmp_path / "없다")

    assert cli.main(["serve"]) == 0
    assert "분석 결과가 0건" in capsys.readouterr().out


def test_collect_reports_missing_config_without_traceback(monkeypatch, capsys):
    """설정 누락은 사용자가 고칠 일이다. 트레이스백 대신 안내를 보여준다."""
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)
    assert cli.main(["collect", "mois_population"]) == 1
    captured = capsys.readouterr()
    assert "DATA_GO_KR_SERVICE_KEY" in captured.err
    assert "Traceback" not in captured.err


def test_collect_warns_when_meta_is_unverified(monkeypatch, capsys):
    """검증되지 않은 수집기는 실행할 때마다 경고가 떠야 한다."""
    from tests.conftest import FakeCollector, make_meta
    from votelink.collect import registry

    unverified = FakeCollector([], meta=make_meta(id="unverified_x", verified=False))
    monkeypatch.setattr(registry, "load", lambda collector_id, **kw: unverified)

    assert cli.main(["collect", "unverified_x", "--dry-run"]) == 0
    assert "검증되지 않았다" in capsys.readouterr().out


def test_collect_is_quiet_when_verified(monkeypatch, capsys):
    from tests.conftest import FakeCollector, make_meta
    from votelink.collect import registry

    verified = FakeCollector([{"n": 1}], meta=make_meta(id="verified_x", verified=True))
    monkeypatch.setattr(registry, "load", lambda collector_id, **kw: verified)

    assert cli.main(["collect", "verified_x", "--dry-run"]) == 0
    assert "검증되지 않았다" not in capsys.readouterr().out


def test_collect_with_an_unknown_district_fails_cleanly(monkeypatch, capsys):
    """meta.yaml 에 없는 선거구를 요구하면 트레이스백이 아니라 한 줄 오류로 끝난다."""
    from tests.conftest import FakeCollector, make_meta
    from votelink.collect import registry

    layered = make_meta(
        id="layered_x",
        verified=True,
        config={"common": {}, "districts": {"seoul_songpa_gap": {}}},
    )

    def fake_load(collector_id, **kw):
        c = FakeCollector([{"n": 1}], meta=layered)
        c.district_id = kw.get("district_id")
        c._config = None
        return c

    monkeypatch.setattr(registry, "load", fake_load)

    rc = cli.main(["collect", "layered_x", "--district", "seoul_gangnam_gap", "--dry-run"])
    assert rc == 1
    assert "선거구 설정 오류" in capsys.readouterr().err
