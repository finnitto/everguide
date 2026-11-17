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


def test_overture_branch_match_requires_one_verified_link_and_exact_postcode():
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import CompaniesHouseCandidate, OvertureCandidate, OvertureCompanyLink
    from app.identity_assessment import matched_overture_company_link

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    company = CompaniesHouseCandidate(
        company_number="01234567", company_name="Example Funeral Directors Ltd", company_status="active"
    )
    first = OvertureCandidate(gers_id="GERS-MATCH-001", candidate_name="Example Funeral Directors", postcode="SS1 1AA")
    second = OvertureCandidate(gers_id="GERS-MATCH-002", candidate_name="Example Funeral Directors Branch 2", postcode="SS2 2BB")
    db.add_all([company, first, second])
    db.flush()
    reviewed = datetime.now(timezone.utc)
    first_link = OvertureCompanyLink(
        overture_candidate_id=first.id, companies_house_candidate_id=company.id,
        status="verified", reviewed_by="reviewer", reviewed_at=reviewed, evidence_json={"finding":"matched"}
    )
    second_link = OvertureCompanyLink(
        overture_candidate_id=second.id, companies_house_candidate_id=company.id,
        status="verified", reviewed_by="reviewer", reviewed_at=reviewed, evidence_json={"finding":"matched"}
    )
    db.add_all([first_link, second_link])
    db.commit()

    match = matched_overture_company_link(db, company.id, "ss1 1aa")
    assert match is not None
    assert match[0].id == first_link.id
    assert match[1].gers_id == "GERS-MATCH-001"
    assert matched_overture_company_link(db, company.id, "SS9 9ZZ") is None
    assert matched_overture_company_link(db, company.id, None) is None

    # Two Overture locations sharing the same postcode are ambiguous, not guessed.
    second.postcode = "SS1 1AA"
    db.commit()
    assert matched_overture_company_link(db, company.id, "SS1 1AA") is None
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
