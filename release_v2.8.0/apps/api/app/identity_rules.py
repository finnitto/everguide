"""Pure identity classification and retained-evidence assessment rules."""
import re
from urllib.parse import urlsplit
from app.candidate_quality import classify_service, website_domain

DIRECTORY_TERMS = (
    "directory", "funeral guide", "compare funeral", "compare 53 local", "find a funeral",
    "find local funeral directors", "find local funeral director", "put you in touch with",
    "funeral comparison", "reviews", "listings", "search funeral directors", "funeral directors near",
)
DIRECTORY_DOMAINS = {
    "funeralguide.co.uk", "funeral-directory.co.uk", "funeralfinder.org", "localfuneral.co.uk",
    "funeralchoice.co.uk", "yourfuneralchoice.com",
}
NON_DIRECTOR_TERMS = (
    "cemetery", "cemeteries", "crematorium", "crematoria", "borough council",
    "city council", "county council", "local authority", "burial ground",
)
IRRELEVANT_TERMS = ("jobs", "careers", "vacancies", "wikipedia", "news", "facebook", "instagram", "linkedin")

def _classify(title, snippet, domain):
    text = f"{title} {snippet} {domain}".lower()
    clean_domain = (domain or "").lower().removeprefix("www.").split(":")[0]
    if any(term in text for term in IRRELEVANT_TERMS):
        return "likely_irrelevant"
    if clean_domain in DIRECTORY_DOMAINS or any(clean_domain.endswith("." + d) for d in DIRECTORY_DOMAINS):
        return "directory_or_comparison"
    if any(term in text for term in DIRECTORY_TERMS):
        return "directory_or_comparison"
    # Explicit adjacent services take precedence over broad funeral taxonomy
    # wording. The shared classifier also catches celebrants, memorial/masonry
    # providers and the common "cemetary" misspelling.
    service_class = classify_service(name=title, website=domain, description=snippet)
    if service_class in {
        "cemetery", "crematorium", "celebrant", "memorial_or_masonry",
        "civic_or_council_service",
    }:
        return "related_service_not_funeral_director"
    if service_class == "directory_or_comparison":
        return "directory_or_comparison"
    if service_class == "likely_irrelevant":
        return "likely_irrelevant"
    if service_class == "funeral_director_candidate":
        return "provider_candidate"
    return "uncertain"


def _normalise_identity_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _provider_quality_assessment(provider, observations):
    """Assess retained evidence, recognising both business-identity and JSON-LD observations.

    This is an evidence sufficiency check, not a live-site or legal-status verification.
    """
    name = (provider.trading_name or "").strip().lower()
    domain = (urlsplit(provider.website or "").hostname or "").lower().removeprefix("www.")
    generic_names = {"admin", "administrator", "test", "unknown", "localfuneral", "funeral directors", "home", "welcome"}
    exclusion_terms = ("cemetery", "cemeteries", "cemetary", "crematorium", "council", "celebrant", "memorial", "headstone", "stonemason", "monumental", "funeralguide", "funeral-directory", "funeralfinder", "localfuneral", "compare-funeral", "directory")
    if (name in generic_names or name.startswith(("http://", "https://", "www."))
            or any(term in name or term in domain for term in exclusion_terms)):
        return "needs_review", "Name or website contains a generic, directory, civic or cemetery signal; manual identity check required."

    provider_name = _normalise_identity_name(provider.trading_name)
    for obs in observations:
        if obs.review_status != "accepted":
            continue
        obs_domain = (urlsplit(obs.source_url or "").hostname or "").lower().removeprefix("www.")
        if not domain or obs_domain != domain:
            continue
        data = obs.observed_data or {}
        observed_name = _normalise_identity_name(data.get("provider_name") or data.get("name"))
        signals = data.get("funeral_signals") or data.get("funeral_context_signals") or []
        source_kind = (obs.source_type or "").lower()
        structured = "structured" in source_kind or str(data.get("source_type", "")).startswith("schema_org_") or bool(data.get("schema_type"))
        # Structured data observations carry the actual business fields under the
        # same provider_name/address keys; don't require a duplicate signal field.
        if structured and not signals:
            signals = ["schema_org_funeral_business_identity"] if data.get("provider_name") and (
                data.get("postcode") or data.get("address_line_1") or data.get("telephone") or data.get("email")
            ) else []
        if not observed_name or not provider_name or not signals:
            continue
        # Tolerate punctuation, common suffixes and a branch descriptor while
        # requiring a meaningful name match rather than a shared generic word.
        exact = observed_name == provider_name
        token_a = set(re.findall(r"[a-z0-9]+", str(data.get("provider_name") or data.get("name") or "").lower()))
        token_b = set(re.findall(r"[a-z0-9]+", name))
        ignored = {"limited", "ltd", "plc", "the", "and", "funeral", "director", "directors", "services", "service"}
        overlap = (token_a - ignored) & (token_b - ignored)
        meaningful_match = exact or len(overlap) >= 2 or (len(overlap) == 1 and len(token_a - ignored) == 1)
        if meaningful_match:
            return "confirmed", "Accepted independent provider-website evidence matches the provider name and domain and records funeral-sector identity signals."
    return "insufficient_evidence", "Retained Everguide evidence does not yet establish a sufficiently clear provider-name and website match; this is not proof that the provider is invalid."

