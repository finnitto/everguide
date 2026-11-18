"""Conservative service classification and candidate-quality helpers.

All functions are deterministic and side-effect free. They create review signals;
they never create, merge, delete, publish or mutate provider/branch records.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

DIRECTORY_DOMAINS = {
    "funeralguide.co.uk",
    "funeral-directory.co.uk",
    "funeralfinder.org",
    "localfuneral.co.uk",
    "funeralchoice.co.uk",
    "yourfuneralchoice.com",
    "192.com",
    "thebusinesslisting.co.uk",
    "ashesregister.com",
}

CATEGORY_TERMS = {
    "directory_or_comparison": (
        "directory", "funeral guide", "compare funeral", "funeral comparison",
        "funeralfinder", "localfuneral", "funeralchoice", "listing service",
    ),
    "cemetery": (
        "cemetery", "cemeteries", "cemetary", "cemetaries",
        "churchyard", "burial ground", "natural burial", "woodland burial",
        "green burial", "burial meadow",
    ),
    "crematorium": ("crematorium", "crematoria"),
    "celebrant": ("celebrant",),
    "memorial_or_masonry": (
        "memorial", "headstone", "monumental mason", "stonemason",
        "stone mason", "monumental masonry",
    ),
    "civic_or_council_service": (
        "borough council", "city council", "county council",
        "local authority", "council cemetery",
    ),
    "likely_irrelevant": (
        "jobs", "careers", "vacancies", "wikipedia", "news",
        "facebook", "instagram", "linkedin",
    ),
}

FUNERAL_TERMS = (
    "funeral director", "funeral directors", "funeral service",
    "funeral services", "funeralcare", "funeral care",
    "undertaker", "undertakers",
)

THURROCK_OUTWARD_CODES = {
    "RM15", "RM16", "RM17", "RM18", "RM19", "RM20", "SS17",
}

UK_POSTCODE_RE = re.compile(
    r"^(?:GIR\s?0AA|(?:[A-Z]{1,2}\d[A-Z\d]?|[A-Z]{1,2}\d{2}|"
    r"[A-Z]{1,2}\d[A-Z]|[A-Z]{1,2}\d{2}[A-Z])\s?\d[A-Z]{2})$",
    re.IGNORECASE,
)


def normalise_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalise_identity_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def normalise_postcode(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").upper())


def normalise_phone(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0044"):
        digits = "0" + digits[4:]
    elif digits.startswith("44") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def website_domain(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else "https://" + raw)
    return (parsed.hostname or "").lower().removeprefix("www.")


def is_valid_uk_postcode(value: object) -> bool:
    return bool(UK_POSTCODE_RE.fullmatch(" ".join(str(value or "").strip().upper().split())))


def postcode_outward_code(value: object) -> str:
    compact = normalise_postcode(value)
    match = re.match(r"^([A-Z]{1,2}\d{1,2}[A-Z]?)", compact)
    return match.group(1) if match else ""


def classify_service(
    *,
    name: object = "",
    basic_category: object = "",
    taxonomy_primary: object = "",
    website: object = "",
    description: object = "",
) -> str:
    """Classify funeral-sector candidates, keeping adjacent services distinct.

    Explicit pet, burial-ground, direct-cremation and funeral-plan signals take
    precedence over broad Overture taxonomy labels such as funeral_service.
    """
    name_text = str(name or "").lower()
    basic_raw = str(basic_category or "").lower()
    taxonomy_raw = str(taxonomy_primary or "").lower()
    category_text = f"{basic_raw} {taxonomy_raw}".replace("_", " ")
    domain = website_domain(website)
    fields = " ".join(
        (name_text, category_text, domain, str(description or "").lower())
    )

    pet_taxonomies = {
        "animal_or_pet_service",
        "pet_cemetery_and_crematorium_service",
        "pet_funeral_service",
        "pet_cremation_service",
    }
    pet_name_signal = bool(re.search(
        r"\b(?:pet|animal)\s+(?:funeral|funerals|cremation|cremations|burial|burials|cemetery|cemeteries)\b",
        name_text,
    ))
    if basic_raw in pet_taxonomies or taxonomy_raw in pet_taxonomies or pet_name_signal:
        return "pet_service"

    if domain and any(domain == item or domain.endswith("." + item) for item in DIRECTORY_DOMAINS):
        return "directory_or_comparison"

    # Natural/woodland/green burial locations are burial-ground services, not
    # funeral-director branches, even when Overture supplies funeral taxonomy.
    if any(term in fields for term in CATEGORY_TERMS["cemetery"]):
        return "cemetery"

    # Direct-cremation businesses are retained under their own service class.
    # A funeral director whose trading name explicitly identifies it as such
    # remains a funeral-director candidate even if it also offers cremations.
    name_has_funeral_director_signal = any(term in name_text for term in FUNERAL_TERMS)
    compact_name = re.sub(r"[^a-z0-9]", "", name_text)
    name_has_cremation_signal = bool(re.search(r"\bcremations?\b", name_text))
    direct_cremation_signal = bool(
        re.search(r"\bdirect\s+cremations?\b", name_text)
        or "direct2grave" in compact_name
        or "godirectcremation" in compact_name
    )
    if direct_cremation_signal or (
        name_has_cremation_signal and not name_has_funeral_director_signal
    ):
        return "direct_cremation_provider"

    # Funeral-plan-only providers are not classified as branch-based funeral
    # directors. Businesses explicitly named as funeral directors remain in
    # scope if they also offer plans.
    plan_fields = f"{name_text} {category_text}"
    funeral_plan_signal = any(term in plan_fields for term in (
        "funeral plan", "funeral plans", "prepaid funeral",
        "pre-paid funeral", "pre paid funeral", "prepaid plan",
        "pre-paid plan",
    ))
    if funeral_plan_signal and not name_has_funeral_director_signal:
        return "funeral_plan_provider"

    for classification in (
        "crematorium",
        "celebrant",
        "memorial_or_masonry",
        "civic_or_council_service",
        "directory_or_comparison",
        "likely_irrelevant",
    ):
        if any(term in fields for term in CATEGORY_TERMS[classification]):
            return classification

    if any(term in fields for term in FUNERAL_TERMS) or "funeral" in category_text:
        return "funeral_director_candidate"
    return "uncertain"

def exact_branch_fingerprint(
    *, name: object = "", postcode: object = "", phone: object = "", website: object = ""
) -> str | None:
    """Strong same-branch duplicate key; different postcodes remain separate."""
    normal_name = normalise_identity_name(name)
    normal_pc = normalise_postcode(postcode)
    normal_tel = normalise_phone(phone)
    domain = website_domain(website)
    if not normal_name or not normal_pc or not (normal_tel or domain):
        return None
    # Phone is preferred; domain is fallback when no phone is available.
    discriminator = normal_tel or domain
    return "|".join((normal_name, normal_pc, discriminator))


def provider_identity_key(
    *, name: object = "", website: object = "", phone: object = ""
) -> str | None:
    """Conservative parent-provider key for suggested grouping, not auto-merging."""
    normal_name = normalise_identity_name(name)
    if not normal_name:
        return None
    domain = website_domain(website)
    phone = normalise_phone(phone)
    if domain:
        return f"{normal_name}|domain:{domain}"
    if phone:
        return f"{normal_name}|phone:{phone}"
    return None


def candidate_location_flags(
    *,
    postcode: object = "",
    latitude: object = None,
    longitude: object = None,
    point_in_boundary: bool | None = None,
    expected_outward_codes: set[str] | None = None,
) -> list[str]:
    """Return location review flags; never infer a replacement address."""
    flags: list[str] = []
    if not is_valid_uk_postcode(postcode):
        flags.append("POSTCODE_MISSING_OR_INVALID")
    else:
        outward = postcode_outward_code(postcode)
        allowed = expected_outward_codes or THURROCK_OUTWARD_CODES
        if outward not in allowed:
            flags.append("POSTCODE_OUTSIDE_EXPECTED_AREA")

    has_lat = latitude not in (None, "")
    has_lon = longitude not in (None, "")
    if has_lat != has_lon:
        flags.append("INCOMPLETE_COORDINATE_PAIR")
    elif has_lat and has_lon:
        try:
            lat, lon = float(latitude), float(longitude)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                flags.append("INVALID_COORDINATE_RANGE")
            elif point_in_boundary is False:
                flags.append("POINT_OUTSIDE_TARGET_BOUNDARY")
        except (TypeError, ValueError):
            flags.append("INVALID_COORDINATES")

    if point_in_boundary is True and "POSTCODE_OUTSIDE_EXPECTED_AREA" in flags:
        flags.append("POSTCODE_COORDINATE_CONFLICT")
    return flags
