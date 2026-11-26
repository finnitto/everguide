from app.pricing_enrichment import _option_group_id, _validate_extracted_prices


def _payload(group_name):
    return {
        "prices": [{
            "service_name": "Attended funeral",
            "option_group_name": group_name,
            "service_category": "funeral",
            "fee_type": "package",
            "amount": 2400,
            "amount_upper": None,
            "currency": "GBP",
            "price_basis": "fixed",
            "includes": [],
            "excludes": [],
            "source_page_url": "https://example.org/prices",
            "source_page_number": None,
            "source_quote": "Attended funeral package £2,400",
            "confidence": 0.9,
        }]
    }


def _pages():
    return [{
        "url": "https://example.org/prices",
        "source_page_number": None,
        "source_format": "html",
        "text": "Attended funeral package £2,400. Simple funeral package £1,500. Premium gold package £2,400.",
        "sha256": "a" * 64,
    }]


def test_group_label_is_retained_only_when_present_in_same_source_page():
    accepted = _validate_extracted_prices(_payload("Attended funeral"), _pages())
    unsupported = _validate_extracted_prices(_payload("Premium gold package"), _pages())

    assert accepted[0]["option_group_name"] == "Attended funeral"
    assert unsupported[0]["option_group_name"] is None
    # Even a label elsewhere on the page cannot claim this quote's price.
    unrelated = _validate_extracted_prices(_payload("Premium gold package"), _pages())
    assert unrelated[0]["option_group_name"] is None
    # Unsupported grouping does not discard independently evidenced price data.
    assert unsupported[0]["amount"] == accepted[0]["amount"]


def test_group_id_is_stable_and_scoped_to_provider_branch():
    first = _option_group_id(10, 20, "Attended Funeral")

    assert first == _option_group_id(10, 20, " attended funeral ")
    assert first != _option_group_id(10, 21, "Attended Funeral")
    assert first != _option_group_id(11, 20, "Attended Funeral")
    assert _option_group_id(10, 20, None) is None
