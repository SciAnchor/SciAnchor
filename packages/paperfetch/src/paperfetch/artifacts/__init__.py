"""SPC 1.0 已验证文件模型与原子保存入口。"""

from paperfetch.artifacts.models import (
    ArtifactFile,
    ArtifactManifest,
    ArtifactPointer,
    ArtifactProducer,
)
from paperfetch.artifacts.store import materialize_artifact, probe_artifact

__all__ = [
    "ArtifactFile",
    "ArtifactManifest",
    "ArtifactPointer",
    "ArtifactProducer",
    "materialize_artifact",
    "probe_artifact",
]
