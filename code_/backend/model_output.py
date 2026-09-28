"""Validate structured model replies before they reach application services."""

from typing import TypeVar

from pydantic import BaseModel

ResultModel = TypeVar("ResultModel", bound=BaseModel)


def parse_model_output(raw: str, schema: type[ResultModel]) -> ResultModel:
    """Accept JSON or one JSON code block while enforcing the response schema."""
    if len(raw) > 16000:
        raise ValueError("Model response exceeds its limit")
    text = raw.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].casefold() in {"```", "```json"} and lines[-1] == "```":
        text = "\n".join(lines[1:-1])
    return schema.model_validate_json(text)
