"""CLI map inputs and timestamp freshness behavior."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from scripts import retrieve
from weather_fixtures import POINT


@pytest.mark.parametrize("exists", [True, False])
def test_freshness_compares_timestamp_date_in_washington_and_closes_connection(monkeypatch, exists):
    """Full observation timestamps must match without reindexing on every command."""
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.simple_query.return_value = [(exists,)]
    monkeypatch.setattr("backend.databases.pgvector.PgVectorConnection", lambda: connection)
    monkeypatch.setattr(retrieve, "washington_today", lambda: date(2026, 9, 9))
    assert retrieve._is_stale() is not exists
    query, params = connection.simple_query.call_args.args
    assert b"left(metadata->>'timestamp', 10) = %s" in query
    assert b"EXISTS" in query and params == ("2026-09-09",)
    connection.__exit__.assert_called_once()


def test_freshness_failure_closes_connection_without_triggering_refresh(monkeypatch):
    """A failed read must not leak the connection or start writes to every index."""
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.simple_query.side_effect = RuntimeError("read failed")
    monkeypatch.setattr("backend.databases.pgvector.PgVectorConnection", lambda: connection)
    assert retrieve._is_stale() is False
    connection.__exit__.assert_called_once()


def test_cli_passes_point_and_preserves_question(monkeypatch, capsys):
    """Manual requests use the same point selection flow as browser requests."""
    model, retriever = MagicMock(), MagicMock()
    retriever.retrieve.return_value = "Weather response"
    monkeypatch.setattr(retrieve.ModelFactory, "load_from_models_yaml", lambda: (model, model))
    monkeypatch.setattr(retrieve, "PgVectorStore", MagicMock())
    monkeypatch.setattr(retrieve, "Retriever", lambda *_: retriever)
    monkeypatch.setattr(
        "sys.argv", ["retrieve", "--no-refresh", "--latitude", "46.73", "--longitude", "-117.18", "Rain yesterday?"]
    )
    retrieve.main()
    retriever.retrieve.assert_called_once_with("Rain yesterday?", point=POINT)
    assert "Weather response" in capsys.readouterr().out


def test_refresh_runs_all_three_loaders():
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


def test_refresh_prints_status_messages(capsys):
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


def _make_main_mocks(is_stale=False):
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


def test_main_skips_refresh_when_not_stale():
    """main() does not call _refresh when _is_stale returns False."""
    patches, _ = _make_main_mocks(is_stale=False)
    with (
        patch("sys.argv", ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "What is the temperature?"]),
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


def test_main_calls_refresh_when_stale():
    """main() calls _refresh when _is_stale returns True and --no-refresh is absent."""
    patches, _ = _make_main_mocks(is_stale=True)
    with (
        patch("sys.argv", ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "What is the temperature?"]),
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


def test_main_no_refresh_flag_skips_stale_check():
    """main() skips _is_stale entirely when --no-refresh is passed."""
    patches, _ = _make_main_mocks(is_stale=True)
    with (
        patch(
            "sys.argv",
            ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "--no-refresh", "What is the temperature?"],
        ),
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


def test_main_passes_question_to_retriever():
    """main() joins CLI words into a single question and passes it to retrieve()."""
    patches, mock_retriever = _make_main_mocks(is_stale=False)
    with (
        patch(
            "sys.argv",
            ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "What", "is", "the", "temperature?"],
        ),
        patch("scripts.retrieve._is_stale", patches["scripts.retrieve._is_stale"]),
        patch("scripts.retrieve._refresh", patches["scripts.retrieve._refresh"]),
        patch("scripts.retrieve.ModelFactory", patches["scripts.retrieve.ModelFactory"]),
        patch("scripts.retrieve.PgVectorStore", patches["scripts.retrieve.PgVectorStore"]),
        patch("scripts.retrieve.Retriever", patches["scripts.retrieve.Retriever"]),
        patch("dotenv.load_dotenv"),
    ):
        from scripts.retrieve import main

        main()
    mock_retriever.retrieve.assert_called_once_with("What is the temperature?", point=POINT)


def test_main_creates_three_vector_stores():
    """main() creates stores for daily_index, live_index, and forecast_index."""
    patches, _ = _make_main_mocks(is_stale=False)
    mock_store_cls = patches["scripts.retrieve.PgVectorStore"]
    with (
        patch("sys.argv", ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "question"]),
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


def test_main_prints_response(capsys):
    """main() prints the retriever response to stdout."""
    patches, _ = _make_main_mocks(is_stale=False)
    with (
        patch("sys.argv", ["retrieve", "--latitude", "46.73", "--longitude", "-117.18", "What is the humidity?"]),
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
