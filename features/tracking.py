import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timedelta, timezone

# --- CONFIGURACIÓN DE LA APP ---
st.set_page_config(page_title="Seguimiento GPS", layout="wide")

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento del Vehículo")

    # --- CONFIGURACIÓN TRACCAR (TUS DATOS) ---
    TRACCAR_URL = "https://traccar-production-8d92.up.railway.app"
    USERNAME = "delgado.ariana18@gmail.com"
    PASSWORD = "lav123"
    DEVICE_ID = 6

    # --- FUNCIONES AUXILIARES ---
    def get_last_position():
        """Obtiene la última posición del dispositivo."""
        url = f"{TRACCAR_URL}/api/positions?deviceId={DEVICE_ID}"
        r = requests.get(url, auth=(USERNAME, PASSWORD))
        r.raise_for_status()
        data = r.json()
        return data[-1] if data else None

    def get_today_positions():
        """Obtiene todas las posiciones del día actual."""
        tz = timezone(timedelta(hours=-5))  # Hora Perú
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now

        params = {
            "deviceId": DEVICE_ID,
            "from": start.isoformat(),
            "to": end.isoformat(),
        }

        url = f"{TRACCAR_URL}/api/positions"
        r = requests.get(url, params=params, auth=(USERNAME, PASSWORD))
        r.raise_for_status()
        return r.json()

    # --- SECCIÓN: UBICACIÓN ACTUAL ---
    st.subheader("📡 Ubicación actual (actualiza cada 15 segundos)")

    # Crear contenedor para el mapa
    map_placeholder = st.empty()

    # Refrescar cada 15 segundos sin recargar toda la app
    st_autorefresh = st.experimental_rerun if st.session_state.get("last_update", 0) < datetime.now().timestamp() - 15 else None

    try:
        last_position = get_last_position()
        if last_position:
            lat = last_position["latitude"]
            lon = last_position["longitude"]
            speed = last_position.get("speed", 0) * 1.852  # Convertir nudos a km/h
            moving = "🟢 En marcha" if speed > 1 else "🔴 Detenido"

            fix_time = datetime.fromisoformat(last_position["fixTime"].replace("Z", "+00:00")).astimezone(
                timezone(timedelta(hours=-5))
            )

            # Mostrar datos al costado del mapa
            col_map, col_info = st.columns([2.5, 1])
            with col_map:
                map_data = pd.DataFrame([[lat, lon]], columns=["lat", "lon"])
                map_placeholder.pydeck_chart(
                    pdk.Deck(
                        map_style="mapbox://styles/mapbox/streets-v12",
                        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=16),
                        layers=[
                            pdk.Layer(
                                "ScatterplotLayer",
                                data=map_data,
                                get_position="[lon, lat]",
                                get_color=[255, 0, 0],
                                get_radius=60,
                            ),
                        ],
                    )
                )
            with col_info:
                st.markdown(f"**Latitud:** {lat}")
                st.markdown(f"**Longitud:** {lon}")
                st.markdown(f"**Velocidad:** {speed:.2f} km/h")
                st.markdown(f"**Hora local:** {fix_time.strftime('%Y-%m-%d %H:%M:%S')}")
                st.markdown(f"**Movimiento:** {moving}")
        else:
            st.warning("No se encontró ubicación reciente para el vehículo.")

    except Exception as e:
        st.error(f"Error al obtener ubicación: {e}")

    # --- SECCIÓN: BOTÓN PARA VER RUTA DEL DÍA ---
    st.markdown("---")
    if st.button("🗺️ Ver ruta completa del día"):
        with st.spinner("Cargando ruta del día..."):
            try:
                positions = get_today_positions()
                if not positions:
                    st.warning("No hay ruta registrada para hoy.")
                else:
                    df = pd.DataFrame(positions)
                    df = df[df["latitude"].diff().abs() > 0.00001]  # Filtrar posiciones idénticas (sin movimiento)

                    df["latitude"] = df["latitude"].astype(float)
                    df["longitude"] = df["longitude"].astype(float)

                    midpoint = (df["latitude"].mean(), df["longitude"].mean())

                    st.subheader("🚗 Ruta recorrida del día")
                    st.pydeck_chart(
                        pdk.Deck(
                            map_style="mapbox://styles/mapbox/outdoors-v12",
                            initial_view_state=pdk.ViewState(
                                latitude=midpoint[0],
                                longitude=midpoint[1],
                                zoom=13,
                                pitch=0,
                            ),
                            layers=[
                                pdk.Layer(
                                    "PathLayer",
                                    data=df,
                                    get_path="[[longitude, latitude]]",
                                    get_color=[0, 100, 255],
                                    width_scale=2,
                                    width_min_pixels=2,
                                ),
                                pdk.Layer(
                                    "ScatterplotLayer",
                                    data=df,
                                    get_position="[longitude, latitude]",
                                    get_color=[255, 0, 0],
                                    get_radius=30,
                                ),
                            ],
                        )
                    )
            except Exception as e:
                st.error(f"Error al obtener la ruta: {e}")

    st.caption("💡 Mapa en vivo (15s) + botón para ver la ruta del día completa.")

