"""Unit tests: text processing, indexing, compression, k-gram, Boolean retrieval."""
import pytest

from searchbridge.index.compression import (delta_encode, front_code, from_gaps, gamma_decode, gamma_encode,
                                            gamma_encode_number, to_gaps, vb_decode, vb_encode, vb_encode_number)
from searchbridge.index.inverted_index import InvertedIndex
from searchbridge.index.kgram import KGramIndex, edit_distance
from searchbridge.retrieval.boolean import And, BooleanParser, BooleanRetriever, Not, Or, Phrase
from searchbridge.text.preprocess import Analyzer, PreprocessConfig, tokenize

DOCS = [("d1", "The boundary layer on a flat plate with heat transfer."),
        ("d2", "Supersonic flow and shock waves over a wedge."),
        ("d3", "Heat transfer in the turbulent boundary layer of supersonic flow."),
        ("d4", "Flat plate boundary layers: laminar transition.")]


@pytest.fixture
def ix():
    return InvertedIndex().build(DOCS)


def test_tokenize_and_analyzer():
    assert tokenize("Café's state-of-the-art NACA-0012!") == ["cafe", "s", "state", "of", "the", "art", "naca", "0012"]
    an = Analyzer()
    assert an("The layers are running") == ["layer", "run"]
    assert Analyzer(PreprocessConfig(stem=False, remove_stopwords=False))("The layers") == ["the", "layers"]


def test_postings_positions(ix):
    p = ix.get_postings("boundari")
    assert set(ix.doc_ids[d] for d in p) == {"d1", "d3", "d4"}
    assert ix.df("plate") == 2 and ix.N == 4


def test_spimi_blocks_equal_single_pass():
    a = InvertedIndex(block_size=3).build(DOCS)
    b = InvertedIndex(block_size=10_000).build(DOCS)
    assert a.blocks_written > 1 and b.blocks_written == 1
    assert a.postings == b.postings


def test_phrase_and_proximity(ix):
    hits = ix.phrase_match(["boundari", "layer"])
    assert {ix.doc_ids[d] for d in hits} == {"d1", "d3", "d4"}
    assert {ix.doc_ids[d] for d in ix.phrase_match(["heat", "layer"], slop=0)} == set()
    assert {ix.doc_ids[d] for d in ix.phrase_match(["heat", "layer"], slop=3)} == {"d3"}


def test_dynamic_index_and_delete(ix):
    ix.add_document("d5", "boundary layer suction")
    assert "d5" in {ix.doc_ids[d] for d in ix.get_postings("suction")}
    ix.delete_document("d1")
    assert "d1" not in {ix.doc_ids[d] for d in ix.get_postings("boundari")}
    assert ix.N == 4


def test_gap_vb_gamma_roundtrip():
    ids = [824, 829, 215406]
    assert to_gaps(ids) == [824, 5, 214577] and from_gaps(to_gaps(ids)) == ids
    assert vb_encode_number(824) == bytes([6, 184])           # IIR Table 5.4
    assert vb_decode(vb_encode([824, 5, 214577])) == [824, 5, 214577]
    assert gamma_encode_number(13) == "1110101"                # IIR Table 5.5
    assert gamma_decode(gamma_encode([0, 1, 12, 1023])) == [0, 1, 12, 1023]
    assert len(delta_encode([10 ** 6])) < len(gamma_encode([10 ** 6]))


def test_front_coding():
    out = front_code(["automata", "automate", "automatic", "automation"])
    assert out[0].startswith("8automat*a")


def test_kgram_wildcard_and_spelling():
    k = KGramIndex().build("aerodynamic aerodynamics supersonic subsonic hypersonic boundary".split())
    assert set(k.wildcard("*sonic")) == {"supersonic", "subsonic", "hypersonic"}
    assert k.wildcard("aero*s") == ["aerodynamics"]
    assert k.suggest("boundry")[0][0] == "boundary"
    assert edit_distance("cat", "act") == 1 and edit_distance("kitten", "sitting") == 3


def test_boolean_parser_precedence():
    node = BooleanParser().parse('a OR b AND NOT c')
    assert isinstance(node, Or) and isinstance(node.children[1], And)
    assert isinstance(node.children[1].children[1], Not)
    assert BooleanParser().parse('"heat transfer"~2') == Phrase(["heat", "transfer"], 2)
    with pytest.raises(ValueError):
        BooleanParser().parse("(a AND b")


def test_boolean_retrieval(ix):
    br = BooleanRetriever(ix, KGramIndex().build(tokenize(" ".join(t for _, t in DOCS))).wildcard)
    ids = lambda s: {ix.doc_ids[d] for d in s}
    assert ids(br.search_query("boundary AND NOT turbulent")) == {"d1", "d4"}
    assert ids(br.search_query("shock OR transition")) == {"d2", "d4"}
    assert ids(br.search_query('"heat transfer" AND supersonic')) == {"d3"}
    assert ids(br.search_query("super*")) == {"d2", "d3"}
