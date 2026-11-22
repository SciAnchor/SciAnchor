"""Zotero write-access helper selection for HTTP confirmation actions."""

from __future__ import annotations

import os
from typing import Any

from research_harness_mcp.zotero_identity import normalize_zotero_library_id


def zotero_api_library_id(value: str | int | None, library_type: str) -> str:
    """Resolve Zotero desktop-local library ids to Zotero Web API ids.

    Zotero Desktop exposes the personal library as local ``libraryID=1``, while
    Zotero Web API writes require the account ``userID``. The side panel sends
    desktop-local ids, so use configured Web API ids for the personal library
    when the local id is supplied.
    """

    normalized = normalize_zotero_library_id(value)
    configured = os.getenv("ZOTERO_LIBRARY_ID", "").strip()
    configured_type = os.getenv("ZOTERO_LIBRARY_TYPE", "user").strip() or "user"
    effective_type = str(library_type or "user").strip() or "user"
    if (
        effective_type == "user"
        and configured
        and configured_type == "user"
        and (not normalized or normalized == "1")
    ):
        return configured
    if not normalized and configured and configured_type == effective_type:
        return configured
    return normalized


def create_zotero_write_client(
    *,
    library_id: str,
    library_type: str,
    api_key: str = "",
    api_base: str = "",
    desktop_library_id: str | int | None = None,
) -> tuple[Any, str]:
    """Create the right Zotero writer for side-panel confirmation actions.

    The Zotero side panel usually runs against the user's open desktop library.
    In that mode there may be no Zotero Web API key, but the local Connector can
    still create items in the currently selected desktop collection.
    """

    from research_harness import zotero_resource

    adapter = zotero_write_adapter(
        library_id=library_id,
        library_type=library_type,
        api_key=api_key,
        desktop_library_id=desktop_library_id,
    )
    client = zotero_resource.create_zotero_resource(
        adapter=adapter,
        library_id=library_id,
        library_type=library_type,
        api_key=api_key,
        base_url=api_base,
    )
    service_library_id = (
        "local"
        if adapter in {"connector", "local", "desktop"} and library_type == "user"
        else library_id
    )
    return client, service_library_id


def zotero_write_adapter(
    *,
    library_id: str,
    library_type: str,
    api_key: str,
    desktop_library_id: str | int | None = None,
) -> str:
    configured = os.getenv("ZOTERO_ADAPTER", "").strip().lower()
    if configured:
        return configured
    if api_key:
        return "web"
    local_id = normalize_zotero_library_id(desktop_library_id)
    is_local_user_library = local_id in {"", "1", "local"} or library_id in {
        "",
        "1",
        "local",
    }
    if library_type == "user" and is_local_user_library:
        return "connector"
    return "web"
