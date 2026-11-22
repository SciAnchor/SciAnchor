from paperfetch.downloaders.pipeline.orchestrator import BatchOrchestrator


def test_phase1_paper_concurrency_defaults_to_two(monkeypatch):
    monkeypatch.delenv("SPC_PHASE1_PAPER_CONCURRENCY", raising=False)

    assert BatchOrchestrator._phase1_paper_concurrency() == 2


def test_phase1_paper_concurrency_is_bounded(monkeypatch):
    monkeypatch.setenv("SPC_PHASE1_PAPER_CONCURRENCY", "99")
    assert BatchOrchestrator._phase1_paper_concurrency() == 4

    monkeypatch.setenv("SPC_PHASE1_PAPER_CONCURRENCY", "invalid")
    assert BatchOrchestrator._phase1_paper_concurrency() == 2
