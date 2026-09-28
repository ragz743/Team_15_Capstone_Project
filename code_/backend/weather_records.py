"""Format retrieved weather records and source labels."""

from langchain_core.documents import Document

TABLE_LABELS = {"daily_index": "Historical Data", "live_index": "Current Conditions", "forecast_index": "Forecast Data"}


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
