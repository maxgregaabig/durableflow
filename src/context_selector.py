from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from typing import Literal


TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RetrievalCandidate:
    """A candidate from retrieval with score and rank."""
    item: ContextItem
    score: float
    rank: int  # 1-indexed position in ranked results


@dataclass(frozen=True)
class SelectionResult:
    """Result of context selection with assembly lineage."""
    selected: list[tuple[RetrievalCandidate, int]]  # (candidate, budget_position)
    rejected: list[tuple[RetrievalCandidate, str]]  # (candidate, rejection_reason)
    retrieval_method: str = "bm25"

    @property
    def selected_items(self) -> list[ContextItem]:
        return [candidate.item for candidate, _ in self.selected]

    @property
    def retrieved_count(self) -> int:
        return len(self.selected) + len(self.rejected)


@dataclass(frozen=True)
class ContextItem:
    id: str
    content: str
    source_type: str
    timestamp: str
    token_count: int


class ContextSelector:
    def select(
        self,
        query: str,
        corpus: list[ContextItem],
        token_budget: int,
    ) -> SelectionResult:
        """Select context items from corpus, recording assembly lineage."""
        if token_budget <= 0 or not corpus:
            return SelectionResult(
                selected=[],
                rejected=[(RetrievalCandidate(item, 0.0, rank + 1), "token_budget")
                          for rank, item in enumerate(corpus)],
            )
        scored = self._score_relevance(query, corpus)
        return self._pack_budget(scored, token_budget)

    def _score_relevance(
        self,
        query: str,
        corpus: list[ContextItem],
    ) -> list[tuple[float, ContextItem]]:
        query_terms = Counter(self._terms(query))
        if not query_terms:
            return [(0.0, item) for item in corpus]
        document_terms = [Counter(self._terms(item.content)) for item in corpus]
        doc_count = len(corpus)
        document_frequency: Counter[str] = Counter()
        for terms in document_terms:
            document_frequency.update(terms.keys())

        scored: list[tuple[float, ContextItem]] = []
        for item, terms in zip(corpus, document_terms, strict=True):
            score = 0.0
            for term, query_tf in query_terms.items():
                if term not in terms:
                    continue
                idf = math.log((doc_count + 1) / (document_frequency[term] + 1)) + 1
                score += query_tf * terms[term] * idf
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].timestamp), reverse=True)
        return scored

    def _pack_budget(
        self,
        scored_items: list[tuple[float, ContextItem]],
        token_budget: int,
    ) -> SelectionResult:
        selected: list[tuple[RetrievalCandidate, int]] = []
        rejected: list[tuple[RetrievalCandidate, str]] = []
        used = 0
        budget_position = 0
        for rank, (score, item) in enumerate(scored_items, start=1):
            candidate = RetrievalCandidate(item, score, rank)
            if item.token_count <= 0:
                rejected.append((candidate, "zero_token_count"))
                continue
            if used + item.token_count <= token_budget:
                selected.append((candidate, budget_position))
                budget_position += 1
                used += item.token_count
            else:
                rejected.append((candidate, "token_budget"))
        return SelectionResult(
            selected=selected,
            rejected=rejected,
            retrieval_method="bm25",
        )

    def _terms(self, text: str) -> list[str]:
        return TOKEN_RE.findall(text.lower())


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) / 0.75))

