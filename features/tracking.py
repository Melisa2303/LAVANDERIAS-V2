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
DEVICE_ID = 6

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

    incluir_estaticos = st.checkbox("Mostrar puntos sin movimiento", value=False)

    posicion = obtener_posicion_actual()
    ruta = obtener_ruta_hoy()

    if not posicion:
        st.warning("No se encontró información del vehículo.")
        return

    lat, lon = posicion["latitude"], posicion["longitude"]
    mapa = folium.Map(location=[lat, lon], zoom_start=15)

    if len(ruta) > 1:
        if not incluir_estaticos:
            ruta = [p for p in ruta if p.get("speed", 0) > 0.5]

        if len(ruta) > 1:
            coords = [(p["latitude"], p["longitude"]) for p in ruta]
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(mapa)
            # Añadimos punto de inicio y fin
            folium.Marker(coords[0], icon=folium.Icon(color="green"), popup="Inicio").add_to(mapa)
            folium.Marker(coords[-1], icon=folium.Icon(color="red"), popup="Fin").add_to(mapa)

    # Posición actual
    folium.Marker(
        [lat, lon],
        popup="Ubicación actual",
        icon=folium.Icon(color="orange", icon="car", prefix="fa")
    ).add_to(mapa)

    # Layout
    col_mapa, col_info = st.columns([2, 1])
    with col_mapa:
        st_folium(mapa, width=700, height=450)
    with col_info:
        st.markdown("### 🧾 Detalles del Vehículo")
        st.write(f"**ID:** {posicion['deviceId']}")
        velocidad_kmh = round(posicion.get("speed", 0) * 1.852, 1)
        st.write(f"**Velocidad:** {velocidad_kmh} km/h")

        hora_local = datetime.datetime.fromisoformat(
            posicion["deviceTime"].replace("Z", "+00:00")
        ).astimezone(datetime.timezone(datetime.timedelta(hours=-5)))
        st.write(f"**Hora local:** {hora_local.strftime('%Y-%m-%d %H:%M:%S')}")

        movimiento = "🟢 En marcha" if velocidad_kmh > 1 else "🔴 Detenido"
        st.write(f"**Movimiento:** {movimiento}")

        if len(ruta) <= 1:
            st.info("ℹ️ No hay ruta registrada para hoy (aún no se ha movido).")

    if st.button("🔄 Actualizar datos"):
        st.rerun()

