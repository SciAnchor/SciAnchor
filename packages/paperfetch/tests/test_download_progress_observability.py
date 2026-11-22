# -*- coding: utf-8 -*-
"""批量下载动态进度状态测试。"""

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.orchestrator import BatchOrchestrator


class DummyProgress:
    def __init__(self):
        self.created = []
        self.updated = []
        self.advanced = 0

    def add_task(self, description, **kwargs):
        task_id = len(self.created)
        self.created.append((description, kwargs))
        return task_id

    def update(self, task_id, **kwargs):
        self.updated.append((task_id, kwargs))

    def advance(self, _task_id):
        self.advanced += 1


def test_progress_reuses_one_task_and_completes_once():
    orchestrator = object.__new__(BatchOrchestrator)
    orchestrator._progress_tasks = {}
    orchestrator._progress_completed = set()
    paper = PaperRecord(
        paper_id="spc:elsevier",
        doi="10.1016/j.example.2026.01.001",
        title="Example",
        publisher="Elsevier",
    )
    progress = DummyProgress()

    first = orchestrator._paper_task(progress, paper, "等待调度")
    second = orchestrator._paper_task(progress, paper, "直连通道")
    orchestrator._complete_progress(progress, 99, paper)
    orchestrator._complete_progress(progress, 99, paper)

    assert first == second
    assert len(progress.created) == 1
    assert progress.advanced == 1
    descriptions = [item[1].get("description", "") for item in progress.updated]
    assert any("DOI=10.1016/j.example.2026.01.001" in value for value in descriptions)
    assert any("出版社=Elsevier" in value for value in descriptions)
