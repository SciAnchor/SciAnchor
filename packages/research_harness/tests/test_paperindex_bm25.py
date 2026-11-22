from __future__ import annotations

from paperindex.retrieval import BM25Document, BM25Index, tokenize_text


def test_bm25_index_supports_term_frequency_and_bm25_scoring():
    index = BM25Index.from_documents(
        [
            BM25Document(
                doc_id="short",
                text="dense retrieval literature search",
            ),
            BM25Document(
                doc_id="long",
                text=(
                    "dense dense dense retrieval literature search "
                    "unrelated padding tokens lower bm25 saturation"
                ),
            ),
        ]
    )

    term_frequency_results = index.search(
        "dense retrieval literature search",
        scoring="term_frequency",
    )
    bm25_results = index.search("dense retrieval literature search", scoring="bm25")

    assert term_frequency_results[0].doc_id == "long"
    assert bm25_results[0].doc_id == "short"
    assert term_frequency_results[0].score > term_frequency_results[1].score
    assert bm25_results[0].score > bm25_results[1].score


def test_bm25_tokenizer_matches_rfb_stopword_policy():
    assert tokenize_text("Research papers with dense-retrieval in 2026") == (
        "dense-retrieval",
        "2026",
    )
