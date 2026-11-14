import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from flask import current_app, has_app_context


ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api"
ADZUNA_REDIRECT_DOMAINS = frozenset(
    {
        "adzuna.in",
        "www.adzuna.in",
        "adzuna.co.uk",
        "www.adzuna.co.uk",
        "adzuna.com",
        "www.adzuna.com",
        "adzuna.com.au",
        "www.adzuna.com.au",
        "adzuna.co.nz",
        "www.adzuna.co.nz",
        "adzuna.sg",
        "www.adzuna.sg",
        "adzuna.de",
        "www.adzuna.de",
        "adzuna.fr",
        "www.adzuna.fr",
    }
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class JobProviderError(RuntimeError):
    code = "job_provider_error"


class JobProviderConfigurationError(JobProviderError):
    code = "job_provider_not_configured"


class JobProviderRateLimitError(JobProviderError):
    code = "job_provider_rate_limited"


class JobProviderUnavailableError(JobProviderError):
    code = "job_provider_unavailable"


class JobProviderResponseError(JobProviderError):
    code = "job_provider_invalid_response"


@dataclass(frozen=True)
class JobListingResult:
    provider_id: str
    title: str
    company: str
    location: str
    description: str
    apply_url: str | None
    posted_at: str | None
    salary_min: int | float | None
    salary_max: int | float | None
    contract_type: str | None


@dataclass(frozen=True)
class JobSearchResult:
    listings: list[JobListingResult]
    total_count: int
    provider: str = "Adzuna"


def safe_adzuna_redirect_url(url: object) -> str | None:
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in ("https", "http")
        or hostname not in ADZUNA_REDIRECT_DOMAINS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 80, 443)
    ):
        return None
    return urlunsplit(("https", hostname, parsed.path, urlencode(parse_qsl(parsed.query, keep_blank_values=True)), ""))


class AdzunaClient:
    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_key: str | None = None,
        country_code: str | None = None,
        timeout_seconds: float | None = None,
    ):
        if has_app_context():
            app_id = app_id or current_app.config.get("ADZUNA_APP_ID")
            app_key = app_key or current_app.config.get("ADZUNA_APP_KEY")
            country_code = country_code or current_app.config.get("ADZUNA_COUNTRY_CODE")
            timeout_seconds = timeout_seconds or current_app.config.get("JOB_SEARCH_TIMEOUT_SECONDS")

        self.app_id = app_id or os.getenv("ADZUNA_APP_ID")
        self.app_key = app_key or os.getenv("ADZUNA_APP_KEY")
        self.country_code = (country_code or os.getenv("ADZUNA_COUNTRY_CODE", "in")).lower()
        self.timeout_seconds = timeout_seconds or 8

    def search(self, query: str, location: str = "", *, page: int = 1, results_per_page: int = 20) -> JobSearchResult:
        query = self._validate_search_term(query, "query", 120, required=True)
        location = self._validate_search_term(location, "location", 120, required=False)
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= 20:
            raise ValueError("page must be between 1 and 20.")
        if not isinstance(results_per_page, int) or isinstance(results_per_page, bool) or not 1 <= results_per_page <= 20:
            raise ValueError("results_per_page must be between 1 and 20.")
        if not self.app_id or not self.app_key:
            raise JobProviderConfigurationError("Adzuna credentials are not configured.")
        if not re.fullmatch(r"[a-z]{2}", self.country_code):
            raise JobProviderConfigurationError("Adzuna country code is invalid.")

        parameters = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": results_per_page,
            "what": query,
            "content-type": "application/json",
        }
        if location:
            parameters["where"] = location
        request_url = (
            f"{ADZUNA_BASE_URL}/jobs/{self.country_code}/search/{page}?"
            f"{urlencode(parameters)}"
        )
        request = Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Pathwise-Job-Search/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code == 429:
                raise JobProviderRateLimitError("Adzuna request rate limit was reached.") from error
            if error.code in (401, 403):
                raise JobProviderConfigurationError("Adzuna rejected the configured credentials.") from error
            if error.code >= 500:
                raise JobProviderUnavailableError("Adzuna is temporarily unavailable.") from error
            raise JobProviderError("Adzuna could not complete the search request.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise JobProviderUnavailableError("Adzuna is temporarily unavailable.") from error

        if len(body) > MAX_RESPONSE_BYTES:
            raise JobProviderResponseError("Adzuna response exceeded the configured size limit.")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise JobProviderResponseError("Adzuna returned an invalid response.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise JobProviderResponseError("Adzuna returned an invalid response shape.")

        total_count = payload.get("count", len(payload["results"]))
        if isinstance(total_count, bool) or not isinstance(total_count, int) or total_count < 0:
            raise JobProviderResponseError("Adzuna returned an invalid result count.")
        if len(payload["results"]) > results_per_page:
            raise JobProviderResponseError("Adzuna returned more results than requested.")

        return JobSearchResult(
            listings=[self._parse_listing(item) for item in payload["results"]],
            total_count=total_count,
        )

    @staticmethod
    def _validate_search_term(value: str, name: str, max_length: int, *, required: bool) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be text.")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{name} is required.")
        if len(value) > max_length:
            raise ValueError(f"{name} must not exceed {max_length} characters.")
        return value

    @staticmethod
    def _parse_listing(item: object) -> JobListingResult:
        if not isinstance(item, dict):
            raise JobProviderResponseError("Adzuna returned an invalid listing.")

        title = item.get("title")
        description = item.get("description")
        provider_id = item.get("id")
        company_data = item.get("company")
        location_data = item.get("location")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 500
            or not isinstance(description, str)
            or len(description) > 20000
            or not isinstance(provider_id, (str, int))
            or isinstance(provider_id, bool)
            or not isinstance(company_data, dict)
            or not isinstance(location_data, dict)
        ):
            raise JobProviderResponseError("Adzuna returned an invalid listing.")

        company = company_data.get("display_name", "Employer not provided")
        location = location_data.get("display_name", "Location not provided")
        if not isinstance(company, str) or not isinstance(location, str):
            raise JobProviderResponseError("Adzuna returned invalid listing details.")

        return JobListingResult(
            provider_id=str(provider_id)[:255],
            title=title.strip(),
            company=company.strip()[:255],
            location=location.strip()[:255],
            description=description.strip(),
            apply_url=safe_adzuna_redirect_url(item.get("redirect_url")),
            posted_at=item.get("created") if isinstance(item.get("created"), str) else None,
            salary_min=_safe_salary(item.get("salary_min")),
            salary_max=_safe_salary(item.get("salary_max")),
            contract_type=item.get("contract_type") if isinstance(item.get("contract_type"), str) else None,
        )


def _safe_salary(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if 0 <= value <= 1_000_000_000 else None
