from __future__ import annotations

from src.context_selector import ContextItem, ContextSelector


def item(item_id: str, content: str, tokens: int = 10) -> ContextItem:
    return ContextItem(item_id, content, "email", "2026-06-17T00:00:00Z", tokens)


def test_large_corpus_stays_under_budget() -> None:
    corpus = [
        item(f"email-{index}", f"workflow approval crash recovery item {index}", tokens=50)
        for index in range(200)
    ]
    selected = ContextSelector().select("approval workflow crash", corpus, token_budget=4096)
    assert sum(entry.token_count for entry in selected) <= 4096


def test_relevance_ranking_prefers_obvious_match() -> None:
    corpus = [
        item("billing", "invoice payment receipt", tokens=5),
        item("board", "q3 board deck sarah feedback review", tokens=5),
        item("lunch", "office lunch menu", tokens=5),
    ]
    selected = ContextSelector().select("sarah board deck feedback", corpus, token_budget=20)
    assert selected[0].id == "board"


def test_empty_corpus_returns_empty() -> None:
    assert ContextSelector().select("anything", [], token_budget=4096) == []


def test_budget_smaller_than_smallest_item_returns_empty() -> None:
    corpus = [item("large", "large item", tokens=100)]
    assert ContextSelector().select("large", corpus, token_budget=10) == []


def test_three_most_relevant_items_are_included_when_budget_allows() -> None:
    corpus = [
        item("top-1", "sarah board deck feedback review", tokens=5),
        item("top-2", "board deck sarah q3 metrics", tokens=5),
        item("top-3", "feedback review q3 board", tokens=5),
        item("low", "lunch menu office", tokens=5),
    ]
    selected = ContextSelector().select("sarah board deck feedback q3", corpus, token_budget=20)
    assert [entry.id for entry in selected[:3]] == ["top-1", "top-2", "top-3"]
