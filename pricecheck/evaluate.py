"""How good are the price ranges? Compares TabPFN with simpler ways of guessing a fair price.

Every listing is hidden in turn (5-fold) and priced only from the others:
  - "same specs median": the median price of listings that match on the recipe's similar_on fields
  - gradient boosting: a standard tabular ML model, to check TabPFN isn't just "any ML would do"
  - TabPFN

    python -m pricecheck.evaluate monitors
"""
import sys

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold

from . import model
from .recipe import Recipe
from .store import Store


def errors(y, pred):
    err = np.abs(np.exp(pred) - np.exp(y)) / np.exp(y)
    return np.median(err) * 100, (err <= 0.15).mean() * 100


def main():
    recipe = Recipe(sys.argv[1] if len(sys.argv) > 1 else "monitors")
    d = model.frame(recipe, Store(recipe))
    d = d[~d.outlier].reset_index(drop=True)
    X, y = model.features(recipe, d), np.log(d.price.to_numpy())
    keys = [k for k in recipe.similar_on if k in d]
    group = d[keys].round().astype(str).agg("|".join, axis=1) if keys else d.price * 0

    preds = {name: np.zeros(len(d)) for name in ["same specs median", "gradient boosting", "TabPFN"]}
    q25, q75 = np.zeros(len(d)), np.zeros(len(d))
    for train, test in KFold(5, shuffle=True, random_state=0).split(X):
        med = d.price.iloc[train].groupby(group.iloc[train]).median()
        overall = d.price.iloc[train].median()
        preds["same specs median"][test] = np.log(group.iloc[test].map(med).fillna(overall).to_numpy())
        preds["gradient boosting"][test] = HistGradientBoostingRegressor(random_state=0).fit(X[train], y[train]).predict(X[test])
        q = model._fit_predict(X[train], y[train], X[test])
        q25[test], preds["TabPFN"][test], q75[test] = np.log(q[:, 0]), np.log(q[:, 1]), np.log(q[:, 2])

    print(f"{len(d)} {recipe.title.lower()} listings, each priced without seeing itself\n")
    print(f"{'method':<22}{'typical error':>15}{'within 15%':>13}")
    for name, p in preds.items():
        med_err, within = errors(y, p)
        print(f"{name:<22}{med_err:>14.1f}%{within:>12.1f}%")
    inside = ((y >= q25) & (y <= q75)).mean() * 100
    print(f"\nTabPFN's 'usual range' (25th-75th percentile) held the real asking price {inside:.0f}% of the time (ideal: 50%)")


if __name__ == "__main__":
    main()
