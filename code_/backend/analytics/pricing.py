"""Model price table used to turn token counts into an estimated cost."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import yaml

_DEFAULT_PRICING_FILE = pathlib.Path(__file__).with_name("pricing.yaml")


@dataclass(frozen=True)
class ModelPrice:
    """Price of a model in USD per one million tokens."""

    input_per_million: float
    output_per_million: float


class PriceTable:
    """Looks up the cost of a model call from a table of per token prices."""

    def __init__(self, prices: dict[str, ModelPrice], free_suffixes: tuple[str, ...] = (":free",)) -> None:
        """Create a price table from explicit prices."""
        self._prices = prices
        self._free_suffixes = free_suffixes

    @classmethod
    def load(cls, path: str | pathlib.Path | None = None) -> PriceTable:
        """Load prices from a yaml file, defaulting to AWN_PRICING_FILE or the bundled pricing.yaml."""
        path = pathlib.Path(path or os.getenv("AWN_PRICING_FILE") or _DEFAULT_PRICING_FILE)
        with path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        prices = {
            str(model): ModelPrice(float(price.get("input", 0)), float(price.get("output", 0)))
            for model, price in (config.get("models") or {}).items()
        }
        return cls(prices, tuple(config.get("free_suffixes") or ()))

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
        """Return (cost in USD, whether the model has a known price)."""
        if model.endswith(self._free_suffixes):
            return 0.0, True

        price = self._prices.get(model)
        if price is None:
            return 0.0, False

        cost = (input_tokens * price.input_per_million + output_tokens * price.output_per_million) / 1_000_000
        return cost, True
