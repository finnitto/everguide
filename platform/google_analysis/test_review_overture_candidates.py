from pathlib import Path
import sys

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_overture_candidates import review_row


def test_review_row_flags_foreign_postcode_even_when_point_is_inside():
    row = {
        "name": "Desmond Maguire Funeral Directors",
        "basic_category": "family_service",
        "taxonomy_primary": "funeral_service",
        "postcode": "G73 2AW",
        "phone": "+441416470900",
        "website": "https://www.desmondmaguire.co.uk/",
        "latitude": "51.4801651",
        "longitude": "0.3741444",
        "confidence": "0.9",
    }
    result, _ = review_row(row, box(0.20, 51.44, 0.56, 51.58))
    assert result["service_class"] == "funeral_director_candidate"
    assert result["point_in_thurrock"] == "inside"
    assert "POSTCODE_COORDINATE_CONFLICT" in result["location_flags"]
    assert result["review_decision"] == "hold_for_manual_location_review"


def test_review_row_excludes_memorial_business_despite_funeral_taxonomy():
    row = {
        "name": "A Elfes",
        "basic_category": "family_service",
        "taxonomy_primary": "funeral_service",
        "postcode": "RM15 4XS",
        "phone": "01708 682790",
        "website": "http://www.memorialgroup.co.uk",
        "latitude": "51.498378",
        "longitude": "0.230176",
    }
    result, _ = review_row(row, box(0.20, 51.44, 0.56, 51.58))
    assert result["service_class"] == "memorial_or_masonry"
    assert result["review_decision"] == "exclude_from_funeral_director_category"
