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

# Coordenadas fijas
COCHERA = {"lat": -16.4141434959913, "lon": -71.51839574233342, "direccion": "Cochera"}

# Cliente de Google Maps
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

def optimizar_ruta_placeholder(data, tiempo_max_seg=60):
    return None

ALG_MAP = {
    "Algoritmo 1 - PCA - GLS": optimizar_ruta_algoritmo22,
    "Algoritmo 2": optimizar_ruta_placeholder,
    "Algoritmo 3": optimizar_ruta_placeholder,
    "Algoritmo 4": optimizar_ruta_algoritmo4,
}

# — Utilidades hora/ventana —
def _hora_a_segundos(hhmm: str) -> int | None:
    if not isinstance(hhmm, str): return None
    parts = hhmm.split(":")
    if len(parts) < 2: return None
    try:
        h, m = int(parts[0]), int(parts[1])
        return h*3600 + m*60
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
    fin_m = min(24*3600, fin + MARGEN)
    return f"{_segundos_a_hora(ini_m)} - {_segundos_a_hora(fin_m)}"

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", datetime.now().date())
    with c2:
        algoritmo = st.selectbox("Algoritmo", list(ALG_MAP.keys()))

    # Reset estado si cambia fecha/algoritmo
    if (st.session_state.get("fecha_actual") != fecha or
        st.session_state.get("algoritmo_actual") != algoritmo):
        for k in ["res","df_clusters","df_etiquetado","df_final","df_ruta","solve_t"]:
            st.session_state[k] = None
        st.session_state["leg_0"] = 0
        st.session_state["fecha_actual"] = fecha
        st.session_state["algoritmo_actual"] = algoritmo

    # Calcular ruta si nada en sesión
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        df_original = pd.DataFrame(pedidos)
        df_clusters, df_et = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_et.copy()

        # DEPÓSITO
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
        df_r["ETA"] = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

    # Mostrar orden de visita
    df_f = st.session_state["df_final"]
    df_r = st.session_state["df_ruta"]
    L = len(ruta := st.session_state["res"]["routes"][0]["route"])
    # Preparamos display sin tocar el df_r original
    df_disp = df_r[["orden","nombre_cliente","direccion","ventana_con_margen","ETA"]].copy()
    df_disp = df_disp.sort_values("orden").reset_index(drop=True)
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_disp, use_container_width=True)

    # Pestañas
    tab1, tab2 = st.tabs(["🚀 Tramo actual","ℹ️ Info general"])
    res = st.session_state["res"]
    df_et = st.session_state["df_etiquetado"]
    leg = st.session_state["leg_0"]

    # Número total de tramos extendidos = original segments + 3
    total_tramos = (L - 1) + 3  # = L+2

    with tab1:
        if leg >= total_tramos:
            st.success("✅ Ruta completada: De vuelta a la cochera")
            return

        # Definir origen/destino según tramo
        if leg == 0:
            # Cochera -> Depósito
            orig_coords = (COCHERA["lat"], COCHERA["lon"])
            dest_idx = ruta[0]
            dest_coords = (df_f.loc[dest_idx,"lat"], df_f.loc[dest_idx,"lon"])
            nombre_dest = df_f.loc[dest_idx,"nombre_cliente"]
            direccion_dest = df_f.loc[dest_idx,"direccion"]
            ETA_dest = df_r.loc[df_r["orden"]==0,"ETA"].iloc[0]
        elif 1 <= leg <= L-1:
            # segmentos originales: deposit/c_i -> c_{i+1}
            idx_o = ruta[leg-1]
            idx_d = ruta[leg]
            orig_coords = (df_f.loc[idx_o,"lat"], df_f.loc[idx_o,"lon"])
            dest_coords = (df_f.loc[idx_d,"lat"], df_f.loc[idx_d,"lon"])
            nombre_dest = df_f.loc[idx_d,"nombre_cliente"]
            direccion_dest = df_f.loc[idx_d,"direccion"]
            ETA_dest = df_r.loc[df_r["orden"]==leg,"ETA"].iloc[0]
        elif leg == L:
            # Último cliente -> Depósito
            idx_o = ruta[L-1]
            orig_coords = (df_f.loc[idx_o,"lat"], df_f.loc[idx_o,"lon"])
            dest_idx = ruta[0]
            dest_coords = (df_f.loc[dest_idx,"lat"], df_f.loc[dest_idx,"lon"])
            nombre_dest = df_f.loc[dest_idx,"nombre_cliente"]
            direccion_dest = df_f.loc[dest_idx,"direccion"]
            ETA_dest = "—"
        else:  # leg == L+1
            # Depósito -> Cochera
            orig_coords = (df_f.loc[ruta[0],"lat"], df_f.loc[ruta[0],"lon"])
            dest_coords = (COCHERA["lat"], COCHERA["lon"])
            nombre_dest = COCHERA["direccion"]
            direccion_dest = COCHERA["direccion"]
            ETA_dest = "—"

        # Mostrar próximo tramo
        st.markdown(
            f"### Próximo → **{nombre_dest}**  \n"
            f"📍 {direccion_dest} (ETA {ETA_dest})",
            unsafe_allow_html=True
        )
        if st.button(f"✅ Llegué a {nombre_dest}"):
            st.session_state["leg_0"] += 1
            st.rerun()

        # Trazar en el mapa
        try:
            dirs = gmaps.directions(
                f"{orig_coords[0]},{orig_coords[1]}",
                f"{dest_coords[0]},{dest_coords[1]}",
                mode="driving",
                departure_time=datetime.now(),
                traffic_model="best_guess"
            )
            leg0 = dirs[0]["legs"][0]
            tiempo_traffic = leg0.get("duration_in_traffic", leg0["duration"])["text"]
            poly = decode_polyline(dirs[0]["overview_polyline"]["points"])
            segmento = [(p["lat"], p["lng"]) for p in poly]
        except:
            tiempo_traffic = None
            segmento = [orig_coords, dest_coords]

        m = folium.Map(location=segmento[0], zoom_start=14)
        folium.PolyLine(segmento, weight=5, opacity=0.8,
                        tooltip=f"⏱ {tiempo_traffic}" if tiempo_traffic else None
        ).add_to(m)
        folium.Marker(segmento[0], icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
        folium.Marker(segmento[-1], icon=folium.Icon(color="blue", icon="flag", prefix="fa")).add_to(m)
        st_folium(m, width=700, height=400)

    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta")
        coords = []
        # inicial: cochera
        coords.append((COCHERA["lat"], COCHERA["lon"]))
        # depósito
        coords.append((df_f.loc[ruta[0],"lat"], df_f.loc[ruta[0],"lon"]))
        # clientes
        for idx in ruta[1:]:
            coords.append((df_f.loc[idx,"lat"], df_f.loc[idx,"lon"]))
        # retorno: depósito y cochera
        coords.append((df_f.loc[ruta[0],"lat"], df_f.loc[ruta[0],"lon"]))
        coords.append((COCHERA["lat"], COCHERA["lon"]))

        m = folium.Map(location=coords[0], zoom_start=13)
        folium.PolyLine(coords, weight=4, opacity=0.7).add_to(m)

        # Marcadores
        folium.Marker(coords[0], popup="Cochera", icon=folium.Icon(color="purple", icon="building", prefix="fa")).add_to(m)
        folium.Marker(coords[1], popup="Depósito", icon=folium.Icon(color="green", icon="home", prefix="fa")).add_to(m)

        for i, idx in enumerate(ruta[1:], start=2):
            folium.Marker(
                coords[i],
                popup=f"{df_f.loc[idx,'nombre_cliente']}<br>{df_f.loc[idx,'direccion']}",
                icon=folium.Icon(color="orange", icon="flag", prefix="fa")
            ).add_to(m)

        folium.Marker(coords[-2], popup="Depósito", icon=folium.Icon(color="green", icon="home", prefix="fa")).add_to(m)
        folium.Marker(coords[-1], popup="Cochera", icon=folium.Icon(color="purple", icon="building", prefix="fa")).add_to(m)

        # puntos individuales en rojo
        for _, row in df_et.iterrows():
            folium.CircleMarker(
                location=(row["lat"], row["lon"]),
                radius=4, color="red", fill=True, fill_opacity=0.7
            ).add_to(m)

        st_folium(m, width=700, height=500)

        # Métricas finales
        st.markdown("## 🔍 Métricas Finales")
        st.markdown(f"- Kilometraje total: **{res['distance_total_m']/1000:.2f} km**")
        st.markdown(f"- Tiempo de cómputo: **{st.session_state['solve_t']:.2f} s**")
        tiempo_total_min = (max(res["routes"][0]["arrival_sec"]) - 9*3600)/60
        st.markdown(f"- Tiempo estimado total: **{tiempo_total_min:.2f} min**")
        st.markdown(f"- Puntos visitados: **{len(ruta)}**")
