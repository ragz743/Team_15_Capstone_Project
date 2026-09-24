"""Station identities and dates for weather retrieval."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta


class QueryClarificationError(ValueError):
    """A question needs more information before records can be selected."""


class MissingDateError(QueryClarificationError):
    """No date was supplied in this turn."""


@dataclass(frozen=True)
class Station:
    """An indexed station's official identity."""

    id: str
    name: str
    county: str


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
