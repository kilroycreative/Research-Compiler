"""Cost and token telemetry helpers."""

from __future__ import annotations

import json
from pathlib import Path


class CostTracker:
    """Maps token counts to estimated USD cost using a static pricing table."""

    def __init__(self, pricing_path: str | Path | None = None) -> None:
        base = Path(__file__).resolve().parent
        self.pricing_path = Path(pricing_path) if pricing_path else base / "models" / "pricing.json"
        self._pricing = json.loads(self.pricing_path.read_text(encoding="utf-8"))

    def estimate(self, model_id: str, *, prompt_tokens: int, completion_tokens: int) -> float:
        pricing = self._pricing.get(model_id)
        if pricing is None:
            return 0.0
        prompt_cost = (prompt_tokens / 1_000_000) * pricing["input_per_million_usd"]
        completion_cost = (completion_tokens / 1_000_000) * pricing["output_per_million_usd"]
        return round(prompt_cost + completion_cost, 6)
