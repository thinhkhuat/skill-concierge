"""EmbeddingGemma-2 task-instruction prefixes.

The model card (huggingface/google/embeddinggemma-2, "1. Task Instruction
Prefixes") pairs a query prefix with a document prefix for asymmetric retrieval,
and formats a titled document as `title: {title} | text: {content}`. Omitting the
prefix "still works but reduces precision" -- measured on this catalogue at
recall@1 0.267 -> 0.433 and NDCG@6 0.325 -> 0.466.

Each test names the defect it would catch.
"""
from skill_search import server


def _as_eg2(monkeypatch):
    monkeypatch.setattr(server, "EMBED_MODEL", "embeddinggemma-2:270m")


def _as_mpnet(monkeypatch):
    monkeypatch.setattr(server, "EMBED_MODEL",
                        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")


def test_doc_prefix_splits_the_title_off_the_body(monkeypatch):
    # `_skill_text` is `name\ndescription\nbody`; a raw passthrough would drop the
    # card's title field and silently lose the strongest signal in the text.
    _as_eg2(monkeypatch)
    assert server._doc_embed_text("nano-pdf\nEdit PDF text.\n# nano-pdf\nBody") == (
        "title: nano-pdf | text: Edit PDF text.\n# nano-pdf\nBody")


def test_doc_prefix_keeps_a_titleless_text_whole(monkeypatch):
    # a text with no newline must still be a titled document, not lose its content
    _as_eg2(monkeypatch)
    assert server._doc_embed_text("lonely") == "title: lonely | text: "


def test_trigger_prefix_belongs_to_its_skill_not_to_query_space(monkeypatch):
    # putting triggers in query space was measured WORSE than no prefix at all
    # (recall@1 0.233 vs 0.267); this pins the winning form.
    _as_eg2(monkeypatch)
    assert server._trigger_embed_text("nano-pdf", "fix typos in pdf") == (
        "title: nano-pdf | text: fix typos in pdf")


def test_query_prefix_names_the_search_task(monkeypatch):
    # a bare query would live in a different space from the prefixed documents
    _as_eg2(monkeypatch)
    assert server._query_embed_text("fix a bug") == "task: search result | query: fix a bug"


def test_a_non_embeddinggemma_model_gets_no_prefix(monkeypatch):
    # mpnet was not trained with prefixes; prepending one would pollute its input.
    # This is the test that keeps the embedder a real config switch for other users.
    _as_mpnet(monkeypatch)
    text = "nano-pdf\nEdit PDF text.\nBody"
    assert server._doc_embed_text(text) == text
    assert server._trigger_embed_text("nano-pdf", "fix typos") == "fix typos"
    assert server._query_embed_text("fix a bug") == "fix a bug"


def test_embed_queries_applies_the_query_prefix(monkeypatch):
    # the prefix must be applied on the query path, not only in the helper, or the
    # two sides diverge and rankings degrade without an error.
    _as_eg2(monkeypatch)
    seen = []
    monkeypatch.setattr(server, "embed_batch", lambda ts: seen.append(ts) or [[0.0]] * len(ts))
    monkeypatch.setattr(server, "EMBED_BACKEND", "ollama")
    server.embed_queries(["fix a bug"])
    assert seen == [["task: search result | query: fix a bug"]]


def test_embed_queries_leaves_a_non_eg2_model_untouched(monkeypatch):
    _as_mpnet(monkeypatch)
    seen = []
    monkeypatch.setattr(server, "embed_batch", lambda ts: seen.append(ts) or [[0.0]] * len(ts))
    monkeypatch.setattr(server, "EMBED_BACKEND", "ollama")
    server.embed_queries(["fix a bug"])
    assert seen == [["fix a bug"]]
