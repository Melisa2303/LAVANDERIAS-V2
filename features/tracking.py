# ================================================
# 📍 Seguimiento de Vehículo - versión Google Sheets (sin Traccar)
# ================================================

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime
import pytz
import time

# ------------------------------------------------
# CONFIGURACIÓN INICIAL
# ------------------------------------------------

st.set_page_config(page_title="Seguimiento de Vehículo", layout="wide")

# URL del CSV publicado desde tu Google Sheet
# 🔧 Reemplaza con tu enlace público al CSV
CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOcPceVl3tWhsP4RPdDVhj-lsZH-giVpzRdqDBKq2LVlaUbZ2QZ7VOZ-Gc9Q-drcdU8Zuhet8eYRe2/pub?gid=0&single=true&output=csv"

# Tiempo de refresco automático (en segundos)
REFRESH_INTERVAL = 10

# ------------------------------------------------
# FUNCIÓN PARA CARGAR Y LIMPIAR DATOS
# ------------------------------------------------

@st.cache_data(ttl=REFRESH_INTERVAL)
def cargar_datos():
    try:
        df = pd.read_csv(CSV_URL)
        df.columns = df.columns.str.strip().str.upper()
        
        # Verificar columnas necesarias
        cols = ['FECHA','DRIVER_ID','LAT','LON','SPEED','TIMESTAMP','TIMESTAMP_GPS']
        df = df[[c for c in cols if c in df.columns]]

        # Limpiar coordenadas
        df["LAT"] = pd.to_numeric(df["LAT"], errors="coerce")
        df["LON"] = pd.to_numeric(df["LON"], errors="coerce")

        # Convertir fechas
        df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")

        # Filtrar solo datos del día actual (zona horaria Lima)
        lima_tz = pytz.timezone("America/Lima")
        hoy = datetime.now(lima_tz).date()
        df = df[df["FECHA"].dt.date == hoy]

        # Ordenar por hora
        df = df.sort_values(by="FECHA")
        return df
    except Exception as e:
        st.error(f"Error al cargar el CSV: {e}")
        return pd.DataFrame()

# ------------------------------------------------
# INTERFAZ PRINCIPAL
# ------------------------------------------------

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📍 Seguimiento de Vehículo")

    df = cargar_datos()
    if df.empty:
        st.warning("No hay datos disponibles para el día de hoy.")
        return

    # Última posición
    ultimo = df.iloc[-1]
    lat, lon = ultimo["LAT"], ultimo["LON"]
    velocidad = ultimo.get("SPEED", 0)
    hora = ultimo["FECHA"]

    # Mapa
    m = folium.Map(location=[lat, lon], zoom_start=14, control_scale=True)

    # Línea de ruta (historial del día)
    if len(df) > 1:
        puntos = df[["LAT", "LON"]].dropna().values.tolist()
        folium.PolyLine(puntos, color="blue", weight=3, opacity=0.7, tooltip="Ruta del Día").add_to(m)

    # Marcador actual
    folium.Marker(
        location=[lat, lon],
        popup=f"Velocidad: {velocidad} km/h\nHora: {hora.strftime('%H:%M:%S')}",
        icon=folium.Icon(color="red", icon="car", prefix="fa")
    ).add_to(m)

    # Mostrar mapa
    st_folium(m, width=800, height=500)

    # Panel de detalles
    st.markdown(f"""
    <div style='background-color:#f9f9f9; padding:15px; border-radius:8px;'>
        <h4>🚗 <b>Detalles del Vehículo</b></h4>
        <p><b>Última actualización:</b> {hora.strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><b>Velocidad actual:</b> {velocidad} km/h</p>
        <p><b>Coordenadas:</b> {lat:.6f}, {lon:.6f}</p>
        <p><b>Total de puntos del día:</b> {len(df)}</p>
    </div>
    """, unsafe_allow_html=True)

    # Botón manual de refresco
    if st.button("🔄 Actualizar ahora"):
        st.cache_data.clear()
        st.experimental_rerun()

    # Actualización automática
    st.markdown(f"<small>⏱️ Actualización automática cada {REFRESH_INTERVAL} segundos</small>", unsafe_allow_html=True)
    time.sleep(REFRESH_INTERVAL)
    st.experimental_rerun()
    
