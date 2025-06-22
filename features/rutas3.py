# features/rutas3.py

import streamlit as st
import pandas as pd
from datetime import datetime
import time as tiempo

import firebase_admin
from firebase_admin import credentials, firestore

import googlemaps
from googlemaps.convert import decode_polyline

import folium
from streamlit_folium import st_folium

from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY

from algorithms.algoritmo22 import (
    optimizar_ruta_algoritmo22,
    cargar_pedidos,
    _crear_data_model,
    agrupar_puntos_aglomerativo,
    MARGEN,
)
from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

# Coordenadas fijas de la cochera
COCHERA = {
    "lat": -16.4141434959913,
    "lon": -71.51839574233342,
    "direccion": "Cochera",
    "hora": "08:00",
}

# Cliente de Google Maps
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


def optimizar_ruta_placeholder(data, tiempo_max_seg=60):
    """Placeholder para algoritmos no implementados aún."""
    return None


ALG_MAP = {
    "Algoritmo 1 - PCA - GLS": optimizar_ruta_algoritmo22,
    "Algoritmo 2": optimizar_ruta_placeholder,
    "Algoritmo 3": optimizar_ruta_placeholder,
    "Algoritmo 4": optimizar_ruta_algoritmo4,
}


def _hora_a_segundos(hhmm: str) -> int | None:
    """Convierte 'HH:MM' o 'HH:MM:SS' a segundos desde medianoche."""
    if not isinstance(hhmm, str):
        return None
    parts = hhmm.split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0])
        m = int(parts[1])
        return h * 3600 + m * 60
    except:
        return None


def _segundos_a_hora(segs: int) -> str:
    """Convierte segundos desde medianoche a 'HH:MM'."""
    h = segs // 3600
    m = (segs % 3600) // 60
    return f"{h:02}:{m:02}"


def _ventana_extendida(row: pd.Series) -> str:
    """Calcula la ventana time_start–time_end extendida ±MARGEN."""
    ini = _hora_a_segundos(row["time_start"])
    fin = _hora_a_segundos(row["time_end"])
    if ini is None or fin is None:
        return "No especificado"
    ini_m = max(0, ini - MARGEN)
    fin_m = min(24 * 3600, fin + MARGEN)
    return f"{_segundos_a_hora(ini_m)} - {_segundos_a_hora(fin_m)}"


def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        algoritmo = st.selectbox("Algoritmo", list(ALG_MAP.keys()))

    # Reset state si cambian fecha o algoritmo
    if (st.session_state.get("fecha_actual") != fecha or
        st.session_state.get("algoritmo_actual") != algoritmo):
        for k in ["res", "df_clusters", "df_etiquetado", "df_final", "df_ruta", "solve_t"]:
            st.session_state[k] = None
        st.session_state["leg_0"] = 0
        st.session_state["fecha_actual"] = fecha
        st.session_state["algoritmo_actual"] = algoritmo

    # Resolver ruta si no existe aún
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        df_original = pd.DataFrame(pedidos)
        df_clusters, df_et = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_et.copy()

        # Depósito (Planta)
        DEP = {
            "id": "DEP",
            "operacion": "Depósito",
            "nombre_cliente": "Depósito",
            "direccion": "Planta Lavandería",
            "lat": -16.40904,
            "lon": -71.53745,
            "time_start": "08:00",
            "time_end": "18:00",
            "demand": 0
        }
        df_final = pd.concat([pd.DataFrame([DEP]), df_clusters], ignore_index=True)
        st.session_state["df_final"] = df_final.copy()

        # Preparar datos y resolver VRP
        data = _crear_data_model(df_final, vehiculos=1)
        alg_fn = ALG_MAP[algoritmo]
        t0 = tiempo.time()
        res = alg_fn(data, tiempo_max_seg=60)
        st.session_state["solve_t"] = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res

        # Construir df_r con ventana y ETA
        ruta_tmp = res["routes"][0]["route"]
        arr_tmp  = res["routes"][0]["arrival_sec"]
        df_r = df_final.loc[ruta_tmp, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ventana_con_margen"] = df_r.apply(_ventana_extendida, axis=1)
        df_r["ETA"] = [ _segundos_a_hora(t) for t in arr_tmp ]
        df_r["orden"] = range(len(ruta_tmp))
        st.session_state["df_ruta"] = df_r.copy()

    # ─── Aquí recuperamos SIEMPRE res, ruta y arr ───
    res   = st.session_state["res"]
    ruta  = res["routes"][0]["route"]
    arr   = res["routes"][0]["arrival_sec"]
    df_r  = st.session_state["df_ruta"]
    df_et = st.session_state["df_etiquetado"]
    L     = len(ruta)

    # Construir tabla de orden de visita
    filas = []

    # 1) Cochera al inicio
    vent_coch = _ventana_extendida(pd.Series({
        "time_start": COCHERA["hora"],
        "time_end":   COCHERA["hora"]
    }))
    filas.append({
        "orden": 0,
        "nombre_cliente": COCHERA["direccion"],
        "direccion": COCHERA["direccion"],
        "ventana_con_margen": vent_coch,
        "ETA": COCHERA["hora"]
    })

    # 2) Depósito (orden 1)
    dep = df_r[df_r["orden"] == 0].iloc[0]
    filas.append({
        "orden": 1,
        "nombre_cliente": dep["nombre_cliente"],
        "direccion": dep["direccion"],
        "ventana_con_margen": dep["ventana_con_margen"],
        "ETA": dep["ETA"]
    })

    # 3) Resto de paradas
    for _, row in df_r[df_r["orden"] >= 1].sort_values("orden").iterrows():
        filas.append({
            "orden": int(row["orden"]) + 1,
            "nombre_cliente": row["nombre_cliente"],
            "direccion": row["direccion"],
            "ventana_con_margen": row["ventana_con_margen"],
            "ETA": row["ETA"]
        })

    # 4) Vuelta final a Cochera (orden L+1)
    final_eta = _segundos_a_hora(arr[-1])
    filas.append({
        "orden": L + 1,
        "nombre_cliente": COCHERA["direccion"],
        "direccion": COCHERA["direccion"],
        "ventana_con_margen": vent_coch,
        "ETA": final_eta
    })

    df_display = pd.DataFrame(filas).sort_values("orden").reset_index(drop=True)
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_display, use_container_width=True)

    # Pestañas: Tramo actual e Info general
    tab1, tab2 = st.tabs(["🚀 Tramo actual", "ℹ️ Info general"])

    # ─── Tab 1: Tramo actual ───
    with tab1:
        total_legs = L + 1
        if st.session_state["leg_0"] > total_legs:
            st.success("✅ Ruta completada")
        else:
            leg = st.session_state["leg_0"]
            # … lógica de origen, destino y mapa tal y como la tenías …

    # ─── Tab 2: Info general ───
    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta (via API)")
        origin    = f"{COCHERA['lat']},{COCHERA['lon']}"
        depot_lat = df_r.loc[0, "lat"]
        depot_lon = df_r.loc[0, "lon"]
        depot     = f"{depot_lat},{depot_lon}"
        waypoints = [depot] + [f"{df_r.loc[i,'lat']},{df_r.loc[i,'lon']}" for i in ruta[1:]] + [depot]

        directions = gmaps.directions(
            origin,
            origin,
            mode="driving",
            departure_time=datetime.now(),
            optimize_waypoints=False,
            waypoints=waypoints
        )

        overview = directions[0]["overview_polyline"]["points"]
        path     = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]
        total_m  = sum(leg["distance"]["value"] for leg in directions[0]["legs"])
        total_s  = sum(leg["duration"]["value"] for leg in directions[0]["legs"])

        m = folium.Map(location=path[0], zoom_start=13)
        folium.PolyLine(path, weight=4, opacity=0.7).add_to(m)

        # Marcadores
        folium.Marker(
            (COCHERA["lat"],COCHERA["lon"]),
            popup="Cochera", tooltip="Cochera",
            icon=folium.Icon(color="purple",icon="building",prefix="fa")
        ).add_to(m)
        folium.Marker(
            (depot_lat,depot_lon),
            popup="Planta Lavandería", tooltip="Depósito",
            icon=folium.Icon(color="green",icon="home",prefix="fa")
        ).add_to(m)
        for i in ruta[1:]:
            folium.Marker(
                (df_r.loc[i,"lat"], df_r.loc[i,"lon"]),
                popup=f"{df_r.loc[i,'nombre_cliente']}<br>{df_r.loc[i,'direccion']}",
                tooltip=df_r.loc[i,'nombre_cliente'],
                icon=folium.Icon(color="orange",icon="flag",prefix="fa")
            ).add_to(m)
        folium.Marker(
            (COCHERA["lat"],COCHERA["lon"]),
            popup="Cochera", tooltip="Cochera",
            icon=folium.Icon(color="purple",icon="building",prefix="fa")
        ).add_to(m)
        for _, row in df_et.iterrows():
            folium.CircleMarker(
                (row["lat"],row["lon"]),
                radius=4, color="red", fill=True, fill_opacity=0.7
            ).add_to(m)

        st_folium(m, width=700, height=500)

        # Métricas reales
        st.markdown("## 🔍 Métricas de la ruta real")
        st.markdown(f"- Distancia total (Driving): **{total_m/1000:.2f} km**")
        st.markdown(f"- Duración estimada (Driving): **{total_s//60:.0f} min**")

        # Métricas finales VRP
        st.markdown("## 🔍 Métricas Finales")
        st.markdown(f"- Kilometraje total: **{res['distance_total_m']/1000:.2f} km**")
        st.markdown(f"- Tiempo de cómputo: **{st.session_state['solve_t']:.2f} s**")
        tiempo_total_min = (max(arr) - 9*3600) / 60
        st.markdown(f"- Tiempo estimado total: **{tiempo_total_min:.2f} min**")
        st.markdown(f"- Puntos visitados: **{len(ruta) + 2}**")  # +2 por cochera inicio/fin
