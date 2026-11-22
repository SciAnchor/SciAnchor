# -*- coding: utf-8 -*-
"""
CuratorContext 模块
此文件定义了任务执行过程中的全局上下文状态类，用于在各个原子动作 (BaseAction) 之间共享和流动数据。
"""

from typing import Dict, List, Any, Optional
from datetime import datetime


class CuratorContext:
    """
    CuratorContext 运行时上下文类

    用于在 Task Pipeline 的执行过程中，承载所有的输入数据、中间状态及最终的输出成果。
    """

    def __init__(self, run_id: str, search_brief: Optional[Dict[str, Any]] = None):
        """
        初始化上下文

        Args:
            run_id (str): 当前运行任务的唯一标识 ID，格式通常为 <date>_<time>_<short_hash>。
            search_brief (Optional[Dict[str, Any]]): 传入的 Search Brief 原始字典。
        """
        self.run_id: str = run_id  # 运行时唯一 ID
        self.search_brief: Optional[Dict[str, Any]] = search_brief  # 检索配置概要

        # 候选论文库，Key 为统一格式的唯一 paper_id（例如 "spc:<uuid>"），Value 为 PaperRecord 实例
        self.candidates: Dict[str, Any] = {}

        # 最终被选定为 Seed 的论文列表，元素为 PaperRecord 实例
        self.top_seeds: List[Any] = []

        # 数据源的健康和可达性状态，Key 为数据源名称（如 "openalex"），Value 为状态详细字典
        self.source_health: Dict[str, Any] = {}

        # 任务执行的开始时间与结束时间
        self.start_time: datetime = datetime.now()
        self.end_time: Optional[datetime] = None

        # 保存运行时产生的一些临时日志或审计信息 (provenance)
        self.provenance_log: List[Dict[str, Any]] = []

        # 运行成果的最终保存根目录
        self.output_dir: Optional[str] = None

        # 供导出与刷新动作使用的轻量运行级元数据。
        self.run_metadata: Dict[str, Any] = {}

    def add_provenance(
        self, action_name: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        添加一条操作审计记录，以便下游追踪数据来源和操作步骤

        Args:
            action_name (str): 执行动作的名称
            message (str): 审计日志文本
            details (Optional[Dict[str, Any]]): 附加结构化细节
        """
        self.provenance_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "action": action_name,
                "message": message,
                "details": details or {},
            }
        )
