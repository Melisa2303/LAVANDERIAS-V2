# ============================
# 📍 Seguimiento del Vehículo - Versión mejorada
# ============================

import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime
import requests
import pytz

# -----------------------------
# 🔧 Configuración del servidor Traccar
# -----------------------------
TRACCAR_URL = "http://traccar-production-8d92.up.railway.app"
TRACCAR_USERNAME = "delgado.ariana18@gmail.com"
TRACCAR_PASSWORD = "lav123"

# -----------------------------
# 📡 Funciones auxiliares
# -----------------------------

@st.cache_data(ttl=10)  # Cache 10 segundos para actualizar rápido
def obtener_posiciones():
    """Obtiene la última posición de los dispositivos."""
    try:
        response = requests.get(
            f"{TRACCAR_URL}/api/positions",
            auth=(TRACCAR_USERNAME, TRACCAR_PASSWORD)
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error al obtener posiciones: {e}")
        return []

def obtener_historial(device_id):
    """Obtiene el historial del día actual (00:00 a ahora) en UTC."""
    try:
        ahora = datetime.utcnow()
        inicio = datetime(ahora.year, ahora.month, ahora.day, 0, 0, 0)
        fin = ahora

        inicio_str = inicio.isoformat() + "Z"
        fin_str = fin.isoformat() + "Z"

        url = f"{TRACCAR_URL}/api/positions?deviceId={device_id}&from={inicio_str}&to={fin_str}"
        response = requests.get(url, auth=(TRACCAR_USERNAME, TRACCAR_PASSWORD))
        response.raise_for_status()
        data = response.json()
        return sorted(data, key=lambda x: x["fixTime"])
    except Exception as e:
        st.error(f"Error al obtener historial: {e}")
        return []

# -----------------------------
# 🗺️ Interfaz principal
# -----------------------------
def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento del Vehículo")

    # Obtener posiciones actuales
    posiciones = obtener_posiciones()
    if not posiciones:
        st.warning("No hay posiciones disponibles en este momento.")
        return

    # Tomamos la primera posición (un vehículo)
    posicion = posiciones[0]
    lat, lon = posicion["latitude"], posicion["longitude"]
    device_id = posicion["deviceId"]
    velocidad = round(posicion.get("speed", 0) * 1.852, 1)  # Convertir de nudos a km/h si aplica
    ultima_actualizacion = posicion.get("fixTime", "No disponible")

    # Convertir a hora local Lima
    try:
        utc_dt = datetime.fromisoformat(ultima_actualizacion.replace("Z", "+00:00"))
        local_tz = pytz.timezone("America/Lima")
        local_dt = utc_dt.astimezone(local_tz)
        ultima_actualizacion_local = local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        ultima_actualizacion_local = "No disponible"

    # Crear mapa base
    m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)

    # 🔵 Dibujar ruta del día
    historial = obtener_historial(device_id)
    if historial and len(historial) > 1:
        ruta = [(p["latitude"], p["longitude"]) for p in historial]
        folium.PolyLine(ruta, color="blue", weight=3, opacity=0.8, tooltip="Ruta del Día").add_to(m)

    # 📍 Marcador de posición actual
    folium.Marker(
        location=[lat, lon],
        popup=f"Vehículo ID: {device_id}\nVelocidad: {velocidad} km/h",
        icon=folium.Icon(color="red", icon="car", prefix="fa")
    ).add_to(m)

    # Mostrar mapa
    st_folium(m, width=700, height=500)

    # Mostrar información lateral
    st.markdown(f"""
        <div style='background-color: #f9f9f9; padding: 15px; border-radius: 5px;'>
            <h4>📋 <b>Detalles del Vehículo</b></h4>
            <p><b>ID:</b> {device_id}</p>
            <p><b>Velocidad:</b> {velocidad} km/h</p>
            <p><b>Última actualización:</b> {ultima_actualizacion_local}</p>
        </div>
    """, unsafe_allow_html=True)

    # Botón manual para refrescar
    st.button("🔄 Actualizar Datos")


