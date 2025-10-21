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

    # URL del Google Sheet publicado como CSV
    csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOcPceVl3tWhsP4RPdDVhj-lsZH-giVpzRdqDBKq2LVlaUbZ2QZ7VOZ-Gc9Q-drcdU8Zuhet8eYRe2/pub?gid=0&single=true&output=csv"

    st.caption("Los datos se actualizan automáticamente desde Google Sheets.")

    try:
        df = pd.read_csv(csv_url)
        df = df.rename(columns=lambda x: x.strip().lower())

        # Verificar columnas necesarias
        if not all(col in df.columns for col in ["fecha", "lat", "lon"]):
            st.error("❌ El CSV debe tener las columnas: FECHA, LAT, LON")
            st.write("Columnas detectadas:", list(df.columns))
            return

        # Asegurar formato correcto de coordenadas
        df['lat'] = df['lat'].astype(str).str.replace(',', '.', regex=False)
        df['lon'] = df['lon'].astype(str).str.replace(',', '.', regex=False)
        df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
        df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
        df = df.dropna(subset=['lat', 'lon'])

        # Convertir fecha con reconocimiento flexible
        df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce', infer_datetime_format=True, dayfirst=True)
        df = df.dropna(subset=['fecha'])

        # Mostrar fechas detectadas
        st.write("🕒 Fechas detectadas:", df['fecha'].dt.date.unique())

        # Filtrar solo por fecha seleccionada (por defecto hoy)
        hoy = datetime.now().date()
        fecha_sel = st.date_input("Selecciona fecha a visualizar", hoy)
        df_sel = df[df['fecha'].dt.date == fecha_sel]

        if df_sel.empty:
            st.warning(f"📅 No hay ubicaciones registradas para {fecha_sel}.")
            return

        # Último punto
        ultimo = df_sel.iloc[-1]
        lat, lon = ultimo['lat'], ultimo['lon']

        # Crear mapa centrado en el último punto
        m = folium.Map(location=[lat, lon], zoom_start=15, control_scale=True)

        # Dibujar ruta
        ruta = list(zip(df_sel['lat'], df_sel['lon']))
        PolyLine(ruta, color="blue", weight=4, opacity=0.7).add_to(m)

        # Agregar marcador de última posición
        Marker(
            [lat, lon],
            popup=f"Última ubicación ({ultimo['fecha'].strftime('%d/%m %H:%M:%S')})",
            icon=folium.Icon(color="red", icon="truck", prefix="fa")
        ).add_to(m)

        # Mostrar mapa
        st_folium(m, width=800, height=500)

        # Mostrar últimas posiciones
        st.subheader(f"📋 Posiciones registradas el {fecha_sel}")
        st.dataframe(df_sel.sort_values(by="fecha", ascending=False).tail(15))

    except Exception as e:
        st.error("⚠️ Error al procesar los datos.")
        st.write(str(e))
