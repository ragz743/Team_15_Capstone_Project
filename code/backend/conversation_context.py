"""Resolve partial weather questions without treating conversation text as evidence."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from backend.weather_query import (
    _DATE_PATTERN,
    _RELATIVE_DATE_PATTERN,
    MissingDateError,
    MissingLocationError,
    QueryClarificationError,
    Station,
    WeatherQuery,
    _dates,
    _location,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

TIMEZONE = ZoneInfo("America/Los_Angeles")
_SUBJECTS = {
    "temperature": r"\b(?:temperature|temperatures|temp|hot|cold)\b",
    "humidity": r"\b(?:humidity|humid)\b",
    "precipitation": r"\b(?:precipitation|precip|rain|rainfall)\b",
    "wind": r"\bwind(?: speed| direction)?\b",
    "frost": r"\b(?:frost|freeze|freezing)\b",
    "soil temperature": r"\bsoil\b",
    "solar radiation": r"\b(?:solar|radiation)\b",
    "weather": r"\b(?:weather|conditions|forecast)\b",
}


def _location_question(stations: list[Station], *, all_locations: bool = False) -> str:
    if all_locations:
        counties = sorted({station.county for station in stations if station.county})
        choices = ", ".join(f"{county} County" for county in counties[:6])
        return (
            "I can check one station or county at a time. "
            + (f"Which county should I use: {choices}?" if choices else "Which station should I use?")
            + ""
        )
    return "Which location should I check? Name a station or county."


class ConversationContext(BaseModel):
    """Validated partial intent belonging to one conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    station_ids: list[str] = Field(default_factory=list, max_length=1000)
    county: str | None = Field(default=None, max_length=100)
    start: date | None = None
    end: date | None = None
    subject: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid_context(self):
        """Reject contradictory dates and unknown subject values at the boundary."""
        if bool(self.start) != bool(self.end) or (self.start and self.end and self.start > self.end):
            raise ValueError("Context needs a valid inclusive date range")
        if any(not re.fullmatch(r"\d{1,20}", value) for value in self.station_ids):
            raise ValueError("Invalid station ID")
        if self.subject and any(part not in _SUBJECTS for part in self.subject.split(", ")):
            raise ValueError("Unsupported weather subject")
        return self


@dataclass(frozen=True)
class ResolvedTurn:
    """The next context and either a safe selection or a clarification."""

    context: ConversationContext
    selection: WeatherQuery | None
    question: str
    clarification: str | None = None


def resolve_turn(
    question: str,
    stations: list[Station],
    previous: ConversationContext | None = None,
    *,
    today: date | None = None,
    metadata_filter: dict[str, str] | None = None,
) -> ResolvedTurn:
    """Apply explicit replacements and inherit only supported weather follow-ups."""
    today = today or datetime.now(TIMEZONE).date()
    # Correct common weather-word typos only; never fuzzy-match a station identity.
    text = re.sub(
        r"\b(?:wather|wether|weater|wheather|weahter)\b",  # codespell:ignore wether,wheather,weahter
        "weather",
        question.strip(),
        flags=re.I,
    )
    all_reply = bool(re.fullmatch(r"(?:all(?: of (?:it|them))?|everything|both)(?: please)?[.!?]*", text, re.I))
    prior_intent = previous is not None and bool(previous.station_ids or previous.start or previous.subject)
    all_locations = bool(
        re.search(r"\b(?:all (?:available )?(?:stations|counties|locations)|everywhere)\b", text, re.I)
    )
    all_dates = bool(re.search(r"\b(?:all (?:dates|time)|all[- ]time|every date)\b", text, re.I))
    if all_reply and prior_intent and previous is not None:
        # The single missing-field question determines what a short reply means.
        all_locations = not previous.station_ids
        all_dates = bool(previous.station_ids) and previous.start is None
    subjects = [name for name, pattern in _SUBJECTS.items() if re.search(pattern, text, re.I)]
    all_measurements = bool(re.search(r"\ball (?:weather )?(?:measurements|readings|conditions)\b", text, re.I))
    if all_measurements or (all_reply and not all_locations and not all_dates):
        subjects = ["weather"]
    if len(subjects) > 1 and "weather" in subjects:
        subjects.remove("weather")
    if "soil temperature" in subjects and "temperature" in subjects:
        subjects.remove("temperature")
    followup = bool(re.match(r"^(?:and\b|also\b|what about\b|how about\b|same\b)", text, re.I))
    errors: list[str] = []
    location = None
    period = None
    bad_location = bad_date = False
    location_text = text
    if previous and previous.station_ids:
        # Personal-place references mean the station already chosen for this chat.
        location_text = re.sub(
            r"\b(?:near me|around me|here|(?:at|in|for) (?:my|this|the selected) (?:location|station))\b",
            "",
            location_text,
            flags=re.I,
        )
    try:
        location = _location(re.sub(r"^(?:and|also)\s+", "", location_text, flags=re.I), stations)
    except MissingLocationError:
        pass
    except QueryClarificationError as exc:
        bad_location = True
        errors.append(str(exc))
    try:
        period = _dates(text, today)
    except MissingDateError:
        pass
    except QueryClarificationError as exc:
        bad_date = True
        errors.append(str(exc))
    # Short unknown replacements must not inherit the last valid station.
    remainder = re.sub(r"^(?:and|also|what about|how about)\s+(?:the\s+)?", "", text, flags=re.I).strip(" ?!.")
    location_words = _DATE_PATTERN.sub("", remainder)
    location_words = _RELATIVE_DATE_PATTERN.sub("", location_words)
    location_words = re.sub(r"\b(?:on|from|to|through|between|and)\b", "", location_words, flags=re.I).strip(" ,?!.")
    if not subjects and not location and not errors and location_words and (followup or period) and not all_reply:
        bad_location = True
        errors.append(
            f"I could not resolve that location or follow-up: '{remainder}'. "
            "Please specify the station, date or measurement."
        )
    if re.search(r"\b(?:except|excluding|not|before|after|since|until)\b|\d{1,2}:\d{2}|\d\s*(?:am|pm)\b", text, re.I):
        bad_date = True
        errors.append("Please specify one location and an inclusive date range, without exclusions or times.")
    continuing = (
        followup
        or all_reply
        or all_locations
        or all_dates
        or bool(subjects)
        or bool(location)
        or bool(period)
        or bool(errors)
    )
    context = previous if previous and continuing else ConversationContext()
    ids, county = location if location else (tuple(context.station_ids), context.county)
    start, end = period if period else (context.start, context.end)
    if bad_location:
        ids, county = (), None
    if bad_date:
        start = end = None
    if len(ids) > 1 and not county:
        ids = ()
        errors.append("Please choose one station or one county for this conversation.")
    if ids and not set(ids).issubset({s.id for s in stations}):
        ids, county = (), None
        errors.append("The previous station is no longer indexed. Please choose an indexed location.")
    if county and ids and any(s.county.casefold() != county.casefold() for s in stations if s.id in ids):
        ids, county = (), None
        errors.append("The station and county do not match. Please clarify the location.")
    if metadata_filter:
        supported = {"station", "county", "state", "id"}
        if set(metadata_filter) - supported:
            errors.append("Unsupported metadata filter. Use station, county, state or id.")
        candidates = stations
        for key, value in metadata_filter.items():
            if key not in {"station", "county", "id"}:
                continue
            attr = "name" if key == "station" else key
            candidates = [s for s in candidates if str(getattr(s, attr)).casefold() == value.casefold()]
        allowed = {s.id for s in candidates}
        has_location_filter = bool(set(metadata_filter) & {"station", "county", "id"})
        if ids and not set(ids).issubset(allowed):
            errors.append("The location conflicts with the supplied filter. Please use matching constraints.")
            ids, county = (), None
        elif not ids and not bad_location and allowed and has_location_filter:
            ids = tuple(sorted(allowed))
            county = metadata_filter.get("county")
        elif not allowed:
            errors.append("The supplied filter does not match an indexed location.")
    if len(ids) > 1 and not county:
        ids = ()
        errors.append("Please choose one station or one county for this conversation.")
    subject = ", ".join(subjects) if subjects else context.subject or ("weather" if location else None)
    # A present-tense general weather question means an overview for today. Past,
    # forecast and malformed dates still need an explicit period. An existing
    # follow-up date stays fixed unless the user makes a fresh present-tense ask.
    present_weather = bool(re.search(r"\b(?:what(?:['’]?s| is)|how(?:['’]?s| is)) (?:the )?weather\b", text, re.I))
    historical_or_forecast = bool(
        re.search(r"\b(?:was|were|did|will|forecast|historical|past|last|next|ago)\b", text, re.I)
    )
    if (
        subjects == ["weather"]
        and not period
        and not bad_date
        and not all_dates
        and not historical_or_forecast
        and (present_weather or (not start and not context.subject))
    ):
        start = end = today
    if all_locations and not (location and location[1]):
        ids, county = (), None
        errors = [_location_question(stations, all_locations=True)]
    if all_dates:
        start = end = None
        errors = ["I need a specific day or date range. Which period should I check—for example, today or last week?"]
    updated = ConversationContext(station_ids=list(ids), county=county, start=start, end=end, subject=subject)
    if errors:
        return ResolvedTurn(updated, None, text, errors[0])
    if not ids:
        prefix = "I’ll check today’s weather. " if subject == "weather" and start == end == today else ""
        return ResolvedTurn(updated, None, text, prefix + _location_question(stations))
    if not start:
        return ResolvedTurn(updated, None, text, "For which day or period? You can say today, yesterday, or last week.")
    if not subject:
        return ResolvedTurn(
            updated, None, text, "Would you like an overall weather report or a particular measurement?"
        )
    assert start is not None and end is not None
    selection = WeatherQuery(tuple(ids), start, end, county)
    names = "; ".join(f"{s.name} (station {s.id})" for s in stations if s.id in ids)
    resolved = f"{text}\nResolved weather request: {subject}; {names}; {start.isoformat()} through {end.isoformat()}."
    return ResolvedTurn(updated, selection, resolved)
