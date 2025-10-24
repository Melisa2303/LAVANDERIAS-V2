import streamlit as st
import requests
import datetime
import folium
from streamlit_folium import st_folium

# ===========================
# CONFIGURACIÓN
# ===========================
TRACCAR_URL = "https://traccar-production-8d92.up.railway.app/"  # Cambia por tu URL real
USERNAME = "Lavanderías Americanas"     # Cambia si usas otro usuario
PASSWORD = "lav123"     # Cambia por tu contraseña
DEVICE_ID = "Arianne"          # Cambia por tu ID real

# ===========================
# FUNCIONES
# ===========================
def obtener_posicion_actual():
    url = f"{TRACCAR_URL}/api/positions"
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    r.raise_for_status()
    data = r.json()
    for pos in data:
        if pos["deviceId"] == DEVICE_ID:
            return pos
    return None

def obtener_ruta_hoy():
    hoy = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    mañana = hoy + datetime.timedelta(days=1)
    url = f"{TRACCAR_URL}/api/positions"
    params = {
        "deviceId": DEVICE_ID,
        "from": hoy.isoformat() + "Z",
        "to": mañana.isoformat() + "Z"
    }
    r = requests.get(url, params=params, auth=(USERNAME, PASSWORD))
    r.raise_for_status()
    return r.json()

# ===========================
# INTERFAZ STREAMLIT
# ===========================
st.title("🚗 Seguimiento GPS del Vehículo")

posicion = obtener_posicion_actual()
ruta = obtener_ruta_hoy()

if posicion:
    lat, lon = posicion["latitude"], posicion["longitude"]
    mapa = folium.Map(location=[lat, lon], zoom_start=14)

    # Dibujar la ruta del día
    if len(ruta) > 1:
        coords = [(p["latitude"], p["longitude"]) for p in ruta]
        folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(mapa)

    # Marcar posición actual
    folium.Marker(
        [lat, lon],
        popup="Ubicación actual",
        icon=folium.Icon(color="red", icon="car", prefix="fa")
    ).add_to(mapa)

    st_folium(mapa, width=700, height=450)

    # Detalles
    st.markdown("### 🧾 Detalles del Vehículo")
    st.write(f"**ID:** {posicion['deviceId']}")
    st.write(f"**Velocidad:** {round(posicion.get('speed', 0) * 1.852, 1)} km/h")  # Convert knots → km/h
    hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace("Z", "+00:00")).astimezone()
    st.write(f"**Última actualización:** {hora_local.strftime('%Y-%m-%d %H:%M:%S')}")

else:
    st.warning("No se encontró información del vehículo.")

if st.button("🔄 Actualizar Datos"):
    st.rerun()
