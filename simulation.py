import requests
import pandas as pd
import numpy as np

import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone

EIA_API_KEY = "3fN7uU71XZYLdcQAPasd0vGhyh2l5KbxOWgldW2y"
BASE_URL = "https://api.eia.gov/v2/electricity/rto/region-sub-ba-data/data"

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
        "length": 5000              
    }

    r = requests.get(url, params=params, timeout=30)

    if r.status_code != 200:
        print("API Error:", r.status_code)
        print(r.text)
        print("URL used:", r.url)    
        return None

    js = r.json()
    data = js.get("response", {}).get("data", [])

    if not data:
        print("No data returned.")
        print("URL used:", r.url)
        return None

    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["period"])
    df["price_or_demand"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["price_or_demand"]).sort_values("time").reset_index(drop=True)
    return df

# 30-day range
end_date = datetime.now(timezone.utc)
start_date = end_date - timedelta(days=30)

df = fetch_eia_hourly(
    EIA_API_KEY,
    start_date.strftime("%Y-%m-%dT%H"),
    end_date.strftime("%Y-%m-%dT%H"),
    parent="ERCO",
    subba="COAS"
)

if df is None or df.empty:
    print("No data available — simulation cannot run.")
    exit()


np.random.seed(42)
df["battery_charge"] = 50
df["compute_util"] = np.clip(np.random.normal(50, 20, len(df)), 0, 100)
df["jobs_in_queue"] = np.random.randint(0, 50, len(df))
df["power_draw"] = df["compute_util"] * np.random.uniform(0.2, 0.4, len(df))

MIN_CHARGE, MAX_CHARGE = 20, 95
CHARGE_RATE, DISCHARGE_RATE = 10, 15

def decision_engine(row):
    demand = row["price_or_demand"]
    battery = row["battery_charge"]
    util = row["compute_util"]
    cheap_thresh = df["price_or_demand"].median()
    if demand < cheap_thresh and battery < MAX_CHARGE:
        return "Charge"
    if demand < cheap_thresh and util > 70:
        return "Run off grid"
    if demand >= cheap_thresh and battery > MIN_CHARGE:
        return "Run off battery"
    return "Idle"

df["decision"] = df.apply(decision_engine, axis=1)

for i in range(1, len(df)):
    prev = df.loc[i-1, "battery_charge"]
    dec = df.loc[i, "decision"]
    if dec == "Charge":
        df.at[i, "battery_charge"] = min(prev + CHARGE_RATE, MAX_CHARGE)
    elif dec == "Run off battery":
        df.at[i, "battery_charge"] = max(prev - DISCHARGE_RATE, MIN_CHARGE)
    else:
        df.at[i, "battery_charge"] = prev


plt.figure(figsize=(14, 8))
plt.plot(df["time"], df["price_or_demand"], label="Demand (Proxy)")
plt.plot(df["time"], df["battery_charge"], label="Battery Charge (%)")
plt.title("30-Day Demand and Battery Simulation")
plt.legend()
plt.show()
