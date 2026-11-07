from types import SimpleNamespace

from app.identity_rules import _classify, _provider_quality_assessment


def test_directory_search_result_is_not_a_provider():
    assert _classify(
        "Funeral Directors in Portsmouth — Compare 53 Local Funeral Services",
        "There are 12 funeral directors based in Portsmouth and 53 within 10 miles.",
        "funeralfinder.org",
    ) == "directory_or_comparison"


def test_localfuneral_directory_is_not_a_provider():
    assert _classify(
        "Find local funeral directors in Dover | 1",
        "localfuneral.co.uk can put you in touch with local independent funeral directors.",
        "localfuneral.co.uk",
    ) == "directory_or_comparison"


def test_cemetery_council_is_related_service_not_funeral_director():
    assert _classify(
        "Ipswich Cemeteries and Crematorium - Ipswich Borough Council",
        "We have four cemeteries and the Ipswich Crematorium and provide funeral services.",
        "ipswichcemetery.co.uk",
    ) == "related_service_not_funeral_director"


def test_genuine_provider_search_result_remains_candidate():
    assert _classify(
        "AH Freemantle Funeral Directors Portsmouth",
        "Independent family-run funeral directors serving Portsmouth.",
        "ahfreemantle.co.uk",
    ) == "provider_candidate"


def test_structured_data_observation_counts_as_quality_evidence():
    provider = SimpleNamespace(trading_name="Jackson Browning Funerals", website="https://jacksonbrowningfunerals.co.uk/")
    observation = SimpleNamespace(
        review_status="accepted",
        source_url="https://jacksonbrowningfunerals.co.uk/oxford-funeral-directors-services/",
        source_type="provider_website_structured_data",
        confidence=0.98,
        observed_data={
            "provider_name": "Jackson Browning Funerals",
            "address_line_1": "Market Place",
            "town_city": "Faringdon",
            "postcode": "SN7 7AA",
            "telephone": "+44 1367 244992",
        },
    )
    status, reason = _provider_quality_assessment(provider, [observation])
    assert status == "confirmed"
    assert "structured" not in reason.lower() or "evidence" in reason.lower()


def test_url_like_and_directory_provider_names_are_held_for_review():
    provider = SimpleNamespace(trading_name="https://ahfreemantle.co.uk/", website="https://ahfreemantle.co.uk/")
    assert _provider_quality_assessment(provider, [])[0] == "needs_review"
    provider = SimpleNamespace(trading_name="FuneralFinder", website="https://funeralfinder.org/")
    assert _provider_quality_assessment(provider, [])[0] == "needs_review"
