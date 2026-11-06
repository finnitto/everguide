"""Conservative technical checks for independently discovered website candidates.
Only page metadata and a digest are retained; response bodies are discarded.
"""
import hashlib
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

USER_AGENT = "EverguideEvidenceBot/0.8 (+https://everguide.example/contact)"
MAX_BYTES = 1_000_000

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_opener = urllib.request.build_opener(NoRedirect)

def _validate_public_https(url: str):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Only HTTPS website URLs are eligible for automated checks.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not eligible.")
    if parsed.port not in (None, 443):
        raise ValueError("Only the standard HTTPS port is eligible for automated checks.")
    host = parsed.hostname.encode("idna").decode("ascii")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local or internal hostnames are not eligible.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("Website hostname could not be resolved.") from exc
    if not addresses:
        raise ValueError("Website hostname did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("Website resolves to a non-public network address; check blocked for safety.")
    return parsed, host

def _get(url: str, limit: int = 4096):
    _validate_public_https(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,text/html;q=0.9,*/*;q=0.1"})
    try:
        response = _opener.open(request, timeout=12)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc.code, exc.headers, b"", exc.headers.get("Location")
        return exc.code, exc.headers, b"", None
    with response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Response exceeded the configured safety size limit.")
        return response.status, response.headers, body, None

def verify_candidate(url: str):
    parsed, _ = _validate_public_https(url)
    origin = f"https://{parsed.netloc}"
    robots_status, _, robots_body, robots_redirect = _get(origin + "/robots.txt", 65536)
    if robots_redirect:
        raise ValueError("robots.txt redirects; automated check stopped for manual review.")
    if robots_status >= 400:
        raise ValueError(f"robots.txt could not be checked (HTTP {robots_status}); page was not fetched.")
    parser = RobotFileParser()
    parser.set_url(origin + "/robots.txt")
    parser.parse(robots_body.decode("utf-8", errors="replace").splitlines())
    if not parser.can_fetch(USER_AGENT, url):
        return {"status": "robots_disallowed", "final_url": url, "http_status": None,
                "content_type": None, "page_title": None, "robots_allowed": False,
                "content_sha256": None, "detail": "robots.txt disallows this page; no page content fetched."}
    code, headers, body, redirect = _get(url, MAX_BYTES)
    if redirect:
        return {"status": "redirect_requires_review", "final_url": urllib.parse.urljoin(url, redirect),
                "http_status": code, "content_type": headers.get("Content-Type"), "page_title": None,
                "robots_allowed": True, "content_sha256": None,
                "detail": "Redirect was not followed. Destination must be independently checked before verification."}
    content_type = headers.get("Content-Type", "")[:160]
    if code < 200 or code >= 300:
        return {"status": "http_error", "final_url": url, "http_status": code,
                "content_type": content_type, "page_title": None, "robots_allowed": True,
                "content_sha256": None, "detail": f"Website returned HTTP {code}."}
    if "text/html" not in content_type.lower():
        return {"status": "not_html", "final_url": url, "http_status": code,
                "content_type": content_type, "page_title": None, "robots_allowed": True,
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "detail": "Reachable response is not HTML; response body discarded."}
    decoded = body.decode("utf-8", errors="replace")
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", decoded, re.I | re.S)
    title = html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).strip() if match else None
    title = re.sub(r"\s+", " ", title or "")[:500] or None
    return {"status": "reachable", "final_url": url, "http_status": code,
            "content_type": content_type, "page_title": title, "robots_allowed": True,
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "detail": "Technical reachability confirmed. This does not establish ownership, identity, reuse rights or permission to publish."}
