"""Tests for the loaders._common functions."""

from backend.loaders import _common


def test_to_markdown_table() -> None:
    """Test the formatting of the to_markdown_table function is correct."""
    actual = [
        _common.MetadataQueryResult(
            "67",
            "Pullman",
            "Whitman",
            "WA",
            "123.4",
            "567.8",
            True,
            True,
            True,
            True,
            True,
        ),
        _common.MetadataQueryResult(
            "10001",
            "Quincy",
            "Grant",
            "WA",
            "100",
            "200",
            False,
            False,
            False,
            False,
            False,
        ),
    ]
    units = ["", "", "", "", "degrees", "degrees", "", "", "", "", ""]
    expected = (
        "| unit_id | station | county | state | station_lat in degrees | station_lng in degrees |"
        " air_temp | rel_humidity | precip | wind_speed | wind_dir |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 67 | Pullman | Whitman | WA | 123.4 | 567.8 | True | True | True | True | True |\n"
        "| 10001 | Quincy | Grant | WA | 100 | 200 | False | False | False | False | False |\n"
    )

    actual_table = _common.to_markdown_table(actual, units)
    assert actual_table == expected, f"found \n{actual_table},\nexpected\n{expected}"
