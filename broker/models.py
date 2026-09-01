from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BrokerHolding:
    ticker: str
    quantity: float
    average_price: float
    market: str = "UNKNOWN"
    last_updated_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    status: str
    failure_reason: Optional[str] = None
    removed_tickers: List[str] = field(default_factory=list)
    updated_tickers: List[str] = field(default_factory=list)
    added_tickers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.removed_tickers = list(self.removed_tickers or [])
        self.updated_tickers = list(self.updated_tickers or [])
        self.added_tickers = list(self.added_tickers or [])
        self.metadata = dict(self.metadata or {})

    @property
    def is_success(self) -> bool:
        return self.status in {"success", "success_no_positions"}

    @property
    def is_error(self) -> bool:
        return self.status == "error"
