# Lógica para el seguimiento del vehiculo

import streamlit as st
import folium
from streamlit_folium import st_folium
from datetime import datetime, time
import requests
import pytz

# Configuración del servidor Traccar
TRACCAR_URL = "https://lavanderias-v2-production.up.railway.app"
TRACCAR_USERNAME = "melisabrigitte@gmail.com"  # Cambia según tus credenciales
TRACCAR_PASSWORD = "lavanderias"  # Cambia según tus credenciales

# Obtener posiciones desde la API de Traccar
@st.cache_data(ttl=10)  # Actualiza cada 10 segundos
def obtener_posiciones():
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
    try:
        ahora = datetime.utcnow()
        inicio = ahora.replace(hour=7, minute=30, second=0, microsecond=0)
        fin = ahora.replace(hour=19, minute=0, second=0, microsecond=0)

        # Asegura que esté en formato ISO (UTC)
        inicio_str = inicio.isoformat() + "Z"
        fin_str = fin.isoformat() + "Z"

        url = f"{TRACCAR_URL}/api/positions?deviceId={device_id}&from={inicio_str}&to={fin_str}"

        response = requests.get(url, auth=(TRACCAR_USERNAME, TRACCAR_PASSWORD))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error al obtener historial: {e}")
        return []

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📍 Seguimiento de Vehículo")

    # Validación de horario permitido 
    hora_actual = datetime.now().time()
    hora_inicio = time(7, 30)
    hora_fin = time(19, 0)

    if not (hora_inicio <= hora_actual <= hora_fin):
        st.warning("🚫 El seguimiento del vehículo solo está disponible de 7:30 a.m. a 7:00 p.m.")
        return
    
    # Obtener posiciones actuales desde la API
    posiciones = obtener_posiciones()
    if posiciones:
        # Suponiendo que obtenemos detalles del primer vehículo
        posicion = posiciones[0]  # Consideramos un solo vehículo
        lat, lon = posicion["latitude"], posicion["longitude"]
        device_id = posicion["deviceId"]
        velocidad = posicion.get("speed", 0)  # Velocidad en km/h
        ultima_actualizacion = posicion.get("fixTime", "No disponible")  # Hora de última posición
       
        # Convertir a hora local
        utc_dt = datetime.fromisoformat(ultima_actualizacion.replace("Z", "+00:00"))
        local_tz = pytz.timezone("America/Lima")
        local_dt = utc_dt.astimezone(local_tz)
        ultima_actualizacion_local = local_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Dividir en columnas para diseño
        col1, col2 = st.columns([2, 1])
        with col1:
            # Mapa interactivo
            m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)
            folium.Marker(
                location=[lat, lon],
                popup=f"Vehículo ID: {device_id}\nVelocidad: {velocidad} km/h",
                icon=folium.Icon(color="red", icon="car", prefix="fa")
            ).add_to(m)
            st_folium(m, width=700, height=500)

        with col2:
            # Panel de detalles
            st.markdown(f"""
                <div style='background-color: #f9f9f9; padding: 15px; border-radius: 5px;'>
                    <h4>🚗 <b>Detalles del Vehículo</b></h4>
                    <p><b>ID:</b> {device_id}</p>
                    <p><b>Velocidad:</b> {velocidad} km/h</p>
                    <p><b>Última Actualización:</b> {ultima_actualizacion_local}</p>
                </div>
            """, unsafe_allow_html=True)

        # Mostrar historial de ruta
        historial = obtener_historial(device_id)
        if historial and len(historial) > 1:
            ruta = [(p["latitude"], p["longitude"]) for p in historial]
            folium.PolyLine(ruta, color="blue", weight=2.5, opacity=0.8, tooltip="Ruta del Día").add_to(m)
            
        # Botón para actualizar manualmente (sin filtro dinámico)
        st.button("🔄 Actualizar Datos")
    else:
        st.warning("No hay posiciones disponibles en este momento.")
