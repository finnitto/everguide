import socket
import pytest
from app import website_checks


def test_only_https_is_accepted():
    with pytest.raises(ValueError, match="Only HTTPS"):
        website_checks._validate_public_https("http://example.org")


def test_nonstandard_port_is_rejected():
    with pytest.raises(ValueError, match="standard HTTPS port"):
        website_checks._validate_public_https("https://example.org:8443")


def test_private_dns_address_is_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        website_checks._validate_public_https("https://example.org")


def test_public_dns_address_is_accepted(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    parsed, host = website_checks._validate_public_https("https://example.org/page")
    assert parsed.scheme == "https"
    assert host == "example.org"


def test_follows_bounded_same_provider_https_redirect_and_rechecks_robots(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(website_checks.settings, "website_max_redirects", 3)
    calls = []

    def fake_get(url, limit):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return 200, {}, b"", None
        if url == "https://example.org/start":
            return 301, {"Location": "/home"}, b"", "/home"
        if url == "https://example.org/home":
            return 200, {"Content-Type": "text/html"}, b"<html><title>Example Funeral Directors</title></html>", None
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(website_checks, "_get", fake_get)
    result = website_checks.verify_candidate("https://example.org/start")

    assert result["status"] == "reachable"
    assert result["final_url"] == "https://example.org/home"
    assert result["redirect_count"] == 1
    assert calls == [
        "https://example.org/robots.txt", "https://example.org/start",
        "https://example.org/robots.txt", "https://example.org/home",
    ]


def test_redirect_limit_stops_before_fetching_excess_destination(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(website_checks.settings, "website_max_redirects", 1)
    page_requests = []

    def fake_get(url, limit):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", None
        page_requests.append(url)
        if url.endswith("/one"):
            return 301, {"Location": "/two"}, b"", "/two"
        if url.endswith("/two"):
            return 302, {"Location": "/three"}, b"", "/three"
        raise AssertionError(f"Excess destination was fetched: {url}")

    monkeypatch.setattr(website_checks, "_get", fake_get)
    result = website_checks.verify_candidate("https://example.org/one")

    assert result["status"] == "redirect_limit_exceeded"
    assert result["redirect_count"] == 1
    assert page_requests == ["https://example.org/one", "https://example.org/two"]


def test_cross_domain_redirect_is_not_followed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(website_checks.settings, "website_max_redirects", 3)
    requests = []

    def fake_get(url, limit):
        requests.append(url)
        if url.endswith("/robots.txt"):
            return 200, {}, b"", None
        return 301, {"Location": "https://other.example/home"}, b"", "https://other.example/home"

    monkeypatch.setattr(website_checks, "_get", fake_get)
    result = website_checks.verify_candidate("https://example.org/start")

    assert result["status"] == "redirect_requires_review"
    assert "Cross-domain" in result["detail"]
    assert requests == ["https://example.org/robots.txt", "https://example.org/start"]


def test_redirect_without_location_fails_closed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(website_checks.settings, "website_max_redirects", 3)

    def fake_get(url, limit):
        if url.endswith("/robots.txt"):
            return 200, {}, b"", None
        return 301, {}, b"", None

    monkeypatch.setattr(website_checks, "_get", fake_get)
    result = website_checks.verify_candidate("https://example.org/start")

    assert result["status"] == "redirect_requires_review"
    assert "no usable Location" in result["detail"]


def test_extracts_explicit_business_status_from_branch_scoped_structured_data():
    decoded = """
    <html><head><title>Example Funeral Directors</title></head>
    <body>Funeral directors and funeral services.
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "FuneralHome",
      "name": "Example Funeral Directors",
      "description": "Funeral directors",
      "businessStatus": "https://schema.org/ClosedPermanently",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "1 High Street",
        "addressLocality": "Tilbury",
        "postalCode": "RM18 7QX",
        "addressCountry": "GB"
      }
    }
    </script></body></html>
    """
    extracted = website_checks._extract_funeral_provider_data(decoded)
    assert extracted is not None
    assert extracted["branch_status"] == "permanently_closed"
    assert extracted["street"] == "1 High Street"
    assert extracted["town"] == "Tilbury"


def test_unknown_or_unscoped_business_status_is_not_treated_as_branch_closure():
    decoded = """
    <html><head><title>Example Funeral Directors</title></head>
    <body>Funeral directors and funeral services.
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      "name": "Example Funeral Directors",
      "description": "Funeral directors",
      "businessStatus": "https://schema.org/ClosedPermanently",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "1 High Street",
        "addressLocality": "Tilbury",
        "postalCode": "RM18 7QX",
        "addressCountry": "GB"
      }
    }
    </script></body></html>
    """
    extracted = website_checks._extract_funeral_provider_data(decoded)
    assert extracted is not None
    assert extracted["branch_status"] is None
