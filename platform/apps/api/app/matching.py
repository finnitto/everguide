"""Conservative matching helpers for provider and source-observation review.

Only compare business fields already present in Everguide's own records. Google
Place IDs are identifiers, not business names or addresses, and are not used to
infer a match against the directory.
"""
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

LEGAL_SUFFIXES = {"limited", "ltd", "plc", "llp", "company", "co"}


def _text(value):
    return str(value or "").strip()


def normalise_name(value):
    words = re.findall(r"[a-z0-9]+", _text(value).lower())
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalise_postcode(value):
    return re.sub(r"\s+", "", _text(value).upper())


def normalise_phone(value):
    digits = re.sub(r"\D", "", _text(value))
    if digits.startswith("0044"):
        digits = "0" + digits[4:]
    elif digits.startswith("44") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def normalise_domain(value):
    value = _text(value).lower()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").removeprefix("www.")
    return host


def observation_fields(observation):
    data = observation.observed_data or {}
    name = next((data.get(k) for k in ("trading_name", "business_name", "display_name", "name", "provider_name") if data.get(k)), None)
    postcode = next((data.get(k) for k in ("postcode", "postal_code", "post_code") if data.get(k)), None)
    phone = next((data.get(k) for k in ("telephone", "phone", "phone_number", "national_phone_number") if data.get(k)), None)
    website = next((data.get(k) for k in ("website", "website_uri", "url", "domain") if data.get(k)), None)
    town = next((data.get(k) for k in ("town_city", "town", "city", "locality") if data.get(k)), None)
    return {"name": _text(name), "postcode": _text(postcode), "phone": _text(phone), "website": _text(website), "town": _text(town)}


def _score(fields, provider, branch):
    score = 0.0
    reasons = []
    obs_postcode = normalise_postcode(fields["postcode"])
    branch_postcode = normalise_postcode(branch.postcode)
    if obs_postcode and branch_postcode and obs_postcode == branch_postcode:
        score += 0.40
        reasons.append("Exact postcode")

    obs_phone = normalise_phone(fields["phone"])
    branch_phone = normalise_phone(branch.telephone)
    if obs_phone and branch_phone and len(obs_phone) >= 7 and obs_phone == branch_phone:
        score += 0.30
        reasons.append("Exact telephone number")

    obs_domain = normalise_domain(fields["website"])
    branch_domain = normalise_domain(branch.website or provider.website)
    if obs_domain and branch_domain and obs_domain == branch_domain:
        score += 0.25
        reasons.append("Exact website domain")

    obs_name = normalise_name(fields["name"])
    candidate_names = [normalise_name(provider.trading_name), normalise_name(branch.branch_name)]
    name_ratio = max((SequenceMatcher(None, obs_name, candidate).ratio() for candidate in candidate_names if obs_name and candidate), default=0.0)
    if name_ratio >= 0.92:
        score += 0.30
        reasons.append("Very similar business name")
    elif name_ratio >= 0.78:
        score += 0.20
        reasons.append("Similar business name")
    elif name_ratio >= 0.65:
        score += 0.10
        reasons.append("Partially similar business name")

    obs_town = normalise_name(fields["town"])
    branch_town = normalise_name(branch.town_city)
    if obs_town and branch_town and obs_town == branch_town:
        score += 0.05
        reasons.append("Same town or city")

    return min(score, 1.0), reasons


def find_provider_matches(observation, providers, max_results=5):
    fields = observation_fields(observation)
    has_identity = any(fields[k] for k in ("name", "postcode", "phone", "website"))
    if not has_identity:
        return {"match_state": "needs_enrichment", "matchable": False, "candidates": [],
                "message": "This observation contains a Google Place ID only. No business details are stored, so a responsible provider match cannot yet be calculated."}

    candidates = []
    for provider in providers:
        for branch in provider.branches:
            score, reasons = _score(fields, provider, branch)
            if score >= 0.20:
                candidates.append({"provider_id": provider.id, "provider_name": provider.trading_name,
                    "provider_status": provider.status, "branch_id": branch.id,
                    "branch_name": branch.branch_name, "town_city": branch.town_city,
                    "postcode": branch.postcode, "score": round(score, 2), "reasons": reasons})
    candidates.sort(key=lambda item: (-item["score"], item["provider_name"], item["branch_name"]))
    candidates = candidates[:max_results]
    if candidates and candidates[0]["score"] >= 0.70:
        state = "strong_candidate"
    elif candidates and candidates[0]["score"] >= 0.40:
        state = "possible_candidate"
    else:
        state = "no_candidate"
    return {"match_state": state, "matchable": True, "candidates": candidates,
            "message": "Suggestions are indicative only. Review the source evidence before linking records."}


def observation_duplicate_key(observation):
    data = observation.observed_data or {}
    place_id = _text(data.get("google_place_id"))
    if place_id:
        return "google_place_id:" + place_id
    fields = observation_fields(observation)
    parts = [normalise_name(fields["name"]), normalise_postcode(fields["postcode"]),
             normalise_phone(fields["phone"]), normalise_domain(fields["website"])]
    useful = [part for part in parts if part]
    if len(useful) < 2:
        return None
    return "business:" + "|".join(parts)
