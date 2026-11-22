"""Unified service dispatcher skeleton for Research Harness."""

from __future__ import annotations

from .dispatcher import ResearchService
from .primitive_contract import primitive_result_to_service_result
from .types import ServiceCommand, ServiceResult

__all__ = [
    "ResearchService",
    "ServiceCommand",
    "ServiceResult",
    "primitive_result_to_service_result",
]
