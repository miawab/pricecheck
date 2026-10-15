"""Bargaining advice, similar listings, the store and recipes: plain code, no Gemma or TabPFN needed."""
import pandas as pd
import pytest

from pricecheck import model
from pricecheck.recipe import Recipe
from pricecheck.store import Store


@pytest.mark.parametrize("price,verdict", [
    (10_000, "too_cheap"),
    (24_000, "good_deal"),
    (30_000, "fair"),
    (40_000, "overpriced"),
])
def test_advice_verdicts(price, verdict):
    assert model.advice(price, 25_000, 30_000, 35_000)["verdict"] == verdict


def test_advice_unsure_when_range_is_wide():
    assert model.advice(30_000, 10_000, 30_000, 40_000)["verdict"] == "unsure"


def test_advice_never_says_pay_more_than_asked():
    a = model.advice(28_000, 25_000, 30_000, 35_000)
    assert a["max_pay"] <= 28_000
    assert a["open_at"] <= a["fair_from"] <= a["fair_to"] <= a["max_pay"]
    assert all(v % 500 == 0 for k, v in a.items() if k in ("open_at", "fair_from", "fair_to", "max_pay"))


def test_similar_matches_specs_and_prefers_nearby():
    recipe = Recipe("monitors")
    d = pd.DataFrame([
        {"id": "a", "size_inch": 27.0, "panel": "ips", "resolution": "1080p", "city_group": "isb_rwp", "price": 40_000, "removed_on": None},
        {"id": "b", "size_inch": 27.0, "panel": "ips", "resolution": "1080p", "city_group": "lahore", "price": 30_000, "removed_on": None},
        {"id": "c", "size_inch": 24.0, "panel": "ips", "resolution": "1080p", "city_group": "isb_rwp", "price": 20_000, "removed_on": None},
        {"id": "d", "size_inch": 27.0, "panel": "va", "resolution": "1080p", "city_group": "isb_rwp", "price": 25_000, "removed_on": None},
        {"id": "e", "size_inch": 27.0, "panel": "ips", "resolution": "1080p", "city_group": "isb_rwp", "price": 35_000, "removed_on": "2026-10-01"},
    ])
    row = {"id": "me", "size_inch": 27.0, "panel": "ips", "resolution": "1080p", "city_group": "isb_rwp"}
    assert list(model.similar(recipe, d, row).id) == ["a", "b"]  # same specs, active, Islamabad first


def test_store_tracks_new_repriced_and_removed(tmp_path, monkeypatch):
    recipe = Recipe("monitors")
    monkeypatch.setattr(recipe, "data_dir", tmp_path)
    store = Store(recipe)
    day1 = [{"id": "1", "price": 30_000}, {"id": "2", "price": 20_000}]
    assert store.merge(day1, today="2026-10-01") == (2, 0, 0)
    day2 = [{"id": "1", "price": 28_000}, {"id": "3", "price": 50_000}]
    assert store.merge(day2, today="2026-10-02") == (1, 1, 1)
    assert store.listings["1"]["price_history"] == [["2026-10-01", 30_000], ["2026-10-02", 28_000]]
    assert store.listings["2"]["removed_on"] == "2026-10-02"


def test_recipe_schema_covers_every_field():
    recipe = Recipe("monitors")
    schema = recipe.schema()
    assert set(schema["required"]) == {f["key"] for f in recipe.fields}
    assert "size_inch" in recipe.spec_names
    assert "{title}" in recipe.prompt() and "{description}" in recipe.prompt()
