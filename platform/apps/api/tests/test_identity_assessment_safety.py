from types import SimpleNamespace

from app.identity_assessment import _clean_business_name, confidence, branch_eligible


def lead(**kwargs):
    base = dict(match_score=1.0, verification_status="identity_signals_found", http_status=200,
                robots_allowed=True, result_url="https://examplefunerals.co.uk/contact", final_url=None,
                page_title="Example Funeral Directors", result_title="Example Funeral Directors", extracted_data={})
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_long_promotional_description_is_not_saved_as_business_name():
    description = ("Funeral Directors Kiveton Park – Independent Funeral Services is a family-run "
                   "funeral directors and funeral home providing personal, caring and professional services "
                   "within Kiveton Park and surrounding areas.")
    assert _clean_business_name(description, "Independent Funeral Services", "Search result") == "Independent Funeral Services"


def test_name_length_is_bounded():
    assert _clean_business_name("X" * 241, "Short Funeral Directors") == "Short Funeral Directors"


def test_identity_score_never_claims_one_hundred_percent():
    assert confidence(lead()) <= 0.75


def test_directory_and_pet_cremation_are_low_confidence():
    directory = lead(result_url="https://192.com/example", extracted_data={})
    pet = lead(result_title="Pet Cremation Services", extracted_data={"name":"Pet Cremation Services"})
    assert confidence(directory) <= 0.20
    assert confidence(pet) <= 0.20


def test_pet_cremation_cannot_create_branch_proposal():
    item = lead(result_title="Pet Cremation Services", extracted_data={})
    data = {"has_complete_branch_address":True, "street":"1 High Street", "town":"York",
            "postcode":"YO1 1AA", "country":"England", "source_type":"schema_org_localbusiness",
            "website":"https://examplefunerals.co.uk"}
    eligible, reason = branch_eligible(item, data)
    assert not eligible
    assert reason == "adjacent_sector_or_non_provider_signal"


def test_unrelated_company_name_is_capped_even_on_official_looking_site():
    item = lead(result_url="https://staffordshirefunerals.co.uk/",
                extracted_data={"name":"Staffordshire Funerals", "website":"https://staffordshirefunerals.co.uk"})
    company = SimpleNamespace(company_name="MY EASY FUNERAL LTD")
    assert confidence(item, company) <= 0.20

def test_matching_company_name_can_score_above_unrelated_match():
    item = lead(result_url="https://derwentsidefuneralservice.co.uk/",
                extracted_data={"name":"Derwentside Funeral Service", "website":"https://derwentsidefuneralservice.co.uk"})
    matching = SimpleNamespace(company_name="DERWENTSIDE FUNERAL SERVICE LIMITED")
    unrelated = SimpleNamespace(company_name="YOGI ALLIANCE LIMITED")
    assert confidence(item, matching) > confidence(item, unrelated)

def test_directory_score_is_capped_at_ten_percent():
    item = lead(result_url="https://ashesregister.com/example",
                extracted_data={"name":"Example Funeral Directors"})
    assert confidence(item, SimpleNamespace(company_name="Example Funeral Directors Ltd")) <= 0.10
