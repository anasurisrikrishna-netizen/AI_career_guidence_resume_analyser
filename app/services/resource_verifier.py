from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ALLOWED_RESOURCE_HOSTS = frozenset(
    {
        "docs.python.org",
        "dev.java",
        "developer.mozilla.org",
        "www.postgresql.org",
        "git-scm.com",
        "pandas.pydata.org",
        "developers.google.com",
        "scikit-learn.org",
        "www.scikit-learn.org",
        "docs.pytorch.org",
        "ai.google.dev",
        "aistudio.google.com",
    }
)


class UnsafeResourceURLError(ValueError):
    pass


def validate_resource_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise UnsafeResourceURLError("Resource URL is invalid.")
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as error:
        raise UnsafeResourceURLError("Resource URL has an invalid port.") from error
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or hostname not in ALLOWED_RESOURCE_HOSTS
    ):
        raise UnsafeResourceURLError("Resource URL must use HTTPS on an approved learning domain.")
    return url


class _ApprovedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        validate_resource_url(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


class ResourceVerifier:
    def __init__(self, timeout_seconds: float = 5):
        self.timeout_seconds = timeout_seconds

    def verify(self, url: str) -> bool:
        approved_url = validate_resource_url(url)
        request = Request(
            approved_url,
            headers={
                "Range": "bytes=0-1023",
                "User-Agent": "Pathwise-Resource-Verifier/1.0",
            },
        )
        opener = build_opener(_ApprovedRedirectHandler())
        try:
            response = opener.open(request, timeout=self.timeout_seconds)
            with response:
                validate_resource_url(response.geturl())
                status = response.getcode()
                response.read(1024)
                return 200 <= status < 400
        except (URLError, TimeoutError, OSError, UnsafeResourceURLError):
            return False
