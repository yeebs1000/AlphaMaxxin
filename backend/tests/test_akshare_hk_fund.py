"""akshare HK fundamentals parsing — pure row→field mapping, offline.
Fixtures use the REAL East Money F10 column codes captured from a live
00700/02015 fetch (2026-07-22), values trimmed."""
from app.data import akshare_provider as aks
from app.skills import fundamentals


def _row(report_date, *, rev, rev_yoy, gross, gross_ratio, ni, ni_yoy,
         net_ratio, roa, ocf_sales, debt_asset, current, eps):
    """One indicator-table row with the fields _hk_raw/_hk_years read."""
    return {
        "REPORT_DATE": f"{report_date} 00:00:00", "SECURITY_NAME_ABBR": "腾讯控股",
        "CURRENCY": "HKD", "OPERATE_INCOME": rev, "OPERATE_INCOME_YOY": rev_yoy,
        "GROSS_PROFIT": gross, "GROSS_PROFIT_RATIO": gross_ratio,
        "HOLDER_PROFIT": ni, "HOLDER_PROFIT_YOY": ni_yoy, "NET_PROFIT_RATIO": net_ratio,
        "ROA": roa, "OCF_SALES": ocf_sales, "DEBT_ASSET_RATIO": debt_asset,
        "CURRENT_RATIO": current, "BASIC_EPS": eps,
    }


# Two years, second improves-into-first on most axes (real Tencent-ish shape).
_ROWS = [
    _row("2025-12-31", rev=751766e6, rev_yoy=13.86, gross=422593e6, gross_ratio=56.21,
         ni=224842e6, ni_yoy=15.85, net_ratio=30.57, roa=11.77, ocf_sales=40.31,
         debt_asset=39.13, current=1.44, eps=24.749),
    _row("2024-12-31", rev=660257e6, rev_yoy=8.41, gross=349246e6, gross_ratio=52.90,
         ni=194073e6, ni_yoy=68.44, net_ratio=29.76, roa=11.56, ocf_sales=28.02,
         debt_asset=40.83, current=1.25, eps=20.938),
]


def test_hk_raw_maps_percentages_to_fractions():
    raw = aks._hk_raw(_ROWS)
    assert raw["gross_margin"] == round(0.5621, 4)
    assert raw["net_margin"] == round(0.3057, 4)
    assert raw["rev_yoy"] == round(0.1386, 4)
    assert raw["current_ratio"] == 1.44
    # True EPS YoY from consecutive basic-EPS (not the net-profit proxy).
    assert abs(raw["eps_yoy"] - (24.749 / 20.938 - 1)) < 1e-9
    assert raw["currency"] == "HKD"


def test_hk_raw_empty_and_single_row_proxy():
    assert aks._hk_raw([]) is None
    one = aks._hk_raw(_ROWS[:1])           # no prior year → net-profit YoY proxy
    assert one["eps_yoy"] == round(0.1585, 4)


def test_hk_years_derive_absolutes_for_fscore():
    years = aks._hk_years(_ROWS)
    y0 = years[0]
    assert y0["period"] == "2025-12-31"
    assert y0["net_income"] == 224842e6
    assert y0["cogs"] == 751766e6 - 422593e6
    # assets = net_income / (ROA/100)
    assert abs(y0["total_assets"] - 224842e6 / 0.1177) < 1
    # cfo = OCF_SALES/100 * revenue
    assert abs(y0["cfo"] - 0.4031 * 751766e6) < 1
    # shares = net_income / basic_eps
    assert abs(y0["shares"] - 224842e6 / 24.749) < 1


def test_hk_years_feed_fscore_end_to_end():
    # The derived years must actually score through the real f_score().
    fs = fundamentals.f_score(aks._hk_years(_ROWS))
    assert fs is not None and 0 <= fs["score"] <= fs["known"]
    # 2025 improved ROA/margin/liquidity + deleveraged vs 2024 → strong.
    assert fs["score"] >= 5


def test_compute_fundamentals_accepts_akshare_source():
    snap = fundamentals.compute_fundamentals("0700.HK", None, akshare_raw=aks._hk_raw(_ROWS))
    assert snap["source"] == "akshare"
    assert snap["margins"]["net"] == round(0.3057, 4)
    # yfinance still wins when both present.
    both = fundamentals.compute_fundamentals(
        "0700.HK", {"ticker": "0700.HK", "net_margin": 0.5}, akshare_raw=aks._hk_raw(_ROWS))
    assert both["source"] == "yfinance"
