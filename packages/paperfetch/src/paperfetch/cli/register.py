# -*- coding: utf-8 -*-
"""按领域组装全部子命令注册。"""

from __future__ import annotations

from paperfetch.cli.biomedical import register_dataset_commands
from paperfetch.cli.doctor import register_doctor_commands
from paperfetch.cli.ops import register_ops_commands
from paperfetch.cli.paper_v1 import register_paper_commands
from paperfetch.cli.seed_pack_v1 import register_seed_pack_commands
from paperfetch.cli.system import register_system_commands
from paperfetch.cli.workflow import register_workflow_commands


def register_all_commands(subparsers):
    parsers = []
    parsers.extend(register_paper_commands(subparsers))
    parsers.extend(register_seed_pack_commands(subparsers))
    parsers.extend(register_system_commands(subparsers))
    parsers.extend(register_doctor_commands(subparsers))
    parsers.extend(register_ops_commands(subparsers))
    parsers.extend(register_workflow_commands(subparsers))
    parsers.extend(register_dataset_commands(subparsers))
    return parsers
