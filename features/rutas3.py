import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY
import requests
from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
import time as tiempo
import googlemaps
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas
# Algoritmo 1
from algorithms.algoritmo22 import optimizar_ruta_algoritmo22, cargar_pedidos, _crear_data_model, agrupar_puntos_aglomerativo
# Algoritmo 3
# Algoritmo 4

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        algoritmo = st.selectbox("Algoritmo", ["Algoritmo 1", "Algoritmo 2", "Algoritmo 3", "Algoritmo 4"])

    # Detectar cambio de fecha o algoritmo para reiniciar todo
    if "fecha_previa" not in st.session_state:
        st.session_state["fecha_previa"] = fecha
    if "algoritmo_previo" not in st.session_state:
        st.session_state["algoritmo_previo"] = algoritmo

    if (fecha != st.session_state["fecha_previa"]) or (algoritmo != st.session_state["algoritmo_previo"]):
        st.cache_data.clear()
        for var in ["res", "df_clusters", "df_etiquetado", "df_final", "ruta_guardada", "leg_0", "solve_t"]:
            st.session_state[var] = None if var != "ruta_guardada" else False
            if var == "leg_0":
                st.session_state[var] = 0
        st.session_state["fecha_previa"] = fecha
        st.session_state["algoritmo_previo"] = algoritmo
        st.rerun()

    # Estado persistente
    if "res" not in st.session_state:
        st.session_state["res"] = None
    if "df_clusters" not in st.session_state:
        st.session_state["df_clusters"] = None
    if "df_etiquetado" not in st.session_state:
        st.session_state["df_etiquetado"] = None
    if "df_final" not in st.session_state:
        st.session_state["df_final"] = None
    if "ruta_guardada" not in st.session_state:
        st.session_state["ruta_guardada"] = False
    if "leg_0" not in st.session_state:
        st.session_state["leg_0"] = 0

    # Procesamiento inicial
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        df_original = pd.DataFrame(pedidos)
        df_clusters, df_etiquetado = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_etiquetado.copy()

        DEP = {
            "id": "DEP", "operacion": "Depósito", "nombre_cliente": "Depósito",
            "direccion": "Planta Lavandería", "lat": -16.40904, "lon": -71.53745,
            "time_start": "08:00", "time_end": "18:00", "demand": 0
        }
        df_final = pd.concat([pd.DataFrame([DEP]), df_clusters], ignore_index=True)
        st.session_state["df_final"] = df_final.copy()

        data = _crear_data_model(df_final, vehiculos=1)
        t0 = tiempo.time()
        res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        solve_t = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res
        st.session_state["solve_t"] = solve_t  # Guardar el tiempo de cómputo
        ruta = res["routes"][0]["route"]
        arr = res["routes"][0]["arrival_sec"]

        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ETA"] = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

    # Mostrar tabla de visitas
    df_r = st.session_state["df_ruta"]
    df_f = st.session_state["df_final"]
    df_cl = st.session_state["df_clusters"]
    df_et = st.session_state["df_etiquetado"]
    ruta = st.session_state["res"]["routes"][0]["route"]

    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_r, use_container_width=True)

    if st.button("🔄 Reiniciar Tramos"):
        st.session_state["leg_0"] = 0

    leg = st.session_state["leg_0"]
    if leg >= len(ruta) - 1:
        st.success("✅ Todas las paradas completadas")
        return

    # Tramo actual
    n_origen = ruta[leg]
    n_dest = ruta[leg + 1]
    nombre_dest = df_f.loc[n_dest, "nombre_cliente"]
    direccion_dest = df_f.loc[n_dest, "direccion"]
    ETA_dest = df_r.loc[df_r["orden"] == leg + 1, "ETA"].values[0]

    st.markdown(f"### Próximo → **{nombre_dest}**<br>📍 {direccion_dest} (ETA {ETA_dest})", unsafe_allow_html=True)
    if st.button(f"✅ Llegué a {nombre_dest}"):
        st.session_state["leg_0"] += 1
        st.rerun()

    # Mapa completo con todos los tramos
    with st.expander("🗺️ Mapa de toda la ruta"):
        coords_final = [(df_f.loc[i, "lat"], df_f.loc[i, "lon"]) for i in ruta]
        m = folium.Map(location=coords_final[0], zoom_start=13)
        folium.PolyLine(coords_final, color="blue", weight=4, opacity=0.7).add_to(m)
        folium.Marker(
            coords_final[0],
            popup="Depósito",
            icon=folium.Icon(color="green", icon="home", prefix="fa")
        ).add_to(m)
        for idx, (lat, lon) in enumerate(coords_final[1:], start=1):
            folium.Marker(
                (lat, lon),
                popup=f"{df_f.loc[ruta[idx], 'nombre_cliente']}<br>{df_f.loc[ruta[idx], 'direccion']}",
                icon=folium.Icon(color="orange", icon="flag", prefix="fa")
            ).add_to(m)
        for _, fila_p in df_et.iterrows():
            folium.CircleMarker(
                location=(fila_p["lat"], fila_p["lon"]),
                radius=4,
                color="red",
                fill=True,
                fill_opacity=0.7
            ).add_to(m)
        st_folium(m, width=700, height=500)

    # Métricas finales (con validación de solve_t)
    st.markdown("## 🔍 Métricas Finales")
    solve_t = st.session_state.get("solve_t", None)
    if solve_t is not None:
        st.markdown(f"- Tiempo de cómputo: **{solve_t:.2f} segundos**")
    else:
        st.markdown("- Tiempo de cómputo: --")
    st.markdown(f"- Kilometraje total: **{st.session_state['res']['distance_total_m'] / 1000:.2f} km**")
    tiempo_estimado = (max(st.session_state["res"]["routes"][0]["arrival_sec"]) - SHIFT_START_SEC) / 60
    st.markdown(f"- Tiempo estimado total: **{tiempo_estimado:.2f} min**")
    st.markdown(f"- Puntos totales visitados: **{len(ruta)}**")

