import importlib

import pytest
import requests


def _http_error(status_code, detail):
    response = requests.Response()
    response.status_code = status_code
    response._content = ('{"detail": "' + detail + '"}').encode()
    response.url = "http://localhost:8766/api/health/record"
    return requests.HTTPError(response=response)


def test_http_error_keeps_422_status_and_api_detail(monkeypatch):
    api_client = importlib.import_module("api_client")
    monkeypatch.setattr(api_client._SESSION, "post", lambda *args, **kwargs: (_ for _ in ()).throw(_http_error(422, "weight is invalid")))

    with pytest.raises(api_client.ApiClientError) as exc_info:
        api_client.api_post("/api/health/record", {})

    assert exc_info.value.status_code == 422
    assert exc_info.value.message == "weight is invalid"
