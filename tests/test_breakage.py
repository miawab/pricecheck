"""When OLX changes its pages: the reader says so clearly, and the report is useful and safe to make public."""
import json
from pathlib import Path

import pytest

from pricecheck import breakage, olx
from pricecheck.rehearsal import change_layout

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "olx"


class Page:
    def __init__(self, text):
        self.text = text


def serve(monkeypatch, html):
    monkeypatch.setattr(olx.requests, "get", lambda url, **_: Page(html))
    monkeypatch.setattr(olx, "DELAY", 0)


def redesigned_search_page():
    return change_layout((FIXTURES / "search_p1.html").read_text(encoding="utf-8"))


def test_redesigned_search_page_raises_layout_changed(monkeypatch):
    serve(monkeypatch, redesigned_search_page())
    with pytest.raises(olx.LayoutChanged, match="search results not where expected") as caught:
        olx.search("computer-components_c708205?filter=type_eq_monitors", log=lambda *_: None)
    assert "listingSearch" in caught.value.html


def test_report_points_at_where_listings_moved(monkeypatch):
    serve(monkeypatch, redesigned_search_page())
    with pytest.raises(olx.LayoutChanged) as caught:
        olx.search("computer-components_c708205", log=lambda *_: None)
    info = breakage.describe(caught.value, "test")
    assert "window.state.listingSearch.page.items[]" in info["body"]
    assert "search page" in info["title"]


def test_fixture_keeps_the_new_shape_and_listings(monkeypatch):
    html = redesigned_search_page()
    data = breakage.page_data(breakage.fixture(html))["state"]
    items = data["listingSearch"]["page"]["items"]
    assert 0 < len(items) <= breakage.KEEP_LISTINGS
    assert data["listingSearch"]["page"]["totalPages"] == 2
    assert all(i["title"] and i["externalID"] for i in items)


def test_fixture_never_contains_seller_details():
    hit = {"externalID": "9", "title": "Dell 24 call 0300 1234567", "price": 20000,
           "contactInfo": {"name": "Ali", "mobile": "03001234567"}, "userExternalID": "u-42",
           "isSellerVerified": True, "description": "whatsapp +92 300-7654321"}
    state = {"user": {"email": "x@y.z"}, "loggedInAgentData": {"id": 1}, "search": {"items": [hit]}}
    html = f"<script>window.state = {json.dumps(state)};</script>"
    out = breakage.fixture(html)
    for secret in ("1234567", "7654321", "Ali", "u-42", "x@y.z", "contactInfo", "loggedInAgentData"):
        assert secret not in out
    kept = breakage.page_data(out)["state"]["search"]["items"][0]
    assert kept["externalID"] == "9" and kept["price"] == 20000 and kept["isSellerVerified"] is True


def test_report_saves_locally_without_gitlab_token(monkeypatch, tmp_path):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setattr(breakage, "ROOT", tmp_path)
    err = olx.LayoutChanged("https://www.olx.com.pk/x", redesigned_search_page(), "test")
    assert breakage.report(err, "test", log=lambda *_: None) is None
    saved = list((tmp_path / "data" / "broken").iterdir())[0]
    assert (saved / "issue.md").exists() and (saved / "fixture.html").exists()
