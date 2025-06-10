import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
import requests  # Importar requests A
from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
from datetime import datetime, timedelta, time
import time as tiempo
import googlemaps
from core.firebase import db, obtener_sucursales
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas
#from algorithms.algoritmo1 import optimizar_ruta_algoritmo1, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix
from algorithms.algoritmo22 import optimizar_ruta_algoritmo22, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix , agrupar_puntos_aglomerativo
#from algorithms.algoritmo3 import optimizar_ruta_algoritmo3
#from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


# ===================== PÁGINA “Ver Ruta Optimizada” =====================

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")

    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        algoritmo = st.selectbox("Seleccionar Algoritmo", ["Algoritmo 1", "Algoritmo 2", "Algoritmo 3", "Algoritmo 4"])

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

    # Solo recalcular si aún no lo hemos hecho para esta sesión
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, "Todos")  # Asumimos que quieres todos los pedidos
        if not pedidos:
            st.info("No hay pedidos para esa fecha.")
            return

        df_original = pd.DataFrame(pedidos)
        df_clusters, df_etiquetado = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"] = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_etiquetado.copy()

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

        data = _crear_data_model(df_final, vehiculos=1, capacidad_veh=None)

        t0 = tiempo.time()
        if algoritmo == "Algoritmo 1":
            res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        elif algoritmo == "Algoritmo 2":
            res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        elif algoritmo == "Algoritmo 3":
            res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        else:
            res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        solve_t = tiempo.time() - t0

        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res

        ruta = res["routes"][0]["route"]
        arr = res["routes"][0]["arrival_sec"]

        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ETA"] = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

        if not st.session_state["ruta_guardada"]:
            doc = {
                "fecha": fecha.strftime("%Y-%m-%d"),
                "algoritmo": algoritmo,
                "creado_en": firestore.SERVER_TIMESTAMP,
                "vehiculos": 1,
                "distancia_total_m": res["distance_total_m"],
                "paradas": []
            }
            for idx, n in enumerate(ruta):
                doc["paradas"].append({
                    "orden": idx,
                    "pedidoId": df_final.loc[n, "id"],
                    "nombre": df_final.loc[n, "nombre_cliente"],
                    "direccion": df_final.loc[n, "direccion"],
                    "lat": df_final.loc[n, "lat"],
                    "lon": df_final.loc[n, "lon"],
                    "ETA": datetime.utcfromtimestamp(arr[idx]).strftime("%H:%M")
                })
            db.collection("rutas").add(doc)
            st.session_state["ruta_guardada"] = True

        # Métricas completas
        st.write("### 📊 Métricas del recorrido")
        st.metric("⏱️ Tiempo de cómputo", f"{solve_t:.2f} s")
        st.metric("📏 Distancia total (km)", f"{res['distance_total_m'] / 1000:.2f}")
        tiempo_total_ruta_min = (arr[-1] - arr[0]) / 60
        st.metric("🕒 Tiempo total estimado (min)", f"{tiempo_total_ruta_min:.1f}")
        st.metric("🗺️ Puntos totales visitados", len(ruta))

    # -------------------- MOSTRAR TABLA Y MAPA --------------------
    df_r = st.session_state["df_ruta"]
    df_f = st.session_state["df_final"]
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

    # Mostrar mapa completo con todas las rutas en pestaña Info
    t1, t2 = st.tabs(["🗺 Tramo", "ℹ️ Mapa Completo"])
    with t1:
        # Tramo actual
        n_origen = ruta[leg]
        n_dest = ruta[leg + 1]
        nombre_dest = df_f.loc[n_dest, "nombre_cliente"]
        direccion_dest = df_f.loc[n_dest, "direccion"]
        ETA_dest = df_r.loc[df_r["orden"] == leg + 1, "ETA"].values[0]

        st.markdown(f"### Próximo → **{nombre_dest}** (ETA {ETA_dest})")
        if st.button(f"Ya llegué a {nombre_dest}"):
            st.session_state["leg_0"] += 1
            st.rerun()

        orig = f"{df_f.loc[n_origen, 'lat']},{df_f.loc[n_origen, 'lon']}"
        dest = f"{df_f.loc[n_dest, 'lat']},{df_f.loc[n_dest, 'lon']}"
        directions = gmaps.directions(orig, dest, mode="driving", departure_time=datetime.now(), traffic_model="best_guess")
        overview = directions[0]["overview_polyline"]["points"]
        segmento = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]

        m = folium.Map(location=segmento[0], zoom_start=14)
        folium.PolyLine(segmento, color="blue", weight=5).add_to(m)
        st_folium(m, width=700, height=400)

    with t2:
        # Mapa completo
        m_all = folium.Map(location=[df_f.loc[ruta[0], "lat"], df_f.loc[ruta[0], "lon"]], zoom_start=13)
        for i in range(len(ruta) - 1):
            orig = f"{df_f.loc[ruta[i], 'lat']},{df_f.loc[ruta[i], 'lon']}"
            dest = f"{df_f.loc[ruta[i+1], 'lat']},{df_f.loc[ruta[i+1], 'lon']}"
            directions = gmaps.directions(orig, dest, mode="driving", departure_time=datetime.now(), traffic_model="best_guess")
            overview = directions[0]["overview_polyline"]["points"]
            segmento = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]
            folium.PolyLine(segmento, color="blue", weight=4).add_to(m_all)
        st_folium(m_all, width=700, height=500)
