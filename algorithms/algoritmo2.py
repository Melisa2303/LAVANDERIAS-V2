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

# Importamos los optimizadores
from algorithms.algoritmo22 import (
    optimizar_ruta_algoritmo22,
    cargar_pedidos,
    _crear_data_model,
    agrupar_puntos_aglomerativo,
    MARGEN,
)
from algorithms.algoritmo2 import optimizar_ruta_cw_tabu
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
    "Algoritmo 2 - CW + Tabu Search": optimizar_ruta_cw_tabu,
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
        h, m = map(int, parts[:2])
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

    # Resetear el estado si cambian fecha o algoritmo
    if (st.session_state.get("fecha_actual") != fecha or
        st.session_state.get("algoritmo_actual") != algoritmo):
        for k in ["res","df_clusters","df_etiquetado","df_final","df_ruta","solve_t"]:
            st.session_state[k] = None
        st.session_state["leg_0"] = 0
        st.session_state["fecha_actual"] = fecha
        st.session_state["algoritmo_actual"] = algoritmo

    # Si aún no hemos resuelto
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        # 1) Agrupar con Agglomerative Clustering
        df_original = pd.DataFrame(pedidos)
        df_clusters, df_et = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_et.copy()

        # 2) Depósito (Planta)
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

        # 3) Crear modelo y resolver VRP
        data = _crear_data_model(df_final, vehiculos=1)
        alg_fn = ALG_MAP[algoritmo]
        t0 = tiempo.time()
        res = alg_fn(data, tiempo_max_seg=60)
        st.session_state["solve_t"] = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res

        # 4) --- Aquí aplanamos TODAS las rutas que devuelve el algoritmo ---
        all_nodes    = []
        all_arrivals = []
        for r in res["routes"]:
            all_nodes    += r["route"]
            all_arrivals += r["arrival_sec"]

        # Eliminamos repeticiones, pero conservamos orden
        seen = set()
        flat_nodes    = []
        flat_arrivals = []
        for node, t in zip(all_nodes, all_arrivals):
            if node not in seen:
                flat_nodes.append(node)
                flat_arrivals.append(t)
                seen.add(node)

        # 5) Montamos el DataFrame intermedio con nombres y ventanas
        df_r = df_final.loc[flat_nodes, ["nombre_cliente","direccion","time_start","time_end"]].copy()
        df_r["ventana_con_margen"] = df_r.apply(_ventana_extendida, axis=1)
        df_r["ETA"]   = [ _segundos_a_hora(t) for t in flat_arrivals ]
        df_r["orden"] = range(len(flat_nodes))
        st.session_state["df_ruta"] = df_r.copy()

    # ==== Construir la tabla de salida con Cochera al inicio y al final ====
    df_r = st.session_state["df_ruta"]
    filas = []

    # Ventana de Cochera
    vent_coch = _ventana_extendida(pd.Series({
        "time_start": COCHERA["hora"],
        "time_end":   COCHERA["hora"]
    }))

    # 1) Cochera (inicio)
    filas.append({
        "orden": 0,
        "nombre_cliente": COCHERA["direccion"],
        "direccion": COCHERA["direccion"],
        "ventana_con_margen": vent_coch,
        "ETA": COCHERA["hora"]
    })

    # 2) Primer nodo de VRP (depósito)
    dep = df_r.iloc[0]
    filas.append({
        "orden": 1,
        "nombre_cliente": dep["nombre_cliente"],
        "direccion": dep["direccion"],
        "ventana_con_margen": dep["ventana_con_margen"],
        "ETA": dep["ETA"]
    })

    # 3) El resto de paradas
    for _, row in df_r.iloc[1:].iterrows():
        filas.append({
            "orden": int(row["orden"]) + 1,
            "nombre_cliente": row["nombre_cliente"],
            "direccion": row["direccion"],
            "ventana_con_margen": row["ventana_con_margen"],
            "ETA": row["ETA"]
        })

    # 4) Cochera (final)
    ultima_arrival = flat_arrivals[-1]
    final_eta      = _segundos_a_hora(ultima_arrival)
    filas.append({
        "orden": len(flat_nodes) + 1,
        "nombre_cliente": COCHERA["direccion"],
        "direccion": COCHERA["direccion"],
        "ventana_con_margen": vent_coch,
        "ETA": final_eta
    })

    df_display = pd.DataFrame(filas).sort_values("orden").reset_index(drop=True)

    # === Mostrar tabla de visitas ===
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_display, use_container_width=True)

    # === Pestañas: Tramo actual / Info general ===
    tab1, tab2 = st.tabs(["🚀 Tramo actual","ℹ️ Info general"])
    df_f  = st.session_state["df_final"]
    df_et = st.session_state["df_etiquetado"]
    res   = st.session_state["res"]
    ruta  = res["routes"][0]["route"]  # para tramos intermedios seguimos con la ruta 0
    leg   = st.session_state["leg_0"]
    L     = len(ruta)

    # — Tramo actual —
    with tab1:
        if leg >= L + 1:
            st.success("✅ Ruta completada")
            return

        # Definir origen/destino para el botón y el mapa
        if leg == 0:
            orig = (COCHERA["lat"], COCHERA["lon"])
            dest_idx = ruta[0]
            ETA_dest = df_display.loc[df_display["orden"] == 1, "ETA"].iloc[0]
            nombre_dest = df_f.loc[dest_idx,"nombre_cliente"]
            dest = (df_f.loc[dest_idx,"lat"], df_f.loc[dest_idx,"lon"])
        elif 1 <= leg < L:
            idx_o = ruta[leg - 1]
            idx_d = ruta[leg]
            orig = (df_f.loc[idx_o,"lat"], df_f.loc[idx_o,"lon"])
            dest = (df_f.loc[idx_d,"lat"], df_f.loc[idx_d,"lon"])
            ETA_dest = df_display.loc[df_display["orden"] == leg + 1, "ETA"].iloc[0]
            nombre_dest = df_f.loc[idx_d,"nombre_cliente"]
        else:
            # Último tramo de depósito → cochera
            idx_o = ruta[-1]
            orig = (df_f.loc[idx_o,"lat"], df_f.loc[idx_o,"lon"])
            dest = (COCHERA["lat"], COCHERA["lon"])
            ETA_dest = "—"
            nombre_dest = COCHERA["direccion"]

        st.markdown(
            f"### Próximo → **{nombre_dest}**  \n"
            f"📍 {dest[0]:.6f},{dest[1]:.6f} (ETA {ETA_dest})",
            unsafe_allow_html=True
        )
        if st.button(f"✅ Llegué a {nombre_dest}"):
            st.session_state["leg_0"] += 1
            st.rerun()

        # Dibujar tramo en Folium
        try:
            directions = gmaps.directions(
                f"{orig[0]},{orig[1]}",
                f"{dest[0]},{dest[1]}",
                mode="driving",
                departure_time=datetime.now(),
                traffic_model="best_guess"
            )
            leg0 = directions[0]["legs"][0]
            tiempo_traffic = leg0.get("duration_in_traffic", leg0["duration"])["text"]
            overview = directions[0]["overview_polyline"]["points"]
            segmento = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]
        except:
            tiempo_traffic = None
            segmento = [orig, dest]

        m = folium.Map(location=segmento[0], zoom_start=14)
        folium.PolyLine(segmento, weight=5, opacity=0.8,
                        tooltip=f"⏱ {tiempo_traffic}" if tiempo_traffic else None
        ).add_to(m)
        folium.Marker(segmento[0], icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
        folium.Marker(segmento[-1], icon=folium.Icon(color="blue", icon="flag", prefix="fa")).add_to(m)
        st_folium(m, width=700, height=400)

    # — Info general: mapa completo + métricas —
    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta (via API)")
        origin      = f"{COCHERA['lat']},{COCHERA['lon']}"
        depot_idx   = ruta[0]
        depot       = f"{df_f.loc[depot_idx,'lat']},{df_f.loc[depot_idx,'lon']}"
        waypoints   = [depot] + [f"{df_f.loc[i,'lat']},{df_f.loc[i,'lon']}" for i in ruta[1:]] + [depot]
        directions  = gmaps.directions(
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
        folium.Marker((COCHERA["lat"],COCHERA["lon"]), popup="Cochera", tooltip="Cochera",
                      icon=folium.Icon(color="purple",icon="building",prefix="fa")).add_to(m)
        folium.Marker((df_f.loc[depot_idx,"lat"],df_f.loc[depot_idx,"lon"]),
                      popup="Planta Lavandería", tooltip="Depósito",
                      icon=folium.Icon(color="green",icon="home",prefix="fa")).add_to(m)
        for idx in ruta[1:]:
            lat, lon = df_f.loc[idx,["lat","lon"]]
            nombre   = df_f.loc[idx,"nombre_cliente"]
            folium.Marker((lat,lon), popup=nombre, tooltip=nombre,
                          icon=folium.Icon(color="orange",icon="flag",prefix="fa")).add_to(m)
        folium.Marker((COCHERA["lat"],COCHERA["lon"]), popup="Cochera", tooltip="Cochera",
                      icon=folium.Icon(color="purple",icon="building",prefix="fa")).add_to(m)

        for _, row in df_et.iterrows():
            folium.CircleMarker((row["lat"],row["lon"]), radius=4,
                                color="red", fill=True, fill_opacity=0.7).add_to(m)

        st_folium(m, width=700, height=500)

        # Métricas de la ruta real (API)
        st.markdown("## 🔍 Métricas de la ruta real")
        st.markdown(f"- Distancia total (Driving): **{total_m/1000:.2f} km**")
        st.markdown(f"- Duración estimada (Driving): **{total_s//60:.0f} min**")

        # Métricas finales del VRP
        st.markdown("## 🔍 Métricas Finales")
        st.markdown(f"- Kilometraje total (VRP): **{res['distance_total_m']/1000:.2f} km**")
        st.markdown(f"- Tiempo de cómputo: **{st.session_state['solve_t']:.2f} s**")
        tiempo_total_min = (max(flat_arrivals) - SHIFT_START_SEC) / 60
        st.markdown(f"- Tiempo estimado total: **{tiempo_total_min:.2f} min**")
        st.markdown(f"- Puntos visitados: **{len(flat_nodes)}**")
