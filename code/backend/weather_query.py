"""Station identities and dates for weather retrieval."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


class QueryClarificationError(ValueError):
    """A question needs more information before records can be selected."""


class MissingLocationError(QueryClarificationError):
    """No location was supplied in this turn."""


class MissingDateError(QueryClarificationError):
    """No date was supplied in this turn."""


@dataclass(frozen=True)
class Station:
    """An indexed station's official identity."""

    id: str
    name: str
    county: str


@dataclass(frozen=True)
class WeatherQuery:
    """Inclusive date bounds and the station IDs allowed for a search."""

    station_ids: tuple[str, ...]
    start: date
    end: date
    county: str | None = None


def _contains(text: str, name: str) -> bool:
    return bool(name.strip()) and bool(re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text))


def _location(question: str, stations: list[Station]) -> tuple[tuple[str, ...], str | None]:
    text = " ".join(question.casefold().split())
    counties = {s.county.casefold() for s in stations if s.county and _contains(text, f"{s.county} county")}
    station_text = text
    for county in counties:
        station_text = re.sub(re.escape(f"{county.casefold()} county"), "", station_text)

    station_ids = re.findall(r"\bstation\s+(?:id\s*)?#?(\d+)\b", station_text)
    if len(set(station_ids)) > 1:
        raise QueryClarificationError("Please choose one station ID for this question.")
    station_id = station_ids[0] if station_ids else None
    matches = []
    remaining = station_text
    # Consume longest names first, so "Pullman East" does not also select "Pullman".
    for name in sorted({s.name for s in stations if s.name.strip()}, key=len, reverse=True):
        if _contains(remaining, name):
            matches.extend(s for s in stations if s.name == name)
            remaining = re.sub(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", "_station_", remaining)
    if re.search(r"_station_\s+(?:and|or|versus|vs)\b|\b(?:and|or|versus|vs)\s+_station_", remaining):
        raise QueryClarificationError("Please choose one station or one county for this question.")
    if re.search(r"\bcounty\b", remaining):
        raise QueryClarificationError("That county is not in the indexed data. Please choose an indexed county.")
    if station_id:
        if matches and all(s.id != station_id for s in matches):
            raise QueryClarificationError("The station name and ID do not match. Please clarify the station.")
        matches = [s for s in stations if s.id == station_id]
        if not matches:
            raise QueryClarificationError(
                "That station ID is not in the indexed data. Please choose an indexed station."
            )

    phrases = re.findall(
        r"\b(?:at|in|near|for|from)\s+(.+?)(?=\s+(?:at|in|near|for|on|from|between|during|today|yesterday|tomorrow|last|this|past|over)\b|[?!.;,]|$)",
        text,
    )
    names = [phrase.strip(" \"'") for phrase in phrases]
    known = {s.name.casefold() for s in stations} | {
        name for s in stations for name in (s.county.casefold(), s.county.casefold() + " county")
    }
    for name in names:
        if re.search(r"\b(?:and|or|versus|vs)\b", name) and not re.match(r"\d", name):
            raise QueryClarificationError("Please choose one station or one county for this question.")
        is_location = name in known or any(s.name.casefold().startswith(name + " ") for s in stations)
        is_other = re.match(
            r"\d|(?:" + _MONTH_PATTERN + r")\b|(?:degrees|fahrenheit|celsius|inches|mph|last|this|past)\b", name
        )
        if not is_location and not is_other and not re.fullmatch(r"station\s+(?:id\s*)?#?\d+", name):
            raise QueryClarificationError(
                "I could not resolve that location. Please use an indexed station name or county."
            )
    if not matches and not counties and names:
        matches = [s for s in stations if any(s.name.casefold().startswith(name + " ") for name in names)]
    if not matches and not counties:
        counties = {s.county.casefold() for s in stations if s.county and _contains(text, s.county)}
    if len(counties) > 1:
        raise QueryClarificationError("Please choose one county for this question.")
    county = next(iter(counties), None)
    if matches and county:
        matches = [s for s in matches if s.county.casefold() == county]
        if not matches:
            raise QueryClarificationError("The named station and county do not match. Please clarify the location.")
    if len({s.id for s in matches}) > 1:
        choices = "; ".join(f"{s.name} (station {s.id}, {s.county} County)" for s in matches[:6])
        raise QueryClarificationError(f"Please specify one station: {choices}.")
    if matches:
        return (matches[0].id,), county
    if counties:
        return tuple(sorted({s.id for s in stations if s.county.casefold() in counties})), county
    raise MissingLocationError(
        "Please specify an indexed station name, station ID, or county. "
        "I could not resolve the requested location from the indexed data."
    )


_MONTHS = {
    name.casefold(): number
    for number in range(1, 13)
    for name in (calendar.month_name[number], calendar.month_abbr[number])
}
_MONTHS["sept"] = 9
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_PATTERN = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b({_MONTH_PATTERN})\.?\s+(\d{{1,2}})"
    r"(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",  # codespell:ignore nd
    re.IGNORECASE,
)
_RELATIVE_DATE_PATTERN = re.compile(
    r"\b(today|yesterday|tomorrow|last week|this week|last month|this month|(?:last|past) \d+ days|\d+ days ago)\b",
    re.IGNORECASE,
)


def _dates(question: str, today: date) -> tuple[date, date]:
    text = question.casefold()
    if re.search(r"\b\d{1,2}/\d{1,2}", text):
        raise QueryClarificationError("Please write dates as YYYY-MM-DD to avoid ambiguous day/month order.")
    found = list(_DATE_PATTERN.finditer(text))
    relative = list(_RELATIVE_DATE_PATTERN.finditer(text))
    if (found and relative) or len(relative) > 1 or len(found) > 2:
        raise QueryClarificationError("Please specify one date or one inclusive date range.")
    if found:
        try:
            dates = [
                date(int(m[3] or today.year), _MONTHS[m[1]], int(m[2])) if m[1] else date.fromisoformat(m[0])
                for m in found
            ]
        except ValueError as exc:
            raise QueryClarificationError("That date is invalid. Please use a valid YYYY-MM-DD date.") from exc
        if len(dates) == 2:
            if any(m[1] and not m[3] for m in found) and any(not m[1] or m[3] for m in found):
                raise QueryClarificationError("Please include the year at both ends of the date range.")
            separator = text[found[0].end() : found[1].start()]
            if not re.search(r"\b(?:to|through)\b|[-–—]", separator) and not (
                "between" in text[: found[0].start()] and separator.strip() == "and"
            ):
                raise QueryClarificationError("For a date range, use 'from YYYY-MM-DD to YYYY-MM-DD'.")
        if re.search(r"\b(?:last|next|previous|year|ago)\b|\band\s+\d", _DATE_PATTERN.sub("", text)):
            raise QueryClarificationError("Please specify the complete date or both endpoints of the date range.")
        start, end = dates[0], dates[-1]
    elif relative:
        value = relative[0][0]
        remaining = text[: relative[0].start()] + text[relative[0].end() :]
        if re.search(r"\b(?:last|next|previous|year|ago|" + _MONTH_PATTERN + r")\b|\b\d{4}\b", remaining):
            raise QueryClarificationError("Please specify one date or one inclusive date range.")
        monday = today - timedelta(days=today.weekday())
        match value:
            case "today":
                start = end = today
            case "yesterday":
                start = end = today - timedelta(days=1)
            case "tomorrow":
                start = end = today + timedelta(days=1)
            case "last week":
                start, end = monday - timedelta(days=7), monday - timedelta(days=1)
            case "this week":
                start, end = monday, today
            case "last month":
                end = today.replace(day=1) - timedelta(days=1)
                start = end.replace(day=1)
            case "this month":
                start, end = today.replace(day=1), today
            case _:
                days = int(next(part for part in value.split() if part.isdigit()))
                if not 1 <= days <= 366:
                    raise QueryClarificationError("Please use a period between 1 and 366 days.")
                start = today - timedelta(days=days)
                end = start if value.endswith("ago") else today - timedelta(days=1)
    else:
        if re.search(
            r"\b(?:on|during|last|next|previous|ago|year|"
            + _MONTH_PATTERN
            + r")\b|\d{4}-|\d+(?:st|nd|rd|th)\b",  # codespell:ignore nd
            text,
        ):
            raise QueryClarificationError("Please specify a complete valid date or inclusive date range.")
        raise MissingDateError(
            "Please specify a date, such as YYYY-MM-DD or yesterday, "
            "or a range such as 'from YYYY-MM-DD to YYYY-MM-DD'."
        )
    if start > end:
        raise QueryClarificationError("The start date must be on or before the end date.")
    return start, end


def resolve_weather_query(question: str, stations: list[Station], *, today: date | None = None) -> WeatherQuery:
    """Resolve one indexed location and a calendar day/range in Washington time."""
    if re.search(
        r"\b(?:except|excluding|not|before|after|since|until)\b|\d{1,2}:\d{2}|\d\s*(?:am|pm)\b", question, re.IGNORECASE
    ):
        raise QueryClarificationError(
            "Please specify one location and an inclusive date or date range, without exclusions or times."
        )
    if not stations:
        raise QueryClarificationError(
            "No stations are available in the indexed data. Weather records must be indexed first."
        )
    ids, county = _location(question, stations)
    start, end = _dates(question, today or datetime.now(ZoneInfo("America/Los_Angeles")).date())
    return WeatherQuery(ids, start, end, county)
