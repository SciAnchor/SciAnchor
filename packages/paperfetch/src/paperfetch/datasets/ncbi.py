"""具备限速与凭证脱敏能力的 NCBI E-utilities 访问实现。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from paperfetch.datasets.acquisition import (
    HostRateLimiter,
    resolve_coordination_root,
    resolve_http_route,
    source_route_from_environment,
)
from paperfetch.observability import get_event_logger

EUTILS_ROOT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ACCESSION_PATTERN = re.compile(r"^[A-Za-z]{1,8}_?[A-Za-z0-9]*(?:\.[0-9]+)?$")
logger = get_event_logger("paperfetch.datasets.ncbi")


class NcbiEutilsError(RuntimeError):
    """E-utilities 请求或校验失败。"""

    error_code = "ncbi_eutils_failed"
    error_class = "acquisition_failed"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        error_class: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code or type(self).error_code
        self.error_class = error_class or type(self).error_class


def _new_session(proxy: Optional[str]) -> requests.Session:
    retry = Retry(
        total=5,
        connect=3,
        read=3,
        status=5,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.trust_env = False
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "SPC-NCBI-Eutils/0.3",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class NcbiEutilsClient:
    """Small E-utilities client with request pacing and redacted reports."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        tool: Optional[str] = None,
        email: Optional[str] = None,
        proxy: Optional[str] = None,
        requests_per_second: Optional[float] = None,
        timeout_seconds: float = 30.0,
        session: Optional[requests.Session] = None,
        coordination_root: Optional[str | os.PathLike[str]] = None,
    ):
        self.api_key = (
            api_key if api_key is not None else os.getenv("NCBI_API_KEY") or ""
        ).strip()
        self.tool = (
            tool if tool is not None else os.getenv("NCBI_TOOL") or "paperfetch"
        ).strip()
        self.email = (
            email if email is not None else os.getenv("NCBI_EMAIL") or ""
        ).strip()
        self.route_decision = (
            resolve_http_route("proxy" if proxy else "direct", proxy)
            if proxy is not None
            else source_route_from_environment("ncbi")
        )
        self.proxy = self.route_decision.proxy_url
        self.advertised_limit = 10.0 if self.api_key else 3.0
        configured_rate = requests_per_second
        if configured_rate is None:
            raw = os.getenv("NCBI_REQUESTS_PER_SECOND")
            try:
                configured_rate = float(raw) if raw else (9.0 if self.api_key else 2.5)
            except (TypeError, ValueError) as exc:
                raise NcbiEutilsError(
                    "NCBI_REQUESTS_PER_SECOND 必须是数值",
                    error_code="invalid_ncbi_request_rate",
                    error_class="invalid_configuration",
                ) from exc
        if configured_rate <= 0 or configured_rate > self.advertised_limit:
            raise NcbiEutilsError(
                f"NCBI 请求速率必须大于 0，且不超过每秒 {self.advertised_limit:g} 次",
                error_code="invalid_ncbi_request_rate",
                error_class="invalid_configuration",
            )
        self.requests_per_second = float(configured_rate)
        self.minimum_interval = 1.0 / self.requests_per_second
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.session = session or _new_session(self.proxy)
        self._owns_session = session is None
        self._lock = threading.Lock()
        self._last_request_started = 0.0
        self.coordination_root = resolve_coordination_root(coordination_root)
        self._host_rate_limiter = (
            HostRateLimiter(
                self.coordination_root,
                "ncbi-eutils",
                self.requests_per_second,
                sleeper=time.sleep,
            )
            if session is None or coordination_root is not None
            else None
        )

    @property
    def authenticated(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "NcbiEutilsClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _pace(self) -> None:
        if self._host_rate_limiter is not None:
            self._host_rate_limiter.wait()
            return
        with self._lock:
            now = time.monotonic()
            remaining = self.minimum_interval - (now - self._last_request_started)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_started = time.monotonic()

    def _parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        value = dict(parameters)
        if self.tool:
            value.setdefault("tool", self.tool)
        if self.email:
            value.setdefault("email", self.email)
        if self.api_key:
            value.setdefault("api_key", self.api_key)
        return value

    def request(
        self,
        utility: str,
        *,
        parameters: dict[str, Any],
        method: str = "GET",
        stream: bool = False,
    ) -> requests.Response:
        self._pace()
        url = f"{EUTILS_ROOT}/{utility}.fcgi"
        kwargs: dict[str, Any] = {
            "timeout": (10.0, self.timeout_seconds),
            "stream": stream,
        }
        safe_parameters = self._parameters(parameters)
        if method.upper() == "POST":
            kwargs["data"] = safe_parameters
        else:
            kwargs["params"] = safe_parameters
        try:
            response = self.session.request(method.upper(), url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 429:
                failure = NcbiEutilsError(
                    "NCBI E-utilities 请求超过速率限制（HTTP 429）",
                    error_code="ncbi_rate_limit_exceeded",
                    error_class="rate_limited",
                )
            else:
                failure = NcbiEutilsError(
                    f"NCBI E-utilities 请求失败：{utility}（{type(exc).__name__}）",
                    error_code="ncbi_request_failed",
                    error_class="network_error",
                )
            logger.event(
                "ncbi.eutils.request_failed",
                phase="dataset_download",
                action="request",
                outcome="failed",
                level="ERROR",
                source="ncbi_eutils",
                error_class=failure.error_class,
                message=f"NCBI E-utilities 请求失败：{utility}",
                diagnostics={
                    "utility": utility,
                    "http_status": status,
                    "error_code": failure.error_code,
                    "exception_type": type(exc).__name__,
                },
            )
            raise failure from exc

    def get_json(
        self, utility: str, **parameters: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        parameters.setdefault("retmode", "json")
        started = time.perf_counter()
        response = self.request(utility, parameters=parameters)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        try:
            payload = response.json()
        except ValueError as exc:
            response.close()
            raise NcbiEutilsError(
                f"NCBI {utility} 返回了无效 JSON",
                error_code="ncbi_invalid_json_response",
                error_class="identity_mismatch",
            ) from exc
        metadata = {
            "utility": utility,
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(response.content),
            "elapsed_ms": elapsed_ms,
            "rate_limit": response.headers.get("X-RateLimit-Limit"),
            "rate_remaining": response.headers.get("X-RateLimit-Remaining"),
        }
        response.close()
        return payload, metadata

    def validate_accession(
        self, accession: str = "NM_007294.4", *, db: str = "nuccore"
    ) -> dict[str, Any]:
        candidate = accession.strip()
        if not ACCESSION_PATTERN.fullmatch(candidate):
            raise NcbiEutilsError(
                f"无效的 NCBI accession：{accession!r}",
                error_code="invalid_ncbi_accession",
                error_class="invalid_argument",
            )
        logger.event(
            "ncbi.accession_validation.started",
            phase="dataset_validation",
            action="validate_accession",
            outcome="started",
            source="ncbi_eutils",
            message=f"开始验证 NCBI accession：{candidate}",
            diagnostics={"accession": candidate, "database": db},
        )
        checks: list[dict[str, Any]] = []
        info, metadata = self.get_json("einfo", db=db)
        checks.append(metadata)
        dbinfo = info.get("einforesult", {}).get("dbinfo") or []
        if not dbinfo or str(dbinfo[0].get("dbname")) != db:
            raise NcbiEutilsError(
                f"NCBI EInfo 数据库身份不一致：{db}",
                error_code="ncbi_database_identity_mismatch",
                error_class="identity_mismatch",
            )

        search, metadata = self.get_json(
            "esearch", db=db, term=f"{candidate}[accn]", retmax=5
        )
        checks.append(metadata)
        identifiers = search.get("esearchresult", {}).get("idlist") or []
        if not identifiers:
            raise NcbiEutilsError(
                f"未找到 NCBI accession：{candidate}",
                error_code="ncbi_accession_not_found",
                error_class="not_found",
            )

        uid = str(identifiers[0])
        summary, metadata = self.get_json("esummary", db=db, id=uid)
        checks.append(metadata)
        actual_accession = str(
            summary.get("result", {}).get(uid, {}).get("accessionversion") or ""
        )
        if actual_accession.upper() != candidate.upper():
            raise NcbiEutilsError(
                f"NCBI accession 身份不一致：预期={candidate}，实际={actual_accession}",
                error_code="ncbi_accession_identity_mismatch",
                error_class="identity_mismatch",
            )

        started = time.perf_counter()
        response = self.request(
            "efetch",
            parameters={"db": db, "id": uid, "rettype": "fasta", "retmode": "text"},
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        payload = response.content
        checks.append(
            {
                "utility": "efetch",
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "bytes": len(payload),
                "elapsed_ms": elapsed_ms,
                "rate_limit": response.headers.get("X-RateLimit-Limit"),
                "rate_remaining": response.headers.get("X-RateLimit-Remaining"),
            }
        )
        response.close()
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NcbiEutilsError(
                "NCBI EFetch FASTA 响应不是有效 UTF-8 文本",
                error_code="ncbi_invalid_text_encoding",
                error_class="identity_mismatch",
            ) from exc
        if not text.startswith(f">{candidate}"):
            raise NcbiEutilsError(
                "NCBI EFetch 返回了非预期的 FASTA 身份",
                error_code="ncbi_fasta_identity_mismatch",
                error_class="identity_mismatch",
            )
        records = sum(1 for line in text.splitlines() if line.startswith(">"))
        bases = sum(
            len(line.strip()) for line in text.splitlines() if not line.startswith(">")
        )
        result = {
            "schema_version": "spc.ncbi.eutils-validation.v1",
            "status": "validated",
            "accession": candidate,
            "uid": uid,
            "database": db,
            "authenticated": self.authenticated,
            "api_key_configured": self.authenticated,
            "tool_configured": bool(self.tool),
            "email_configured": bool(self.email),
            "requests_per_second": self.requests_per_second,
            "advertised_limit": self.advertised_limit,
            "proxy_mode": self.route_decision.route,
            "proxy_ref": self.route_decision.proxy_ref,
            "checks": checks,
            "fasta_records": records,
            "fasta_bases": bases,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        logger.event(
            "ncbi.accession_validation.completed",
            phase="dataset_validation",
            action="validate_accession",
            outcome="success",
            source="ncbi_eutils",
            message=f"NCBI accession 验证通过：{candidate}",
            diagnostics={
                "accession": candidate,
                "database": db,
                "fasta_records": records,
                "fasta_bases": bases,
            },
        )
        return result

    def download_record(
        self,
        *,
        db: str,
        identifier: str,
        rettype: str,
        retmode: str,
        output_path: str | os.PathLike[str],
    ) -> dict[str, Any]:
        target = Path(output_path).expanduser().resolve()
        logger.event(
            "ncbi.record_download.started",
            phase="dataset_download",
            action="download_record",
            outcome="started",
            source="ncbi_eutils",
            message=f"开始下载 NCBI 记录：{identifier}",
            diagnostics={"database": db, "identifier": identifier, "rettype": rettype},
        )
        started = time.perf_counter()
        response = self.request(
            "efetch",
            parameters={
                "db": db,
                "id": identifier,
                "rettype": rettype,
                "retmode": retmode,
            },
        )
        payload = response.content
        content_type = str(response.headers.get("Content-Type") or "")
        status = response.status_code
        response.close()
        if not payload:
            raise NcbiEutilsError(
                "NCBI EFetch 返回了空响应",
                error_code="ncbi_empty_response",
                error_class="identity_mismatch",
            )
        stripped = payload.lstrip()
        if stripped.lower().startswith(b"<html"):
            raise NcbiEutilsError(
                "NCBI EFetch 返回了 HTML，而不是请求的记录",
                error_code="unexpected_html_content",
                error_class="identity_mismatch",
            )
        if rettype.lower() == "fasta" and not stripped.startswith(b">"):
            raise NcbiEutilsError(
                "NCBI EFetch 响应不是 FASTA",
                error_code="ncbi_invalid_fasta_response",
                error_class="identity_mismatch",
            )
        if retmode.lower() == "json":
            try:
                json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise NcbiEutilsError(
                    "NCBI EFetch 响应不是有效 JSON",
                    error_code="ncbi_invalid_json_response",
                    error_class="identity_mismatch",
                ) from exc
        _atomic_write(target, payload)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        report = {
            "schema_version": "spc.ncbi.record-download.v1",
            "status": "complete",
            "database": db,
            "identifier": identifier,
            "rettype": rettype,
            "retmode": retmode,
            "path": str(target),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content_type": content_type,
            "elapsed_ms": elapsed_ms,
            "bytes_per_second": round(len(payload) / max(elapsed_ms / 1000, 0.001)),
            "authenticated": self.authenticated,
            "api_key_configured": self.authenticated,
            "proxy_mode": self.route_decision.route,
            "proxy_ref": self.route_decision.proxy_ref,
            "http_status": status,
        }
        _atomic_write(
            target.with_suffix(target.suffix + ".validation.json"),
            (json.dumps(report, indent=2) + "\n").encode("utf-8"),
        )
        logger.event(
            "ncbi.record_download.completed",
            phase="dataset_download",
            action="download_record",
            outcome="success",
            source="ncbi_eutils",
            message=f"NCBI 记录下载完成：{identifier}",
            diagnostics={
                "database": db,
                "identifier": identifier,
                "bytes": len(payload),
                "elapsed_ms": elapsed_ms,
            },
        )
        return report
