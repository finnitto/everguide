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
