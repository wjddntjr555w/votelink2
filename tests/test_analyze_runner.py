"""분석 런타임 — 실패 철학과 upsert 저장."""

from collections.abc import Iterator

from tests.conftest import make_record
from votelink import store
from votelink.analyze import runner
from votelink.analyze.base import AnalyzeError, BaseAnalyzer
from votelink.analyze.meta import AnalyzerMeta
from votelink.contract.enums import RecordKind
from votelink.contract.models import Record, Rejected


def meta(**over) -> AnalyzerMeta:
    base = dict(
        id="fake_analyzer",
        name="시험 분석기",
        inputs=[RecordKind.ELECTION_RESULT],
        outputs=[RecordKind.SEGMENT_PROFILE],
        geo_level="emd",
    )
    base.update(over)
    return AnalyzerMeta(**base)


class FakeAnalyzer(BaseAnalyzer):
    id = "fake_analyzer"

    def __init__(self, *, inputs=None, results=None, error=None):
        super().__init__(meta=meta())
        self._inputs = inputs if inputs is not None else [make_record(1)]
        self._results = results
        self._error = error

    def load(self, space) -> list[Record]:
        return self._inputs

    def compute(self, records: list[Record]) -> Iterator[Record | Rejected]:
        if self._error:
            raise AnalyzeError(self._error)
        yield from self._results if self._results is not None else [make_record(10)]


class TestFailurePhilosophy:
    def test_empty_input_is_a_failure_not_a_success(self, space):
        """조용히 0건을 내면 '분석이 돌았는데 결과가 없다'와 '수집이 안 됐다'를
        구분할 수 없다."""
        report = runner.run(FakeAnalyzer(inputs=[]), space=space)
        assert report.failed
        assert "입력 레코드가 0건" in report.failure_reason
        assert report.accepted == 0

    def test_analyze_error_aborts_without_partial_save(self, space):
        report = runner.run(FakeAnalyzer(error="진영 매핑에 없는 후보"), space=space)
        assert report.failed
        assert "진영 매핑" in report.failure_reason
        assert store.existing_record_ids("fake_analyzer", space) == set()

    def test_one_bad_item_does_not_kill_the_rest(self, space):
        # 21건 중 1건 격리 = 4.8% 로 임계(5%) 바로 아래다.
        results: list = [make_record(i) for i in range(10, 30)]
        results.append(Rejected(reason="ValueError: 깨짐"))
        report = runner.run(FakeAnalyzer(results=results), space=space)
        assert not report.failed
        assert report.accepted == 20
        assert report.rejected == 1
        assert len(store.existing_record_ids("fake_analyzer", space)) == 20

    def test_reject_rate_over_threshold_blocks_valid_records(self, space):
        """5%가 조용히 누락되면 그 5%가 어느 동네인지 아무도 모른 채 전략에서 빠진다."""
        results = [make_record(i) for i in range(10, 30)]
        results.extend(Rejected(reason=f"ValueError: {i}") for i in range(5))
        report = runner.run(FakeAnalyzer(results=results), space=space)
        assert report.failed
        assert "격리율" in report.failure_reason
        assert store.existing_record_ids("fake_analyzer", space) == set()

    def test_rejected_items_are_quarantined_with_reason(self, space):
        runner.run(
            FakeAnalyzer(results=[make_record(10), Rejected(reason="ValueError: 깨짐")]),
            space=space,
        )
        files = list((space.rejected / "fake_analyzer").glob("*.jsonl"))
        assert files and "깨짐" in files[0].read_text(encoding="utf-8")

    def test_dry_run_writes_nothing(self, space):
        report = runner.run(FakeAnalyzer(), dry_run=True, space=space)
        assert not report.failed
        assert report.accepted == 1
        assert store.existing_record_ids("fake_analyzer", space) == set()

    def test_injected_records_bypass_load(self, space):
        """records= 를 주면 analyzer.load() 를 부르지 않는다 — analyze --all 이
        같은 kind 를 조합마다 다시 읽지 않도록 한 번 읽어 공유하는 통로다."""

        class Exploding(FakeAnalyzer):
            def load(self, space):
                raise AssertionError("load() 가 불렸다 — records= 를 무시했다")

        report = runner.run(Exploding(), records=[make_record(10)], space=space)
        assert not report.failed
        assert report.inputs == 1
        assert report.accepted == 1


class TestUpsert:
    """분석 결과는 append 가 아니라 upsert 다. 수집기와 다른 유일한 지점."""

    def test_rerun_replaces_instead_of_duplicating(self, space):
        first = runner.run(FakeAnalyzer(), space=space)
        assert (first.replaced, first.added) == (0, 1)

        second = runner.run(FakeAnalyzer(), space=space)
        assert (second.replaced, second.added) == (1, 0)
        assert len(store.existing_record_ids("fake_analyzer", space)) == 1

    def test_changed_payload_actually_lands(self, space):
        """참조 데이터를 고치고 재실행했는데 산출물이 그대로면 안 된다.

        append 만 하면 같은 record_id 가 '중복'으로 버려져 정확히 그 일이 일어난다.
        """
        original = make_record(10)
        runner.run(FakeAnalyzer(results=[original]), space=space)

        updated = original.model_copy(deep=True)
        updated.payload["title"] = "매핑을 고친 뒤의 결과"
        runner.run(FakeAnalyzer(results=[updated]), space=space)

        lines = (space.records / "fake_analyzer.jsonl").read_text(encoding="utf-8")
        assert lines.count("\n") == 1  # 줄이 늘지 않았다
        assert "매핑을 고친 뒤의 결과" in lines

    def test_other_records_in_the_file_survive(self, space):
        """다른 as_of 의 과거 분석은 record_id 가 달라 그대로 남아야 한다."""
        store.append_records("fake_analyzer", [make_record(1), make_record(2)], space)
        runner.run(FakeAnalyzer(results=[make_record(10)]), space=space)
        assert len(store.existing_record_ids("fake_analyzer", space)) == 3


class TestLoadFiltersInputs:
    def test_load_reads_only_declared_kinds(self, space):
        store.append_records("some_collector", [make_record(1)], space)  # news_article
        analyzer = FakeAnalyzer()
        analyzer.load = BaseAnalyzer.load.__get__(analyzer)  # 기본 구현으로 되돌린다

        # inputs 가 election_result 뿐이므로 news_article 레코드는 안 읽힌다.
        # 새 수집기가 붙어도 기존 분석기가 영향받지 않는다는 뜻이다.
        assert analyzer.load(space) == []

    def test_load_excludes_own_output(self, space):
        """자기 결론을 입력으로 다시 먹으면 재실행마다 결과가 흘러간다."""
        analyzer = FakeAnalyzer()
        analyzer.load = BaseAnalyzer.load.__get__(analyzer)
        store.append_records("fake_analyzer", [make_record(1)], space)
        assert analyzer.load(space) == []


def test_reject_rate_is_zero_when_nothing_computed():
    report = runner.AnalysisReport(analyzer_id="x", started_at=None)
    assert report.reject_rate == 0.0
