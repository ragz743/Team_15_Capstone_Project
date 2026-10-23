"""Filter retrieved records and format their public source information."""

from datetime import date

from backend.weather_query import WeatherQuery
from langchain_core.documents import Document

TABLE_LABELS = {"daily_index": "Historical Data", "live_index": "Current Conditions", "forecast_index": "Forecast Data"}


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _forecast_document(doc: Document, selection: WeatherQuery) -> Document | None:
    lines = doc.page_content.splitlines()
    header_end = next((i + 1 for i, line in enumerate(lines) if line.startswith("| ---")), 0)
    if not header_end:
        return None
    kept, days = [], set()
    for line in lines[header_end:]:
        cells = line.split("|")
        day = _day(cells[1].strip()) if len(cells) > 2 else None
        if day is not None and selection.start <= day <= selection.end:
            kept.append(line)
            days.add(day.isoformat())
    if not kept:
        return None
    metadata = {key: value for key, value in doc.metadata.items() if key not in ("date", "timestamp")}
    metadata["dates"] = sorted(days)
    return Document(page_content="\n".join(lines[:header_end] + kept), metadata=metadata)


def dated_document(doc: Document, table: str, selection: WeatherQuery) -> Document | None:
    """Reject scope mismatches and remove forecast rows outside the requested dates."""
    if str(doc.metadata.get("id")) not in selection.station_ids:
        return None
    if selection.county and str(doc.metadata.get("county", "")).casefold() != selection.county.casefold():
        return None
    if table == "forecast_index":
        return _forecast_document(doc, selection)
    day = _day(doc.metadata.get("date" if table == "daily_index" else "timestamp"))
    return doc if day is not None and selection.start <= day <= selection.end else None


def document_context(doc: Document, table: str) -> str:
    """Include source identity and correctly labeled dates without private coordinates."""
    fields = [("station", "Station"), ("county", "County"), ("state", "State")]
    if table == "forecast_index":
        fields.append(("dates", "Forecast dates"))
    else:
        fields.extend([("date", "Observation date"), ("timestamp", "Observation timestamp")])
    identity = "\n".join(f"{label}: {doc.metadata[key]}" for key, label in fields if doc.metadata.get(key))
    return f"{identity}\n{doc.page_content}" if identity else doc.page_content


def source_label(doc: Document, table: str) -> str:
    """Describe the records used without treating a forecast as an observation."""
    metadata = doc.metadata
    if table == "forecast_index":
        times, kind = metadata["dates"], "forecast"
    else:
        times, kind = [metadata["date" if table == "daily_index" else "timestamp"]], "observation"
    county = metadata.get("county")
    return (
        str(metadata["station"])
        + (f", {county} County" if county else "")
        + f": {', '.join(str(value) for value in times)} ({kind})"
    )


def append_sources(answer: str, sources: list[str]) -> str:
    """Append unique evidence labels only to nonempty answers."""
    if not answer.strip():
        return answer
    return (
        answer
        + "\n\nRetrieved records:\n"
        + "\n".join(dict.fromkeys(sources))
        + "\nThese records may not cover every day or measurement you requested."
    )
