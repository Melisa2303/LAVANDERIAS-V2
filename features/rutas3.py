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
from algorithms.algoritmo22 import optimizar_ruta_algoritmo22, cargar_pedidos, _crear_data_model, agrupar_puntos_aglomerativo

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        algoritmo = st.selectbox("Algoritmo", ["Algoritmo 1", "Algoritmo 2", "Algoritmo 3", "Algoritmo 4"])

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

    # Procesamiento
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
        st.metric("⏱️ Tiempo de cómputo", f"{solve_t:.2f} s")
        st.metric("📏 Distancia total (km)", f"{res['distance_total_m'] / 1000:.2f}")

        ruta = res["routes"][0]["route"]
        arr = res["routes"][0]["arrival_sec"]

        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ETA"] = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

    # Mostramos resultados
    df_r = st.session_state["df_ruta"]
    df_f = st.session_state["df_final"]
    df_cl = st.session_state["df_clusters"]
    df_et = st.session_state["df_etiquetado"]
    ruta = st.session_state["res"]["routes"][0]["route"]
    res = st.session_state["res"]

    # Tabs de "Tramo" e "Info"
    tab1, tab2 = st.tabs(["🚀 Tramo actual", "ℹ️ Info general"])
    with tab1:
        leg = st.session_state["leg_0"]
        if leg >= len(ruta) - 1:
            st.success("✅ Todas las paradas completadas")
            return

        n_origen = ruta[leg]
        n_dest = ruta[leg + 1]
        nombre_dest = df_f.loc[n_dest, "nombre_cliente"]
        direccion_dest = df_f.loc[n_dest, "direccion"]
        ETA_dest = df_r.loc[df_r["orden"] == leg + 1, "ETA"].values[0]

        st.markdown(f"### Próximo → **{nombre_dest}** (ETA {ETA_dest})")
        if st.button(f"✅ Llegué a {nombre_dest}"):
            st.session_state["leg_0"] += 1
            st.rerun()

        orig = f"{df_f.loc[n_origen, 'lat']},{df_f.loc[n_origen, 'lon']}"
        dest = f"{df_f.loc[n_dest, 'lat']},{df_f.loc[n_dest, 'lon']}"
        try:
            directions = gmaps.directions(orig, dest, mode="driving", departure_time=datetime.now(), traffic_model="best_guess")
            leg0 = directions[0]["legs"][0]
            tiempo_traffic = leg0.get("duration_in_traffic", leg0["duration"])["text"]
            overview = directions[0]["overview_polyline"]["points"]
            segmento = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]
        except:
            tiempo_traffic = None
            segmento = [(df_f.loc[n_origen, "lat"], df_f.loc[n_origen, "lon"]), (df_f.loc[n_dest, "lat"], df_f.loc[n_dest, "lon"])]

        m = folium.Map(location=segmento[0], zoom_start=14)
        folium.PolyLine(segmento, color="blue", weight=5, opacity=0.8, tooltip=f"⏱ {tiempo_traffic}" if tiempo_traffic else None).add_to(m)
        folium.Marker(segmento[0], icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
        folium.Marker(segmento[-1], icon=folium.Icon(color="blue", icon="flag", prefix="fa")).add_to(m)
        st_folium(m, width=700, height=400)

    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta")
        coords_final = [(df_f.loc[i, "lat"], df_f.loc[i, "lon"]) for i in ruta]
        m = folium.Map(location=coords_final[0], zoom_start=13)
        folium.PolyLine(coords_final, color="blue", weight=4, opacity=0.7).add_to(m)

        folium.Marker(coords_final[0], popup="Depósito", icon=folium.Icon(color="green", icon="home", prefix="fa")).add_to(m)
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

    # Métricas finales
    st.markdown("## 🔍 Métricas Finales")
    st.markdown(f"- Kilometraje total: **{res['distance_total_m'] / 1000:.2f} km**")
    st.markdown(f"- Tiempo de cómputo: **{solve_t:.2f} segundos**")
    tiempo_total_min = (max(res['routes'][0]['arrival_sec']) - 9 * 3600) / 60
    st.markdown(f"- Tiempo estimado total: **{tiempo_total_min:.2f} min**")
    st.markdown(f"- Puntos totales visitados: **{len(ruta)}**")
