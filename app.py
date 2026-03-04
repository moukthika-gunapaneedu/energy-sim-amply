import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

EIA_API_KEY = "3fN7uU71XZYLdcQAPasd0vGhyh2l5KbxOWgldW2y"


def fetch_eia_hourly(api_key, start, end, parent="ERCO", subba="COAS"):
    url = "https://api.eia.gov/v2/electricity/rto/region-sub-ba-data/data/"
    params = {
        "api_key": api_key,
        "frequency": "hourly",
        "data[0]": "value",
        "facets[parent][]": parent,
        "facets[subba][]": subba,
        "start": start,
        "end": end,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json().get("response", {}).get("data", [])
    if not data:
        return None
    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["period"])
    df["price_or_demand"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["price_or_demand"]).sort_values("time").reset_index(drop=True)
    return df


def run_simulation(df, charge_rate, discharge_rate, min_charge, max_charge):
    np.random.seed(42)
    df = df.copy()
    df["battery_charge"] = 50.0
    df["compute_util"] = np.clip(np.random.normal(50, 20, len(df)), 0, 100)
    df["jobs_in_queue"] = np.random.randint(0, 50, len(df))
    df["power_draw"] = df["compute_util"] * np.random.uniform(0.2, 0.4, len(df))

    cheap_thresh = df["price_or_demand"].median()

    def decision_engine(row):
        demand = row["price_or_demand"]
        battery = row["battery_charge"]
        util = row["compute_util"]
        if demand < cheap_thresh and battery < max_charge:
            return "Charge"
        if demand < cheap_thresh and util > 70:
            return "Run off grid"
        if demand >= cheap_thresh and battery > min_charge:
            return "Run off battery"
        return "Idle"

    df["decision"] = df.apply(decision_engine, axis=1)

    for i in range(1, len(df)):
        prev = df.loc[i - 1, "battery_charge"]
        dec = df.loc[i, "decision"]
        if dec == "Charge":
            df.at[i, "battery_charge"] = min(prev + charge_rate, max_charge)
        elif dec == "Run off battery":
            df.at[i, "battery_charge"] = max(prev - discharge_rate, min_charge)
        else:
            df.at[i, "battery_charge"] = prev

    return df


DECISION_COLORS = {
    "Charge": "rgba(46,204,113,0.25)",
    "Run off battery": "rgba(231,76,60,0.25)",
    "Run off grid": "rgba(52,152,219,0.25)",
    "Idle": "rgba(149,165,166,0.15)",
}


def build_chart(df):
    fig = go.Figure()

    # Color-coded decision background bands
    for decision, color in DECISION_COLORS.items():
        mask = df["decision"] == decision
        if not mask.any():
            continue
        fig.add_trace(
            go.Scatter(
                x=df.loc[mask, "time"],
                y=df.loc[mask, "price_or_demand"],
                mode="markers",
                marker=dict(size=4, color=color),
                name=decision,
                legendgroup=decision,
                showlegend=True,
            )
        )

    # Demand line (left y-axis)
    fig.add_trace(
        go.Scatter(
            x=df["time"],
            y=df["price_or_demand"],
            mode="lines",
            name="Demand (MW)",
            line=dict(color="#2c3e50", width=1.5),
            yaxis="y",
        )
    )

    # Battery line (right y-axis)
    fig.add_trace(
        go.Scatter(
            x=df["time"],
            y=df["battery_charge"],
            mode="lines",
            name="Battery %",
            line=dict(color="#e67e22", width=2),
            yaxis="y2",
        )
    )

    fig.update_layout(
        title="Energy Demand & Battery Simulation",
        xaxis=dict(title="Time"),
        yaxis=dict(title="Demand (MW)", side="left"),
        yaxis2=dict(title="Battery Charge %", side="right", overlaying="y", range=[0, 100]),
        legend=dict(orientation="h", y=-0.15),
        height=550,
        margin=dict(l=60, r=60, t=50, b=80),
    )
    return fig


# ── Streamlit UI ──

st.set_page_config(page_title="Amply Energy Sim", layout="wide")
st.title("Amply Energy Simulation")

# Sidebar controls
st.sidebar.header("Simulation Parameters")
num_days = st.sidebar.slider("Date range (days)", 1, 60, 30)
charge_rate = st.sidebar.slider("Charge rate (%/hr)", 1, 30, 10)
discharge_rate = st.sidebar.slider("Discharge rate (%/hr)", 1, 30, 15)
min_charge = st.sidebar.slider("Min charge %", 0, 50, 20)
max_charge = st.sidebar.slider("Max charge %", 50, 100, 95)

# Fetch data
end_date = datetime.now(timezone.utc)
start_date = end_date - timedelta(days=num_days)

with st.spinner("Fetching EIA data..."):
    df = fetch_eia_hourly(
        EIA_API_KEY,
        start_date.strftime("%Y-%m-%dT%H"),
        end_date.strftime("%Y-%m-%dT%H"),
    )

if df is None or df.empty:
    st.error("No data returned from EIA API. Try a different date range.")
    st.stop()

# Run simulation
df = run_simulation(df, charge_rate, discharge_rate, min_charge, max_charge)

# Chart
st.plotly_chart(build_chart(df), use_container_width=True)

# Decision summary table
st.subheader("Decision Summary")
counts = df["decision"].value_counts()
summary = pd.DataFrame({"Decision": counts.index, "Hours": counts.values})
summary["% of Time"] = (summary["Hours"] / summary["Hours"].sum() * 100).round(1)
st.dataframe(summary, hide_index=True, use_container_width=False)
