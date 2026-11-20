"""Offline tests for the OpenAlex downloader (no network)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("fo", Path(__file__).resolve().parents[1] / "scripts/fetch_openalex.py")
fo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fo)

WORK = {"id": "https://openalex.org/W1", "title": "Attention Is <i>All</i> You Need", "publication_year": 2017,
        "authorships": [{"author": {"display_name": f"Author {i}"}} for i in range(8)],
        "primary_location": {"source": {"display_name": "NeurIPS"}, "landing_page_url": "https://x"},
        "abstract_inverted_index": {f"word{i}": [i] for i in range(60)},
        "cited_by_count": 100000, "primary_topic": {"display_name": "NLP"},
        "keywords": [{"display_name": "transformer"}, {"display_name": "attention"}],
        "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W9"], "doi": "https://doi.org/10.1/abc", "type": "preprint"}


def test_abstract_reconstruction():
    assert fo.abstract_from_index({"world": [1], "hello": [0, 2]}) == "hello world hello"
    assert fo.abstract_from_index(None) == ""


def test_record_and_links():
    r = fo.to_record(WORK, "Artificial Intelligence")
    assert r["id"] == "W1" and r["title"] == "Attention Is All You Need" and r["type"] == "Preprint"
    assert r["authors"].endswith("et al.") and r["tags"] == ["transformer", "attention"] and r["year"] == "2017"
    other = dict(WORK, id="https://openalex.org/W2", referenced_works=[])
    recs = fo.finalise([r, fo.to_record(other, "AI")])
    assert recs[0]["links"] == ["W2"] and "refs" not in recs[0]
    assert fo.to_record(dict(WORK, abstract_inverted_index={"too": [0], "short": [1]}), "AI") is None
