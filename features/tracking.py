import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timedelta

# --- CONFIGURACIÓN TRACCAR ---
TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"
USERNAME = "delgado.ariana18@gmail.com"
PASSWORD = "lav123"
DEVICE_ID = 6

# --- FUNCIONES AUXILIARES ---
def obtener_datos_traccar():
    """Obtiene la posición actual y el historial del día desde Traccar."""
    try:
        # Posición actual
        url_posicion = f"{TRACCAR_URL}/api/positions?deviceId={DEVICE_ID}"
        resp_pos = requests.get(url_posicion, auth=(USERNAME, PASSWORD))
        resp_pos.raise_for_status()
        posicion = resp_pos.json()

        # Historial del día (ruta)
        inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        fin = datetime.utcnow()
        url_historial = f"{TRACCAR_URL}/api/reports/route?deviceId={DEVICE_ID}&from={inicio.isoformat()}Z&to={fin.isoformat()}Z"
        resp_hist = requests.get(url_historial, auth=(USERNAME, PASSWORD))
        resp_hist.raise_for_status()
        historial = resp_hist.json()

        return posicion, historial
    except Exception as e:
        st.error(f"❌ Error al obtener datos de Traccar: {e}")
        return None, None


def seguimiento_vehiculo():
    # --- ENCABEZADO ORIGINAL ---
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento del Vehículo")

    # --- OBTENER DATOS ---
    posicion, historial = obtener_datos_traccar()

    if not posicion:
        st.warning("⚠️ No hay datos de posición disponibles.")
        return

    # --- DATOS DE POSICIÓN ACTUAL ---
    pos = posicion[0]
    lat = pos["latitude"]
    lon = pos["longitude"]
    velocidad = round(pos["speed"] * 3.6, 2)  # m/s → km/h
    hora_utc = datetime.fromisoformat(pos["deviceTime"].replace("Z", "+00:00"))
    hora_local = hora_utc - timedelta(hours=5)  # Perú UTC-5

    # --- DISEÑO EN DOS COLUMNAS ---
    col_mapa, col_info = st.columns([2, 1])

    with col_mapa:
        # Historial del día (ruta)
        if historial and isinstance(historial, list) and len(historial) > 1:
            df_hist = pd.DataFrame(historial)
            df_hist["latitude"] = df_hist["latitude"].astype(float)
            df_hist["longitude"] = df_hist["longitude"].astype(float)
        else:
            df_hist = pd.DataFrame(columns=["latitude", "longitude"])

        # Capas del mapa
        capa_actual = pdk.Layer(
            "ScatterplotLayer",
            data=pd.DataFrame([{"lat": lat, "lon": lon}]),
            get_position='[lon, lat]',
            get_color='[255, 0, 0]',
            get_radius=50,
        )

        capa_ruta = None
        if not df_hist.empty:
            capa_ruta = pdk.Layer(
                "PathLayer",
                data=[{"path": df_hist[["longitude", "latitude"]].values.tolist()}],
                get_color='[0, 0, 255]',
                width_scale=2,
                width_min_pixels=2,
            )

        capas = [capa_actual] + ([capa_ruta] if capa_ruta else [])
        vista = pdk.ViewState(latitude=lat, longitude=lon, zoom=15)

        st.pydeck_chart(
            pdk.Deck(
                map_style="mapbox://styles/mapbox/streets-v11",
                initial_view_state=vista,
                layers=capas,
            )
        )

    with col_info:
        st.markdown("### 📍 Datos del vehículo")
        st.write(f"**Latitud:** {lat}")
        st.write(f"**Longitud:** {lon}")
        st.write(f"**Velocidad:** {velocidad} km/h")
        st.write(f"**Hora local:** {hora_local.strftime('%Y-%m-%d %H:%M:%S')}")
        st.write(f"**Movimiento:** {'🟢 En marcha' if pos['attributes'].get('motion') else '🔴 Detenido'}")

        if df_hist.empty:
            st.info("ℹ️ No hay ruta registrada para hoy.")
        else:
            st.success(f"✅ Ruta registrada con {len(df_hist)} puntos del día.")

