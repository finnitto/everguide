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
