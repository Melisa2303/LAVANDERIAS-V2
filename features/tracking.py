import streamlit as st
import requests
import datetime
import folium
from streamlit_folium import st_folium

# ===========================
# CONFIGURACIÓN
# ===========================
TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"
USERNAME = "delgado.ariana18@gmail.com"
PASSWORD = "lav123"
DEVICE_ID = 6   # ID del dispositivo (ver en Traccar -> Dispositivos)

# ===========================
# FUNCIONES
# ===========================
def obtener_posicion_actual():
    """Obtiene la última posición registrada del dispositivo."""
    url = f"{TRACCAR_URL}/api/positions"
    r = requests.get(url, auth=(USERNAME, PASSWORD))
    r.raise_for_status()
    posiciones = r.json()
    for pos in posiciones:
        if pos.get("deviceId") == DEVICE_ID:
            return pos
    return None

def obtener_ruta_hoy():
    """Obtiene todas las posiciones del día actual."""
    hoy = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    mañana = hoy + datetime.timedelta(days=1)
    url = f"{TRACCAR_URL}/api/reports/route"
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
def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento del Vehículo")

    # Obtener datos
    posicion = obtener_posicion_actual()
    ruta = obtener_ruta_hoy()

    if not posicion:
        st.warning("No se encontró información del vehículo.")
        return

    lat, lon = posicion["latitude"], posicion["longitude"]

    # Crear mapa
    mapa = folium.Map(location=[lat, lon], zoom_start=14)

    # Dibujar ruta del día
    if isinstance(ruta, list) and len(ruta) > 1:
        coords = [(p["latitude"], p["longitude"]) for p in ruta]
        folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(mapa)
        folium.Marker(coords[0], popup="Inicio del día", icon=folium.Icon(color="green")).add_to(mapa)
        folium.Marker(coords[-1], popup="Última posición", icon=folium.Icon(color="red", icon="car", prefix="fa")).add_to(mapa)
    else:
        folium.Marker([lat, lon], popup="Ubicación actual", icon=folium.Icon(color="red")).add_to(mapa)

    # Mostrar mapa y datos
    col_mapa, col_info = st.columns([3, 1])
    with col_mapa:
        st_folium(mapa, width=700, height=450)

    with col_info:
        st.markdown("### 🧾 Detalles del Vehículo")
        st.write(f"**ID:** {posicion['deviceId']}")
        st.write(f"**Velocidad:** {round(posicion.get('speed', 0) * 1.852, 1)} km/h")  # knots a km/h
        hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace("Z", "+00:00")).astimezone()
        st.write(f"**Última actualización:** {hora_local.strftime('%Y-%m-%d %H:%M:%S')}")

    # Botón actualizar
    if st.button("🔄 Actualizar Datos"):
        st.rerun()

