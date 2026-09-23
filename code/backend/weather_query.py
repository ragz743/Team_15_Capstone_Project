"""Station identities used by weather retrieval."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    """An indexed station's official identity."""

    id: str
    name: str
    county: str
