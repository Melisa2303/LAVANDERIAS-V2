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
def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento del Vehículo")

    # Selector de vista
    vista = st.radio("Selecciona una vista:", ["📍 Ubicación en vivo", "🗺️ Ruta del día"])

    if vista == "📍 Ubicación en vivo":
        posicion = obtener_posicion_actual()

        if posicion:
            lat, lon = posicion["latitude"], posicion["longitude"]
            mapa = folium.Map(location=[lat, lon], zoom_start=15)

            folium.Marker(
                [lat, lon],
                popup="Ubicación actual",
                icon=folium.Icon(color="red", icon="car", prefix="fa")
            ).add_to(mapa)

            st_folium(mapa, width=700, height=450)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 🧾 Detalles del Vehículo")
                st.write(f"**ID:** {posicion['deviceId']}")
                st.write(f"**Latitud:** {lat}")
                st.write(f"**Longitud:** {lon}")
                st.write(f"**Velocidad:** {round(posicion.get('speed', 0) * 1.852, 2)} km/h")
                hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace("Z", "+00:00")).astimezone()
                st.write(f"**Hora local:** {hora_local.strftime('%Y-%m-%d %H:%M:%S')}")
                en_movimiento = posicion.get("attributes", {}).get("motion", False)
                st.write(f"**Movimiento:** {'🟢 En marcha' if en_movimiento else '🔴 Detenido'}")

            with col2:
                if st.button("🔄 Actualizar ubicación"):
                    st.rerun()
        else:
            st.warning("No se encontró información del vehículo.")

    elif vista == "🗺️ Ruta del día":
        ruta = obtener_ruta_hoy()

        if ruta and len(ruta) > 1:
            coords = [(p["latitude"], p["longitude"]) for p in ruta]
            lat_prom = sum(p[0] for p in coords) / len(coords)
            lon_prom = sum(p[1] for p in coords) / len(coords)

            mapa = folium.Map(location=[lat_prom, lon_prom], zoom_start=14)
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(mapa)

            # Punto inicial y final
            folium.Marker(coords[0], popup="Inicio", icon=folium.Icon(color="green")).add_to(mapa)
            folium.Marker(coords[-1], popup="Última posición", icon=folium.Icon(color="red")).add_to(mapa)

            st_folium(mapa, width=700, height=450)
        else:
            st.info("ℹ️ No hay ruta registrada para hoy.")

