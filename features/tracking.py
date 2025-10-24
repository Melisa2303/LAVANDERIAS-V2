import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timedelta
import pytz

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Seguimiento Vehicular", layout="wide")

TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"
USERNAME = "delgado.ariana18@gmail.com"
PASSWORD = "lav123"
DEVICE_ID = 6

# --- FUNCIONES ---
def obtener_posicion_actual():
    url = f"{TRACCAR_URL}/api/positions"
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    if r.status_code == 200:
        data = r.json()
        for pos in data:
            if pos.get("deviceId") == DEVICE_ID:
                return pos
    return None

def obtener_ruta_dia():
    hoy = datetime.utcnow().date()
    inicio = datetime.combine(hoy, datetime.min.time())
    fin = datetime.combine(hoy, datetime.max.time())
    url = f"{TRACCAR_URL}/api/reports/route?deviceId={DEVICE_ID}&from={inicio.isoformat()}Z&to={fin.isoformat()}Z"
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    if r.status_code == 200:
        return r.json()
    return []

def convertir_hora_local(utc_str):
    try:
        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        lima_tz = pytz.timezone("America/Lima")
        return utc_dt.astimezone(lima_tz).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return utc_str

# --- ENCABEZADO ---
st.title("🚛 Seguimiento Vehicular")

# --- SELECCIÓN ---
vista = st.radio("Selecciona vista:", ["📍 Ubicación en vivo", "🗺️ Ruta del día"])

# --- UBICACIÓN EN VIVO ---
if vista == "📍 Ubicación en vivo":
    posicion = obtener_posicion_actual()
    if posicion:
        lat, lon = posicion["latitude"], posicion["longitude"]
        velocidad = round(posicion["speed"] * 3.6, 2)
        hora_local = convertir_hora_local(posicion["fixTime"])
        movimiento = "🟢 En marcha" if posicion["attributes"].get("motion") else "🔴 Detenido"

        col1, col2 = st.columns([2, 1])

        with col1:
            st.pydeck_chart(pdk.Deck(
                map_style="mapbox://styles/mapbox/streets-v12",
                initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=16, pitch=45),
                layers=[
                    pdk.Layer(
                        "ScatterplotLayer",
                        data=pd.DataFrame([{"lat": lat, "lon": lon}]),
                        get_position=["lon", "lat"],
                        get_color=[0, 255, 0],
                        get_radius=10,
                    )
                ],
            ))

        with col2:
            st.markdown(
                f"""
                <div style="background-color:white; border-radius:15px; padding:20px; box-shadow:0px 2px 10px rgba(0,0,0,0.1); font-size:16px;">
                    <h4 style="color:#1f77b4;">📡 Datos de la ubicación</h4>
                    <b>Latitud:</b> {lat:.6f}<br>
                    <b>Longitud:</b> {lon:.6f}<br>
                    <b>Velocidad:</b> {velocidad} km/h<br>
                    <b>Hora local:</b> {hora_local}<br>
                    <b>Movimiento:</b> {movimiento}
                </div>
                """,
                unsafe_allow_html=True
            )

        st.button("🔄 Actualizar ubicación")

    else:
        st.warning("No se pudo obtener la ubicación actual del dispositivo.")

# --- RUTA DEL DÍA ---
elif vista == "🗺️ Ruta del día":
    ruta = obtener_ruta_dia()
    if ruta:
        df = pd.DataFrame(ruta)
        df["lat"] = df["latitude"]
        df["lon"] = df["longitude"]

        st.pydeck_chart(pdk.Deck(
            map_style="mapbox://styles/mapbox/streets-v12",
            initial_view_state=pdk.ViewState(latitude=df["lat"].mean(), longitude=df["lon"].mean(), zoom=14),
            layers=[
                pdk.Layer(
                    "PathLayer",
                    data=[{"path": df[["lon", "lat"]].values.tolist(), "color": [255, 0, 0]}],
                    get_color="color",
                    width_scale=2,
                    width_min_pixels=3,
                ),
                pdk.Layer(
                    "ScatterplotLayer",
                    data=pd.DataFrame([{"lat": df["lat"].iloc[-1], "lon": df["lon"].iloc[-1]}]),
                    get_position=["lon", "lat"],
                    get_color=[0, 255, 0],
                    get_radius=10,
                )
            ],
        ))
    else:
        st.info("ℹ️ No hay ruta registrada para hoy.")
