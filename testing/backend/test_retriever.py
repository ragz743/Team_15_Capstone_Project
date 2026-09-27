"""Tests for backend.retriever and the retrieve CLI script."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from backend.retriever import RAG_PROMPT_TEMPLATE, Retriever
from langchain_core.documents import Document


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store with standard stubs."""
    store = MagicMock()
    store.table = "live_index"
    store.distinct_metadata_values.return_value = []
    store.similarity_search.return_value = [
        Document(page_content="Temperature: 72F", metadata={"station": "Pullman"}),
        Document(page_content="Humidity: 45%", metadata={"station": "Pullman"}),
    ]
    return store


@pytest.fixture
def mock_chatbot():
    """Create a mock chatbot."""
    chatbot = MagicMock()
    chatbot.invoke.return_value = "The temperature at Pullman is 72F."
    return chatbot


def test_rag_prompt_template_has_required_variables() -> None:
    """Check that the prompt template contains context and question variables."""
    assert "context" in RAG_PROMPT_TEMPLATE.input_variables
    assert "question" in RAG_PROMPT_TEMPLATE.input_variables


def test_retriever_calls_vector_store(mock_vector_store, mock_chatbot) -> None:
    """Check that retrieve calls each vector store with the question."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the temperature?")
    mock_vector_store.similarity_search.assert_called_once_with("What is the temperature?", k=8, filter=None)


def test_retriever_calls_chatbot(mock_vector_store, mock_chatbot) -> None:
    """Check that retrieve passes a formatted prompt to the chatbot."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the temperature?")
    mock_chatbot.invoke.assert_called_once()


def test_retriever_returns_chatbot_response(mock_vector_store, mock_chatbot) -> None:
    """Check that retrieve returns the chatbot response."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    response = retriever.retrieve("What is the temperature?")
    assert response == "The temperature at Pullman is 72F."


def test_retriever_queries_all_stores(mock_chatbot) -> None:
    """Check that retrieve calls similarity_search on every store in the list."""
    store_a = MagicMock()
    store_a.table = "daily_index"
    store_a.distinct_metadata_values.return_value = []
    store_a.similarity_search.return_value = [Document(page_content="Rain: 0.2 in", metadata={})]

    store_b = MagicMock()
    store_b.table = "live_index"
    store_b.distinct_metadata_values.return_value = []
    store_b.similarity_search.return_value = [Document(page_content="Wind: 12 mph", metadata={})]

    retriever = Retriever([store_a, store_b], mock_chatbot)
    retriever.retrieve("What is the wind speed?")

    store_a.similarity_search.assert_called_once_with("What is the wind speed?", k=8, filter=None)
    store_b.similarity_search.assert_called_once_with("What is the wind speed?", k=8, filter=None)


def test_retriever_passes_explicit_filter_to_stores(mock_chatbot) -> None:
    """Check that an explicitly passed metadata filter overrides automatic detection."""
    store = MagicMock()
    store.table = "live_index"
    store.distinct_metadata_values.return_value = ["Pullman"]
    store.similarity_search.return_value = []

    retriever = Retriever([store], mock_chatbot)
    # Question mentions Pullman, but explicit filter requests Spokane
    retriever.retrieve("Temperature in Pullman?", filter={"station": "Spokane"})

    store.similarity_search.assert_called_once_with("Temperature in Pullman?", k=8, filter={"station": "Spokane"})


def test_retriever_detects_station_filter_automatically(mock_chatbot) -> None:
    """Check that a station mentioned in the question is detected and applied as a filter."""
    store = MagicMock()
    store.table = "live_index"
    store.distinct_metadata_values.side_effect = (
        lambda key: ["Pullman", "Pullman NE"] if key == "station" else ["Whitman"]
    )
    store.similarity_search.return_value = []

    retriever = Retriever([store], mock_chatbot)
    # Longer station match should be preferred over shorter prefix
    retriever.retrieve("How cold is it at Pullman NE today?")

    store.similarity_search.assert_called_once_with(
        "How cold is it at Pullman NE today?", k=8, filter={"station": "Pullman NE"}
    )


def test_retriever_prefers_station_over_county_filter(mock_chatbot) -> None:
    """Check that station filter takes priority when both station and county are present."""
    store = MagicMock()
    store.table = "live_index"
    store.distinct_metadata_values.side_effect = lambda key: ["Pullman"] if key == "station" else ["Whitman"]
    store.similarity_search.return_value = []

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("Is Pullman in Whitman county windy?")

    store.similarity_search.assert_called_once_with(
        "Is Pullman in Whitman county windy?", k=8, filter={"station": "Pullman"}
    )


def test_retriever_handles_empty_store_results(mock_chatbot) -> None:
    """Check that retrieve still calls the chatbot when no documents are returned."""
    store = MagicMock()
    store.table = "live_index"
    store.distinct_metadata_values.return_value = []
    store.similarity_search.return_value = []

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("What is the humidity?")

    mock_chatbot.invoke.assert_called_once()


def test_retriever_context_includes_section_label(mock_chatbot) -> None:
    """Check that the prompt sent to the chatbot contains a labeled section header."""
    store = MagicMock()
    store.table = "daily_index"
    store.distinct_metadata_values.return_value = []
    store.similarity_search.return_value = [Document(page_content="Temp: 65F", metadata={})]

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("Historical temperature?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "[Historical Data]" in prompt_arg


def test_retriever_accepts_single_store(mock_chatbot) -> None:
    """Check that Retriever wraps a bare PgVectorStore in a list."""
    from backend.vector_store import PgVectorStore

    store = MagicMock(spec=PgVectorStore)
    store.table = "forecast_index"
    store.distinct_metadata_values.return_value = []
    store.similarity_search.return_value = []

    retriever = Retriever(store, mock_chatbot)
    retriever.retrieve("Will it rain tomorrow?")

    store.similarity_search.assert_called_once_with("Will it rain tomorrow?", k=8, filter=None)


def test_retriever_prompt_contains_question(mock_vector_store, mock_chatbot) -> None:
    """Check that the formatted prompt contains the user's question."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the forecast for Pullman?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "What is the forecast for Pullman?" in prompt_arg


def test_retriever_prompt_contains_context(mock_vector_store, mock_chatbot) -> None:
    """Check that the formatted prompt includes document content from the store."""
    retriever = Retriever([mock_vector_store], mock_chatbot)
    retriever.retrieve("What is the humidity?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "Humidity: 45%" in prompt_arg


# retrieve CLI tests: _is_stale, _refresh, main()


def test_is_stale_returns_true_when_no_rows_today() -> None:
    """_is_stale returns True when live_index has no record for today."""
    from scripts.retrieve import _is_stale

    mock_conn = MagicMock()
    mock_conn.simple_query.return_value = [(0,)]
    with patch("backend.databases.pgvector.PgVectorConnection", return_value=mock_conn):
        assert _is_stale() is True


def test_is_stale_returns_false_when_rows_exist_today() -> None:
    """_is_stale returns False when live_index has at least one record for today."""
    from scripts.retrieve import _is_stale

    mock_conn = MagicMock()
    mock_conn.simple_query.return_value = [(5,)]
    with patch("backend.databases.pgvector.PgVectorConnection", return_value=mock_conn):
        assert _is_stale() is False


def test_is_stale_returns_false_on_db_error() -> None:
    """_is_stale returns False (non-blocking) when the database is unreachable."""
    from scripts.retrieve import _is_stale

    with patch("backend.databases.pgvector.PgVectorConnection", side_effect=Exception("connection refused")):
        assert _is_stale() is False


def test_refresh_runs_all_three_loaders() -> None:
    """_refresh calls .index() on DailyLoader, LiveLoader, and ForecastLoader."""
    from scripts.retrieve import _refresh

    daily, live, forecast = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("backend.loaders.daily_loader.DailyLoader", return_value=daily),
        patch("backend.loaders.live_loader.LiveLoader", return_value=live),
        patch("backend.loaders.forecast_loader.ForecastLoader", return_value=forecast),
    ):
        _refresh(MagicMock())

    daily.index.assert_called_once()
    live.index.assert_called_once()
    forecast.index.assert_called_once()


def test_refresh_prints_status_messages(capsys) -> None:
    """_refresh prints start and completion messages."""
    from scripts.retrieve import _refresh

    with (
        patch("backend.loaders.daily_loader.DailyLoader"),
        patch("backend.loaders.live_loader.LiveLoader"),
        patch("backend.loaders.forecast_loader.ForecastLoader"),
    ):
        _refresh(MagicMock())

    captured = capsys.readouterr()
    assert "stale" in captured.out.lower() or "refresh" in captured.out.lower()
    assert "complete" in captured.out.lower() or "refresh" in captured.out.lower()


def _make_main_mocks(is_stale: bool = False):
    """Return patch dict and mock retriever for testing main()."""
    mock_embedding = MagicMock()
    mock_chatbot = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = "The temperature is 72F."
    patches = {
        "scripts.retrieve.ModelFactory": MagicMock(
            load_from_models_yaml=MagicMock(return_value=(mock_embedding, mock_chatbot))
        ),
        "scripts.retrieve.PgVectorStore": MagicMock(),
        "scripts.retrieve.Retriever": MagicMock(return_value=mock_retriever),
        "scripts.retrieve._is_stale": MagicMock(return_value=is_stale),
        "scripts.retrieve._refresh": MagicMock(),
    }
    return patches, mock_retriever


def test_main_skips_refresh_when_not_stale() -> None:
    """main() does not call _refresh when _is_stale returns False."""
    patches, _ = _make_main_mocks(is_stale=False)
    with (
        patch("sys.argv", ["retrieve", "What is the temperature?"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    patches["scripts.retrieve._refresh"].assert_not_called()


def test_main_calls_refresh_when_stale() -> None:
    """main() calls _refresh when _is_stale returns True and --no-refresh is absent."""
    patches, _ = _make_main_mocks(is_stale=True)
    with (
        patch("sys.argv", ["retrieve", "What is the temperature?"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    patches["scripts.retrieve._refresh"].assert_called_once()


def test_main_no_refresh_flag_skips_stale_check() -> None:
    """main() skips _is_stale entirely when --no-refresh is passed."""
    patches, _ = _make_main_mocks(is_stale=True)
    with (
        patch("sys.argv", ["retrieve", "--no-refresh", "What is the temperature?"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    patches["scripts.retrieve._is_stale"].assert_not_called()
    patches["scripts.retrieve._refresh"].assert_not_called()


def test_main_passes_question_to_retriever() -> None:
    """main() joins CLI words into a single question and passes it to retrieve()."""
    patches, mock_retriever = _make_main_mocks(is_stale=False)
    with (
        patch("sys.argv", ["retrieve", "What", "is", "the", "temperature?"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    mock_retriever.retrieve.assert_called_once_with("What is the temperature?")


def test_main_creates_three_vector_stores() -> None:
    """main() creates stores for daily_index, live_index, and forecast_index."""
    patches, _ = _make_main_mocks(is_stale=False)
    mock_store_cls = patches["scripts.retrieve.PgVectorStore"]
    with (
        patch("sys.argv", ["retrieve", "question"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", mock_store_cls),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    tables = [c.kwargs.get("table") or c.args[1] for c in mock_store_cls.call_args_list]
    assert "daily_index" in tables
    assert "live_index" in tables
    assert "forecast_index" in tables


def test_main_prints_response(capsys) -> None:
    """main() prints the retriever response to stdout."""
    patches, _ = _make_main_mocks(is_stale=False)
    with (
        patch("sys.argv", ["retrieve", "What is the humidity?"]),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    assert "72F" in capsys.readouterr().out


def test_load_known_values_caches_result(mock_chatbot) -> None:
    """Check that _load_known_values returns cached dictionary on second call."""
    store = MagicMock()
    store.distinct_metadata_values.return_value = ["Pullman"]
    retriever = Retriever([store], mock_chatbot)

    first_call = retriever._load_known_values()
    second_call = retriever._load_known_values()

    assert first_call is second_call
    assert store.distinct_metadata_values.call_count == 2


def test_load_known_values_handles_store_exceptions(mock_chatbot) -> None:
    """Check that _load_known_values gracefully continues when a store throws an exception."""
    broken_store = MagicMock()
    broken_store.distinct_metadata_values.side_effect = RuntimeError("DB connection lost")

    working_store = MagicMock()
    working_store.distinct_metadata_values.side_effect = lambda key: ["Pullman"] if key == "station" else []

    retriever = Retriever([broken_store, working_store], mock_chatbot)
    known = retriever._load_known_values()

    assert known["station"] == ["Pullman"]


def test_detect_filter_returns_none_when_no_match(mock_chatbot) -> None:
    """Check that _detect_filter returns None when no known station/county is mentioned."""
    store = MagicMock()
    store.distinct_metadata_values.return_value = ["Pullman", "Whitman"]
    retriever = Retriever([store], mock_chatbot)

    assert retriever._detect_filter("How is the weather in Seattle?") is None


def test_detect_filter_matches_county_when_station_absent(mock_chatbot) -> None:
    """Check that county filter is applied when only county name appears in the question."""
    store = MagicMock()
    store.distinct_metadata_values.side_effect = lambda key: ["Pullman"] if key == "station" else ["Whitman"]
    retriever = Retriever([store], mock_chatbot)

    filter_result = retriever._detect_filter("What is the forecast for Whitman?")
    assert filter_result == {"county": "Whitman"}


def test_retrieve_uses_fallback_table_label_when_not_in_mapping(mock_chatbot) -> None:
    """Check that store.table is used directly as label if not found in _TABLE_LABELS."""
    store = MagicMock()
    store.table = "custom_unknown_index"
    store.distinct_metadata_values.return_value = []
    store.similarity_search.return_value = [Document(page_content="Sample content", metadata={})]

    retriever = Retriever([store], mock_chatbot)
    retriever.retrieve("What is happening?")

    prompt_arg = mock_chatbot.invoke.call_args[0][0][0]
    assert "[custom_unknown_index]" in prompt_arg
