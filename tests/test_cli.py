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

    assert cli.main(["serve", "--host", "127.0.0.1", "--port", "9000"]) == 0
    assert (calls["host"], calls["port"]) == ("127.0.0.1", 9000)


def test_serve_refuses_to_expose_without_auth(monkeypatch, capsys):
    """**인증이 꺼져 있으면 로컬 밖으로 열지 않는다** (P-002 §2).

    예전에는 비노출 자체가 인증을 대신했다. 이제 인증이 그 일을 하므로 노출을
    허용하되, 인증 없이 노출하는 조합만은 막는다 — 미검토 산출물이 경고와 함께
    뜨는 화면을 아무나 열 수 있으면 그게 의도치 않은 공표다.
    """
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: pytest.fail("띄우면 안 된다"))

    assert cli.main(["serve", "--host", "0.0.0.0"]) == 1
    assert "--auth" in capsys.readouterr().err


def test_serve_with_auth_bootstraps_the_first_operator(monkeypatch, capsys):
    """서버를 띄우기 전에 명령을 하나 더 기억하지 않아도 되게 한다.
    운영자가 하나도 없을 때만 만든다."""
    from votelink.control import accounts as acc

    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))

    assert cli.main(["serve", "--auth"]) == 0
    made = acc.by_email(acc.BOOTSTRAP_ID)
    assert made is not None
    assert made.role is acc.Role.OPERATOR and made.is_active
    assert acc.BOOTSTRAP_ID in capsys.readouterr().out, "만들었으면 알려준다"


def test_serve_does_not_touch_an_existing_operator(monkeypatch, capsys):
    from votelink.control import accounts as acc

    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    assert cli.main(["account", "create-operator", "ops@test", "제대로된비번"]) == 0
    capsys.readouterr()

    assert cli.main(["serve", "--auth"]) == 0
    assert acc.by_email(acc.BOOTSTRAP_ID) is None, "이미 운영자가 있으면 만들지 않는다"
    assert acc.BOOTSTRAP_ID not in capsys.readouterr().out


def test_serve_refuses_to_expose_with_the_bootstrap_password(monkeypatch, capsys):
    """**아는 비밀번호가 서버에 있으면 인증이 없는 것과 같다.**

    `--auth` 가 `0.0.0.0` 을 허용하는 근거(P-002 §2)는 "인증이 비노출을 대신한다"인데,
    배포 기본 비밀번호가 그대로면 그 근거가 무너진다.
    """
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: pytest.fail("띄우면 안 된다"))

    assert cli.main(["serve", "--auth", "--host", "0.0.0.0"]) == 1
    assert "기본 비밀번호" in capsys.readouterr().err


def test_changing_the_bootstrap_password_opens_the_bind(monkeypatch, capsys):
    from votelink.control import accounts as acc

    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(kw))
    assert cli.main(["serve", "--auth"]) == 0  # root/root 를 만든다
    acc.set_password(acc.by_email(acc.BOOTSTRAP_ID).id, "이제바꿨다")

    assert cli.main(["serve", "--auth", "--host", "0.0.0.0"]) == 0
    assert calls["host"] == "0.0.0.0"


def test_serve_refuses_auth_with_a_pinned_camp(monkeypatch, capsys):
    """캠프를 두 곳에서 정하면 화면이 어느 쪽을 따르는지 알 수 없다.
    인증이 켜지면 캠프는 세션이 정한다."""
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: pytest.fail("띄우면 안 된다"))

    assert cli.main(["serve", "--auth", "--camp", "아무캠프"]) == 1
    assert "함께 쓸 수 없다" in capsys.readouterr().err


def test_serve_warns_but_still_starts_with_no_records(monkeypatch, tmp_path, capsys):
    """서버가 안 뜨면 *왜* 비었는지 볼 화면조차 없다. 경고하고 띄운다."""
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: None)
    # 레코드가 없는 상태는 루트 conftest 의 autouse 픽스처가 이미 만들어 준다
    # (`store.DATA_DIR` 이 빈 임시 경로를 가리킨다).

    assert cli.main(["serve"]) == 0
    assert "분석 결과가 0건" in capsys.readouterr().out


def test_collect_reports_missing_config_without_traceback(monkeypatch, capsys):
    """설정 누락은 사용자가 고칠 일이다. 트레이스백 대신 안내를 보여준다."""
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)
    # 실제 저장소 .env 가 키를 도로 채우지 않게 한다 — 이 테스트는 '키가 아예 없을 때'를 본다.
    monkeypatch.setattr(cli, "_load_env", lambda: None)
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


def test_collect_all_districts_runs_every_registered_block(monkeypatch, capsys):
    """--all-districts 는 meta.yaml 의 config.districts 를 전부 순회하고 합산을 낸다."""
    from tests.conftest import FakeCollector, make_meta
    from votelink.collect import registry

    layered = make_meta(
        id="multi_x",
        verified=True,
        config={
            "common": {},
            "districts": {"seoul_songpa_gap": {}, "seoul_gangnam_gap": {}},
        },
    )
    seen = []

    def fake_load(collector_id, **kw):
        seen.append(kw.get("district_id"))
        c = FakeCollector([{"n": 1}], meta=layered)
        c.district_id = kw.get("district_id")
        c._config = None
        return c

    monkeypatch.setattr(registry, "load", fake_load)

    rc = cli.main(["collect", "multi_x", "--all-districts", "--dry-run"])
    assert rc == 0
    # base 로딩 1회(district_id=None) + 등록된 선거구마다 1회
    assert seen == [None, "seoul_songpa_gap", "seoul_gangnam_gap"]
    assert "[합계] 선거구 2/2" in capsys.readouterr().out


def test_collect_district_and_all_districts_are_mutually_exclusive():
    """둘을 같이 주면 argparse 가 파싱 단계에서 막는다."""
    with pytest.raises(SystemExit):
        cli.main(["collect", "x", "--district", "seoul_songpa_gap", "--all-districts"])


def test_collect_all_districts_needs_district_blocks(monkeypatch, capsys):
    from tests.conftest import FakeCollector, make_meta
    from votelink.collect import registry

    flat = make_meta(id="flat_x", verified=True)  # config.districts 없음
    monkeypatch.setattr(registry, "load", lambda cid, **kw: FakeCollector([], meta=flat))

    assert cli.main(["collect", "flat_x", "--all-districts"]) == 1
    assert "config.districts 가 없다" in capsys.readouterr().err


def test_analyze_all_districts_runs_every_registered_block(monkeypatch, capsys):
    from collections.abc import Iterator

    from tests.conftest import make_record
    from votelink.analyze import registry as analyze_registry
    from votelink.analyze.base import BaseAnalyzer
    from votelink.analyze.meta import AnalyzerMeta
    from votelink.contract.enums import RecordKind
    from votelink.contract.models import Record, Rejected

    ameta = AnalyzerMeta(
        id="multi_a",
        name="시험 분석기",
        inputs=[RecordKind.ELECTION_RESULT],
        outputs=[RecordKind.SEGMENT_PROFILE],
        geo_level="emd",
        config={"common": {}, "districts": {"seoul_songpa_gap": {}, "seoul_gangnam_gap": {}}},
    )

    class FakeAnalyzer(BaseAnalyzer):
        id = "multi_a"

        def __init__(self, meta=None, district_id=None):
            super().__init__(meta=meta or ameta)
            self.district_id = district_id

        def load(self, space) -> list[Record]:
            return [make_record(1)]

        def compute(self, records: list[Record]) -> Iterator[Record | Rejected]:
            yield make_record(10)

    seen = []

    def fake_load(analyzer_id, **kw):
        seen.append(kw.get("district_id"))
        return FakeAnalyzer(district_id=kw.get("district_id"))

    monkeypatch.setattr(analyze_registry, "load", fake_load)

    rc = cli.main(["analyze", "multi_a", "--all-districts", "--dry-run"])
    assert rc == 0
    assert seen == [None, "seoul_songpa_gap", "seoul_gangnam_gap"]
    assert "[합계] 선거구 2/2" in capsys.readouterr().out


def test_analyze_all_runs_every_analyzer_over_its_districts(monkeypatch, capsys):
    """--all 은 등록된 전 분석기를 각자의 config.districts 로 돌리고,
    입력 kind 는 한 번만 읽어 전 실행에 공유한다."""
    from collections.abc import Iterator

    from tests.conftest import make_record
    from votelink.analyze import registry as analyze_registry
    from votelink.analyze.base import BaseAnalyzer
    from votelink.analyze.meta import AnalyzerMeta
    from votelink.contract.enums import RecordKind
    from votelink.contract.models import Record, Rejected

    def ameta(aid, districts):
        return AnalyzerMeta(
            id=aid,
            name=f"시험 {aid}",
            inputs=[RecordKind.NEWS_ARTICLE],
            outputs=[RecordKind.NEWS_PULSE],
            geo_level="sigungu",
            config={"common": {}, "districts": {d: {} for d in districts}},
        )

    metas = {
        "a_one": ameta("a_one", ["seoul_songpa_gap", "seoul_gangnam_gap"]),
        "a_two": ameta("a_two", ["seoul_jongno"]),
    }

    class FakeAnalyzer(BaseAnalyzer):
        def __init__(self, aid, meta, district_id):
            self.id = aid
            super().__init__(meta=meta)
            self.district_id = district_id

        def load(self, space) -> list[Record]:
            raise AssertionError("--all 은 records= 로 입력을 주입한다")

        def compute(self, records: list[Record]) -> Iterator[Record | Rejected]:
            assert records, "공유 입력이 이 분석기 kind 로 걸러져 넘어와야 한다"
            yield make_record(10)

    ran: list[tuple[str, str]] = []
    load_calls = []

    monkeypatch.setattr(analyze_registry, "discover", lambda **kw: metas)
    monkeypatch.setattr(
        analyze_registry,
        "load",
        lambda aid, **kw: FakeAnalyzer(aid, metas[aid], kw.get("district_id")),
    )

    def spy_load_records(kinds, **kw):
        load_calls.append(list(kinds))
        return [make_record(1)]  # news_article

    monkeypatch.setattr(cli.store, "load_records", spy_load_records)

    orig_run = cli.analyze_runner.run

    def traced_run(analyzer, **kw):
        ran.append((analyzer.id, analyzer.district_id))
        return orig_run(analyzer, **kw)

    monkeypatch.setattr(cli.analyze_runner, "run", traced_run)

    rc = cli.main(["analyze", "--all", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert ran == [
        ("a_one", "seoul_songpa_gap"),
        ("a_one", "seoul_gangnam_gap"),
        ("a_two", "seoul_jongno"),
    ]
    assert len(load_calls) == 1, "입력을 조합마다 다시 읽었다"
    assert "[합계] 실행 3" in out


def test_analyze_all_and_district_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.main(["analyze", "x", "--all", "--district", "seoul_songpa_gap"])
