"""
Retail Demand Intelligence - Streamlit app (Charts 1-7).

Run locally:   streamlit run app/app.py
Deploy:        share.streamlit.io -> this repo -> main file app/app.py

Data source: app/data/*.csv exported from the Gold layer by notebooks/04_analysis_queries.py.
To query the live warehouse instead, add to Streamlit secrets (Settings -> Secrets):

    [databricks]
    server_hostname = "dbc-xxxx.cloud.databricks.com"
    http_path       = "/sql/1.0/warehouses/xxxx"
    access_token    = "dapi..."
    catalog         = "workspace"
"""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import chart_data as cd

st.set_page_config(page_title="Retail Demand Intelligence", page_icon="🛒", layout="wide")
NAVY, ORANGE, TEAL = "#1a3a5c", "#c45000", "#2a9d8f"
CH_COLORS = {"In-Store": NAVY, "Online": ORANGE, "Mobile App": TEAL}


@st.cache_data(ttl=3600, show_spinner="Loading Gold data…")
def get_frames():
    try:
        settings = dict(st.secrets["databricks"])
    except Exception:
        settings = cd.settings_from_env()
    return cd.load_frames(settings)


def footer(source, text):
    st.caption(f"**Interpretation:** {text}")
    st.caption(f"Source: {source}")


fr = get_frames()

# ---- sidebar filters (drive Charts 1, 2, 3, 4, 6; year also drives Chart 5) ----------------
st.sidebar.header("Filters")
years = st.sidebar.multiselect("Year", [2024, 2025], default=[2024, 2025])
channels = st.sidebar.multiselect("Channel", cd.CHANNELS, default=cd.CHANNELS)
anomaly_cat = st.sidebar.selectbox("Chart 7 category", sorted(fr["category_trends"]["Category"].unique()),
                                   index=sorted(fr["category_trends"]["Category"].unique()).index("Gifts & Seasonal"))
st.sidebar.caption("Year and Channel filters update Charts 1, 2, 3, 4 and 6; Year also updates Chart 5.")
if not years or not channels:
    st.warning("Select at least one year and one channel.")
    st.stop()

st.title("🛒 Retail Demand Intelligence")
st.markdown("Category demand, channel mix, store outliers, return risk and inventory alerts — "
            "built on the `retail_gold` Delta tables.")

# KPI strip
cm = cd._f(fr["channel_month"], years, channels)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Net revenue", cd.money(cm["revenue"].sum()))
k2.metric("Units (net)", f"{cm['units'].sum():,.0f}")
k3.metric("Return rate (lines)", f"{cm['return_lines'].sum() / cm['lines'].sum():.1%}")
k4.metric("Revenue lost to returns", cd.money(cm["gross_revenue"].sum() - cm["revenue"].sum()))

# ---- Chart 1 & 2 ------------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    d, txt = cd.chart1_channel(fr, years, channels)
    fig = px.bar(d.assign(Year=d.invoice_year.astype(str)), x="Channel", y="revenue", color="Year",
                 barmode="group", color_discrete_map={"2024": "#8fa9c4", "2025": NAVY},
                 labels={"revenue": "Net revenue ($)"}, title="Chart 1 · Revenue by Channel")
    fig.update_yaxes(tickprefix="$")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.retail_analytics (Q1)", txt)
with c2:
    d, txt = cd.chart2_monthly(fr, years, channels)
    fig = px.line(d.assign(Year=d.invoice_year.astype(str)), x="invoice_month", y="revenue", color="Year",
                  markers=True, color_discrete_map={"2024": "#8fa9c4", "2025": NAVY},
                  labels={"invoice_month": "Month", "revenue": "Net revenue ($)"},
                  title="Chart 2 · Monthly Revenue Trend")
    fig.update_xaxes(tickmode="array", tickvals=list(range(1, 13)), ticktext=cd.MONTHS)
    fig.update_yaxes(tickprefix="$")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.retail_analytics (Q2)", txt)

# ---- Chart 3 & 4 ------------------------------------------------------------------------------
c3, c4 = st.columns(2)
with c3:
    d, txt = cd.chart3_hourly(fr, years, channels)
    fig = px.area(d, x="invoice_hour", y="revenue", color="Channel", color_discrete_map=CH_COLORS,
                  labels={"invoice_hour": "Hour of day (0-23)", "revenue": "Net revenue ($)"},
                  title="Chart 3 · Hour-of-Day Demand Curve")
    fig.update_traces(stackgroup=None, fill="tozeroy")
    fig.update_xaxes(dtick=1, range=[0, 23]); fig.update_yaxes(tickprefix="$")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.retail_analytics (Q3)", txt)
with c4:
    d, txt = cd.chart4_categories(fr, years, channels)
    fig = px.bar(d.sort_values("revenue"), x="revenue", y="Category", orientation="h",
                 labels={"revenue": "Net revenue ($)"}, title="Chart 4 · Top 10 Revenue Categories",
                 color_discrete_sequence=[NAVY])
    fig.update_xaxes(tickprefix="$")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.retail_analytics (Q4)", txt)

# ---- Chart 5 & 6 ------------------------------------------------------------------------------
c5, c6 = st.columns(2)
with c5:
    d, txt = cd.chart5_store_heatmap(fr, years)
    fig = px.imshow(d, text_auto=".3s", color_continuous_scale="Blues", aspect="auto",
                    labels={"x": "Store type", "y": "Region", "color": "Revenue ($)"},
                    title="Chart 5 · Store Performance Heatmap")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.store_performance (Q5)", txt)
with c6:
    d, txt = cd.chart6_return_heatmap(fr, years, channels)
    fig = px.imshow(d, text_auto=".1%", color_continuous_scale="OrRd", zmin=0, zmax=0.25, aspect="auto",
                    labels={"x": "Channel", "y": "Category", "color": "Return rate"},
                    title="Chart 6 · Return Rate Heatmap (0-25%)")
    st.plotly_chart(fig, width="stretch")
    footer("retail_gold.retail_analytics (Q6)", txt)

# ---- Chart 7 ----------------------------------------------------------------------------------
d, a, txt = cd.chart7_anomaly(fr, anomaly_cat)
fig = go.Figure()
fig.add_bar(x=d.week_start, y=d.weekly_revenue, name="Weekly net revenue", marker_color=NAVY)
fig.add_scatter(x=d.week_start, y=d.rolling_4wk_avg_revenue, name="Rolling 4-week average",
                line=dict(color="#6b7280", dash="dash"))
fig.add_annotation(x=a.week_start, y=a.weekly_revenue, ax=120, ay=40, showarrow=True, arrowhead=2,
                   arrowsize=1.5, arrowwidth=2, arrowcolor=ORANGE, font=dict(color=ORANGE, size=13),
                   text=f"<b>ANOMALY</b> — week of {a.week_start:%b %d, %Y}<br>"
                        f"{cd.money(a.weekly_revenue)} = {a.revenue_vs_prior_4wk:.1f}x prior 4-week avg")
fig.update_layout(title=f"Chart 7 · Anomaly Highlight — {anomaly_cat} Weekly Revenue",
                  xaxis_title="Week starting", yaxis_title="Weekly net revenue ($)", yaxis_tickprefix="$")
st.plotly_chart(fig, width="stretch")
footer("retail_gold.category_trends (Q7)", txt)

# ---- Q8 inventory alerts ----------------------------------------------------------------------
with st.expander("Q8 · SKUs at reorder point (slowest net sellers first)"):
    st.dataframe(fr["reorder_alerts"], width="stretch", hide_index=True)
    st.caption("Source: retail_gold.retail_analytics (Q8) · at_reorder_point = StockOnHand ≤ ReorderPoint")
