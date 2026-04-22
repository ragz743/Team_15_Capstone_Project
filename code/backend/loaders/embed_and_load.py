"""Offline Pipeline.

Chunk AgWeatherNet schema descriptions and weather context records, embed them
with the configured embedding model, and upsert the results into the pgvector store.
"""

# This script is the ONLY write path to the agwn_embeddings table and must
# NEVER be called from user-facing request handlers (FR-12). Run it:
# - Once at initial deployment to index schema documentation (FR-16)
# - Again whenever the AgWeatherNet database schema changes
# - Again whenever station descriptions or metric definitions are updated
# - On a per-station basis to re-index after delete_by_station()

# The embedding model is loaded from models.yaml using the same dynamic

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import time
from datetime import date

import yaml

from ..databases.vector_store import ChunkMetadata, VectorStore

# PATH BOOTSTRAP
# Allows the path to be run directly (python .../embed_and_load.py) while
# still resolving the sibling packages in code/backend/.
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# LOGGING
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# CONSTANTS

VALID_DATA_TYPES = {"live", "historical", "forecast", "aggregate", "schema"}
# Tune CHUNK_SIZE and CHUNK_OVERLAP if embedding model has a tighter token budget
CHUNK_SIZE = 512  # Characters per chunk
CHUNK_OVERLAP = 64  # Overlap between adjacent chunks


# CHUNKING


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping character-level windows.

    Overlap preserves sentence context across chunk boundaries, which
    improves retrieval precision (NFR-2).

    Parameters
    ----------
    text:
        Input text to split.
    chunk_size:
        Target chunk length in characters.
    overlap:
        Number of characters shared between adjacent chunks.

    Returns: List of non-empty chunk strings.

    """
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start += chunk_size - overlap
    return chunks


# DOCUMENT LOADERS


def load_text_file(
    file_path: str,
    base_metadata: dict,
) -> list[tuple[str, ChunkMetadata]]:
    """Load a .txt or .md file and return (chunk, ChunkMetadata) pairs.

    Used for schema documentation, station description prose, and any unstructured text
    that should be indexed as 'schema' context.

    Parameters
    ----------
    file_path:
        Path to the plain-text or Markdown file.
    base_metadata:
        Dict supplying default values for ChunkMetadata fields
        (data_type, station_id, metric, source_table).

    Returns: List of (chunk, ChunkMetadata) tuples ready for embedding.

    """
    with open(file_path, encoding="utf-8") as fh:
        content = fh.read()

    return [
        (
            chunk,
            ChunkMetadata(
                data_type=base_metadata.get("data_type", "schema"),
                station_id=base_metadata.get("station_id"),
                metric=base_metadata.get("metric"),
                source_table=base_metadata.get("source_table"),
            ),
        )
        for chunk in chunk_text(content)
    ]


def load_json_records(
    file_path: str,
    base_metadata: dict,
) -> list[tuple[str, ChunkMetadata]]:
    """Load a JSON array of weather records and return (chunk, ChunkMetadata) pairs.

    Each record is serialized to a human-readable key-value string so the LLM
    receives labelled values rather than raw JSON in its context (FR-34).

    Expected JSON format:

      [
        {
          "station_id": "pullman_wsda",
          "timestamp": "2026-04-17T14:00:00Z",
          "temperature_f": 54.2,
          "percipitation_in": 0.0
        },
        ...
      ]

    Parameters
    ----------
    file_path:
        Path to the JSON file containing a list of weather records.
    base_metadata:
        Dict supplying default values for ChunkMetadata fields.

    Returns
    -------
        List of (chunk, ChunkMetadata) tuples ready for embedding.

    Raises
    ------
        ValueError: If the JSON file does not contain a top-level list.

    """
    with open(file_path, encoding="utf-8") as fh:
        records: list[dict] = json.load(fh)

    if not isinstance(records, list):
        raise ValueError(f"Expected a JSON array in {file_path}, got {type(records).__name__}")

    pairs: list[tuple[str, ChunkMetadata]] = []
    for rec in records:
        station_id: str | None = rec.get("station_id") or base_metadata.get("station_id")

        # Convert each record to labelled prose so embeddings capture semantics
        text = "\n".join(f"{k}: {v}" for k, v in rec.items())
        meta = ChunkMetadata(
            station_id=station_id,
            data_type=base_metadata.get("data_type", "historical"),
            data_start=rec.get("data_start") or base_metadata.get("data_start"),
            data_end=rec.get("data_end") or base_metadata.get("data_end"),
            metric=base_metadata.get("metric"),
            source_table=base_metadata.get("source_table"),
        )
        pairs.append((text, meta))

    return pairs


# MODEL LOADER


def load_embedding_model(models_yaml_path: str):
    """Instantiate the embedding model described in models.yaml.

    Mirrors the project's existing model-loading convention (README) so the same
    class and configuration is used by both the offline loader and the live
    pipeline (NFR-7 modularity, NFR-2 consistency).

    Parameters
    ----------
    models_yaml_path:
        Path to the models.yaml configuration file at the repo root.

    """
    with open(models_yaml_path, encoding="utf-8") as fh:
        config: dict = yaml.safe_load(fh)

    emb_cfg: dict = config["models"]["embedding"]
    class_file: str = emb_cfg["class_file"].replace(".py", "")
    class_name: str = emb_cfg["class"]
    kwargs: dict = emb_cfg.get("kwargs", {})

    # Add modules/ directory to system.path so the class file can be imported
    models_dir = os.path.join(BACKEND_DIR, "models")
    if models_dir not in sys.path:
        sys.path.insert(0, models_dir)

    module = importlib.import_module(class_file)
    cls = getattr(module, class_name)
    logger.info("Loaded embedding model: %s.%s kwargs=%s", class_file, class_name, kwargs)
    return cls(**kwargs)


# DATE-RANGE GUARD


def validate_date_range(data_start: str | None, data_end: str | None) -> None:
    """Warn when a chunk's date range exceed MAX_DATE_RANGE_DAYS.

    Chunks that span very long ranges produce vague context; splitting them
    into smaller time windows produces better retrieval (FR-13).
    """
    from ..databases.vector_store import MAX_DATE_RANGE_DAYS

    if data_start is None or data_end is None:
        return
    try:
        start = date.fromisoformat(data_start)
        end = date.fromisoformat(data_end)
        span = (end - start).days
        if span > MAX_DATE_RANGE_DAYS:
            logger.warning(
                "Chunk date range %s -> %s spans %d days (> MAX_DATE_RANGE_DAYS=%d). "
                "Consider splitting into smaller time windows for better retrieval.",
                data_start,
                data_end,
                span,
                MAX_DATE_RANGE_DAYS,
            )
    except ValueError:
        pass  # Non-ISO dates are fine; skip the check


# FILE COLLECTION


def collect_files(source: str) -> list[str]:
    """Return sorted .txt, .md, and .json files at source (file or directory)."""
    if os.path.isfile(source):
        return [source]
    if os.path.isdir(source):
        return [os.path.join(source, f) for f in sorted(os.listdir(source)) if f.endswith((".txt", ".md", ".json"))]
    raise FileNotFoundError(f"Source path not found: {source!r}")


# MAIN


def main() -> None:
    """Entry point for the script.

    Parses command-line arguments, processes documents, generates embeddings, and loads them into the vector store.
    """
    parser = argparse.ArgumentParser(
        description="Chunk, embed, and load documents into the AgWeatherNet pgvector store.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source", required=True, help="Path to a file or directory of .txt/.md/.json documents to index."
    )
    parser.add_argument(
        "--models-yaml",
        default="models.yaml",
        help="Path to models.yaml (repo root).",
    )
    parser.add_argument(
        "--data-type",
        default="schema",
        choices=sorted(VALID_DATA_TYPES),
        help="data_type tag applied to all chunks from this run.",
    )
    parser.add_argument(
        "--station-id",
        default=None,
        help="AgWeatherNet station_id to tag all chunks with.",
    )
    parser.add_argument(
        "--source_table",
        default=None,
        help="AgWeatherNet DB table name to tag all chunks with.",
    )
    parser.add_argument(
        "--metric",
        default=None,
        help="Weather metric name to tag all chunks with (e.g. temperature).",
    )
    parser.add_argument(
        "--data-start",
        default=None,
        help="ISO-8601 start date for time-scoped chunks (e.g. 2026-01-01).",
    )
    parser.add_argument(
        "--data-end",
        default=None,
        help="ISO-8601 end date for time-scoped chunks (e.g. 2026-01-01).",
    )
    parser.add_argument(
        "--embedding-dim",
        type=int,
        default=1024,
        help="Embedding vector dimension - must match the model in models.yaml.",
    )
    parser.add_argument(
        "--delete-station",
        default=None,
        metavar="STATION_ID",
        help="Delete all existing chunks for this station_id before loading. Use when re-indexing a station.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Embed chunks but do NOT write to the database.",
    )
    args = parser.parse_args()

    # Load embedding model
    logger.info("Loading embedding model from %s ...", args.models_yaml)
    embed_model = load_embedding_model(args.models_yaml)

    # Connect to pgvector
    vs = VectorStore(embedding_dim=args.embedding_dim)
    if not args.dry_run:
        vs.connect()
        vs.create_table()

        if args.delete_station:
            deleted = vs.delete_by_station(args.delete_station)
            logger.info("Deleted %d chunks for station=%s", deleted, args.delete_station)

    # Collect source files
    try:
        files = collect_files(args.source)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    logger.info("Found %d file(s) to process.", len(files))

    base_metadata = {
        "data_type": args.data_type,
        "station_id": args.station_id,
        "source_table": args.source_table,
        "metric": args.metric,
        "date_start": args.data_start,
        "date_end": args.data_end,
    }

    total_chunks = 0
    total_files = 0

    for file_path in files:
        logger.info("Processing %s", file_path)
        try:
            if file_path.endswith(".json"):
                pairs = load_json_records(file_path, base_metadata)
            else:
                pairs = load_text_file(file_path, base_metadata)
        except Exception as exc:
            logger.warning("Skipping %s - could not read: %s", file_path, exc)
            continue

        for content, metadata in pairs:
            validate_date_range(metadata.data_start, metadata.data_end)

            # Embed via Embedding (or whatever model is in models.yaml)
            t0 = time.monotonic()
            try:
                # Use embed() shortcut (plain string -> vector)
                embedding: list[float] = embed_model.embed(content)
            except Exception as exc:
                logger.warning("Embedding failed for chunk (len=%d chars): %s", len(content), exc)
                continue
            embed_ms = (time.monotonic() - t0) * 1000.0

            if args.dry_run:
                logger.info(
                    "[DRY-RUN] chunk len=%d chars embed_ms=%.0f station=%s type=%s table=%s",
                    len(content),
                    embed_ms,
                    metadata.station_id,
                    metadata.data_type,
                    metadata.source_table,
                )
            else:
                try:
                    row_id = vs.upsert_chunk(content, embedding, metadata)
                    logger.info(
                        "Upserted id=%d embed_ms=%.0f station=%s type=%s",
                        row_id,
                        embed_ms,
                        metadata.station_id,
                        metadata.data_type,
                    )
                except Exception as exc:
                    logger.error("Failed to upsert chunk: %s", exc)
                    continue

            total_chunks += 1

        total_files += 1

    logger.info(
        "Done. Processed %d file(s) and %d chunk(s)%s.",
        total_files,
        total_chunks,
        " (dry-run - nothing written to DB)" if args.dry_run else "",
    )

    if not args.dry_run:
        vs.disconnect()


if __name__ == "__main__":
    main()
