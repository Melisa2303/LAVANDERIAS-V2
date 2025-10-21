import streamlit as st
import pandas as pd
import folium
from folium import PolyLine, Marker
from streamlit_folium import st_folium
from datetime import datetime

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📍 Seguimiento de Vehículo")

    # 👉 Pega aquí el link de tu Google Sheet publicado como CSV
    csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOcPceVl3tWhsP4RPdDVhj-lsZH-giVpzRdqDBKq2LVlaUbZ2QZ7VOZ-Gc9Q-drcdU8Zuhet8eYRe2/pub?gid=0&single=true&output=csv"

    st.caption("Los datos se actualizan automáticamente desde Google Sheets.")

    try:
        # Leer CSV directamente desde Google Sheets
        df = pd.read_csv(csv_url)
        df = df.rename(columns=lambda x: x.strip().lower())

        # Verificar columnas esperadas
        if not all(col in df.columns for col in ["fecha", "lat", "lon"]):
            st.error("❌ El CSV debe tener las columnas: FECHA, LAT, LON")
            st.write("Columnas detectadas:", list(df.columns))
            return

        # Convertir coordenadas a número
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

        # Si hay demasiados NaN, probablemente hay comas en vez de puntos
        if df["lat"].isna().mean() > 0.5:
            df["lat"] = df["lat"].astype(str).str.replace(",", ".", regex=False)
            df["lon"] = df["lon"].astype(str).str.replace(",", ".", regex=False)
            df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
            df["lon"] = pd.to_numeric(df["lon"], errors="coerce")

        # Eliminar filas sin coordenadas válidas
        df = df.dropna(subset=["lat", "lon"])

        # Convertir columna de fecha (día/mes/año hh:mm:ss)
        df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce", dayfirst=True)
        df = df.dropna(subset=["fecha"])

        # Filtrar solo los datos del día actual
        hoy = datetime.now().date()
        df_hoy = df[df["fecha"].dt.date == hoy]

        if df_hoy.empty:
            st.warning("📅 No hay ubicaciones registradas para hoy aún.")
            return

        # Tomar el último punto registrado
        ultimo = df_hoy.iloc[-1]
        lat, lon = ultimo["lat"], ultimo["lon"]

        # Mostrar hora de última actualización
        ultima_hora = ultimo["fecha"].strftime("%d/%m/%Y %H:%M:%S")
        st.markdown(f"🕒 **Última actualización:** {ultima_hora}")

        # Crear el mapa centrado en el último punto
        m = folium.Map(location=[lat, lon], zoom_start_
