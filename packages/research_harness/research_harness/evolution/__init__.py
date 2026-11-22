"""Evolution subsystem.

This package covers two complementary scopes:

- ``evolution.topic``: per-topic strategy injection, trajectory capture, lesson
  extraction, strategy distillation, nudges, and session learning.
- ``evolution.harness``: project-level self-improvement for the Research
  Harness tool itself, including candidate archives, champion registry evidence,
  PDF quality signals, replay gates, and skill lifecycle records.

These scopes lived in separate top-level packages before 2026-06. New imports
should use ``research_harness.evolution.topic`` or
``research_harness.evolution.harness`` explicitly.
"""
