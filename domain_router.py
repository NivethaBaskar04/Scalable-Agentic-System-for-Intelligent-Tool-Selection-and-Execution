"""
Tool Domain Router.

Given a user query, ranks *domains* (invoices, payments, customers, ...)
by relevance BEFORE any individual tool is considered. This is what lets
the system stay fast at 500-1000 tools: instead of comparing the query
against every tool, we first shrink the candidate pool to the tools that
live in the top-matching domain(s).

Deliberately metadata/TF-IDF driven, not "if 'invoice' in query: domain=invoices".
Each domain's profile is built dynamically from the descriptions/tags of the
tools that currently belong to it, so it stays correct as the registry grows
or shrinks (e.g. via generate_tools.py).
"""
from __future__ import annotations
from typing import List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.registry.store import ToolRegistry


class DomainRouter:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self._domain_names: List[str] = []
        self._vectorizer: TfidfVectorizer | None = None
        self._domain_matrix = None
        self.rebuild()

    def rebuild(self) -> None:
        """Recompute domain profiles from the current registry state."""
        domains = self.registry.domains()
        profiles = []
        for d in domains:
            tools = self.registry.by_domain(d)
            text = " ".join(t.searchable_text() for t in tools)
            profiles.append(text if text else d)

        self._domain_names = domains
        if profiles:
            self._vectorizer = TfidfVectorizer(stop_words="english")
            self._domain_matrix = self._vectorizer.fit_transform(profiles)
        else:
            self._vectorizer = None
            self._domain_matrix = None

    def route(self, query: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """Returns up to top_k (domain, score) pairs, highest score first."""
        if not self._vectorizer or self._domain_matrix is None or not self._domain_names:
            return []
        query_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self._domain_matrix)[0]
        ranked = sorted(zip(self._domain_names, sims), key=lambda x: x[1], reverse=True)
        # Always include "knowledge" and "system" domains as low-priority fallbacks
        # so rag_search / system_search remain reachable even if their TF-IDF
        # score is low for a given phrasing.
        return [(d, float(s)) for d, s in ranked[:top_k] if s > 0] or ranked[:1]
