import streamlit as st
import requests
import datetime
import folium
from streamlit_folium import st_folium

# ===========================
# CONFIGURACIÓN
# ===========================
TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"  # Tu URL real
USERNAME = "delgado.ariana18@gmail.com"     # Tu usuario
PASSWORD = "lav123"                         # Tu contraseña
DEVICE_ID = 6                               # Tu ID real

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
    # ---- ENCABEZADO ORIGINAL ----
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)

    st.title("🚗 Seguimiento del Vehículo")

    # ---- SELECCIÓN DE VISTA ----
    opcion = st.radio("Selecciona vista:", ["📍 Ubicación en vivo", "🗺️ Ruta del día"], horizontal=True)

    # ==========================================================
    # 📍 UBICACIÓN EN VIVO
    # ==========================================================
    if opcion == "📍 Ubicación en vivo":
        posicion = obtener_posicion_actual()

        if posicion:
            lat, lon = posicion["latitude"], posicion["longitude"]
            velocidad = round(posicion.get("speed", 0) * 1.852, 2)  # nudos a km/h
            movimiento = "🟢 En marcha" if velocidad > 0.5 else "🔴 Detenido"
            hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace("Z", "+00:00")).astimezone().strftime('%Y-%m-%d %H:%M:%S')

            # Diseño en columnas
            col_mapa, col_datos = st.columns([2, 1])

            with col_mapa:
                mapa = folium.Map(location=[lat, lon], zoom_start=16)
                folium.Marker([lat, lon],
                              popup="Ubicación actual",
                              icon=folium.Icon(color="red", icon="car", prefix="fa")).add_to(mapa)
                st_folium(mapa, width=700, height=500)

            with col_datos:
                st.markdown(
                    f"""
                    <div style='background-color:#f0f2f6; padding:15px; border-radius:10px;'>
                        <h4 style='color:#2E86C1;'>📊 Datos del Vehículo</h4>
                        <p><b>Latitud:</b> {lat:.6f}</p>
                        <p><b>Longitud:</b> {lon:.6f}</p>
                        <p><b>Velocidad:</b> {velocidad} km/h</p>
                        <p><b>Hora local:</b> {hora_local}</p>
                        <p><b>Movimiento:</b> {movimiento}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

        else:
            st.warning("No se encontró información del vehículo.")

        if st.button("🔄 Actualizar ubicación"):
            st.rerun()

    # ==========================================================
    # 🗺️ RUTA DEL DÍA
    # ==========================================================
    elif opcion == "🗺️ Ruta del día":
        ruta = obtener_ruta_hoy()

        if ruta:
            coords = [(p["latitude"], p["longitude"]) for p in ruta]
            mapa = folium.Map(location=coords[-1], zoom_start=14)
            folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(mapa)
            folium.Marker(coords[0], popup="Inicio", icon=folium.Icon(color="green")).add_to(mapa)
            folium.Marker(coords[-1], popup="Fin", icon=folium.Icon(color="red")).add_to(mapa)
            st_folium(mapa, width=900, height=550)
        else:
            st.warning("ℹ️ No hay ruta registrada para hoy.")
