import io
import urllib.error
from email.message import Message
from unittest.mock import patch

import pytest

from app import companies_house


def _http_error(code, headers=None, body=b"temporary"):
    response_headers = Message()
    for key, value in (headers or {}).items():
        response_headers[key] = value
    return urllib.error.HTTPError(
        url="https://api.company-information.service.gov.uk/company/00000000",
        code=code, msg="test", hdrs=response_headers, fp=io.BytesIO(body),
    )

def test_rate_limit_pauses_immediately_without_retry_or_sleep():
    with patch.object(companies_house.urllib.request, "urlopen", side_effect=_http_error(429, {"Retry-After": "60"})) as request, \
         patch.object(companies_house.time, "sleep") as sleep:
        with pytest.raises(companies_house.CompaniesHousePause, match="HTTP 429") as caught:
            companies_house._get_company_resource("test-key", "/company/00000000")
    assert "60 seconds" in str(caught.value)
    request.assert_called_once()
    sleep.assert_not_called()

def test_server_error_pauses_batch():
    with patch.object(companies_house.urllib.request, "urlopen", side_effect=_http_error(503)):
        with pytest.raises(companies_house.CompaniesHousePause, match="HTTP 503"):
            companies_house._get_company_resource("test-key", "/company/00000000")

def test_not_found_is_a_normal_empty_result_and_is_paced():
    with patch.object(companies_house.urllib.request, "urlopen", side_effect=_http_error(404)), \
         patch.object(companies_house.time, "sleep") as sleep:
        assert companies_house._get_company_resource("test-key", "/company/00000000") == {}
    sleep.assert_called_once_with(1.1)

def test_successful_profile_is_paced():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"company_number":"00000000"}'
    with patch.object(companies_house.urllib.request, "urlopen", return_value=Response()), \
         patch.object(companies_house.time, "sleep") as sleep:
        assert companies_house._get_company_resource("test-key", "/company/00000000")["company_number"] == "00000000"
    sleep.assert_called_once_with(1.1)


def test_rate_limit_reset_header_is_reported():
    from datetime import datetime, timezone
    reset = str(int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()))
    headers = Message()
    headers["X-Ratelimit-Reset"] = reset
    assert "2030-01-01T00:00:00+00:00" in companies_house._rate_limit_resume_hint(headers)


def test_authentication_error_pauses_batch():
    with patch.object(companies_house.urllib.request, "urlopen", side_effect=_http_error(401)):
        with pytest.raises(companies_house.CompaniesHousePause, match="HTTP 401"):
            companies_house._get_company_resource("test-key", "/company/00000000")
