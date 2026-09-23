"""
chart_data.py - data access + aggregation shared by the Streamlit app and the static chart renderer.

Every chart function takes the loaded frames plus the active filters and returns
(dataframe_for_the_chart, one_sentence_interpretation). Keeping this logic in one place
guarantees the live app, the grading-artifact screenshots and the slides all show the same numbers.

Data source:
  * default: pre-exported Gold aggregates in app/data/*.csv (written by notebooks/04_analysis_queries.py)
  * optional: live Databricks SQL warehouse, if DATABRICKS_* settings are supplied (see load_frames)
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
CHANNELS = ["In-Store", "Online", "Mobile App"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Same SQL as Part C of notebooks/04_analysis_queries.py (used only in live-warehouse mode)
LIVE_SQL = {
    "channel_month": """SELECT invoice_year, invoice_month, invoice_month_name, Channel, COUNT(*) AS lines,
        SUM(net_quantity) AS units, ROUND(SUM(revenue),2) AS revenue, ROUND(SUM(gross_revenue),2) AS gross_revenue,
        SUM(CAST(is_return AS INT)) AS return_lines FROM retail_gold.retail_analytics GROUP BY 1,2,3,4""",
    "hour_channel": """SELECT invoice_year, invoice_hour, Channel, COUNT(*) AS transactions,
        ROUND(SUM(revenue),2) AS revenue FROM retail_gold.retail_analytics GROUP BY 1,2,3""",
    "category_channel": """SELECT invoice_year, Category, Channel, COUNT(*) AS lines, SUM(net_quantity) AS units,
        ROUND(SUM(revenue),2) AS revenue, ROUND(SUM(gross_revenue),2) AS gross_revenue,
        SUM(CAST(is_return AS INT)) AS return_lines FROM retail_gold.retail_analytics
        WHERE Category IS NOT NULL GROUP BY 1,2,3""",
    "daytype_channel": """SELECT invoice_year, Channel, day_type, invoice_dayofweek,
        COUNT(DISTINCT invoice_date) AS days, ROUND(SUM(revenue),2) AS revenue
        FROM retail_gold.retail_analytics GROUP BY 1,2,3,4""",
    "store_performance": """SELECT StoreID, StoreName, Region, StoreType, invoice_year, invoice_month, month_start,
        monthly_revenue, regional_median_revenue, vs_regional_median_pct, peer_median_revenue,
        vs_peer_median_pct, return_rate FROM retail_gold.store_performance""",
    "category_trends": """SELECT Category, week_start, weekly_revenue, weekly_units, rolling_4wk_avg_revenue,
        revenue_vs_prior_4wk, is_partial_week FROM retail_gold.category_trends""",
    "reorder_alerts": """SELECT StockCode, Description, Category, ReorderPoint, SUM(net_quantity) AS net_sold
        FROM retail_gold.retail_analytics WHERE at_reorder_point=TRUE
        GROUP BY 1,2,3,4 ORDER BY net_sold ASC LIMIT 20""",
}


def load_frames(settings: dict | None = None) -> dict[str, pd.DataFrame]:
    """Load all app datasets. settings = {"server_hostname", "http_path", "access_token", "catalog"}."""
    settings = settings or {}
    if settings.get("server_hostname") and settings.get("access_token"):
        from databricks import sql  # databricks-sql-connector

        with sql.connect(server_hostname=settings["server_hostname"], http_path=settings["http_path"],
                         access_token=settings["access_token"]) as conn, conn.cursor() as cur:
            if settings.get("catalog"):
                cur.execute(f"USE CATALOG {settings['catalog']}")
            frames = {}
            for name, q in LIVE_SQL.items():
                cur.execute(q)
                frames[name] = pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
    else:
        frames = {p.stem: pd.read_csv(p) for p in DATA_DIR.glob("*.csv")}

    frames["category_trends"]["week_start"] = pd.to_datetime(frames["category_trends"]["week_start"])
    frames["store_performance"]["month_start"] = pd.to_datetime(frames["store_performance"]["month_start"])
    for df in frames.values():               # numeric columns can arrive as Decimal/str from the connector
        for c in df.columns:
            if df[c].dtype == object and c not in ("Channel", "Category", "Region", "StoreType", "StoreName",
                                                   "StoreID", "StockCode", "Description", "day_type",
                                                   "invoice_month_name"):
                try:
                    df[c] = pd.to_numeric(df[c])
                except (ValueError, TypeError):
                    pass
    return frames


def _f(df, years, channels):
    out = df[df["invoice_year"].isin(years)]
    return out[out["Channel"].isin(channels)] if "Channel" in out.columns else out


def money(x):
    return f"${x / 1e6:,.2f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}K"


# --- Chart 1 ------------------------------------------------------------------------------
def chart1_channel(fr, years, channels):
    d = _f(fr["channel_month"], years, channels).groupby(["Channel", "invoice_year"], as_index=False)["revenue"].sum()
    tot = d.groupby("Channel")["revenue"].sum().sort_values(ascending=False)
    share = tot / tot.sum() * 100
    lead = tot.index[0]
    txt = f"{lead} is the largest channel with {share[lead]:.1f}% of net revenue in the selection"
    if {2024, 2025} <= set(years):
        p = d.pivot(index="Channel", columns="invoice_year", values="revenue")
        g = (p[2025] / p[2024] - 1) * 100
        txt += f"; {g.idxmax()} grew fastest year over year ({g.max():+.1f}%)."
    else:
        txt += "."
    return d, txt


# --- Chart 2 ------------------------------------------------------------------------------
def chart2_monthly(fr, years, channels):
    d = _f(fr["channel_month"], years, channels).groupby(["invoice_year", "invoice_month"], as_index=False)["revenue"].sum()
    peak = d.loc[d["revenue"].idxmax()]
    trough = d.loc[d["revenue"].idxmin()]
    txt = (f"Revenue peaks in {MONTHS[int(peak.invoice_month) - 1]} {int(peak.invoice_year)} ({money(peak.revenue)}) "
           f"and bottoms out in {MONTHS[int(trough.invoice_month) - 1]} {int(trough.invoice_year)} "
           f"({money(trough.revenue)}), a {peak.revenue / trough.revenue:.1f}x seasonal swing.")
    return d, txt


# --- Chart 3 ------------------------------------------------------------------------------
def chart3_hourly(fr, years, channels):
    d = _f(fr["hour_channel"], years, channels).groupby(["invoice_hour", "Channel"], as_index=False)["revenue"].sum()
    peaks = d.loc[d.groupby("Channel")["revenue"].idxmax()].set_index("Channel")["invoice_hour"]
    parts = [f"{c} at {int(h):02d}:00" for c, h in peaks.items()]
    txt = "Demand peaks at different hours by channel (" + ", ".join(parts) + \
          "), so staffing and digital promotions should follow separate clocks."
    return d, txt


# --- Chart 4 ------------------------------------------------------------------------------
def chart4_categories(fr, years, channels):
    d = (_f(fr["category_channel"], years, channels).groupby("Category", as_index=False)["revenue"].sum()
         .sort_values("revenue", ascending=False).head(10))
    top3 = d["revenue"].head(3).sum() / _f(fr["category_channel"], years, channels)["revenue"].sum() * 100
    txt = (f"{d.iloc[0].Category} leads with {money(d.iloc[0].revenue)}; the top three categories "
           f"deliver {top3:.0f}% of categorised net revenue.")
    return d, txt


# --- Chart 5 ------------------------------------------------------------------------------
def chart5_store_heatmap(fr, years):
    sp = fr["store_performance"][fr["store_performance"]["invoice_year"].isin(years)]
    d = sp.pivot_table(index="Region", columns="StoreType", values="monthly_revenue", aggfunc="sum")
    d = d.reindex(columns=[c for c in ["Flagship", "Standard", "Outlet", "Express"] if c in d.columns])
    peer = sp.groupby(["StoreID", "StoreName", "Region", "StoreType"], as_index=False)["vs_peer_median_pct"].mean()
    lo, hi = peer.loc[peer["vs_peer_median_pct"].idxmin()], peer.loc[peer["vs_peer_median_pct"].idxmax()]
    r, c = divmod(int(d.values.argmax()), d.shape[1])
    txt = (f"{d.index[r]} {d.columns[c]} stores generate the most revenue ({money(d.values.max())}); "
           f"vs. same-type peers, {lo.StoreID} {lo.StoreName} trails by {abs(lo.vs_peer_median_pct):.0f}% while "
           f"{hi.StoreID} {hi.StoreName} leads by {hi.vs_peer_median_pct:+.0f}%.")
    return d, txt


# --- Chart 6 ------------------------------------------------------------------------------
def chart6_return_heatmap(fr, years, channels):
    cc = _f(fr["category_channel"], years, channels)
    g = cc.groupby(["Category", "Channel"], as_index=False)[["return_lines", "lines"]].sum()
    g["return_rate"] = g["return_lines"] / g["lines"]
    d = g.pivot(index="Category", columns="Channel", values="return_rate")
    d = d.reindex(columns=[c for c in CHANNELS if c in d.columns])
    d = d.loc[d.mean(axis=1).sort_values(ascending=False).index]
    worst = g.loc[g["return_rate"].idxmax()]
    lost = (cc["gross_revenue"].sum() - cc["revenue"].sum())
    txt = (f"{worst.Category} bought via {worst.Channel} has the highest return rate ({worst.return_rate:.1%}); "
           f"returns erase {money(lost)} of gross revenue in the selection.")
    return d, txt


# --- Chart 7 ------------------------------------------------------------------------------
def chart7_anomaly(fr, category="Gifts & Seasonal"):
    d = fr["category_trends"]
    d = d[(d["Category"] == category)].sort_values("week_start").copy()
    full = d[~d["is_partial_week"].astype(bool)]
    a = full.loc[full["revenue_vs_prior_4wk"].idxmax()]
    same_next = d[d["week_start"] == a.week_start + pd.Timedelta(weeks=52)]
    tail = ""
    if len(same_next):
        tail = f" and {a.weekly_revenue / same_next.iloc[0].weekly_revenue:.1f}x the same week one year later"
    txt = (f"The week of {a.week_start:%b %d, %Y} {category} earned {money(a.weekly_revenue)}, "
           f"{a.revenue_vs_prior_4wk:.1f}x the average of the prior four weeks{tail} - a one-off demand spike, "
           f"not a repeating seasonal pattern.")
    return d, a, txt


def settings_from_env() -> dict:
    return {k: os.environ.get(f"DATABRICKS_{k.upper()}") for k in
            ("server_hostname", "http_path", "access_token", "catalog")}
