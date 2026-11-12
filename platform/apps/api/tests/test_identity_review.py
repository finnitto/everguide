from types import SimpleNamespace
from app.routers.identity_review import _domain, _confidence


def test_domain_normalises_www_and_path():
    assert _domain('https://www.example.co.uk/contact') == 'example.co.uk'


def test_identity_signal_increases_review_confidence():
    lead = SimpleNamespace(match_score=0.4, verification_status='identity_signals_found', http_status=200, robots_allowed=True)
    assert _confidence(lead) == 0.75


def test_unverified_search_result_keeps_original_match_score():
    lead = SimpleNamespace(match_score=0.62, verification_status='check_blocked_or_failed', http_status=403, robots_allowed=False)
    assert _confidence(lead) == 0.62

from app.routers.identity_review import _branch_eligible


def test_directory_signal_cannot_receive_high_identity_confidence():
    lead = SimpleNamespace(match_score=1.0, verification_status='identity_signals_found', http_status=200,
                           robots_allowed=True, result_url='https://ashesregister.com/example', final_url=None)
    assert _confidence(lead) == 0.49


def test_branch_requires_uk_structured_data_and_non_directory_domain():
    data = {'has_complete_branch_address': True, 'street': '1 High Street', 'town': 'York',
            'postcode': 'YO1 1AA', 'country': 'gb', 'source_type': 'schema_org_localbusiness'}
    official = SimpleNamespace(result_url='https://examplefunerals.co.uk/contact', final_url=None)
    directory = SimpleNamespace(result_url='https://ashesregister.com/example', final_url=None)
    assert _branch_eligible(official, data) is True
    assert _branch_eligible(directory, data) is False
    assert _branch_eligible(official, {**data, 'country': 'unspecified'}) is False
    assert _branch_eligible(official, {**data, 'source_type': 'page_text'}) is False
