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
    csv_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTOcPceVl3tWhsP4RPdDVhj-lsZH-giVpzRdqDBKq2LVlaUbZ2QZ7VOZ-Gc9Q-drcdU8Zuhet8eYRe2/pub?gid=0&single=true&output=csv"  # Ejemplo: "https://docs.google.com/spreadsheets/d/e/.../pub?output=csv"

    st.caption("Los datos se actualizan automáticamente desde Google Sheets.")

    try:
        # Leer CSV directamente desde la web
        df = pd.read_csv(csv_url)
        df = df.rename(columns=lambda x: x.strip().lower())

        # Verificar columnas
        if not all(col in df.columns for col in ["fecha", "latitud", "longitud"]):
            st.error("❌ El CSV debe tener las columnas: Fecha, Latitud, Longitud")
            st.write("Columnas detectadas:", list(df.columns))
            return

        # Intentar convertir coordenadas a número
        df['latitud'] = pd.to_numeric(df['latitud'], errors='coerce')
        df['longitud'] = pd.to_numeric(df['longitud'], errors='coerce')

        # Si hay muchos NaN, intentar corregir (significa que venían con comas)
        if df['latitud'].isna().mean() > 0.5:
            df['latitud'] = df['latitud'].astype(str).str.replace(',', '.', regex=False)
            df['longitud'] = df['longitud'].astype(str).str.replace(',', '.', regex=False)
            df['latitud'] = pd.to_numeric(df['latitud'], errors='coerce')
            df['longitud'] = pd.to_numeric(df['longitud'], errors='coerce')

        # Limpiar filas vacías
        df = df.dropna(subset=['latitud', 'longitud'])

        # Convertir fechas
        df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
        df = df.dropna(subset=['fecha'])

        # Filtrar por día actual
        hoy = datetime.now().date()
        df_dia = df[df['fecha'].dt.date == hoy]

        if df_dia.empty:
            st.warning("📅 No hay ubicaciones registradas para hoy aún.")
            return

        # Última ubicación
        ultimo = df_dia.iloc[-1]
        lat, lon = ultimo['latitud'], ultimo['longitud']

        # Crear mapa centrado en la última posición
        m = folium.Map(location=[lat, lon], zoom_start=15, control_scale=True)

        # Dibujar ruta recorrida
        ruta = list(zip(df_dia['latitud'], df_dia['longitud']))
        PolyLine(ruta, color="blue", weight=4, opacity=0.7).add_to(m)

        # Marcar última posición
        Marker(
            [lat, lon],
            popup=f"Última ubicación ({ultimo['fecha'].strftime('%H:%M:%S')})",
            icon=folium.Icon(color="red", icon="truck", prefix="fa")
        ).add_to(m)

        # Mostrar mapa
        st_folium(m, width=800, height=500)

        # Mostrar últimas coordenadas
        st.subheader("📋 Últimas posiciones del día")
        st.dataframe(df_dia.tail(10).sort_values(by="fecha", ascending=False))

    except Exception as e:
        st.error("⚠️ Error al procesar los datos.")
        st.write(str(e))
