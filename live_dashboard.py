import os, json, threading, time
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
from paho.mqtt import client as mqtt
from dash import Dash, html, dcc, Output, Input, State, no_update
import dash_leaflet as dl
import config
_latest_by_facility: Dict[str, Dict[str, Any]] = {}
_store_lock = threading.Lock()

def load_facility_metadata_from_cache() -> pd.DataFrame:
    """load facility metadata"""
    cache_file = os.path.join(config.DATA_DIR, "cache", "facilities_list.json")
    if not os.path.exists(cache_file):
        return pd.DataFrame()

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        facilities = cache.get("facilities", [])
        if not facilities:
            return pd.DataFrame()

        rows = []
        for x in facilities:
            code = x.get("code") or x.get("facility_code") or ""
            name = x.get("name") or code

            # Compatibility of longitude and latitude
            loc = (x.get("location") or {})
            lat = x.get("lat") or x.get("latitude") or loc.get("lat") or loc.get("latitude")
            lon = x.get("lon") or x.get("lng") or x.get("longitude") or loc.get("lng") or loc.get("longitude")

            region = x.get("network_region") or x.get("region")
            fuel = x.get("fueltech") or x.get("fuel_tech") or x.get("fueltech_id")
            if not fuel:
                units = x.get("units") or []
                if units:
                    fuel = units[0].get("fueltech_id")

            rows.append({
                "facility_id": str(code),
                "facility_name": str(name),
                "lat": lat,
                "lon": lon,
                "region": region,
                "fuel_tech": fuel,
            })

        df = pd.DataFrame(rows).drop_duplicates(subset=["facility_id"])
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df = df.dropna(subset=["lat", "lon"])
        df = df[(df["lat"].between(-90, 90)) & (df["lon"].between(-180, 180))]

        return df 
    except Exception as e:
        print(f"[WARN] Failed to read the facility cache: {e}")
        return pd.DataFrame()



FAC_META = load_facility_metadata_from_cache()
HAS_COORDS = (not FAC_META.empty) and FAC_META[["lat", "lon"]].notna().all(axis=1).any()
print(f"[INFO] Facility metadata has been loaded successfully: {len(FAC_META)}, Including coordinates:{HAS_COORDS}")


def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT backend subscribe """
    print(f"[MQTT] Connected rc={rc}")
    client.subscribe(config.MQTT_TOPIC, qos=1)
    print(f"[MQTT] Subscribed topic={config.MQTT_TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        fac_id = str(payload.get("facility_id") or "")
        if not fac_id:
            return
        rec = {
            "facility_id": fac_id,
            "facility_name": payload.get("facility_name") or fac_id,
            "network": payload.get("network"),
            "timestamp": payload.get("timestamp"),           
            "power_generated": payload.get("power_generated"),
            "co2_emissions": payload.get("co2_emissions"),
        }

        if not FAC_META.empty:
            meta = FAC_META[FAC_META["facility_id"] == fac_id]
            if not meta.empty:
                m = meta.iloc[0].to_dict()
                rec.update({
                    "lat": m.get("lat"),
                    "lon": m.get("lon"),
                    "region": m.get("region"),
                    "fuel_tech": m.get("fuel_tech"),
                })

        with _store_lock:
            _latest_by_facility[fac_id] = rec

    except Exception as e:
        print(f"[MQTT] message parse error: {e}")

def start_mqtt_thread():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="a2_task4_dashboard")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=60)
    t = threading.Thread(target=client.loop_forever, daemon=True)
    t.start()
    return client

# ========== Dash App ==========
app = Dash(__name__)
app.title = "NEM Facilities - Live Power & Emissions"

region_opts = sorted([x for x in FAC_META["region"].dropna().unique()]) if not FAC_META.empty and "region" in FAC_META else []
fuel_opts = sorted([x for x in FAC_META["fuel_tech"].dropna().unique()]) if not FAC_META.empty and "fuel_tech" in FAC_META else []

left_panel = html.Div([
    html.H3("Live Dashboard"),
    html.Div([
        html.Div(["Broker: ", html.Code(f"{config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}")]),
        html.Div(["Topic: ", html.Code(config.MQTT_TOPIC)]),
    ], style={"fontSize": "12px", "color": "#666", "marginBottom": "8px"}),

    html.Label("Metric"),
    dcc.RadioItems(
        id="metric", inline=True,
        options=[{"label": "Power (MW)", "value": "power_generated"},
                 {"label": "CO₂ (t)", "value": "co2_emissions"}],
        value="power_generated"
    ),

    html.Div(style={"height": "8px"}),

    html.Label("Region"),
    dcc.Dropdown(id="region", options=[{"label": r, "value": r} for r in region_opts], multi=True, placeholder="All regions"),

    html.Label("Fuel Tech", style={"marginTop": "8px"}),
    dcc.Dropdown(id="fuel", options=[{"label": f, "value": f} for f in fuel_opts], multi=True, placeholder="All fuels"),

    html.Label("Automatic refresh (in milliseconds)", style={"marginTop": "8px"}),
    dcc.Slider(id="interval_ms", min=500, max=5000, step=500, value=2000,
               marks={i: str(i) for i in range(500, 5001, 500)}),

    dcc.Interval(id="tick", interval=2000, n_intervals=0),

    html.Div(id="stats", style={"marginTop": "10px", "fontSize": "12px", "color": "#444"}),
], style={"width": "320px", "padding": 14, "borderRight": "1px solid #eee", "height": "100vh", "overflow": "auto"})

# If there are no coordinates, a table will be displayed
map_container = html.Div([
    dl.Map(center=(-26.5, 134.5), zoom=4, children=[
        dl.TileLayer(),
        dl.LayerGroup(id="markers"),
    ], style={"width": "100%", "height": "70vh"}),
    html.Div(id="table_holder", style={"padding": "8px 12px"}),
], style={"flex": 1})

app.layout = html.Div([left_panel, map_container], style={"display": "flex", "gap": 0})

# refresh rate
@app.callback(Output("tick", "interval"), Input("interval_ms", "value"))
def set_interval(ms):
    try:
        return int(ms)
    except Exception:
        return 2000

# Statistical map table
@app.callback(
    Output("markers", "children"),
    Output("table_holder", "children"),
    Output("stats", "children"),
    Input("tick", "n_intervals"),
    State("metric", "value"),
    State("region", "value"),
    State("fuel", "value"),
)
def update_view(_n, metric, regions, fuels):

    with _store_lock:
        data = list(_latest_by_facility.values())

    if not data:
        return [], html.Div("Data has not been received yet. Please confirm that the publishing end is running"), "Records: 0"

    df = pd.DataFrame(data)

    if regions and "region" in df.columns:
        df = df[df["region"].isin(regions)]
    if fuels and "fuel_tech" in df.columns:
        df = df[df["fuel_tech"].isin(fuels)]

    rec_cnt = len(df)
    total_power = df["power_generated"].fillna(0).sum() if "power_generated" in df else 0
    total_co2 = df["co2_emissions"].fillna(0).sum() if "co2_emissions" in df else 0
    stats = f"Records: {rec_cnt} | Σ Power(MW): {total_power:.1f} | Σ CO₂(t): {total_co2:.1f}"

    markers = []
    has_coords = ("lat" in df.columns and "lon" in df.columns and df[["lat", "lon"]].notna().all(axis=1).any())
    if has_coords:
        vals = df[metric].fillna(0).abs()
        vmax = max(vals.max(), 1.0)
        radii = (vals / vmax * 12 + 4).tolist()  # 4-16 px
        for i, row in df.reset_index(drop=True).iterrows():
            lat, lon = row.get("lat"), row.get("lon")
            if pd.isna(lat) or pd.isna(lon):
                continue
            radius = radii[i]
            color = "#2c7fb8" if metric == "power_generated" else "#de2d26"
            tooltip = f"{row.get('facility_name','?')} — {metric}: {row.get(metric,'-')}"
            popup = html.Div([
                html.B(row.get("facility_name", "?")), html.Br(),
                html.Span(f"Region: {row.get('region','-')}  |  Fuel: {row.get('fuel_tech','-')}"), html.Br(),
                html.Span(f"Power: {row.get('power_generated','-')} MW"), html.Br(),
                html.Span(f"CO₂: {row.get('co2_emissions','-')} t"), html.Br(),
                html.Span(f"Updated: {row.get('timestamp','')}")
            ])
            markers.append(
                dl.CircleMarker(center=(lat, lon), radius=radius, color=color, fillColor=color, fillOpacity=0.6,
                                children=[dl.Tooltip(tooltip), dl.Popup(popup)])
            )

    table_cols = ["facility_id", "facility_name", "timestamp", "power_generated", "co2_emissions"]
    extra_cols = [c for c in ["region", "fuel_tech"] if c in df.columns]
    show_cols = table_cols + extra_cols
    table_df = df[show_cols].copy()
    table_df = table_df.sort_values("timestamp", ascending=False).head(200)
    table = html.Div([
        html.H4("Latest Records"),
        html.Table([
            html.Thead(html.Tr([html.Th(c) for c in show_cols])),
            html.Tbody([html.Tr([html.Td(str(table_df.iloc[i][c])) for c in show_cols]) for i in range(len(table_df))])
        ], style={"width": "100%", "fontSize": "12px", "borderCollapse": "collapse"})
    ])

    if not has_coords:
        return [], table, stats
    else:
        return markers, table, stats

if __name__ == "__main__":
    print(f"Starting MQTT consumer on {config.MQTT_BROKER_HOST}:{config.MQTT_BROKER_PORT}, topic={config.MQTT_TOPIC}")
    start_mqtt_thread()
    app.run(debug=True, host="0.0.0.0", port=8050)




'''
Acknowledgment of AI Use

Portions of this project were developed with the assistance of OpenAI's ChatGPT (GPT-5). The tool was used to help with:
	•	Structuring and refining Python code for data retrieval, cleaning, and MQTT integration;
	•	Support code snippets for dashboard visualisation; and
	•	Reviewing and improving the clarity and grammar of written documentation.

All AI-generated content was critically reviewed, tested, and modified by the authors to ensure accuracy, originality, and compliance with the project requirements.
'''