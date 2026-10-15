"""The OLX reader, tested against saved pages (tests/fixtures/olx) so no request reaches OLX."""
from pathlib import Path

import pytest

from pricecheck import olx

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "olx"


class Page:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def fake_olx(monkeypatch):
    """Serve fixture pages instead of OLX: search page N -> search_pN.html, a listing -> item.html."""
    requested = []

    def get(url, **_):
        requested.append(url)
        if "/item/" in url:
            name = "item.html"
        else:
            name = f"search_p{url.split('page=')[1] if 'page=' in url else 1}.html"
        return Page((FIXTURES / name).read_text(encoding="utf-8"))

    monkeypatch.setattr(olx.requests, "get", get)
    monkeypatch.setattr(olx, "DELAY", 0)
    return requested


def test_search_reads_every_page(fake_olx):
    rows = olx.search("https://www.olx.com.pk/computer-components_c708205?filter=type_eq_monitors", log=lambda *_: None)
    assert len(rows) == 12
    assert len(fake_olx) == 2
    assert fake_olx[1].endswith("&page=2")
    assert len({r["id"] for r in rows}) == 12


def test_search_listing_fields(fake_olx):
    rows = olx.search("computer-components_c708205?filter=type_eq_monitors", log=lambda *_: None)
    for r in rows:
        assert r["id"].isdigit()
        assert r["url"].startswith("https://www.olx.com.pk/item/") and r["url"].endswith(f"-iid-{r['id']}")
        assert r["title"]
        assert isinstance(r["price"], (int, float)) and r["price"] > 0
        assert r["city"]


def test_details_reads_description_and_price(fake_olx):
    row = olx.details("https://www.olx.com.pk/item/samsung-32-inch-iid-1120313885")
    assert row["id"] == "1120313885"
    assert row["price"] == 65000  # the top-level price is 0 on this page; the real one is in extraFields
    assert row["description"].startswith("Samsung 32-inch")
    assert row["active"] is True
    assert row["city"] == "Lahore" and row["area"] == "Gulberg"


def test_page_without_data_fails_loudly(monkeypatch):
    monkeypatch.setattr(olx.requests, "get", lambda url, **_: Page("<html>new layout</html>"))
    with pytest.raises(olx.LayoutChanged, match="no `window.state` page data"):
        olx.details("https://www.olx.com.pk/item/x-iid-1")


@pytest.mark.parametrize("title", [
    "Dell 24 monitor 0300 1234567",
    "Dell 24 monitor +92 300-1234567",
    "Dell 24 monitor 03001234567 call now",
])
def test_phone_numbers_are_removed(title):
    assert "1234567" not in olx.no_phones(title)
    assert olx.no_phones(title).startswith("Dell 24 monitor")


def test_item_url_never_contains_phone():
    url = olx.item_url(123, "LG 27 IPS 0300 1234567")
    assert url == "https://www.olx.com.pk/item/lg-27-ips-iid-123"
    assert olx.listing_id(url) == "123"


@pytest.fixture
def fake_olx_listing_search(monkeypatch):
    """Serve the newer layout (`state.listingSearch.page.items`) for every search page, as fake_olx does for the old one."""
    requested = []

    def get(url, **_):
        requested.append(url)
        return Page((FIXTURES / "search_listingsearch.html").read_text(encoding="utf-8"))

    monkeypatch.setattr(olx.requests, "get", get)
    monkeypatch.setattr(olx, "DELAY", 0)
    return requested


def test_search_reads_listing_search_layout(fake_olx_listing_search):
    rows = olx.search("https://www.olx.com.pk/computer-components_c708205?filter=type_eq_monitors", log=lambda *_: None)
    assert len(rows) == 6
    assert len({r["id"] for r in rows}) == 6
    for r in rows:
        assert r["id"].isdigit()
        assert r["url"].startswith("https://www.olx.com.pk/item/") and r["url"].endswith(f"-iid-{r['id']}")
        assert r["title"]
        assert isinstance(r["price"], (int, float)) and r["price"] > 0  # top-level price is 0; real one is in extraFields
        assert r["city"]
    first = rows[0]
    assert first["id"] == "1120313885" and first["price"] == 65000
    assert first["city"] == "Lahore" and first["area"] == "Gulberg"
    assert first["brand_dropdown"] == "samsung" and first["condition_dropdown"] == "used"
    assert first["featured"] is True


def test_search_matching_neither_layout_raises_layout_changed(monkeypatch):
    html = '<script>window.state = {"somethingNew": {}};</script>'
    monkeypatch.setattr(olx.requests, "get", lambda url, **_: Page(html))
    with pytest.raises(olx.LayoutChanged):
        olx.search("computer-components_c708205", log=lambda *_: None)
