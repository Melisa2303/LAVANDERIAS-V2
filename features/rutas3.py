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
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas

from algorithms.algoritmo22 import (
    optimizar_ruta_algoritmo22,
    cargar_pedidos,
    _crear_data_model,
    agrupar_puntos_aglomerativo,
    MARGEN,
)
from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

COCHERA = {
    "lat": -16.4141434959913,
    "lon": -71.51839574233342,
    "direccion": "Cochera",
    "hora": "08:00",
}

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def optimizar_ruta_placeholder(data, tiempo_max_seg=60):
    return None

ALG_MAP = {
    "Algoritmo 1 - PCA - GLS": optimizar_ruta_algoritmo22,
    "Algoritmo 2": optimizar_ruta_placeholder,
    "Algoritmo 3": optimizar_ruta_placeholder,
    "Algoritmo 4": optimizar_ruta_algoritmo4,
}

def _hora_a_segundos(hhmm: str) -> int | None:
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
    h = segs // 3600
    m = (segs % 3600) // 60
    return f"{h:02}:{m:02}"

def _ventana_extendida(row: pd.Series) -> str:
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

    # reset state on change
    if (st.session_state.get("fecha_actual") != fecha or
        st.session_state.get("algoritmo_actual") != algoritmo):
        for k in ["res","df_clusters","df_etiquetado","df_final","df_ruta","solve_t"]:
            st.session_state[k] = None
        st.session_state["leg_0"] = 0
        st.session_state["fecha_actual"] = fecha
        st.session_state["algoritmo_actual"] = algoritmo

    # compute route
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        df_original = pd.DataFrame(pedidos)
        df_clusters, df_et = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_et.copy()

        DEP = {
            "id":"DEP","operacion":"Depósito","nombre_cliente":"Depósito",
            "direccion":"Planta Lavandería","lat":-16.40904,"lon":-71.53745,
            "time_start":"08:00","time_end":"18:00","demand":0
        }
        df_final = pd.concat([pd.DataFrame([DEP]), df_clusters], ignore_index=True)
        st.session_state["df_final"] = df_final.copy()

        data = _crear_data_model(df_final, vehiculos=1)
        alg_fn = ALG_MAP[algoritmo]
        t0 = tiempo.time()
        res = alg_fn(data, tiempo_max_seg=60)
        st.session_state["solve_t"] = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return
        st.session_state["res"] = res

        ruta = res["routes"][0]["route"]
        arr   = res["routes"][0]["arrival_sec"]
        df_r = df_final.loc[ruta, ["nombre_cliente","direccion","time_start","time_end"]].copy()
        df_r["ventana_con_margen"] = df_r.apply(_ventana_extendida, axis=1)
        df_r["ETA"]   = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

    # prepare display table with Cochera before Depósito
    df_r = st.session_state["df_ruta"]
    filas = []
    # Cochera
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
    # Depósito
    dep = df_r[df_r["orden"]==0].iloc[0]
    filas.append({
        "orden": 1,
        "nombre_cliente": dep["nombre_cliente"],
        "direccion": dep["direccion"],
        "ventana_con_margen": dep["ventana_con_margen"],
        "ETA": dep["ETA"]
    })
    # rest +1
    for _, row in df_r[df_r["orden"]>=1].sort_values("orden").iterrows():
        filas.append({
            "orden": int(row["orden"])+1,
            "nombre_cliente": row["nombre_cliente"],
            "direccion": row["direccion"],
            "ventana_con_margen": row["ventana_con_margen"],
            "ETA": row["ETA"]
        })

    df_display = pd.DataFrame(filas).sort_values("orden").reset_index(drop=True)
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_display, use_container_width=True)

    # tabs
    tab1, tab2 = st.tabs(["🚀 Tramo actual","ℹ️ Info general"])
    df_f = st.session_state["df_final"]
    df_et = st.session_state["df_etiquetado"]
    res  = st.session_state["res"]
    ruta = res["routes"][0]["route"]
    leg  = st.session_state["leg_0"]
    L = len(ruta)
    total_legs = (L - 1) + 2

    with tab1:
        if leg > total_legs:
            st.success("✅ Ruta completada")
            return
        # compute origin/dest per leg...
        # <igual que antes>
        pass

    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta (via API)")
        # build directions API request
        origin = f"{COCHERA['lat']},{COCHERA['lon']}"
        depot_idx = ruta[0]
        depot = f"{df_f.loc[depot_idx,'lat']},{df_f.loc[depot_idx,'lon']}"
        waypoints = [depot] + [f"{df_f.loc[i,'lat']},{df_f.loc[i,'lon']}" for i in ruta[1:]] + [depot]
        destination = origin

        directions = gmaps.directions(
            origin,
            destination,
            mode="driving",
            departure_time=datetime.now(),
            optimize_waypoints=False,
            waypoints=waypoints
        )

        # decode entire path
        overview = directions[0]["overview_polyline"]["points"]
        path = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]

        # compute metrics
        total_m = sum(leg_obj["distance"]["value"] for leg_obj in directions[0]["legs"])
        total_s = sum(leg_obj["duration"]["value"] for leg_obj in directions[0]["legs"])

        # draw map
        m = folium.Map(location=path[0], zoom_start=13)
        folium.PolyLine(path, weight=4, opacity=0.7).add_to(m)

        # markers at fixed stops (not path points)
        # Cochera
        folium.Marker(
            location=(COCHERA["lat"],COCHERA["lon"]),
            popup="Cochera",
            tooltip="Cochera",
            icon=folium.Icon(color="purple",icon="building",prefix="fa")
        ).add_to(m)
        # Depósito
        folium.Marker(
            location=(df_f.loc[ruta[0],"lat"],df_f.loc[ruta[0],"lon"]),
            popup="Planta Lavandería",
            tooltip="Depósito: Planta Lavandería",
            icon=folium.Icon(color="green",icon="home",prefix="fa")
        ).add_to(m)
        # Clientes
        for idx in ruta[1:]:
            lat, lon = df_f.loc[idx,["lat","lon"]]
            nombre = df_f.loc[idx,"nombre_cliente"]
            direccion = df_f.loc[idx,"direccion"]
            folium.Marker(
                location=(lat,lon),
                popup=f"{nombre}<br>{direccion}",
                tooltip=nombre,
                icon=folium.Icon(color="orange",icon="flag",prefix="fa")
            ).add_to(m)
        # return Cochera
        folium.Marker(
            location=(COCHERA["lat"],COCHERA["lon"]),
            popup="Cochera",
            tooltip="Cochera",
            icon=folium.Icon(color="purple",icon="building",prefix="fa")
        ).add_to(m)

        # pedidos individuales en rojo
        for _, row in df_et.iterrows():
            folium.CircleMarker(
                location=(row["lat"],row["lon"]),
                radius=4, color="red", fill=True, fill_opacity=0.7
            ).add_to(m)

        st_folium(m, width=700, height=500)

        # metrics
        st.markdown("## 🔍 Métricas de la ruta real")
        st.markdown(f"- Distancia total (Driving): **{total_m/1000:.2f} km**")
        st.markdown(f"- Duración estimada (Driving): **{total_s//60:.0f} min**")
