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

# ─── Coordenadas y hora de la Cochera ───
COCHERA = {
    "lat": -16.4141434959913,
    "lon": -71.51839574233342,
    "direccion": "Cochera",
    "hora": "08:00",
}

# Inicializar cliente Google Maps
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


# ─── Utilidades para hora y ventana extendida ───

def _hora_a_segundos(hhmm: str) -> int | None:
    """Convierte 'HH:MM' o 'HH:MM:SS' a segundos desde medianoche."""
    if not isinstance(hhmm, str):
        return None
    parts = hhmm.split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        return h * 3600 + m * 60
    except:
        return None


def _segundos_a_hora(segs: int) -> str:
    """Convierte segundos desde medianoche a 'HH:MM'."""
    h = segs // 3600
    m = (segs % 3600) // 60
    return f"{h:02}:{m:02}"


def _ventana_extendida(ts_row: pd.Series) -> str:
    """Calcula la ventana time_start–time_end extendida ±MARGEN."""
    ini = _hora_a_segundos(ts_row["time_start"])
    fin = _hora_a_segundos(ts_row["time_end"])
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

    # Reiniciar estado si cambia fecha o algoritmo
    if (st.session_state.get("fecha_actual") != fecha or
        st.session_state.get("algoritmo_actual") != algoritmo):
        for k in ["res", "df_clusters", "df_etiquetado", "df_final", "df_ruta", "solve_t"]:
            st.session_state[k] = None
        st.session_state["leg_0"] = 0
        st.session_state["fecha_actual"] = fecha
        st.session_state["algoritmo_actual"] = algoritmo

    # Calcular la ruta optimizada si no existe
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        # Clustering de pedidos
        df_original = pd.DataFrame(pedidos)
        df_clusters, df_etiquetado = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_etiquetado.copy()

        # Punto depósito (Planta)
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

        # Preparar y resolver VRP
        data = _crear_data_model(df_final, vehiculos=1)
        alg_fn = ALG_MAP[algoritmo]
        t0 = tiempo.time()
        res = alg_fn(data, tiempo_max_seg=60)
        st.session_state["solve_t"] = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res

        # Construir DataFrame de ruta con ventana y ETA
        ruta = res["routes"][0]["route"]
        arr   = res["routes"][0]["arrival_sec"]
        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ventana_con_margen"] = df_r.apply(_ventana_extendida, axis=1)
        df_r["ETA"]   = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

    # Preparamos la tabla de orden de visita, insertando Cochera antes del Depósito
    df_r = st.session_state["df_ruta"]
    filas = []

    # 1) Cochera (orden 0)
    ventana_cochera = _ventana_extendida(pd.Series({
        "time_start": COCHERA["hora"],
        "time_end":   COCHERA["hora"]
    }))
    filas.append({
        "orden": 0,
        "nombre_cliente": COCHERA["direccion"],
        "direccion": COCHERA["direccion"],
        "ventana_con_margen": ventana_cochera,
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

    # 3) Resto de paradas (desplazadas +1)
    for _, row in df_r[df_r["orden"] >= 1].sort_values("orden").iterrows():
        filas.append({
            "orden": int(row["orden"]) + 1,
            "nombre_cliente": row["nombre_cliente"],
            "direccion": row["direccion"],
            "ventana_con_margen": row["ventana_con_margen"],
            "ETA": row["ETA"]
        })

    df_display = pd.DataFrame(filas).sort_values("orden").reset_index(drop=True)

    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(df_display, use_container_width=True)

    # ─── Pestañas: tramo actual y mapa general ───
    tab1, tab2 = st.tabs(["🚀 Tramo actual", "ℹ️ Info general"])
    df_f = st.session_state["df_final"]
    df_et = st.session_state["df_etiquetado"]
    res  = st.session_state["res"]
    ruta = res["routes"][0]["route"]
    leg  = st.session_state["leg_0"]

    # Total de legs: Cochera→Depósito + (DEP→C1, C1→C2… CL→CL+1) + CL→Cochera
    L = len(ruta)
    total_legs = (L - 1) + 2  # (DEP→C1…C(L-1)→CL) más Cochera→DEP y CL→Cochera

    with tab1:
        if leg > total_legs:
            st.success("✅ Ruta completada")
            return

        # Definir coordenadas de origen y destino según el leg actual
        if leg == 0:
            # Cochera → Depósito
            orig = (COCHERA["lat"], COCHERA["lon"])
            dest_idx = ruta[0]
            dest = (df_f.loc[dest_idx, "lat"], df_f.loc[dest_idx, "lon"])
            nombre_dest = df_f.loc[dest_idx, "nombre_cliente"]
            ETA_dest = df_r.loc[df_r["orden"] == 0, "ETA"].iloc[0]
        elif 1 <= leg < L:
            # DEP → C1, C1→C2, etc.
            idx_o = ruta[leg - 1]
            idx_d = ruta[leg]
            orig = (df_f.loc[idx_o, "lat"], df_f.loc[idx_o, "lon"])
            dest = (df_f.loc[idx_d, "lat"], df_f.loc[idx_d, "lon"])
            nombre_dest = df_f.loc[idx_d, "nombre_cliente"]
            ETA_dest = df_r.loc[df_r["orden"] == leg, "ETA"].iloc[0]
        elif leg == L:
            # Último cliente → Cochera
            idx_o = ruta[L - 1]
            orig = (df_f.loc[idx_o, "lat"], df_f.loc[idx_o, "lon"])
            dest = (COCHERA["lat"], COCHERA["lon"])
            nombre_dest = COCHERA["direccion"]
            ETA_dest = "—"
        else:
            st.success("✅ Ruta completada")
            return

        # Mostrar info del próximo tramo
        st.markdown(
            f"### Próximo → **{nombre_dest}**  \n"
            f"📍 {dest[0]:.6f},{dest[1]:.6f} (ETA {ETA_dest})",
            unsafe_allow_html=True
        )
        if st.button(f"✅ Llegué a {nombre_dest}"):
            st.session_state["leg_0"] += 1
            st.rerun()

        # Dibujar tramo en el mapa
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

        # Mapa completo e info general
    with tab2:
        st.subheader("🗺️ Mapa de toda la ruta")
        coords_final = [(df_f.loc[i, "lat"], df_f.loc[i, "lon"]) for i in ruta]
        m = folium.Map(location=coords_final[0], zoom_start=13)
        folium.PolyLine(coords_final, weight=4, opacity=0.7).add_to(m)

        # Depósito
        folium.Marker(
            coords_final[0],
            popup="Depósito",
            icon=folium.Icon(color="green", icon="home", prefix="fa")
        ).add_to(m)

        # Marcadores de clientes con ventana en popup
        for idx, (lat, lon) in enumerate(coords_final[1:], start=1):
            ventana = df_r.loc[df_r["orden"] == idx, "ventana_con_margen"].iloc[0]
            folium.Marker(
                (lat, lon),
                popup=(
                    f"{df_f.loc[ruta[idx],'nombre_cliente']}<br>"
                    f"{df_f.loc[ruta[idx],'direccion']}<br>"
                    f"Ventana: {ventana}"
                ),
                icon=folium.Icon(color="orange", icon="flag", prefix="fa")
            ).add_to(m)

        # Pedidos individuales
        for _, fila_p in df_et.iterrows():
            folium.CircleMarker(
                location=(fila_p["lat"], fila_p["lon"]),
                radius=4, color="red", fill=True, fill_opacity=0.7
            ).add_to(m)

        st_folium(m, width=700, height=500)

        # Métricas finales
        st.markdown("## 🔍 Métricas Finales")
        st.markdown(f"- Kilometraje total: **{res['distance_total_m']/1000:.2f} km**")
        st.markdown(f"- Tiempo de cómputo: **{st.session_state['solve_t']:.2f} s**")
        tiempo_total_min = (max(res['routes'][0]['arrival_sec']) - 9*3600) / 60
        st.markdown(f"- Tiempo estimado total: **{tiempo_total_min:.2f} min**")
        st.markdown(f"- Puntos visitados: **{len(ruta)}**")

