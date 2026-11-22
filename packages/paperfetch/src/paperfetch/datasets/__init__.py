"""SPC 数据集获取基础能力。"""

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    AcquisitionConfigurationError,
    DownloadCoordinator,
    HostRateLimiter,
    RouteDecision,
    build_acquisition_plan,
    error_payload,
    resolve_http_route,
    write_acquisition_report,
)
from paperfetch.datasets.geo import (
    DEFAULT_MAX_DOWNLOAD_GB,
    GeoDataError,
    GeoDatasetStore,
    GeoLargeDownloadBlocked,
    normalize_gse_id,
    resolve_geo_root,
)

__all__ = [
    "AcquisitionBusy",
    "AcquisitionConfigurationError",
    "DEFAULT_MAX_DOWNLOAD_GB",
    "DownloadCoordinator",
    "GeoDataError",
    "GeoDatasetStore",
    "GeoLargeDownloadBlocked",
    "HostRateLimiter",
    "RouteDecision",
    "build_acquisition_plan",
    "error_payload",
    "normalize_gse_id",
    "resolve_http_route",
    "resolve_geo_root",
    "write_acquisition_report",
]
