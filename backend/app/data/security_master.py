"""Security master — canonical identity and a two-level taxonomy for the
US/HK/SG research universe.

Phase 1 of the sector-relative research prototype (see
`~/infra/SECTOR-ANALYSIS-WORK-BRIEF.md` §3.3-§3.4). This module owns
normalization, identity, source precedence, conflict reporting, cache-record
schemas and resumable merge logic. It performs **no** network, filesystem,
broker or LLM access and never reads the clock — every `now` is passed in.
Network calls live in the provider/broker adapters; this file must stay
testable entirely from supplied rows.

Two classification levels exist and only two: canonical `sector` and canonical
`industry`. IBKR's `ContractDetails.subcategory` is deliberately ignored — not
persisted, not mapped, not ranked on, not exposed.

The provider field names do not agree with each other, so the source-to-
canonical contract is explicit rather than implied by field name:

    canonical result | Yahoo source field | IBKR source field
    -----------------|--------------------|------------------
    sector           | sector             | industry
    industry         | industry           | category

Neither provider guarantees GICS, and neither supplies point-in-time history.
Every artifact therefore keeps the four raw provider labels verbatim, records
the taxonomy version and an as-of time, and never treats a current label as a
historical classification.
"""
import re
import unicodedata

SCHEMA_VERSION = "security_master-1"
TAXONOMY_VERSION = "taxonomy-1"

# §3.3: the only source fields this feature reads, retained verbatim on every
# row so an audit can always see what the provider actually said.
RETAINED_RAW_FIELDS = (
    "ibkr_industry",    # -> canonical sector
    "ibkr_category",    # -> canonical industry
    "yahoo_sector",     # -> canonical sector
    "yahoo_industry",   # -> canonical industry
)

SOURCE_FIELD_CONTRACT = {
    "ibkr": {"sector": "ibkr_industry", "industry": "ibkr_category"},
    "yahoo": {"sector": "yahoo_sector", "industry": "yahoo_industry"},
}

# Cache policy from the brief: successful contract metadata for 30 days,
# negative results for 24 hours. Long positive TTL is safe because a listing's
# classification moves on the order of years; the short negative TTL keeps a
# transient gateway failure from pinning a name as unresolvable.
POSITIVE_TTL_S = 30 * 86400
NEGATIVE_TTL_S = 24 * 3600

REGIONS = ("US", "HK", "SG")


# ---------------------------------------------------------------------------
# label form normalization
# ---------------------------------------------------------------------------
# Form normalization only: case, whitespace, unicode dashes, and "&"/"and".
# It changes how a label is spelled, never what it means, so it is not a
# mapping and cannot invent a classification. Meaning-changing moves happen
# exclusively through the explicit alias tables below.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")


def normalize_label_form(raw) -> str | None:
    """Canonical spelling of a provider label, or None if there is nothing
    there. Pure text hygiene — no aliasing, no guessing."""
    if raw is None or isinstance(raw, bool) or not isinstance(raw, str):
        return None
    text = unicodedata.normalize("NFKC", raw).translate(_DASHES)
    text = text.replace("&", " and ")
    text = re.sub(r"[\s ]+", " ", text).strip(" ,;/-")
    if not text:
        return None
    # Title-ish casing would corrupt acronyms (REIT, ETF); compare case-folded
    # instead and keep the provider's own capitalization for display.
    return text


def _lookup_key(raw) -> str | None:
    form = normalize_label_form(raw)
    return form.casefold() if form else None


# ---------------------------------------------------------------------------
# canonical sector vocabulary — CLOSED
# ---------------------------------------------------------------------------
# Sector is a closed vocabulary because peer pools, the both-providers-agree
# check and the coverage audit all depend on two labels being comparable. An
# unknown sector label maps to None and is reported as unmapped; it is never
# guessed, never substring-matched, never sent to a model.
CANONICAL_SECTORS = (
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial Services",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
)

# Yahoo's own sector vocabulary is the canonical one — it is the vocabulary
# actually observed at scale in this project's cached fundamentals, so adopting
# it introduces no translation error on the fallback path.
_YAHOO_SECTOR_ALIASES = {s.casefold(): s for s in CANONICAL_SECTORS}
_YAHOO_SECTOR_ALIASES.update({
    "financial": "Financial Services",
    "consumer discretionary": "Consumer Cyclical",
    "consumer staples": "Consumer Defensive",
    "information technology": "Technology",
    "materials": "Basic Materials",
    "health care": "Healthcare",
})

# IBKR's ContractDetails.industry is a Bloomberg-style level-1 vocabulary, not
# GICS and not Yahoo's. These entries are PROVISIONAL: they were written from
# the documented vocabulary, not from a measured coverage audit of this box's
# own universe, and the brief blocks preferring IBKR until that audit exists.
# Anything absent here resolves to None -> `ibkr_unmapped`, which is the
# finding the audit is supposed to surface. Do not extend this table by
# guesswork; extend it from observed labels the owner has approved.
_IBKR_SECTOR_ALIASES = {
    "energy": "Energy",
    "basic materials": "Basic Materials",
    "industrial": "Industrials",
    "utilities": "Utilities",
    "technology": "Technology",
    "communications": "Communication Services",
    "financial": "Financial Services",
    "consumer, cyclical": "Consumer Cyclical",
    # NOTE: IBKR's "Consumer, Non-cyclical" spans what Yahoo splits into
    # Consumer Defensive AND Healthcare. It is deliberately NOT mapped — a
    # one-way choice here would manufacture agreement that does not exist and
    # would silently misfile every pharma name. Leave it unmapped and let the
    # audit show how much of the universe it covers.
}

# Industry is an OPEN vocabulary, unlike sector. Yahoo alone emits ~150
# industry labels and no verified IBKR `category` vocabulary has been measured
# on this box, so a closed list would reject most real data on day one. Form
# normalization plus the explicit alias table below is the whole mechanism;
# an unrecognized label passes through as itself, which is declining to map
# rather than guessing a mapping.
_YAHOO_INDUSTRY_ALIASES = {
    "reit - diversified": "REIT - Diversified",
    "reit - industrial": "REIT - Industrial",
    "reit - office": "REIT - Office",
    "reit - residential": "REIT - Residential",
    "reit - retail": "REIT - Retail",
}

# Empty on purpose. IBKR cannot be the preferred INDUSTRY source until a
# measured coverage audit produces a real `category` vocabulary for the owner
# to approve (brief §3.3, §8.1). Until then every row resolves industry from
# Yahoo and the audit reports 100% yahoo_fallback at industry level — which is
# the evidence the owner asked for, not a bug.
_IBKR_INDUSTRY_ALIASES: dict = {}


def canonical_sector(raw, source: str) -> str | None:
    """Canonical sector from one provider's raw label, or None if unmapped."""
    key = _lookup_key(raw)
    if key is None:
        return None
    table = _IBKR_SECTOR_ALIASES if source == "ibkr" else _YAHOO_SECTOR_ALIASES
    return table.get(key)


def canonical_industry(raw, source: str) -> str | None:
    """Canonical industry from one provider's raw label, or None."""
    form = normalize_label_form(raw)
    if form is None:
        return None
    table = _IBKR_INDUSTRY_ALIASES if source == "ibkr" else _YAHOO_INDUSTRY_ALIASES
    aliased = table.get(form.casefold())
    if aliased:
        return aliased
    if source == "ibkr":
        # No approved IBKR category vocabulary yet — decline rather than guess.
        return None
    return form


# ---------------------------------------------------------------------------
# industry groups — the middle peer tier
# ---------------------------------------------------------------------------
# A third level, added after the census measured what two levels cost: US
# Consumer Cyclical spreads 119 names over 22 industries with none reaching the
# 12-name minimum, so every one of them falls through to a 119-name sector
# pool and is compared against restaurants, car makers and casinos at once.
#
# Grouping is by economic comparability, following GICS industry-group logic
# where Yahoo's labels map onto it cleanly. The table is exhaustive over the
# labels actually observed across US/HK/SG (131 of them, 2026-09-07); anything
# absent returns None and falls through to the sector, which is the same
# failure mode an unmapped sector already has. Extend it from observed labels,
# never by guessing at one.
INDUSTRY_GROUP_VERSION = "industry_group-1"

INDUSTRY_GROUPS = {
    # --- Consumer Cyclical -------------------------------------------------
    "Auto Parts": "Automotive",
    "Auto Manufacturers": "Automotive",
    "Auto & Truck Dealerships": "Automotive",
    "Recreational Vehicles": "Automotive",
    "Specialty Retail": "Consumer Retail",
    "Internet Retail": "Consumer Retail",
    "Apparel Retail": "Consumer Retail",
    "Department Stores": "Consumer Retail",
    "Home Improvement Retail": "Consumer Retail",
    "Luxury Goods": "Apparel & Luxury",
    "Footwear & Accessories": "Apparel & Luxury",
    "Apparel Manufacturing": "Apparel & Luxury",
    "Textile Manufacturing": "Apparel & Luxury",
    "Restaurants": "Hospitality & Leisure",
    "Lodging": "Hospitality & Leisure",
    "Leisure": "Hospitality & Leisure",
    "Resorts & Casinos": "Hospitality & Leisure",
    "Travel Services": "Hospitality & Leisure",
    "Gambling": "Hospitality & Leisure",
    "Personal Services": "Hospitality & Leisure",
    "Furnishings, Fixtures & Appliances": "Consumer Durables & Packaging",
    "Packaging & Containers": "Consumer Durables & Packaging",
    "Residential Construction": "Consumer Durables & Packaging",

    # --- Real Estate -------------------------------------------------------
    "Real Estate - Development": "Real Estate Operating",
    "Real Estate Services": "Real Estate Operating",
    "Real Estate - Diversified": "Real Estate Operating",
    "REIT - Industrial": "REITs",
    "REIT - Retail": "REITs",
    "REIT - Specialty": "REITs",
    "REIT - Residential": "REITs",
    "REIT - Healthcare Facilities": "REITs",
    "REIT - Office": "REITs",
    "REIT - Diversified": "REITs",
    "REIT - Hotel & Motel": "REITs",
    "REIT - Mortgage": "REITs",

    # --- Consumer Defensive ------------------------------------------------
    "Packaged Foods": "Food Products",
    "Farm Products": "Food Products",
    "Confectioners": "Food Products",
    "Beverages - Non-Alcoholic": "Beverages",
    "Beverages - Brewers": "Beverages",
    "Beverages - Wineries & Distilleries": "Beverages",
    "Household & Personal Products": "Household & Personal Products",
    "Tobacco": "Household & Personal Products",
    "Food Distribution": "Food & Staples Retailing",
    "Grocery Stores": "Food & Staples Retailing",
    "Discount Stores": "Food & Staples Retailing",
    "Education & Training Services": "Education Services",

    # --- Basic Materials ---------------------------------------------------
    "Specialty Chemicals": "Chemicals",
    "Chemicals": "Chemicals",
    "Agricultural Inputs": "Chemicals",
    "Steel": "Metals & Mining",
    "Gold": "Metals & Mining",
    "Other Industrial Metals & Mining": "Metals & Mining",
    "Aluminum": "Metals & Mining",
    "Copper": "Metals & Mining",
    "Other Precious Metals & Mining": "Metals & Mining",
    "Coking Coal": "Metals & Mining",
    "Building Materials": "Construction Materials & Forest Products",
    "Lumber & Wood Production": "Construction Materials & Forest Products",
    "Paper & Paper Products": "Construction Materials & Forest Products",

    # --- Utilities ---------------------------------------------------------
    "Utilities - Regulated Electric": "Regulated Utilities",
    "Utilities - Regulated Gas": "Regulated Utilities",
    "Utilities - Regulated Water": "Regulated Utilities",
    "Utilities - Diversified": "Regulated Utilities",
    "Utilities - Independent Power Producers": "Power & Renewables",
    "Utilities - Renewable": "Power & Renewables",

    # --- Energy ------------------------------------------------------------
    "Oil & Gas E&P": "Oil & Gas Upstream",
    "Oil & Gas Integrated": "Oil & Gas Upstream",
    "Oil & Gas Drilling": "Oil & Gas Upstream",
    "Oil & Gas Equipment & Services": "Energy Equipment & Services",
    "Oil & Gas Refining & Marketing": "Oil & Gas Downstream",
    "Oil & Gas Midstream": "Oil & Gas Downstream",
    "Thermal Coal": "Coal & Uranium",
    "Uranium": "Coal & Uranium",

    # --- Technology --------------------------------------------------------
    "Software - Application": "Software & IT Services",
    "Software - Infrastructure": "Software & IT Services",
    "Information Technology Services": "Software & IT Services",
    "Semiconductors": "Semiconductors & Equipment",
    "Semiconductor Equipment & Materials": "Semiconductors & Equipment",
    "Solar": "Semiconductors & Equipment",
    "Electronic Components": "Hardware & Components",
    "Communication Equipment": "Hardware & Components",
    "Computer Hardware": "Hardware & Components",
    "Scientific & Technical Instruments": "Hardware & Components",
    "Electronics & Computer Distribution": "Hardware & Components",
    "Consumer Electronics": "Hardware & Components",

    # --- Financial Services ------------------------------------------------
    "Banks - Regional": "Banks",
    "Banks - Diversified": "Banks",
    "Asset Management": "Capital Markets",
    "Capital Markets": "Capital Markets",
    "Financial Data & Stock Exchanges": "Capital Markets",
    "Financial Conglomerates": "Capital Markets",
    "Insurance - Life": "Insurance",
    "Insurance - Property & Casualty": "Insurance",
    "Insurance Brokers": "Insurance",
    "Insurance - Reinsurance": "Insurance",
    "Insurance - Diversified": "Insurance",
    "Insurance - Specialty": "Insurance",
    "Credit Services": "Consumer Finance",
    "Mortgage Finance": "Consumer Finance",

    # --- Communication Services --------------------------------------------
    "Telecom Services": "Telecommunications",
    "Entertainment": "Media & Entertainment",
    "Internet Content & Information": "Media & Entertainment",
    "Advertising Agencies": "Media & Entertainment",
    "Electronic Gaming & Multimedia": "Media & Entertainment",
    "Publishing": "Media & Entertainment",
    "Broadcasting": "Media & Entertainment",

    # --- Industrials -------------------------------------------------------
    "Specialty Industrial Machinery": "Machinery & Equipment",
    "Farm & Heavy Construction Machinery": "Machinery & Equipment",
    "Electrical Equipment & Parts": "Machinery & Equipment",
    "Metal Fabrication": "Machinery & Equipment",
    "Tools & Accessories": "Machinery & Equipment",
    "Pollution & Treatment Controls": "Machinery & Equipment",
    "Engineering & Construction": "Construction & Engineering",
    "Building Products & Equipment": "Construction & Engineering",
    "Infrastructure Operations": "Construction & Engineering",
    "Aerospace & Defense": "Aerospace & Defense",
    "Integrated Freight & Logistics": "Transportation",
    "Marine Shipping": "Transportation",
    "Railroads": "Transportation",
    "Airlines": "Transportation",
    "Trucking": "Transportation",
    "Airports & Air Services": "Transportation",
    "Specialty Business Services": "Commercial & Professional Services",
    "Industrial Distribution": "Commercial & Professional Services",
    "Rental & Leasing Services": "Commercial & Professional Services",
    "Waste Management": "Commercial & Professional Services",
    "Consulting Services": "Commercial & Professional Services",
    "Security & Protection Services": "Commercial & Professional Services",
    "Business Equipment & Supplies": "Commercial & Professional Services",
    "Staffing & Employment Services": "Commercial & Professional Services",
    "Conglomerates": "Conglomerates",

    # --- Healthcare --------------------------------------------------------
    "Biotechnology": "Pharma & Biotech",
    "Drug Manufacturers - Specialty & Generic": "Pharma & Biotech",
    "Drug Manufacturers - General": "Pharma & Biotech",
    "Medical Devices": "Medical Devices & Diagnostics",
    "Medical Instruments & Supplies": "Medical Devices & Diagnostics",
    "Diagnostics & Research": "Medical Devices & Diagnostics",
    "Medical Care Facilities": "Healthcare Providers & Services",
    "Health Information Services": "Healthcare Providers & Services",
    "Medical Distribution": "Healthcare Providers & Services",
    "Healthcare Plans": "Healthcare Providers & Services",
    "Pharmaceutical Retailers": "Healthcare Providers & Services",
}


# The table above is written with "&" because that is how the labels read to a
# human, but normalize_label_form rewrites "&" to " and ". Both sides must go
# through the SAME normalization or every ampersand label silently misses --
# measured: 42 of 143 labels, including Aerospace & Defense and Oil & Gas E&P.
_INDUSTRY_GROUP_LOOKUP = {
    normalize_label_form(label).casefold(): group
    for label, group in INDUSTRY_GROUPS.items()
    if normalize_label_form(label)
}


def industry_group(industry) -> str | None:
    """Coarser peer tier for a canonical industry, or None when unmapped.

    None is a real answer: an unmapped label falls through to the sector pool
    rather than being guessed into a group it may not belong in.
    """
    form = normalize_label_form(industry)
    return _INDUSTRY_GROUP_LOOKUP.get(form.casefold()) if form else None


# ---------------------------------------------------------------------------
# symbol normalization and identity
# ---------------------------------------------------------------------------
# Conventions match data/index_constituents.py so a row built here and a row
# built by the existing screener path refer to the same instrument. They are
# reimplemented rather than imported because that module reaches the network
# at import-adjacent call sites and this one must stay inert.
_US_RE = re.compile(r"[A-Z][A-Z\-]{0,5}$")
_SG_RE = re.compile(r"[A-Z0-9]{1,5}$")


def normalize_symbol(raw, region: str) -> str | None:
    """Provider/exchange symbol -> AlphaMaxxin ticker, or None if it is not a
    plausible ordinary listing code for that region."""
    if not isinstance(raw, str):
        return None
    cell = unicodedata.normalize("NFKC", raw).strip()
    if not cell:
        return None
    if region == "US":
        text = cell.upper().replace(".", "-")           # BRK.B -> BRK-B
        return text if _US_RE.fullmatch(text) else None
    if region == "HK":
        digits = re.sub(r"\D", "", cell)                # "SEHK: 388" -> "388"
        return f"{digits.zfill(4)}.HK" if 1 <= len(digits) <= 5 else None
    if region == "SG":
        code = cell.split(":")[-1].strip().upper()      # "SGX: A17U" -> "A17U"
        return f"{code}.SI" if _SG_RE.fullmatch(code) else None
    return None


# Ticker suffix -> region. AlphaMaxxin's own ticker convention already encodes
# the listing venue, so region is derivable and must never be assumed from the
# scope a caller asked for. A `--region US` run that inherits its region from
# the request will happily rank a Tokyo listing against the S&P — measured, not
# hypothetical: the first live probe did exactly that.
_SUFFIX_REGION = {".HK": "HK", ".SI": "SG"}

# Venues outside Phase 1. Named rather than lumped into "unknown" so the
# coverage audit can say how much of the cache was dropped and why.
_OUT_OF_SCOPE_SUFFIXES = (".T", ".KS", ".KQ", ".SS", ".SZ", ".TW", ".AX",
                          ".L", ".PA", ".DE", ".TO", ".NS", ".BO")


def region_for_ticker(ticker) -> str | None:
    """US/HK/SG from the ticker suffix, or None when the venue is out of Phase 1
    scope. None is a real answer here — it means 'do not pool this name'."""
    if not isinstance(ticker, str) or not ticker:
        return None
    for suffix, region in _SUFFIX_REGION.items():
        if ticker.upper().endswith(suffix):
            return region
    if any(ticker.upper().endswith(s) for s in _OUT_OF_SCOPE_SUFFIXES):
        return None
    return "US" if _US_RE.fullmatch(ticker.upper()) else None


# Stock types excluded from a research universe unless a declared rule admits
# them. REIT is deliberately NOT in this set: REITs are economically central in
# Singapore, so they are an explicit caller decision (`include_reits`) rather
# than a silent exclusion, and they need their own factor profile before they
# can be ranked against operating companies.
EXCLUDED_STOCK_TYPES = frozenset({
    "warrant", "option", "future", "bond", "etf", "etn", "fund",
    "right", "unit", "adr_preferred", "preferred", "suspended", "delisted",
})

_STOCK_TYPE_ALIASES = {
    "common": "common", "common stock": "common", "cs": "common",
    "stk": "common", "ord": "common", "ordinary": "common",
    "reit": "reit", "real estate investment trust": "reit",
    "business trust": "reit",
    "etf": "etf", "exchange traded fund": "etf", "etn": "etn",
    "warrant": "warrant", "wnt": "warrant", "opt": "option",
    "fut": "future", "bond": "bond", "bnd": "bond", "fund": "fund",
    "right": "right", "rights": "right", "unit": "unit",
    "preferred": "preferred", "pfd": "preferred",
    "suspended": "suspended", "delisted": "delisted",
}


def classify_stock_type(raw) -> str | None:
    """Normalized stock type, or None when the provider did not say. None is
    NOT treated as an exclusion — a missing type is missing data, and the
    coverage audit reports it rather than the universe silently shrinking."""
    key = _lookup_key(raw)
    if key is None:
        return None
    return _STOCK_TYPE_ALIASES.get(key, key)


def inclusion_verdict(row: dict, *, include_reits: bool = False,
                      include_catalist: bool = False) -> tuple[bool, list]:
    """(included, reasons). Reasons are recorded on excluded rows so the audit
    can show exactly why the universe is the size it is."""
    reasons = []
    stock_type = classify_stock_type(row.get("stock_type"))
    if stock_type in EXCLUDED_STOCK_TYPES:
        reasons.append(f"stock_type:{stock_type}")
    if stock_type == "reit" and not include_reits:
        reasons.append("reit_excluded_by_default")
    if row.get("board") and str(row["board"]).casefold() == "catalist" \
            and not include_catalist:
        reasons.append("catalist_excluded_by_default")
    if not row.get("ticker"):
        reasons.append("unnormalizable_symbol")
    if row.get("region") not in REGIONS:
        reasons.append("region_out_of_scope")
    return (not reasons), reasons


def identity_key(row: dict) -> str:
    """Stable identity. conId first — it survives ticker changes and share-class
    formatting differences, which plain symbol text does not."""
    con_id = row.get("con_id")
    if con_id not in (None, "", 0):
        return f"conId:{con_id}"
    return f"{row.get('region')}:{row.get('ticker')}"


def dedupe_rows(rows) -> tuple[list, list]:
    """(unique_rows, duplicate_reports). First occurrence wins; later ones are
    reported, never silently dropped."""
    seen, unique, dupes = {}, [], []
    for row in rows or []:
        key = identity_key(row)
        if key in seen:
            dupes.append({"identity": key, "kept": seen[key].get("ticker"),
                          "dropped": row.get("ticker")})
            continue
        seen[key] = row
        unique.append(row)
    return unique, dupes


# ---------------------------------------------------------------------------
# taxonomy resolution and conflict reporting
# ---------------------------------------------------------------------------
def resolve_taxonomy(row: dict, *, prefer: str = "ibkr") -> dict:
    """Canonical two-level taxonomy for one row, with the raw provider labels
    retained and any disagreement reported rather than reconciled.

    Statuses:
      both_agree      both providers mapped and produced the same result
      taxonomy_conflict  both mapped and disagreed — both raws kept, no forcing
      ibkr_only / yahoo_fallback  only one provider mapped
      unmapped        neither provider produced a canonical value
    """
    resolved = {"taxonomy_version": TAXONOMY_VERSION}
    for field in RETAINED_RAW_FIELDS:
        resolved[field] = row.get(field)

    per_source = {}
    for source in ("ibkr", "yahoo"):
        fields = SOURCE_FIELD_CONTRACT[source]
        per_source[source] = {
            "sector": canonical_sector(row.get(fields["sector"]), source),
            "industry": canonical_industry(row.get(fields["industry"]), source),
        }

    other = "yahoo" if prefer == "ibkr" else "ibkr"
    for level in ("sector", "industry"):
        preferred_value = per_source[prefer][level]
        other_value = per_source[other][level]
        if preferred_value and other_value:
            if preferred_value == other_value:
                value, status = preferred_value, "both_agree"
            else:
                # Never force agreement. Keep the preferred value so downstream
                # grouping still works, flag the row, and keep both raws.
                value, status = preferred_value, "taxonomy_conflict"
        elif preferred_value:
            value, status = preferred_value, f"{prefer}_only"
        elif other_value:
            value, status = other_value, (
                "yahoo_fallback" if other == "yahoo" else "ibkr_fallback")
        else:
            value, status = None, "unmapped"
        resolved[level] = value
        resolved[f"{level}_status"] = status
        resolved[f"{level}_source"] = (
            prefer if status in ("both_agree", f"{prefer}_only", "taxonomy_conflict")
            else (other if value else None))
    resolved["taxonomy_conflict"] = (
        resolved["sector_status"] == "taxonomy_conflict"
        or resolved["industry_status"] == "taxonomy_conflict")
    return resolved


def build_row(raw_row: dict, *, prefer: str = "ibkr", include_reits: bool = False,
              include_catalist: bool = False) -> dict:
    """One normalized security-master row from one raw universe/enrichment row."""
    region = raw_row.get("region")
    ticker = raw_row.get("ticker") or normalize_symbol(
        raw_row.get("source_symbol"), region)
    row = {
        "schema_version": SCHEMA_VERSION,
        "region": region,
        "ticker": ticker,
        "source_symbol": raw_row.get("source_symbol"),
        "universe_source": raw_row.get("universe_source"),
        "universe_source_version": raw_row.get("universe_source_version"),
        "con_id": raw_row.get("con_id"),
        "local_symbol": raw_row.get("local_symbol"),
        "primary_exchange": raw_row.get("primary_exchange"),
        "currency": raw_row.get("currency"),
        "long_name": raw_row.get("long_name"),
        "stock_type": raw_row.get("stock_type"),
        "board": raw_row.get("board"),
        "fetched_at": raw_row.get("fetched_at"),
        "taxonomy_fetched_at": raw_row.get("taxonomy_fetched_at"),
        "gateway_version": raw_row.get("gateway_version"),
    }
    row.update(resolve_taxonomy(raw_row, prefer=prefer))
    row["industry_group"] = industry_group(row.get("industry"))
    row["industry_group_version"] = INDUSTRY_GROUP_VERSION
    included, reasons = inclusion_verdict(
        row, include_reits=include_reits, include_catalist=include_catalist)
    row["included"] = included
    row["exclusions"] = reasons
    row["identity"] = identity_key(row)
    return row


# ---------------------------------------------------------------------------
# cache records and resumable merge
# ---------------------------------------------------------------------------
def make_cache_record(key: str, payload, *, now: float, ok: bool,
                      source: str, schema_version: str = SCHEMA_VERSION,
                      gateway_version=None) -> dict:
    """A cache record carries its own verdict and TTL so a negative result is a
    first-class fact with a short life, not an absent entry that gets retried
    every run."""
    return {
        "key": key,
        "ok": bool(ok),
        "payload": payload if ok else None,
        "fetched_at": float(now),
        "ttl_s": POSITIVE_TTL_S if ok else NEGATIVE_TTL_S,
        "source": source,
        "schema_version": schema_version,
        "gateway_version": gateway_version,
    }


def cache_record_fresh(record, *, now: float) -> bool:
    if not isinstance(record, dict):
        return False
    try:
        age = float(now) - float(record.get("fetched_at", 0))
        return age <= float(record.get("ttl_s", 0))
    except (TypeError, ValueError):
        return False


def merge_universe(existing, incoming, *, failures=None) -> dict:
    """Incremental, resumable merge.

    A partial enrichment pass must never shrink the universe: rows that were
    not refetched are carried forward untouched, and a failure is recorded
    against the identity instead of deleting it. This is the difference between
    an interrupted run costing one retry and costing the whole table.
    """
    merged, order = {}, []
    for row in existing or []:
        key = identity_key(row)
        if key not in merged:
            order.append(key)
        merged[key] = dict(row)
    refreshed = 0
    for row in incoming or []:
        key = identity_key(row)
        if key not in merged:
            order.append(key)
            merged[key] = dict(row)
        else:
            # Incoming wins field by field, but only where it actually says
            # something — a provider omitting a field must not blank a value an
            # earlier pass established.
            for field, value in row.items():
                if value is not None:
                    merged[key][field] = value
        refreshed += 1
    failed = []
    for key in (failures or []):
        failed.append(key)
        if key in merged:
            merged[key]["last_failure_key"] = key
    return {
        "rows": [merged[k] for k in order],
        "refreshed": refreshed,
        "carried_forward": max(len(order) - refreshed, 0),
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# coverage audit
# ---------------------------------------------------------------------------
def coverage_audit(rows, *, duplicates=None, elapsed_s=None, errors=None) -> dict:
    """The measurement the owner asked for before approving IBKR precedence:
    fill rate, unresolved rate, label cardinality, disagreement rate,
    duplicates, elapsed time and errors."""
    rows = list(rows or [])
    total = len(rows)
    included = [r for r in rows if r.get("included")]
    by_region, sector_labels, industry_labels = {}, set(), set()
    unmapped_raw = {"sector": {}, "industry": {}}
    counters = {
        "sector_resolved": 0, "industry_resolved": 0,
        "con_id_present": 0, "taxonomy_conflict": 0,
        "sector_status": {}, "industry_status": {},
    }
    for row in rows:
        region = row.get("region") or "UNKNOWN"
        by_region[region] = by_region.get(region, 0) + 1
        if row.get("con_id") not in (None, "", 0):
            counters["con_id_present"] += 1
        if row.get("taxonomy_conflict"):
            counters["taxonomy_conflict"] += 1
        for level, labels in (("sector", sector_labels), ("industry", industry_labels)):
            status = row.get(f"{level}_status") or "unmapped"
            counters[f"{level}_status"][status] = \
                counters[f"{level}_status"].get(status, 0) + 1
            value = row.get(level)
            if value:
                counters[f"{level}_resolved"] += 1
                labels.add(value)
            else:
                # Which raw labels are costing coverage — the list the owner
                # needs in order to approve crosswalk additions.
                for field in SOURCE_FIELD_CONTRACT["ibkr"][level], \
                        SOURCE_FIELD_CONTRACT["yahoo"][level]:
                    raw = normalize_label_form(row.get(field))
                    if raw:
                        unmapped_raw[level][raw] = unmapped_raw[level].get(raw, 0) + 1

    def rate(count):
        return round(count / total, 4) if total else None

    return {
        "schema_version": SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "rows_in": total,
        "rows_included": len(included),
        "by_region": by_region,
        "sector_fill_rate": rate(counters["sector_resolved"]),
        "industry_fill_rate": rate(counters["industry_resolved"]),
        "sector_unresolved": total - counters["sector_resolved"],
        "industry_unresolved": total - counters["industry_resolved"],
        "con_id_fill_rate": rate(counters["con_id_present"]),
        "taxonomy_conflict_count": counters["taxonomy_conflict"],
        "taxonomy_conflict_rate": rate(counters["taxonomy_conflict"]),
        "sector_status_counts": counters["sector_status"],
        "industry_status_counts": counters["industry_status"],
        "sector_label_cardinality": len(sector_labels),
        "industry_label_cardinality": len(industry_labels),
        "unmapped_raw_labels": {
            level: dict(sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[:40])
            for level, v in unmapped_raw.items()
        },
        "duplicates": list(duplicates or []),
        "duplicate_count": len(duplicates or []),
        "elapsed_s": elapsed_s,
        "errors": list(errors or []),
    }
