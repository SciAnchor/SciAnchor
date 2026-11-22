"""Shape tests for the extracted CLI registration composer."""

from __future__ import annotations


def test_cli_registration_module_exports_ordered_phases() -> None:
    from research_harness import cli_registration

    assert callable(cli_registration.register_main_before_topic)
    assert callable(cli_registration.register_topic)
    assert callable(cli_registration.register_main_between_topic_and_paper)
    assert callable(cli_registration.register_paper_and_remaining)
