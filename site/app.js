// pricecheck front end. Reads data/<recipe>.json (made daily by `python -m pricecheck.update`)
// and, when served from your own PC, can also check brand-new listings live through /api/check.
const RECIPE = new URLSearchParams(location.search).get("r") || "monitors";
const LOCAL = ["localhost", "127.0.0.1"].includes(location.hostname);
const PAGE = 30;

let data, byId = {}, shown = PAGE;
const state = {}; // recipe filter name -> chosen value
const $ = (id) => document.getElementById(id);

const rs = (n) => "Rs " + Math.round(n).toLocaleString("en-PK");
const k = (n) => (n >= 1000 ? Math.round(n / 500) / 2 + "k" : n);
const VERDICT = { good_deal: "Good deal", fair: "Fair price", overpriced: "Overpriced", too_cheap: "Suspiciously cheap", unsure: "Hard to judge" };
const ICON = { good_deal: "✓", fair: "≈", overpriced: "↑", too_cheap: "!", unsure: "?" };

function ago(ts) {
  const d = (Date.now() / 1000 - ts) / 86400;
  if (d < 1) return "today";
  if (d < 2) return "1 day ago";
  if (d < 30) return Math.floor(d) + " days ago";
  return Math.floor(d / 30) + " month" + (d >= 60 ? "s" : "") + " ago";
}

// Short codes like "ips" read better as "IPS"; longer words stay as they are.
const show = (v) => (typeof v === "string" && v.length <= 3 ? v.toUpperCase() : String(v).replace(/_/g, " "));
const known = (v) => v !== null && v !== undefined && v !== "" && v !== "unknown";

function specChips(l) {
  const out = [];
  for (const f of data.recipe.fields) {
    if (f.name === "brand" || f.name === "model") continue;
    const v = l[f.name];
    if (f.type === "boolean") { if (v) out.push(f.label); continue; }
    if (known(v)) out.push(f.type === "enum" || f.type === "string" ? show(v) : v + f.unit);
  }
  if (known(l.condition)) out.push(l.condition.replace("_", " "));
  if (l.has_box) out.push("box");
  if (l.has_warranty) out.push("warranty");
  if (l.has_fault) out.push("⚠ fault mentioned");
  return out.map((s) => `<span class="spec">${s}</span>`).join("");
}

function rangeBar(l) {
  const lo = Math.min(l.q25, l.price) * 0.85, hi = Math.max(l.q75, l.price) * 1.1;
  const pos = (v) => ((v - lo) / (hi - lo)) * 100;
  return `<div class="range" title="Green: where half of similar listings are priced. Line: this listing.">
    <div class="track"></div>
    <div class="band" style="left:${pos(l.q25)}%;width:${pos(l.q75) - pos(l.q25)}%"></div>
    <div class="mark" style="left:${pos(l.price)}%"></div>
    <span class="lbl" style="left:${pos(l.q25)}%">${k(l.q25)}</span>
    <span class="lbl" style="left:${pos(l.q75)}%">${k(l.q75)}</span>
  </div>`;
}

function verdictTag(l) {
  const v = l.advice.verdict, gap = l.advice.gap_pct;
  const pct = v === "fair" || v === "unsure" ? "" : ` · ${gap > 0 ? "+" : ""}${gap}% vs usual`;
  return `<span class="verdict v-${v}">${ICON[v]} ${VERDICT[v]}${pct}</span>`;
}

function card(l) {
  return `<article class="card" data-id="${l.id}">
    <div class="img" style="background-image:url('${l.photo || ""}')">${l.featured ? '<span class="tag">Featured</span>' : ""}</div>
    <div class="body">
      <div class="price">${rs(l.price)}</div>
      <div class="title">${escapeHtml(l.title)}</div>
      <div class="specs">${specChips(l)}</div>
      ${verdictTag(l)}
      <div class="usual">Similar ones usually ask <b>${rs(l.q25)} – ${rs(l.q75)}</b></div>
      ${rangeBar(l)}
      <div class="meta">${[l.area, l.city].filter(Boolean).join(", ")} • ${ago(l.posted)}</div>
    </div>
  </article>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function filtered() {
  const budget = +$("f-budget").value || 0, bargain = $("f-bargain").checked, city = $("f-city").value;
  let items = data.listings.filter((l) => {
    for (const [name, v] of Object.entries(state)) if (v !== null && filterValue(name, l) !== v) return false;
    if (city && l.city !== city) return false;
    if ($("f-reputable").checked && !l.reputable) return false;
    if ($("f-nofault").checked && l.has_fault) return false;
    if ($("f-good").checked && l.advice.verdict !== "good_deal") return false;
    if (budget && l.price > budget && !(bargain && l.advice.fair_from <= budget)) return false;
    return true;
  });
  const sort = $("sort").value;
  if (sort === "deal") items.sort((a, b) => dealScore(a) - dealScore(b));
  if (sort === "price") items.sort((a, b) => a.price - b.price);
  if (sort === "new") items.sort((a, b) => b.posted - a.posted);
  return items;
}

// Lower is better; ones we can't judge and suspiciously cheap ones go last because they need extra care.
const dealScore = (l) => ({ unsure: 500, too_cheap: 1000 }[l.advice.verdict] ?? l.advice.gap_pct);

function render() {
  const items = filtered();
  $("results-title").innerHTML = `${data.recipe.title} in ${$("f-city").value || "Pakistan"} <small>${items.length} listings</small>`;
  $("list").innerHTML = items.length
    ? items.slice(0, shown).map(card).join("")
    : `<div class="empty">Nothing matches these filters. Try a higher budget or fewer filters.</div>`;
  $("more").hidden = items.length <= shown;
}

const fieldDef = (name) => data.recipe.fields.find((f) => f.name === name) || { name, label: name, type: "string", unit: "" };

// Numbers are grouped by whole values (27.0 and 27.5 both count as 27); everything else as written.
function filterValue(name, l) {
  const v = l[name];
  if (!known(v)) return null;
  const f = fieldDef(name);
  return f.type === "number" || f.type === "integer" ? Math.round(v) : f.type === "boolean" ? String(v) : v;
}

function buildFilters() {
  $("recipe-filters").innerHTML = data.recipe.filters.map((name) =>
    `<div class="box"><h3>${fieldDef(name).label}</h3><div class="chips" data-filter="${name}"></div></div>`).join("");
  for (const name of data.recipe.filters) {
    const f = fieldDef(name);
    state[name] = null;
    let values = counts((l) => filterValue(name, l));
    if (f.type === "number" || f.type === "integer") values.sort((a, b) => a[0] - b[0]);
    else values.sort((a, b) => b[1] - a[1]);
    const box = document.querySelector(`.chips[data-filter="${name}"]`);
    box.innerHTML = values.map(([v, n]) => `<button class="chip" data-v="${v}">${f.type === "enum" || f.type === "string" ? show(v) : v + f.unit} <small>${n}</small></button>`).join("");
    box.onclick = (e) => {
      const b = e.target.closest(".chip");
      if (!b) return;
      const v = f.type === "number" || f.type === "integer" ? +b.dataset.v : b.dataset.v;
      state[name] = state[name] === v ? null : v;
      box.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", String(state[name]) === c.dataset.v));
      shown = PAGE;
      render();
    };
  }
}

function counts(fn, min = 3) {
  const c = {};
  data.listings.forEach((l) => { const v = fn(l); if (v != null && v !== "unknown") c[v] = (c[v] || 0) + 1; });
  return Object.entries(c).filter(([, n]) => n >= min);
}

function sheet(l) {
  const a = l.advice;
  const dropped = l.first_price && l.first_price !== l.price
    ? `<p class="read">Price history: listed at ${rs(l.first_price)}, now ${rs(l.price)} (${l.price < l.first_price ? "dropped" : "raised"} since we first saw it).</p>` : "";
  const sims = l.similar.map((id) => byId[id]).filter(Boolean);
  const read = [l.brand !== "unknown" && l.brand, l.model, specChips(l).replace(/<[^>]+>/g, " ").trim()].filter(Boolean).join(" · ");
  $("sheet-body").innerHTML = `
    <div class="sheet-top">
      <img src="${l.photo || ""}" alt="">
      <div>
        <div class="price">${rs(l.price)}</div>
        <div class="title">${escapeHtml(l.title)}</div>
        <div class="meta">${[l.area, l.city].filter(Boolean).join(", ")} • ${ago(l.posted)}</div>
        <p>${verdictTag(l)}</p>
        <p class="big-say">${a.say}</p>
      </div>
    </div>
    <div class="usual" style="margin-top:14px">Half of similar listings ask between <b>${rs(l.q25)}</b> and <b>${rs(l.q75)}</b> (middle: ${rs(l.q50)}).</div>
    ${rangeBar(l)}
    <div class="plan">
      <div><small>Open your offer at</small><b>${rs(a.open_at)}</b></div>
      <div><small>A fair deal is</small><b>${a.fair_from === a.fair_to ? rs(a.fair_from) : k(a.fair_from) + " – " + k(a.fair_to)}</b></div>
      <div><small>Most you should pay</small><b>${rs(a.max_pay)}</b></div>
    </div>
    ${dropped}
    ${newPrice(l)}
    <h4>What the listing says (read by Gemma)</h4>
    <p class="read">${read || "Not much: the seller didn't list specs."}${data.recipe.inspect ? " Check in person: " + data.recipe.inspect + "." : ""}</p>
    ${sims.length ? `<h4>Similar listings</h4><div class="minis">${sims.map((s) => `
      <div class="mini" data-id="${s.id}"><div class="img" style="background-image:url('${s.photo || ""}')"></div>
      <div><b>${rs(s.price)}</b><br>${escapeHtml(s.title).slice(0, 48)}<br><span class="meta">${s.city || ""}</span></div></div>`).join("")}</div>` : ""}
    <div class="btns"><a class="btn solid" href="${l.url}" target="_blank" rel="noopener">View on OLX</a></div>`;
  $("sheet").hidden = false;
}

// What Pakistani shops charge for the same model (from a Google search). Shop prices are often for
// imported or refurbished units, and shops disagree, so we only give one number when they roughly agree.
function newPrice(l) {
  const n = l.new_price;
  if (!n) return "";
  const links = n.sources.map((s) => `<a href="${s.link}" target="_blank" rel="noopener">${escapeHtml(s.site)} ${k(s.price)}</a>`).join(" · ");
  const head = `<h4>Shop price for this model</h4>`;
  if (!n.confident) return `${head}<p class="read">Shops list it between ${rs(n.low)}${n.high !== n.low ? " and " + rs(n.high) : ""}, too far apart to compare. ${links}</p>`;
  const save = Math.round((1 - l.price / n.price) * 100);
  const say = save >= 20 ? `This listing is <b>${save}% cheaper</b> than buying from a shop.`
    : save > 0 ? `Only <b>${save}%</b> cheaper than a shop. A shop's checking warranty may be worth the difference.`
    : `<b>It costs more than a shop</b> (${-save}% more). Ask the shop first.`;
  return `${head}<p class="read">Shops sell this model for about <b>${rs(n.price)}</b> (often imported or refurbished). ${say} ${links}</p>`;
}

async function check(e) {
  e.preventDefault();
  const url = $("check-url").value.trim(), msg = $("check-msg");
  const id = (url.match(/iid-(\d+)/) || [])[1];
  msg.hidden = false;
  if (!id) { msg.textContent = "That doesn't look like an OLX listing link (it should contain 'iid-' and a number)."; return; }
  if (byId[id]) { msg.hidden = true; sheet(byId[id]); return; }
  if (!LOCAL) { msg.textContent = "This listing isn't in the latest update (or isn't a single monitor). Live checks of brand-new links run on the owner's PC, with local Gemma and TabPFN."; return; }
  msg.textContent = "New listing: Gemma is reading it and TabPFN is pricing it (about 10–20 seconds)…";
  try {
    const r = await fetch(`/api/check?recipe=${RECIPE}&url=${encodeURIComponent(url)}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "check failed");
    byId[j.id] = j;
    msg.hidden = true;
    sheet(j);
  } catch (err) {
    msg.textContent = "Couldn't check it: " + err.message;
  }
}

async function main() {
  const index = await fetch("data/index.json").then((r) => (r.ok ? r.json() : [])).catch(() => []);
  if (index.length > 1) {
    $("recipe-pick").hidden = false;
    $("recipe-pick").innerHTML = index.map((r) => `<option value="${r.name}" ${r.name === RECIPE ? "selected" : ""}>${r.title}</option>`).join("");
    $("recipe-pick").onchange = (e) => (location.search = "?r=" + e.target.value);
  }
  data = await (await fetch(`data/${RECIPE}.json`)).json();
  data.listings.forEach((l) => (byId[l.id] = l));
  document.title = `pricecheck · Is this OLX ${data.recipe.item} price fair?`;
  $("check-url").placeholder = `Paste an OLX ${data.recipe.item} link, e.g. https://www.olx.com.pk/item/...-iid-1120146181`;
  $("reputable-row").hidden = !data.recipe.has_reputable;
  buildFilters();
  const cities = counts((l) => l.city, 1).sort((a, b) => b[1] - a[1]);
  $("f-city").innerHTML += cities.map(([c, n]) => `<option value="${c}">${c} (${n})</option>`).join("");

  const acc = data.accuracy, c = data.counts;
  $("footer").innerHTML = `Prices learned from <b>${c.priced}</b> OLX listings (${c.removed_kept} of them already sold or removed), updated ${data.updated.replace("T", " ")}.
    On listings it hadn't seen, the middle of the range was typically within <b>${acc.median_error_pct}%</b> of the asking price, and ${acc.range_hit_pct}% of asking prices fell inside the "usual" range.
    Gemma (running locally) reads each listing; TabPFN learns what similar ones cost; plain code turns that into bargaining advice. It only sees asking prices, never what people actually paid.`;

  ["f-budget", "f-bargain", "f-city", "f-reputable", "f-nofault", "f-good", "sort"].forEach((id) =>
    $(id).addEventListener("input", () => { shown = PAGE; render(); }));
  $("more").onclick = () => { shown += PAGE; render(); };
  $("list").onclick = (e) => { const c = e.target.closest(".card"); if (c) sheet(byId[c.dataset.id]); };
  $("sheet-body").onclick = (e) => { const m = e.target.closest(".mini"); if (m) sheet(byId[m.dataset.id]); };
  $("sheet-close").onclick = () => ($("sheet").hidden = true);
  $("sheet").onclick = (e) => { if (e.target.id === "sheet") $("sheet").hidden = true; };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("sheet").hidden = true; });
  $("check-form").onsubmit = check;
  render();
}

main();
