from app.company_classification import classify_name

def test_funeral_director_name_is_likely_not_verified():
    category, confidence, reason = classify_name('Example Funeral Directors Limited')
    assert category == 'likely_funeral_director'
    assert confidence == 'medium'
    assert 'not yet verified' in reason

def test_council_name_is_related_service():
    category, confidence, _ = classify_name('Example Borough Council')
    assert category == 'related_service'
    assert confidence == 'medium'

def test_directory_name_is_not_funeral_director():
    category, confidence, _ = classify_name('Funeral Finder Directory')
    assert category == 'directory_or_comparison'
    assert confidence == 'high'

def test_uninformative_name_stays_uncertain():
    category, confidence, _ = classify_name('ABC Services Limited')
    assert category == 'uncertain'
    assert confidence == 'low'
