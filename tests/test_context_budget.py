from __future__ import annotations

from src.context_selector import ContextItem, ContextSelector


def item(item_id: str, content: str, tokens: int = 10) -> ContextItem:
    return ContextItem(item_id, content, "email", "2026-06-17T00:00:00Z", tokens)


def test_large_corpus_stays_under_budget() -> None:
    corpus = [
        item(f"email-{index}", f"workflow approval crash recovery item {index}", tokens=50)
        for index in range(200)
    ]
    result = ContextSelector().select("approval workflow crash", corpus, token_budget=4096)
    selected_items = result.selected_items
    assert sum(entry.token_count for entry in selected_items) <= 4096
    # Verify rejected items are tracked
    assert len(result.rejected) > 0


def test_relevance_ranking_prefers_obvious_match() -> None:
    corpus = [
        item("billing", "invoice payment receipt", tokens=5),
        item("board", "q3 board deck sarah feedback review", tokens=5),
        item("lunch", "office lunch menu", tokens=5),
    ]
    result = ContextSelector().select("sarah board deck feedback", corpus, token_budget=20)
    selected_items = result.selected_items
    assert selected_items[0].id == "board"
    # Verify retrieval metadata
    assert result.selected[0][0].rank == 1
    assert result.selected[0][0].score > 0


def test_empty_corpus_returns_empty() -> None:
    result = ContextSelector().select("anything", [], token_budget=4096)
    assert result.selected_items == []
    assert result.rejected == []
    assert result.retrieved_count == 0


def test_budget_smaller_than_smallest_item_returns_empty() -> None:
    corpus = [item("large", "large item", tokens=100)]
    result = ContextSelector().select("large", corpus, token_budget=10)
    assert result.selected_items == []
    assert len(result.rejected) == 1
    assert result.rejected[0][1] == "token_budget"


def test_three_most_relevant_items_are_included_when_budget_allows() -> None:
    corpus = [
        item("top-1", "sarah board deck feedback review", tokens=5),
        item("top-2", "board deck sarah q3 metrics", tokens=5),
        item("top-3", "feedback review q3 board", tokens=5),
        item("low", "lunch menu office", tokens=5),
    ]
    result = ContextSelector().select("sarah board deck feedback q3", corpus, token_budget=20)
    selected_items = result.selected_items
    assert [entry.id for entry in selected_items[:3]] == ["top-1", "top-2", "top-3"]
    # Verify ranks are sequential
    assert [candidate.rank for candidate, _ in result.selected[:3]] == [1, 2, 3]


def test_assembly_lineage_tracks_retrieved_and_rejected() -> None:
    corpus = [
        item("top-1", "sarah board deck feedback review", tokens=5),
        item("top-2", "board deck sarah q3 metrics", tokens=5),
        item("low", "lunch menu office", tokens=5),
    ]
    result = ContextSelector().select("sarah board deck feedback q3", corpus, token_budget=10)
    # Should have retrieved all 3 candidates
    assert result.retrieved_count == 3
    # Should have selected 2 (top-1 and top-2)
    assert len(result.selected) == 2
    # Should have rejected 1 (low) due to token budget
    assert len(result.rejected) == 1
    # Verify rejection reason
    assert result.rejected[0][1] == "token_budget"
    # Verify retrieval method
    assert result.retrieval_method == "bm25"
