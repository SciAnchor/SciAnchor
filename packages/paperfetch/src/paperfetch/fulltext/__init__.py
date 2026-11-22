"""单篇已验证 PDF、可选入包解析，以及无绑定身份的物理解析；不含检索、不含数据集。"""

from paperfetch.fulltext.service import (
    DownloadOutcome,
    DownloadRequest,
    PaperDownloadService,
)

__all__ = ["DownloadOutcome", "DownloadRequest", "PaperDownloadService"]
