"""등록부 — registry.yaml 은 meta.yaml 들에서 자동 생성된다."""

import sys
import textwrap

import pytest
import yaml

from votelink.collect import registry


@pytest.fixture
def fake_collectors(tmp_path, monkeypatch):
    """임시 collectors 패키지를 만들고 import 가능하게 한다."""
    root = tmp_path / "collectors"
    (root / "demo_source").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo_source" / "__init__.py").write_text("", encoding="utf-8")
    (root / "demo_source" / "meta.yaml").write_text(
        textwrap.dedent("""
        id: demo_source
        name: 시험 출처
        kinds: [news_article]
        source_name: 시험 기관
        source_url: https://example.test
        source_license: api_tos
        access: api
        incremental: false
        geo_level: emd
        """).strip(),
        encoding="utf-8",
    )
    (root / "demo_source" / "collector.py").write_text(
        textwrap.dedent("""
        from votelink.collect.base import BaseCollector

        class Collector(BaseCollector):
            id = "demo_source"

            def fetch(self, since):
                return iter(())

            def parse(self, raw):
                return iter(())
        """).strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield root
    for name in [m for m in sys.modules if m.startswith("collectors")]:
        del sys.modules[name]


def test_discover_finds_collectors(fake_collectors):
    metas = registry.discover(fake_collectors)
    assert list(metas) == ["demo_source"]
    assert metas["demo_source"].source_name == "시험 기관"


def test_sync_writes_generated_registry(fake_collectors):
    path = registry.sync(fake_collectors)
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert body["count"] == 1
    assert body["collectors"][0]["id"] == "demo_source"
    assert "손으로 고치지 말 것" in path.read_text(encoding="utf-8")


def test_load_returns_instance_with_meta(fake_collectors):
    collector = registry.load("demo_source", fake_collectors)
    assert collector.id == "demo_source"
    assert collector.meta.access == "api"


def test_unknown_collector_lists_known_ones(fake_collectors):
    with pytest.raises(KeyError, match="demo_source"):
        registry.load("nope", fake_collectors)


def test_meta_id_must_match_folder_name(fake_collectors):
    meta_path = fake_collectors / "demo_source" / "meta.yaml"
    meta_path.write_text(
        meta_path.read_text(encoding="utf-8").replace("id: demo_source", "id: other_name"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="폴더명"):
        registry.discover(fake_collectors)


def test_discover_on_missing_dir_is_empty(tmp_path):
    assert registry.discover(tmp_path / "nope") == {}
