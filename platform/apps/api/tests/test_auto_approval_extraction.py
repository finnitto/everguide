from app.website_checks import _extract_funeral_provider_data, _structured_funeral_home_data


def test_extracts_complete_uk_funeral_home():
    html = '''<script type="application/ld+json">{"@type":"FuneralHome","name":"Example Funeral Directors","address":{"streetAddress":"1 High Street","addressLocality":"York","postalCode":"YO1 1AA","addressCountry":"GB"},"telephone":"01904 123456"}</script>'''
    result = _structured_funeral_home_data(html)
    assert result["name"] == "Example Funeral Directors"
    assert result["postcode"] == "YO1 1AA"
    assert result["has_complete_branch_address"] is True


def test_accepts_localbusiness_when_page_has_funeral_context():
    html = '''<title>Example Funeral Directors</title><script type="application/ld+json">{"@type":"LocalBusiness","name":"Example Funeral Directors","address":{"streetAddress":"1 High Street","addressLocality":"York","postalCode":"YO1 1AA","addressCountry":"GB"}}</script>'''
    result = _extract_funeral_provider_data(html)
    assert result is not None
    assert result["source_type"] == "schema_org_localbusiness"


def test_accepts_provider_identity_without_complete_branch_address():
    html = '''<title>Example Funeral Directors - Independent Funeral Services</title><script type="application/ld+json">{"@type":"Organization","name":"Example Funeral Directors","url":"https://example.test"}</script>'''
    result = _extract_funeral_provider_data(html)
    assert result is not None
    assert result["has_complete_branch_address"] is False
    assert result["postcode"] is None


def test_rejects_generic_business_without_funeral_context():
    html = '''<title>Example Retail Shop</title><script type="application/ld+json">{"@type":"LocalBusiness","name":"Example Retail Shop","address":{"streetAddress":"1 High Street","addressLocality":"York","postalCode":"YO1 1AA","addressCountry":"GB"}}</script>'''
    assert _extract_funeral_provider_data(html) is None


def test_rejects_incomplete_non_funeral_identity():
    html = '''<script type="application/ld+json">{"@type":"LocalBusiness","name":"Example Business","address":{"addressLocality":"York"}}</script>'''
    assert _extract_funeral_provider_data(html) is None


def test_rejects_non_uk_postcode_and_country():
    html = '''<title>Paris Funeral Directors</title><script type="application/ld+json">{"@type":"FuneralHome","name":"Paris Funeral Directors","address":{"streetAddress":"1 Main Street","addressLocality":"Paris","postalCode":"75001","addressCountry":"FR"}}</script>'''
    assert _extract_funeral_provider_data(html) is None
