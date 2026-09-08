"""이슈 어휘집 로더 — 형식 검증과 캐시 (A-003).

어휘집은 지역적·정치적 편집 판단이라 party_lineage.yaml 과 같은 구조로 파일에 두고,
로더는 형식이 계약에 맞는지만 강제한다 (key 중복 금지, 빈 keyword 금지).
"""

from __future__ import annotations

import pytest

from votelink.reference import issue_lexicon as lex


@pytest.fixture(autouse=True)
def fresh_cache():
    lex.reset_cache()
    yield
    lex.reset_cache()


def write(tmp_path, text: str):
    path = tmp_path / "issue_lexicon.yaml"
    path.write_text(text, encoding="utf-8")
    return path


GOOD = (
    'version: "2026-09-06"\n'
    "categories:\n"
    "  - { key: transit, label: 교통, keywords: [트램, 9호선] }\n"
    "  - { key: redevelopment, label: 재건축, keywords: [재건축] }\n"
)


def test_loads_and_caches(tmp_path):
    path = write(tmp_path, GOOD)
    a = lex.load_lexicon(path)
    assert a.version == "2026-09-06"
    assert [c.key for c in a.categories] == ["transit", "redevelopment"]
    # 캐시: 같은 객체가 다시 나온다 (force 없이).
    assert lex.load_lexicon(path) is a
    assert lex.load_lexicon(path, force=True) is not a


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        lex.load_lexicon(tmp_path / "nope.yaml")


def test_version_is_required(tmp_path):
    path = write(tmp_path, "categories:\n  - { key: a, label: A, keywords: [x] }\n")
    with pytest.raises(lex.LexiconError):
        lex.load_lexicon(path, force=True)


def test_empty_categories_rejected(tmp_path):
    path = write(tmp_path, 'version: "v1"\ncategories: []\n')
    with pytest.raises(lex.LexiconError):
        lex.load_lexicon(path, force=True)


def test_duplicate_key_rejected(tmp_path):
    path = write(
        tmp_path,
        'version: "v1"\n'
        "categories:\n"
        "  - { key: transit, label: 교통, keywords: [트램] }\n"
        "  - { key: transit, label: 교통2, keywords: [버스] }\n",
    )
    with pytest.raises(lex.LexiconError, match="중복"):
        lex.load_lexicon(path, force=True)


def test_empty_keyword_list_rejected(tmp_path):
    path = write(tmp_path, 'version: "v1"\ncategories:\n  - { key: a, label: A, keywords: [] }\n')
    with pytest.raises(lex.LexiconError):
        lex.load_lexicon(path, force=True)


def test_blank_keyword_rejected(tmp_path):
    path = write(
        tmp_path,
        'version: "v1"\ncategories:\n  - { key: a, label: A, keywords: [재건축, "  "] }\n',
    )
    with pytest.raises(lex.LexiconError):
        lex.load_lexicon(path, force=True)


def test_unknown_field_rejected(tmp_path):
    path = write(
        tmp_path,
        'version: "v1"\ncategories:\n  - { key: a, label: A, keywords: [x], weight: 2 }\n',
    )
    with pytest.raises(lex.LexiconError):
        lex.load_lexicon(path, force=True)


def test_repo_lexicon_is_valid():
    """저장소에 커밋된 data/shared/reference/issue_lexicon.yaml 이 계약을 지키는지."""
    lexicon = lex.load_lexicon(force=True)
    assert lexicon.version
    assert lexicon.categories
    keys = [c.key for c in lexicon.categories]
    assert len(keys) == len(set(keys))
