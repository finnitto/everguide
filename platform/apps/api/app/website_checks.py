"""Conservative technical checks for independently discovered website candidates.
Only page metadata and a digest are retained; response bodies are discarded.
"""
import hashlib
import json
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

def _extract_funeral_provider_data(decoded: str):
    """Extract factual provider identity only when page-level evidence is strong.

    Structured data is supporting evidence, never sufficient by itself. Directory,
    council, cemetery and generic account pages are excluded from provider approval.
    """
    scripts = re.findall(r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', decoded, re.I | re.S)
    visible = html.unescape(re.sub(r'<(script|style|noscript)\b[^>]*>.*?</\1\s*>', ' ', decoded, flags=re.I | re.S))
    visible = re.sub(r'<[^>]+>', ' ', visible)
    visible = re.sub(r'\s+', ' ', visible).strip()
    title_match = re.search(r'<title\b[^>]*>(.*?)</title\s*>', decoded, re.I | re.S)
    title_text = html.unescape(re.sub(r'<[^>]+>', ' ', title_match.group(1))).strip() if title_match else ''
    context = (title_text + ' ' + visible).lower()
    exclusion_terms = ('funeral directory', 'funeral directories', 'compare funeral', 'funeral comparison',
        'find local funeral directors', 'put you in touch with local', 'cemetery', 'cemeteries',
        'burial ground', 'crematorium', 'crematoria', 'borough council', 'city council',
        'county council', 'local authority', 'jobs and careers', 'vacancies', 'login',
        'sign in', 'admin dashboard')
    if any(term in context for term in exclusion_terms):
        return None
    funeral_terms = ('funeral director', 'funeral directors', 'funeral service', 'funeral services',
        'funeral home', 'funeral homes', 'undertaker', 'undertakers', 'funeralcare', 'funeral care')
    context_hits = sorted({term for term in funeral_terms if term in context})
    # A generic account label is not a business identity.
    generic_names = {'admin', 'administrator', 'home', 'welcome', 'contact us', 'about us', 'funeral directors'}
    candidates = []
    for raw in scripts[:30]:
        try:
            payload = json.loads(html.unescape(raw.strip()))
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get('@graph')
            if isinstance(graph, list): stack.extend(graph[:150])
            typ = item.get('@type', [])
            types = [typ] if isinstance(typ, str) else typ if isinstance(typ, list) else []
            type_names = [str(t).rsplit('/', 1)[-1].lower() for t in types]
            if not any(t in ('funeralhome', 'localbusiness', 'organization', 'professionalservice') for t in type_names):
                continue
            name = re.sub(r'\s+', ' ', str(item.get('name') or '')).strip()[:240]
            if not name or name.lower().strip(' .-') in generic_names or len(re.findall(r'[a-zA-Z]{2,}', name)) < 2:
                continue
            description = str(item.get('description') or '')[:1000]
            local_text = (name + ' ' + description).lower()
            hits = sorted(set(context_hits) | {term for term in funeral_terms if term in local_text})
            # Require explicit funeral-sector language on the fetched page, not just JSON-LD.
            if not hits:
                continue
            address = item.get('address') or {}
            if isinstance(address, list): address = address[0] if address else {}
            if not isinstance(address, dict): address = {}
            country = address.get('addressCountry') or ''
            if isinstance(country, dict): country = country.get('name', '')
            country_text = str(country).lower()
            if country_text and not any(x in country_text for x in ('gb', 'uk', 'united kingdom', 'england')):
                continue
            street = re.sub(r'\s+', ' ', str(address.get('streetAddress') or '')).strip()[:240]
            town = re.sub(r'\s+', ' ', str(address.get('addressLocality') or '')).strip()[:120]
            postcode = re.sub(r'\s+', ' ', str(address.get('postalCode') or '')).strip().upper()[:12]
            postcode_ok = bool(re.fullmatch(r'[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}', postcode))
            telephone = str(item.get('telephone') or '')[:40] or None
            email = str(item.get('email') or '')[:254] or None
            website = str(item.get('url') or '')[:1000] or None
            complete_address = bool(street and town and postcode_ok)
            # At least one independent contact/location signal is mandatory.
            if not (complete_address or telephone or email):
                continue
            explicit_funeral_type = 'funeralhome' in type_names
            confidence = 0.94 if explicit_funeral_type and complete_address and telephone else 0.88 if complete_address and telephone else 0.84
            candidates.append({'name': name, 'street': street or None, 'town': town or None,
                'postcode': postcode if postcode_ok else None, 'telephone': telephone, 'email': email,
                'website': website, 'source_type': 'schema_org_funeralhome' if explicit_funeral_type else 'schema_org_' + (type_names[0] if type_names else 'business'),
                'country': country_text or 'unspecified', 'confidence': confidence,
                'funeral_signals': hits, 'has_complete_branch_address': complete_address})
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x['confidence'], bool(x['telephone']), bool(x['email'])), reverse=True)[0]


def _structured_funeral_home_data(decoded: str):
    """Backward-compatible name for the expanded factual provider extractor."""
    return _extract_funeral_provider_data(decoded)

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
    extracted = _extract_funeral_provider_data(decoded)
    return {"status": "reachable", "final_url": url, "http_status": code,
            "content_type": content_type, "page_title": title, "robots_allowed": True,
            "content_sha256": hashlib.sha256(body).hexdigest(), "extracted_data": extracted,
            "detail": "Technical reachability confirmed. Business identity signals were inspected transiently; the page body was discarded."}
