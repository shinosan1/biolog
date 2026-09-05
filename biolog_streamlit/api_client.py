import requests
from urllib.parse import urlparse

from config import API_BASE


_LOCAL_API_HOSTS = {"localhost", "127.0.0.1", "::1", "biolog-api"}


def _validated_api_base(value: str) -> str:
    try:
        parsed = urlparse(value)
        _ = parsed.port
    except (TypeError, ValueError):
        raise ValueError("BIOLOG_API_URL must be a valid local HTTP URL")
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in _LOCAL_API_HOSTS:
        raise ValueError("BIOLOG_API_URL must point to the local Biolog API")
    return value.rstrip("/")


_API_BASE = _validated_api_base(API_BASE)
_SESSION = requests.Session()
_SESSION.trust_env = False


class ApiClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _detail_from_http_error(e: requests.HTTPError) -> str:
    if e.response is None:
        return str(e)
    try:
        return e.response.json().get("detail", str(e))
    except Exception:
        return str(e)


def api_get(path: str, params: dict = None, suppress_404: bool = False):
    try:
        r = _SESSION.get(f"{_API_BASE}{path}", params=params, timeout=10)
        if suppress_404 and r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise ApiClientError(_detail_from_http_error(e), e.response.status_code if e.response is not None else None)


def api_post(path: str, body: dict):
    try:
        r = _SESSION.post(f"{_API_BASE}{path}", json=body, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise ApiClientError(_detail_from_http_error(e), e.response.status_code if e.response is not None else None)
    except Exception as e:
        raise ApiClientError(str(e))


def api_put(path: str, body: dict):
    try:
        r = _SESSION.put(f"{_API_BASE}{path}", json=body, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise ApiClientError(_detail_from_http_error(e), e.response.status_code if e.response is not None else None)
    except Exception as e:
        raise ApiClientError(str(e))


def api_delete(path: str):
    try:
        r = _SESSION.delete(f"{_API_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        raise ApiClientError(_detail_from_http_error(e), e.response.status_code if e.response is not None else None)
    except Exception as e:
        raise ApiClientError(str(e))
