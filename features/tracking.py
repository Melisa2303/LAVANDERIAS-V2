import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import pytz

# --- Configuración Traccar ---
TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"
USERNAME = "delgado.ariana18@gmail.com"
PASSWORD = "lav123"
DEVICE_ID = 6

# --- Fecha actual (ajustada a tu zona horaria) ---
tz = pytz.timezone("America/Lima")
today = datetime.now(tz)
start_time = today.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.UTC)
end_time = today.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(pytz.UTC)

# --- Título ---
st.title("📍 Seguimiento GPS - Vehículo")

# --- Solicitud a Traccar ---
url = f"{TRACCAR_URL}/api/positions"
params = {
    "deviceId": DEVICE_ID,
    "from": start_time.isoformat(),
    "to": end_time.isoformat()
}
response = requests.get(url, params=params, auth=(USERNAME, PASSWORD))

if response.status_code == 200:
    positions = response.json()
    if positions:
        # --- Ordenar por tiempo ---
        positions.sort(key=lambda x: x["fixTime"])
        
        # --- Coordenadas ---
        latitudes = [p["latitude"] for p in positions]
        longitudes = [p["longitude"] for p in positions]
        latest = positions[-1]
        lat = latest["latitude"]
        lon = latest["longitude"]
        
        # --- Crear mapa ---
        m = folium.Map(location=[lat, lon], zoom_start=15, tiles="OpenStreetMap")

        # --- Dibujar ruta si hay más de un punto ---
        if len(positions) > 1:
            route = list(zip(latitudes, longitudes))
            folium.PolyLine(route, color="blue", weight=5, opacity=0.7).add_to(m)
            ruta_texto = f"📈 Ruta registrada con {len(positions)} puntos."
        else:
            ruta_texto = "ℹ️ No hay ruta registrada para hoy."
        
        # --- Marcador del punto actual ---
        folium.Marker(
            [lat, lon],
            tooltip="Posición actual",
            popup=f"Velocidad: {latest['speed']*1.852:.2f} km/h",
            icon=folium.Icon(color="green" if latest["attributes"].get("motion", False) else "red")
        ).add_to(m)
        
        # --- Mostrar datos al costado ---
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"**Latitud:** {lat:.6f}")
            st.markdown(f"**Longitud:** {lon:.6f}")
            st.markdown(f"**Velocidad:** {latest['speed']*1.852:.2f} km/h")
            st.markdown(f"**Hora local:** {datetime.fromisoformat(latest['fixTime'].replace('Z', '+00:00')).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            motion = "🟢 En marcha" if latest["attributes"].get("motion", False) else "🔴 Detenido"
            st.markdown(f"**Movimiento:** {motion}")
            st.markdown(ruta_texto)

        with col2:
            st_folium(m, width=700, height=500)
    else:
        st.warning("⚠️ No se encontraron posiciones para el día actual.")
else:
    st.error(f"Error {response.status_code}: {response.text}")
