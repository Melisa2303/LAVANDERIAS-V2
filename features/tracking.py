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

def obtener_ruta_por_fecha(fecha):
    tz_peru = datetime.timezone(datetime.timedelta(hours=-5))
    inicio = datetime.datetime.combine(fecha, datetime.time.min, tz_peru)
    fin = datetime.datetime.combine(fecha + datetime.timedelta(days=1), datetime.time.min, tz_peru)
    inicio_utc = inicio.astimezone(datetime.timezone.utc)
    fin_utc = fin.astimezone(datetime.timezone.utc)

    url = f"{TRACCAR_URL}/api/positions"
    params = {
        "deviceId": DEVICE_ID,
        "from": inicio_utc.isoformat().replace("+00:00", "Z"),
        "to": fin_utc.isoformat().replace("+00:00", "Z")
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

    vista = st.radio("Selecciona una vista:", ["📍 Ubicación en vivo", "🗺️ Ruta del día"])

    # =====================
    # 📍 UBICACIÓN EN VIVO
    # =====================
    if vista == "📍 Ubicación en vivo":
        posicion = obtener_posicion_actual()

        if posicion:
            lat, lon = posicion["latitude"], posicion["longitude"]

            col_mapa, col_info = st.columns([2.3, 1])

            # --- Mapa ---
            with col_mapa:
                mapa = folium.Map(location=[lat, lon], zoom_start=15)
                folium.Marker(
                    [lat, lon],
                    popup="Ubicación actual",
                    icon=folium.Icon(color="red", icon="car", prefix="fa")
                ).add_to(mapa)
                st_folium(mapa, width=700, height=450)

            # --- Detalles del vehículo (recuadro mejorado) ---
            with col_info:
                hora_local = datetime.datetime.fromisoformat(posicion["deviceTime"].replace('Z', '+00:00')).astimezone()
                en_movimiento = posicion.get("attributes", {}).get("motion", False)

                st.markdown(f"""
                <div style='background-color: #f9fafc; padding: 22px; border-radius: 12px;
                            box-shadow: 0 3px 8px rgba(0,0,0,0.08); border: 1px solid #e0e0e0;'>
                    <h4 style='color:#2E86C1; text-align:center;'>🚘 Detalles del Vehículo</h4>
                    <hr style='border: none; border-top: 1px solid #d0d0d0;'>
                    <p><b>ID:</b> {posicion['deviceId']}</p>
                    <p><b>Latitud:</b> {lat}</p>
                    <p><b>Longitud:</b> {lon}</p>
                    <p><b>Velocidad:</b> {round(posicion.get('speed', 0) * 1.852, 2)} km/h</p>
                    <p><b>Hora local:</b> {hora_local.strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <p><b>Estado:</b> {'🟢 En marcha' if en_movimiento else '🔴 Detenido'}</p>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🔄 Actualizar ubicación"):
                    st.rerun()
        else:
            st.warning("No se encontró información del vehículo.")

    # =====================
    # 🗺️ RUTA DEL DÍA
    # =====================
    elif vista == "🗺️ Ruta del día":
        col_mapa, col_filtro = st.columns([3, 1])

        with col_filtro:
            st.markdown("""
            <div style='background-color: #f8f9fa; padding: 20px; border-radius: 12px; 
                        box-shadow: 0 2px 6px rgba(0,0,0,0.1); text-align:center;'>
                <h4 style='color:#2E86C1;'>📅 Seleccionar fecha</h4>
            </div>
            """, unsafe_allow_html=True)
            fecha = st.date_input("Fecha de ruta", datetime.date.today())

        with col_mapa:
            ruta = obtener_ruta_por_fecha(fecha)
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
                st.info("ℹ️ No hay ruta registrada para la fecha seleccionada.")

