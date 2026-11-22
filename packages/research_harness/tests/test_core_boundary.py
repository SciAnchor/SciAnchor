from __future__ import annotations


def test_core_modules_are_canonical_and_public_path_reexports() -> None:
    from research_harness._core.core.circuit_breaker import CircuitBreaker
    from research_harness._core.core.paper_pool import PaperPool
    from research_harness._core.core.review_manager import ReviewManager
    from research_harness._core.core.search_cache import cache_get
    from research_harness.core.circuit_breaker import (
        CircuitBreaker as PublicCircuitBreaker,
    )
    from research_harness.core.paper_pool import PaperPool as PublicPaperPool
    from research_harness.core.review_manager import (
        ReviewManager as PublicReviewManager,
    )
    from research_harness.core.search_cache import cache_get as public_cache_get

    assert PublicCircuitBreaker is CircuitBreaker
    assert PublicPaperPool is PaperPool
    assert PublicReviewManager is ReviewManager
    assert public_cache_get is cache_get
