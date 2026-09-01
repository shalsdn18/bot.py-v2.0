from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from .models import SyncResult
from .reconciler import reconcile_positions
from .toss_client import TossClient, normalize_holdings


def sync_positions(local_positions: Optional[Dict[str, Dict[str, Any]]] = None, client: Optional[Any] = None) -> Dict[str, Any]:
    """Load the current local state, sync against Toss, and return merged data plus a SyncResult."""
    base_positions = copy.deepcopy(local_positions or {})

    if client is None:
        try:
            client = TossClient()
        except Exception as exc:  # pragma: no cover - safety wrapper for config issues
            result = SyncResult(status="error", failure_reason=str(exc))
            return {"result": result, "positions": base_positions}

    try:
        raw_response = client.fetch_holdings()
    except Exception as exc:
        result = SyncResult(status="error", failure_reason=str(exc))
        return {"result": result, "positions": base_positions}

    normalized = normalize_holdings(raw_response)
    merged_positions, result = reconcile_positions(base_positions, normalized)

    if result.is_success and result.status == "success_no_positions":
        return {"result": result, "positions": merged_positions}

    if result.is_error:
        return {"result": result, "positions": base_positions}

    return {"result": result, "positions": merged_positions}
