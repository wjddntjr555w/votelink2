"""store.iter_records / count_records — kind·geo 필터의 정독.

`naver_news.jsonl` 이 수만 줄이 되면서 붙은 것들이다: kind·geo_code 를 값비싼
`json.loads`/`load_record` 앞에서 부분문자열로 거르고, geo 필터를 로더가 아니라
스캐너에서 건다 (`docs/11-storage.md §6`).
"""

from tests.conftest import make_record
from votelink import store
from votelink.contract.enums import RecordKind

NEWS = RecordKind.NEWS_ARTICLE
OTHER = RecordKind.ELECTION_RESULT

GA = "1111054000"
NA = "1111055000"


def test_count_records_counts_only_the_asked_kind(data_root):
    store.append_records("c", [make_record(1), make_record(2), make_record(3)])
    assert store.count_records([NEWS]) == 3
    # 그 kind 레코드가 하나도 없으면 0 — json.loads 없이 마커 카운트다.
    assert store.count_records([OTHER]) == 0


def test_count_records_on_empty_dir_is_zero(data_root):
    assert store.count_records([NEWS]) == 0


def test_iter_records_geo_codes_filters_to_the_wanted_sigungu(data_root):
    store.append_records(
        "c",
        [
            make_record(1, geo_code=GA),
            make_record(2, geo_code=NA),
            make_record(3, geo_code=GA),
        ],
    )
    got = list(store.iter_records([NEWS], geo_codes={GA}))
    assert {r.geo_code for r in got} == {GA}
    assert len(got) == 2


def test_iter_records_empty_geo_codes_yields_nothing(data_root):
    """빈 컬렉션 = '원하는 geo 가 없다' — 필터 없음(None)과 구분한다."""
    store.append_records("c", [make_record(1, geo_code=GA)])
    assert list(store.iter_records([NEWS], geo_codes=set())) == []
    assert len(list(store.iter_records([NEWS], geo_codes=None))) == 1


def test_iter_records_skips_files_without_the_wanted_kind(data_root):
    """news_article 만 든 파일은 election_result 를 물어보면 통째로 건너뛴다
    (`_file_may_contain`). 결과가 비어야 맞다."""
    store.append_records("c", [make_record(1), make_record(2)])
    assert list(store.iter_records([OTHER])) == []
