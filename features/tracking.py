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
    tz_peru = datetime.timezone(datetime.timedelta(hours=-5))
    hoy_local = datetime.datetime.now(tz_peru).replace(hour=0, minute=0, second=0, microsecond=0)
    mañana_local = hoy_local + datetime.timedelta(days=1)

    hoy_utc = hoy_local.astimezone(datetime.timezone.utc)
    mañana_utc = mañana_local.astimezone(datetime.timezone.utc)

    url = f"{TRACCAR_URL}/api/positions"
    params = {
        "deviceId": DEVICE_ID,
        "from": hoy_utc.isoformat().replace("+00:00", "Z"),
        "to": mañana_utc.isoformat().replace("+00:00", "Z")
    }
    r = requests.get(url, params=params, auth=(USERNAME, PASSWORD))
    r.raise_for_status()
    return r.json()

# ===========================
# INTERFAZ STREAMLIT
# ===========================
def seguimiento_vehiculo():
    # Encabezado original
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

            # Mapa y detalles al costado
            col_mapa, col_datos = st.columns([2, 1])

            with col_mapa:
                mapa = folium.Map(location=[lat, lon], zoom_start=15)
                folium.Marker(
                    [lat, lon],
                    popup="Ubicación actual",
                    icon=folium.Icon(color="red", icon="car", prefix="fa")
                ).add_to(mapa)
                st_folium(mapa, width=700, height=450)

            with col_datos:
                st.markdown("""
                <div style="
                    background-color: #f8f9fa;
                    border: 1px solid #dcdcdc;
                    border-radius: 10px;
                    padding: 15px;
                    box-shadow: 0px 2px 6px rgba(0,0,0,0.1);
                ">
                    <h4 style="text-align:center; color:#2E86C1;">🧾 Detalles del Vehículo</h4>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                <p><b>🚘 ID:</b> {posicion['deviceId']}</p>
                <p><b>📍 Latitud:</b> {posicion['latitude']}</p>
                <p><b>📍 Longitud:</b> {posicion['longitude']}</p>
                <p><b>💨 Velocidad:</b> {round(posicion.get('speed', 0) * 1.852, 2)} km/h</p>
                """, unsafe_allow_html=True)

                hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace("Z", "+00:00")).astimezone()
                hora_str = hora_local.strftime('%Y-%m-%d %H:%M:%S')
                st.markdown(f"<p><b>🕓 Hora local:</b> {hora_str}</p>", unsafe_allow_html=True)

                en_movimiento = posicion.get("attributes", {}).get("motion", False)
                color_estado = "#28B463" if en_movimiento else "#CB4335"
                texto_estado = "🟢 En marcha" if en_movimiento else "🔴 Detenido"
                st.markdown(f"<p><b>⚙️ Movimiento:</b> <span style='color:{color_estado};'>{texto_estado}</span></p>", unsafe_allow_html=True)

                st.markdown("</div>", unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                st.button("🔄 Actualizar ubicación")

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

            folium.Marker(coords[0], popup="Inicio", icon=folium.Icon(color="green")).add_to(mapa)
            folium.Marker(coords[-1], popup="Última posición", icon=folium.Icon(color="red")).add_to(mapa)

            st_folium(mapa, width=700, height=450)
        else:
            st.info("ℹ️ No hay ruta registrada para hoy.")


