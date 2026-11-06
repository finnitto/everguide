from app.website_checks import _structured_funeral_home_data


def test_extracts_complete_uk_funeral_home():
    html = '''<script type="application/ld+json">{"@type":"FuneralHome","name":"Example Funeral Directors","address":{"streetAddress":"1 High Street","addressLocality":"York","postalCode":"YO1 1AA","addressCountry":"GB"},"telephone":"01904 123456"}</script>'''
    result = _structured_funeral_home_data(html)
    assert result["name"] == "Example Funeral Directors"
    assert result["postcode"] == "YO1 1AA"


def test_rejects_incomplete_address():
    html = '''<script type="application/ld+json">{"@type":"FuneralHome","name":"Example Funeral Directors","address":{"addressLocality":"York"}}</script>'''
    assert _structured_funeral_home_data(html) is None


def test_rejects_non_funeralhome_schema():
    html = '''<script type="application/ld+json">{"@type":"LocalBusiness","name":"Example Funeral Directors","address":{"streetAddress":"1 High Street","addressLocality":"York","postalCode":"YO1 1AA","addressCountry":"GB"}}</script>'''
    assert _structured_funeral_home_data(html) is None


def test_rejects_non_uk_postcode():
    html = '''<script type="application/ld+json">{"@type":"FuneralHome","name":"Example Funeral Directors","address":{"streetAddress":"1 Main Street","addressLocality":"Paris","postalCode":"75001","addressCountry":"FR"}}</script>'''
    assert _structured_funeral_home_data(html) is None
