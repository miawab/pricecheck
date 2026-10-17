# pricecheck

**Is this OLX price fair?** Paste an OLX link or browse a category, and see what similar listings usually ask, whether this one is a good deal, and what to offer when you bargain.

Built for the [Hacktoberfest 2026 DEV Challenge, Week 2: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).

Everything runs on your own computer with open models:

- **Gemma** (Google's open-weight model, run locally with Ollama) reads each messy listing ("27 inch ips lush condition 10/10 box available") into clean columns.
- **TabPFN** (Prior Labs' tabular model, also local) learns from all the other listings what a similar item usually costs, and gives a price *range*.
- **Plain code** turns that range into advice: open at, fair deal, most you should pay. The models supply facts; code decides.

Nothing runs in the background. Data only changes when you run the update yourself.

## What you need

- A Windows, Mac or Linux PC. An NVIDIA GPU with 6 GB+ makes Gemma fast (a few seconds per listing); without one it still works on the CPU, just slower.
- About 10 GB free disk space (the Gemma model is ~6 GB).
- Python 3.11 or newer.

## Setup (once)

1. **Install Ollama** from [ollama.com](https://ollama.com) and open it.
2. **Download Gemma** (about 6 GB):
   ```
   ollama pull gemma4:e4b-it-qat
   ```
   On a weaker PC use the smaller `gemma4:e2b-it-qat` instead, and add `PRICECHECK_MODEL=gemma4:e2b-it-qat` to `.env` (step 5).
3. **Get the code and its packages:**
   ```
   git clone https://github.com/miawab/pricecheck
   cd pricecheck
   python -m venv .venv
   .venv\Scripts\activate          (Windows)
   source .venv/bin/activate       (Mac/Linux)
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```
4. **Get a free TabPFN key:** sign up at [ux.priorlabs.ai](https://ux.priorlabs.ai), accept the license on the **Licenses** tab, and copy your API key from the **Account** page.
5. **Add the key:** copy `.env.example` to `.env` and paste the key after `TABPFN_TOKEN=`.
6. **Check everything:**
   ```
   python -m pricecheck.doctor
   ```
   It tells you exactly what's missing and how to fix it.

## Use it

```
python -m pricecheck.update monitors --limit 100   # first try: collect monitors, let Gemma read 100 of them
python -m pricecheck.app                           # then open http://localhost:8000
```

When you're happy, run `python -m pricecheck.update monitors` without `--limit` to read everything (about an hour for ~1,200 listings on a mid-range GPU; each later run only reads the new ones). Run it again whenever you want fresh prices.

| Command | What it does |
|---|---|
| `python -m pricecheck.update <recipe>` | Collect listings, let Gemma read new ones, price everything |
| `... --limit 100` | Read at most 100 new listings this run |
| `... --no-collect` | Re-price what you already have, without visiting OLX |
| `... --no-gemma` | Collect and price, but don't use Gemma (no GPU load) |
| `python -m pricecheck.app` | Start the page at http://localhost:8000 (also checks brand-new links live) |
| `python -m pricecheck.doctor` | Check your setup |
| `python -m pricecheck.evaluate <recipe>` | Measure how accurate the price ranges are vs simpler methods |
| `python -m pricecheck.new_recipe <name> "<OLX link>"` | Draft a recipe for another category |

## Any OLX category

A **recipe** (`recipes/<name>.toml`) tells pricecheck where to collect from and what matters for the price. Monitors is one recipe. To add another:

1. Open the OLX category you want in your browser (e.g. Mobile Phones) and copy the address.
2. Let Gemma draft the recipe from real listings:
   ```
   python -m pricecheck.new_recipe phones "https://www.olx.com.pk/mobile-phones_c1453"
   ```
3. Open `recipes/phones.toml`, read it, and fix anything that looks off (field names, allowed values, what to check in person).
4. Run it: `python -m pricecheck.update phones --limit 100`, then `python -m pricecheck.app`. The page builds its filters from the recipe, and a category switcher appears at the top.

## How it works

```
OLX category page ──► collect (2 s per page, public pages only, no names or phone numbers kept)
                      │
                      ▼
            Gemma reads each listing once ──► specs (brand, size, panel, condition, ...)
                      │
                      ▼
            TabPFN prices every listing from the others ──► usual range (25th–75th percentile)
                      │
                      ▼
            code: good deal / fair / overpriced / too cheap / hard to judge + what to offer
                      │
                      ▼
            site/data/<recipe>.json ──► the page (works as plain files, so it can be hosted anywhere)
```

- **Removed listings are kept.** When a listing disappears it was probably sold, so its last price is the closest thing to a real sale price. It's hidden from the page but still teaches the model.
- **Price changes are tracked**, so you can see sellers coming down over time.
- **No retraining.** TabPFN reads the current listings every time it predicts, so prices follow the market as you refresh.
- **Each listing is priced by a model that never saw it** (5-fold), so its own price can't leak into its "usual" range.

## Optional: compare with shop prices (SerpApi)

Add `SERPAPI_KEY=<your key>` to `.env` (free plan at [serpapi.com](https://serpapi.com), 250 searches a month). Then:

- each live check on the local page looks up what Pakistani shops charge for that exact model (one Google search, saved so it's never repeated), and
- `python -m pricecheck.update monitors --new-prices 30` looks up the 30 most common models for the whole page.

Shop prices are often for imported or refurbished units, and shops disagree, so the page only gives one number when the shops roughly agree (within 60% of each other); otherwise it shows the range and the links. OLX's own listings are left out.

## Optional: see every check in Sentry

Add `SENTRY_DSN=<your DSN>` to `.env` (create a Python/FastAPI project at [sentry.io](https://sentry.io), free plan) and each price check shows up as an AI agent run:

```
invoke_agent pricecheck                ← one "is this price fair?" check
  ├── execute_tool fetch_olx_listing   ← read the OLX page
  ├── chat gemma4:e4b-it-qat           ← Gemma reads the listing: tokens, retries, cut-off answers
  ├── execute_tool tabpfn_price_range  ← TabPFN predicts the usual range
  ├── execute_tool bargain_advice      ← code turns it into what to offer
  └── execute_tool serpapi_new_price   ← what shops charge for the same model
```

That's how we found that a cold Gemma (not yet loaded into the GPU) takes ~2 minutes on the first check, versus ~5 seconds once it's warm. Only public listing text is sent; no IPs or personal data.

## When OLX changes its site: pricecheck heals itself

Scrapers break whenever a site moves its data around. pricecheck fixes itself on GitLab, with nobody in the loop:

```
your PC   python -m pricecheck.update monitors      OLX page doesn't match any layout pricecheck knows
            └─ breakage.py                          saves a trimmed copy (no seller details, no phone numbers)
               opens a GitLab issue  ─────────┐     "listings moved to window.__OLX_STATE__.search.results[]"
                                              ▼
GitLab    flow trigger: issue created → Scraper Medic flow (.gitlab/duo/flows/scraper-medic.yml)
            ├─ scraper_medic   diagnoses, reproduces with a failing test, fixes olx.py for old AND new
            │                  layouts, opens a merge request, reads the log and fixes it if the pipeline fails
            ├─ reviewer        independent check: scope, no weakened tests, old layouts still read,
            │                  no personal data, pipeline green → APPROVE, or stop and ask a human
            └─ shipper         fast-forwards main, reports back on the issue
          main pipeline (.gitlab-ci.yml)
            test → SAST, secret + dependency scanning → package the site → deploy → release → smoke-test the live site
your PC   git pull, run again: it reads OLX again
```

Nothing runs on a timer: the loop starts only when you run pricecheck and it finds OLX changed.

**Rehearse it.** OLX can't be asked to redesign on cue, so `PRICECHECK_REHEARSE_OLX_CHANGE=<1|2|3>` rewrites the real
pages the way a redesign might (results moved, page data renamed, listing id renamed); see `pricecheck/rehearsal.py`.
To open issues automatically, put `GITLAB_TOKEN` (a personal access token with the `api` scope) and `GITLAB_PROJECT`
in `.env`.

## What it can't do

- It only sees **asking prices**, never what people actually paid. Removed listings are an estimate of sold prices, not proof.
- It believes what sellers **claim** ("IPS", "10/10 condition"). It can't check the item; the page tells you what to check in person.
- **Rare items** with few similar listings get wide ranges, and the page says "hard to judge" instead of guessing.
- A **sudden market change** (a new import tax, a currency jump) takes a few days to show up in listings.
- OLX shows at most ~50 pages per search, so very large categories need a narrower link (a sub-category or a filter).

## Privacy and politeness

Collection waits 2 seconds between pages, only reads public pages that OLX's robots.txt allows, and strips phone numbers from titles and descriptions. Seller names and phone numbers are never stored.
