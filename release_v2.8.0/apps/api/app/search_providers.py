"""Provider-independent web search adapters for Everguide."""
import json
import urllib.error
import urllib.parse
from urllib.request import Request, urlopen

class SearchProviderError(RuntimeError):
    pass

def search_web(query: str, *, provider: str, brave_api_key: str, count: int = 10):
    """Return normalized results: title, url, description, provider."""
    provider = (provider or "brave").strip().lower()
    if provider == "brave":
        if not brave_api_key:
            raise SearchProviderError("Brave Search is selected but BRAVE_SEARCH_API_KEY is not configured.")
        params = urllib.parse.urlencode({
            "q": query, "country": "GB", "search_lang": "en",
            "count": min(max(count, 1), 20), "safesearch": "moderate"
        })
        request = Request(
            "https://api.search.brave.com/res/v1/web/search?" + params,
            headers={"X-Subscription-Token": brave_api_key, "Accept": "application/json",
                     "User-Agent": "EverguideResearch/0.6.1"}
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise SearchProviderError(f"Brave Search API returned HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise SearchProviderError(f"Brave Search request failed: {type(exc).__name__}: {exc}") from exc
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""),
             "description": x.get("description", ""), "provider": "brave"}
            for x in payload.get("web", {}).get("results", [])
        ]
    if provider == "google":
        raise SearchProviderError(
            "Google Custom Search JSON API is not enabled for new customers. "
            "A supported Google search product and its eligibility must be configured before selecting it."
        )
    raise SearchProviderError(f"Unsupported SEARCH_PROVIDER '{provider}'. Supported adapter: brave.")
