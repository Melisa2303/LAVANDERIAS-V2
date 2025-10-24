import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta

# ---- CONFIG ----
TRACCAR_URL = "https://traccar-production-8c8a.up.railway.app"
USERNAME = "admin"
PASSWORD = "admin"
DEVICE_ID = 1  # ID del dispositivo de tu celular

st.title("🚚 Seguimiento GPS - Vehículo en tiempo real")

# ---- FUNCIONES ----
def obtener_posicion_actual():
    url = f"{TRACCAR_URL}/api/positions"
    response = requests.get(url, auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        posiciones = response.json()
        for pos in posiciones:
            if pos["deviceId"] == DEVICE_ID:
                return pos
    return None

def obtener_ruta_dia():
    ahora = datetime.utcnow()
    inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = ahora
    url = f"{TRACCAR_URL}/api/reports/route?deviceId={DEVICE_ID}&from={inicio.isoformat()}Z&to={fin.isoformat()}Z"
    response = requests.get(url, auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        return response.json()
    return []

# ---- OPCIÓN 1: Última ubicación ----
st.subheader("📍 Última ubicación (actualizable manualmente)")

if st.button("🔄 Actualizar ubicación"):
    posicion = obtener_posicion_actual()
    if posicion:
        lat = posicion["latitude"]
        lon = posicion["longitude"]
        map_ = folium.Map(location=[lat, lon], zoom_start=16)
        folium.Marker(
            [lat, lon],
            popup=f"Última posición: {datetime.fromtimestamp(posicion['fixTime']/1000)}",
            tooltip="Ubicación actual",
            icon=folium.Icon(color="blue", icon="car", prefix="fa")
        ).add_to(map_)
        st_folium(map_, width=700, height=450)
    else:
        st.warning("No se pudo obtener la posición actual. Revisa la conexión con Traccar.")

# ---- OPCIÓN 2: Ver ruta del día ----
st.subheader("🗺️ Ruta completa del día (hasta este momento)")

if st.button("📅 Ver ruta del día"):
    ruta = obtener_ruta_dia()
    if ruta:
        # Filtramos puntos válidos
        puntos = [(p["latitude"], p["longitude"]) for p in ruta if p.get("latitude") and p.get("longitude")]
        if puntos:
            map_ruta = folium.Map(location=puntos[-1], zoom_start=14)
            folium.PolyLine(puntos, color="red", weight=4, opacity=0.7).add_to(map_ruta)
            folium.Marker(puntos[0], popup="Inicio", icon=folium.Icon(color="green")).add_to(map_ruta)
            folium.Marker(puntos[-1], popup="Último punto", icon=folium.Icon(color="blue")).add_to(map_ruta)
            st_folium(map_ruta, width=700, height=450)
        else:
            st.info("No hay puntos registrados para hoy.")
    else:
        st.warning("No se pudo obtener la ruta del día.")
