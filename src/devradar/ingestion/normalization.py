"""Deterministic V1 normalization and canonical job hashing."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
from urllib.parse import unquote_plus, urljoin, urlsplit, urlunsplit

from devradar.catalog.models import JobLevel

_ZERO_WIDTH_CHARACTERS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")
_NUMBER_PATTERN = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")


@dataclass(frozen=True, slots=True)
class NormalizedValue[T]:
    raw: str | None
    value: T | None
    warnings: tuple[str, ...] = ()


def normalize_text(raw: str | None) -> NormalizedValue[str]:
    if raw is None:
        return NormalizedValue(raw=None, value=None)

    unicode_normalized = unicodedata.normalize("NFC", raw).translate(_ZERO_WIDTH_CHARACTERS)
    lines = []
    for line in unicode_normalized.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        collapsed = " ".join(line.split())
        if collapsed:
            lines.append(collapsed)
    value = "\n".join(lines) or None
    return NormalizedValue(raw=raw, value=value)


def normalize_canonical_url(
    raw: str,
    *,
    base_url: str,
    allowed_hosts: tuple[str, ...],
    removable_query_params: frozenset[str] = frozenset(),
) -> NormalizedValue[str]:
    cleaned = normalize_text(raw).value
    if cleaned is None or "\n" in cleaned:
        raise ValueError("URL must not be blank or multiline")

    resolved = urljoin(base_url, cleaned)
    parsed = urlsplit(resolved)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL has an invalid port") from error

    hostname = parsed.hostname.lower() if parsed.hostname else None
    if (
        parsed.scheme != "https"
        or hostname not in allowed_hosts
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise ValueError("URL must be HTTPS on an allowed host without user info or custom port")

    query_parts = []
    removed = False
    for part in parsed.query.split("&") if parsed.query else ():
        encoded_name = part.split("=", 1)[0]
        if unquote_plus(encoded_name) in removable_query_params:
            removed = True
            continue
        query_parts.append(part)

    normalized = urlunsplit(("https", hostname, parsed.path or "/", "&".join(query_parts), ""))
    warnings = ("removed_allowlisted_query_parameter",) if removed else ()
    return NormalizedValue(raw=raw, value=normalized, warnings=warnings)


class WorkMode(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class NormalizedLocation:
    city: str | None
    province: str | None
    work_mode: WorkMode | None


_LOCATION_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, str]], ...] = (
    (
        re.compile(r"\b(?:ho chi minh city|ho chi minh|hcmc|hồ chí minh)\b", re.IGNORECASE),
        ("Ho Chi Minh City", "Ho Chi Minh City"),
    ),
    (
        re.compile(r"\b(?:hanoi|ha noi|hà nội)\b", re.IGNORECASE),
        ("Hanoi", "Hanoi"),
    ),
    (
        re.compile(r"\b(?:da nang|đà nẵng)\b", re.IGNORECASE),
        ("Da Nang", "Da Nang"),
    ),
)
_WORK_MODE_PATTERNS: tuple[tuple[WorkMode, re.Pattern[str]], ...] = (
    (WorkMode.HYBRID, re.compile(r"\bhybrid\b|kết hợp", re.IGNORECASE)),
    (WorkMode.REMOTE, re.compile(r"\bremote\b|từ xa", re.IGNORECASE)),
    (
        WorkMode.ONSITE,
        re.compile(r"\bon[ -]?site\b|tại văn phòng", re.IGNORECASE),
    ),
)


def normalize_location(raw: str | None) -> NormalizedValue[NormalizedLocation]:
    cleaned = normalize_text(raw)
    if cleaned.value is None:
        return NormalizedValue(raw=raw, value=None)

    locations = {
        canonical for pattern, canonical in _LOCATION_PATTERNS if pattern.search(cleaned.value)
    }
    work_modes = {mode for mode, pattern in _WORK_MODE_PATTERNS if pattern.search(cleaned.value)}
    warnings = []

    city: str | None = None
    province: str | None = None
    if len(locations) == 1:
        city, province = next(iter(locations))
    elif len(locations) > 1:
        warnings.append("ambiguous_location")

    work_mode: WorkMode | None = None
    if len(work_modes) == 1:
        work_mode = next(iter(work_modes))
    elif len(work_modes) > 1:
        warnings.append("ambiguous_work_mode")

    value = NormalizedLocation(city=city, province=province, work_mode=work_mode)
    return NormalizedValue(raw=raw, value=value, warnings=tuple(warnings))


class SalaryPeriod(StrEnum):
    HOUR = "hour"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True, slots=True)
class NormalizedSalary:
    minimum: Decimal | None
    maximum: Decimal | None
    currency: str | None
    period: SalaryPeriod | None


_CURRENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("VND", re.compile(r"\b(?:vnd|vnđ)\b|₫", re.IGNORECASE)),
    ("USD", re.compile(r"\busd\b", re.IGNORECASE)),
    ("EUR", re.compile(r"\beur\b|€", re.IGNORECASE)),
)
_PERIOD_PATTERNS: tuple[tuple[SalaryPeriod, re.Pattern[str]], ...] = (
    (SalaryPeriod.HOUR, re.compile(r"(?:/|per\s+)(?:hour|hr)\b|(?:mỗi\s+)?giờ\b", re.IGNORECASE)),
    (SalaryPeriod.MONTH, re.compile(r"(?:/|per\s+)month\b|(?:mỗi\s+)?tháng\b", re.IGNORECASE)),
    (SalaryPeriod.YEAR, re.compile(r"(?:/|per\s+)year\b|(?:mỗi\s+)?năm\b", re.IGNORECASE)),
)
_MILLION_PATTERN = re.compile(r"\bmillion\b|triệu", re.IGNORECASE)
_THOUSAND_PATTERN = re.compile(r"\b(?:thousand|k|nghìn|ngàn)\b", re.IGNORECASE)
_UP_TO_PATTERN = re.compile(r"\bup to\b|tối đa|lên đến", re.IGNORECASE)
_FROM_PATTERN = re.compile(r"\bfrom\b|tối thiểu|ít nhất|\btừ\b", re.IGNORECASE)


def _parse_decimal_token(token: str) -> Decimal:
    dot_count = token.count(".")
    comma_count = token.count(",")
    normalized = token

    if dot_count and comma_count:
        decimal_separator = "." if token.rfind(".") > token.rfind(",") else ","
        group_separator = "," if decimal_separator == "." else "."
        decimal_digits = len(token) - token.rfind(decimal_separator) - 1
        if decimal_digits <= 2:
            normalized = token.replace(group_separator, "").replace(decimal_separator, ".")
        else:
            normalized = token.replace(".", "").replace(",", "")
    elif dot_count or comma_count:
        separator = "." if dot_count else ","
        parts = token.split(separator)
        if len(parts) > 2:
            if any(len(part) != 3 for part in parts[1:]):
                raise ValueError("ambiguous numeric grouping")
            normalized = "".join(parts)
        elif len(parts[1]) == 3:
            normalized = "".join(parts)
        else:
            normalized = f"{parts[0]}.{parts[1]}"

    try:
        return Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("invalid numeric salary") from error


def _single_match[T](
    text: str, patterns: tuple[tuple[T, re.Pattern[str]], ...], warning: str
) -> tuple[T | None, tuple[str, ...]]:
    matches = {value for value, pattern in patterns if pattern.search(text)}
    if len(matches) == 1:
        return next(iter(matches)), ()
    if len(matches) > 1:
        return None, (warning,)
    return None, ()


def normalize_salary(raw: str | None) -> NormalizedValue[NormalizedSalary]:
    cleaned = normalize_text(raw)
    if cleaned.value is None:
        return NormalizedValue(raw=raw, value=None)

    currency, currency_warnings = _single_match(
        cleaned.value, _CURRENCY_PATTERNS, "ambiguous_currency"
    )
    period, period_warnings = _single_match(
        cleaned.value, _PERIOD_PATTERNS, "ambiguous_salary_period"
    )
    warnings = [*currency_warnings, *period_warnings]
    if "$" in cleaned.value and currency is None:
        warnings.append("ambiguous_currency_symbol")

    tokens = _NUMBER_PATTERN.findall(cleaned.value)
    if not tokens:
        return NormalizedValue(raw=raw, value=None, warnings=(*warnings, "salary_not_numeric"))
    if len(tokens) > 2:
        return NormalizedValue(
            raw=raw,
            value=None,
            warnings=(*warnings, "ambiguous_salary_numbers"),
        )

    try:
        amounts = [_parse_decimal_token(token) for token in tokens]
    except ValueError:
        return NormalizedValue(raw=raw, value=None, warnings=(*warnings, "ambiguous_salary_number"))

    has_multiplier = False
    multiplier = Decimal(1)
    if _MILLION_PATTERN.search(cleaned.value):
        multiplier = Decimal(1_000_000)
        has_multiplier = True
    elif _THOUSAND_PATTERN.search(cleaned.value):
        multiplier = Decimal(1_000)
        has_multiplier = True
    amounts = [amount * multiplier for amount in amounts]

    minimum: Decimal | None
    maximum: Decimal | None
    if len(amounts) == 2:
        minimum, maximum = amounts
        if minimum > maximum:
            return NormalizedValue(
                raw=raw,
                value=None,
                warnings=(*warnings, "salary_range_reversed"),
            )
    elif _UP_TO_PATTERN.search(cleaned.value):
        minimum, maximum = None, amounts[0]
    elif _FROM_PATTERN.search(cleaned.value):
        minimum, maximum = amounts[0], None
    elif currency is not None or has_multiplier:
        minimum = maximum = amounts[0]
    else:
        return NormalizedValue(
            raw=raw,
            value=None,
            warnings=(*warnings, "insufficient_salary_evidence"),
        )

    return NormalizedValue(
        raw=raw,
        value=NormalizedSalary(
            minimum=minimum,
            maximum=maximum,
            currency=currency,
            period=period,
        ),
        warnings=tuple(warnings),
    )


_LEVEL_PATTERNS: tuple[tuple[JobLevel, re.Pattern[str]], ...] = (
    (JobLevel.INTERN, re.compile(r"\bintern(?:ship)?\b|thực tập", re.IGNORECASE)),
    (JobLevel.FRESHER, re.compile(r"\bfresher\b", re.IGNORECASE)),
    (JobLevel.JUNIOR, re.compile(r"\b(?:junior|jr\.?)\b", re.IGNORECASE)),
    (JobLevel.MID, re.compile(r"\b(?:mid(?:dle)?|intermediate)\b", re.IGNORECASE)),
    (JobLevel.SENIOR, re.compile(r"\b(?:senior|sr\.?)\b", re.IGNORECASE)),
    (
        JobLevel.LEAD,
        re.compile(r"\b(?:(?:technical|tech|team)\s+lead|lead)\b", re.IGNORECASE),
    ),
    (JobLevel.MANAGER, re.compile(r"\bmanager\b", re.IGNORECASE)),
)


def normalize_levels(raw: str | None) -> NormalizedValue[tuple[JobLevel, ...]]:
    cleaned = normalize_text(raw)
    if cleaned.value is None:
        return NormalizedValue(raw=raw, value=())
    levels = tuple(level for level, pattern in _LEVEL_PATTERNS if pattern.search(cleaned.value))
    return NormalizedValue(raw=raw, value=levels)


@dataclass(frozen=True, slots=True)
class NormalizedExperience:
    minimum_years: Decimal | None
    maximum_years: Decimal | None


_EXPERIENCE_UNIT_PATTERN = re.compile(r"\b(?:years?|yrs?)\b|năm", re.IGNORECASE)
_EXPERIENCE_UP_TO_PATTERN = re.compile(r"\bup to\b|tối đa", re.IGNORECASE)
_EXPERIENCE_MIN_PATTERN = re.compile(
    r"\bat least\b|minimum|tối thiểu|ít nhất|\bfrom\b|\btừ\b|\+", re.IGNORECASE
)


def normalize_experience(raw: str | None) -> NormalizedValue[NormalizedExperience]:
    cleaned = normalize_text(raw)
    if cleaned.value is None:
        return NormalizedValue(raw=raw, value=None)
    if not _EXPERIENCE_UNIT_PATTERN.search(cleaned.value):
        return NormalizedValue(raw=raw, value=None, warnings=("experience_unit_missing",))

    tokens = _NUMBER_PATTERN.findall(cleaned.value)
    if not tokens or len(tokens) > 2:
        return NormalizedValue(raw=raw, value=None, warnings=("ambiguous_experience",))
    try:
        amounts = [_parse_decimal_token(token) for token in tokens]
    except ValueError:
        return NormalizedValue(raw=raw, value=None, warnings=("ambiguous_experience",))

    minimum: Decimal | None
    maximum: Decimal | None
    if len(amounts) == 2:
        minimum, maximum = amounts
        if minimum > maximum:
            return NormalizedValue(raw=raw, value=None, warnings=("experience_range_reversed",))
    elif _EXPERIENCE_UP_TO_PATTERN.search(cleaned.value):
        minimum, maximum = None, amounts[0]
    else:
        minimum, maximum = amounts[0], None
        if not _EXPERIENCE_MIN_PATTERN.search(cleaned.value):
            return NormalizedValue(
                raw=raw,
                value=NormalizedExperience(minimum_years=minimum, maximum_years=maximum),
                warnings=("experience_interpreted_as_minimum",),
            )

    return NormalizedValue(
        raw=raw,
        value=NormalizedExperience(minimum_years=minimum, maximum_years=maximum),
    )


def normalize_skill_mentions(raw_mentions: tuple[str, ...]) -> tuple[NormalizedValue[str], ...]:
    return tuple(normalize_text(raw) for raw in raw_mentions)


@dataclass(frozen=True, slots=True)
class CanonicalJobContent:
    canonical_url: str
    title: str
    company_name: str
    description_text: str | None
    location_raw: str | None
    location: NormalizedLocation | None
    salary_raw: str | None
    salary: NormalizedSalary | None
    level_raw: str | None
    levels: tuple[JobLevel, ...]
    experience: NormalizedExperience | None

    def __post_init__(self) -> None:
        parsed_url = urlsplit(self.canonical_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.fragment
            or parsed_url.username
            or parsed_url.password
        ):
            raise ValueError("canonical_url must be a normalized HTTPS URL")
        if (
            normalize_text(self.title).value is None
            or normalize_text(self.company_name).value is None
        ):
            raise ValueError("title and company_name must not be blank")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("levels must not contain duplicates")
        canonical_order = {level: index for index, level in enumerate(JobLevel)}
        if tuple(sorted(self.levels, key=canonical_order.__getitem__)) != self.levels:
            raise ValueError("levels must use canonical order")


CANONICAL_HASH_VERSION = "job-content-v1"


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value.normalize(), "f") if value is not None else None


def canonical_job_content_hash(content: CanonicalJobContent) -> str:
    location = content.location
    salary = content.salary
    experience = content.experience
    payload = {
        "version": CANONICAL_HASH_VERSION,
        "canonical_url": content.canonical_url,
        "title": normalize_text(content.title).value,
        "company_name": normalize_text(content.company_name).value,
        "description_text": normalize_text(content.description_text).value,
        "location_raw": normalize_text(content.location_raw).value,
        "location_city": location.city if location else None,
        "location_province": location.province if location else None,
        "work_mode": location.work_mode.value if location and location.work_mode else None,
        "salary_raw": normalize_text(content.salary_raw).value,
        "salary_min": _decimal_text(salary.minimum) if salary else None,
        "salary_max": _decimal_text(salary.maximum) if salary else None,
        "currency": salary.currency if salary else None,
        "salary_period": salary.period.value if salary and salary.period else None,
        "level_raw": normalize_text(content.level_raw).value,
        "levels": [level.value for level in content.levels],
        "experience_min": _decimal_text(experience.minimum_years) if experience else None,
        "experience_max": _decimal_text(experience.maximum_years) if experience else None,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(serialized.encode("utf-8")).hexdigest()
