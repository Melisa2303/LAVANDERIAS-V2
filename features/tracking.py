import streamlit as st
import requests
import datetime
import folium
from streamlit_folium import st_folium

# ===========================
# CONFIGURACIÓN
# ===========================
TRACCAR_URL = "https://traccar-production-ccd9.up.railway.app/"
USERNAME = "delgado.ariana18@gmail.com"
PASSWORD = "TRACCAR"
DEVICE_ID = 1

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

# ---------------------------
# Helper: parsear tiempo y devolver hora local (Perú)
# ---------------------------
def obtener_hora_local_desde_posicion(pos):
    """
    Usa el primer campo disponible entre 'fixTime', 'deviceTime', 'serverTime',
    lo parsea como UTC y lo convierte a hora local de Perú (UTC-5).
    """
    tz_peru = datetime.timezone(datetime.timedelta(hours=-5))
    # elegir campo preferido
    ts = None
    for key in ("fixTime", "deviceTime", "serverTime", "time"):
        if pos.get(key):
            ts = pos.get(key)
            break
    if not ts:
        # fallback: ahora en UTC
        return datetime.datetime.now(tz_peru)

    # Normalizar 'Z' a +00:00 para fromisoformat
    try:
        ts_norm = ts.replace("Z", "+00:00") if isinstance(ts, str) else ts
        dt_utc = datetime.datetime.fromisoformat(ts_norm)
        # si el timestamp no tiene info de zona, tratarlo como UTC
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        # fallback robusto
        try:
            # intentar parsear truncando milisegundos erráticos
            if isinstance(ts, str) and "." in ts:
                base = ts.split(".")[0] + "+00:00"
                dt_utc = datetime.datetime.fromisoformat(base)
                dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)
            else:
                dt_utc = datetime.datetime.now(datetime.timezone.utc)
        except Exception:
            dt_utc = datetime.datetime.now(datetime.timezone.utc)

    # convertir a hora de Perú
    return dt_utc.astimezone(tz_peru)

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

            # columnas ajustadas
            col_mapa, col_info = st.columns([2.3, 0.9])

            # --- Mapa ---
            with col_mapa:
                mapa = folium.Map(location=[lat, lon], zoom_start=15)
                folium.Marker(
                    [lat, lon],
                    popup="Ubicación actual",
                    icon=folium.Icon(color="red", icon="car", prefix="fa")
                ).add_to(mapa)
                st_folium(mapa, width=700, height=450)

            # --- Detalles del vehículo ---
            with col_info:
                # -> Aquí usamos la función segura que selecciona fixTime/deviceTime/serverTime
                hora_local = obtener_hora_local_desde_posicion(posicion)
                en_movimiento = posicion.get("attributes", {}).get("motion", False)

                st.markdown(f"""
                <div style='background-color: #f9fafc; padding: 15px; border-radius: 10px;
                            box-shadow: 0 2px 6px rgba(0,0,0,0.07); border: 1px solid #e0e0e0;
                            font-size: 14px; line-height: 1.4;'>
                    <h4 style='color:#2E86C1; text-align:center; margin-bottom:8px;'>🚘 Detalles</h4>
                    <hr style='border: none; border-top: 1px solid #d0d0d0; margin: 6px 0;'>
                    <p><b>ID:</b> {posicion['deviceId']}</p>
                    <p><b>Latitud:</b> {lat}</p>
                    <p><b>Longitud:</b> {lon}</p>
                    <p><b>Velocidad:</b> {round(posicion.get('speed', 0) * 1.852, 2)} km/h</p>
                    <p><b>Hora local (Perú):</b> {hora_local.strftime('%Y-%m-%d %H:%M:%S')}</p>
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
        # -> obtener la fecha por defecto en hora local (Perú) para evitar salto de día
        tz_peru = datetime.timezone(datetime.timedelta(hours=-5))
        fecha_default = datetime.datetime.now(tz_peru).date()

        col_mapa, col_filtro = st.columns([2.8, 0.9])

        with col_filtro:
            st.markdown("""
            <div style='background-color: #f8f9fa; padding: 20px; border-radius: 12px; 
                        box-shadow: 0 2px 6px rgba(0,0,0,0.1); text-align:center;'>
                <h4 style='color:#2E86C1;'>📅 Seleccionar fecha</h4>
            </div>
            """, unsafe_allow_html=True)
            # usamos la fecha por defecto en hora local
            fecha = st.date_input("Fecha de ruta", fecha_default)

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

