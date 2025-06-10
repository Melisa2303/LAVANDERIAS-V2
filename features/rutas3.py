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
from algorithms.algoritmo2 import optimizar_ruta_algoritmo22, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix , agrupar_puntos_aglomerativo
#from algorithms.algoritmo3 import optimizar_ruta_algoritmo3
#from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


# ===================== CARGAR PEDIDOS DESDE FIRESTORE =====================

@st.cache_data(ttl=300)
def cargar_pedidos(fecha, tipo):
    """
    Lee de Firestore las colecciones 'recogidas' filtradas por fecha de recojo/entrega
    y tipo de servicio. Retorna una lista de dict con los campos necesarios:
      - id, operacion, nombre_cliente, direccion, lat, lon, time_start, time_end, demand
    """
    col = db.collection('recogidas')
    docs = []
    # Todas las recogidas cuya fecha_recojo coincida
    docs += col.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()
    # Todas las recogidas cuya fecha_entrega coincida
    docs += col.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream()
    if tipo != "Todos":
        tf = "Sucursal" if tipo == "Sucursal" else "Cliente Delivery"
        docs = [d for d in docs if d.to_dict().get("tipo_solicitud") == tf]

    out = []
    for d in docs:
        data = d.to_dict()
        is_recojo = data.get("fecha_recojo") == fecha.strftime("%Y-%m-%d")
        op = "Recojo" if is_recojo else "Entrega"
        # Extraer coordenadas y dirección según tipo
        key_coord = f"coordenadas_{'recojo' if is_recojo else 'entrega'}"
        key_dir   = f"direccion_{'recojo' if is_recojo else 'entrega'}"
        coords = data.get(key_coord, {})
        lat, lon = coords.get("lat"), coords.get("lon")
        direccion = data.get(key_dir, "") or ""
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}", "")
        ts, te = (hs, hs) if hs else ("08:00", "18:00")
        out.append({
            "id":             d.id,
            "operacion":      op,
            "nombre_cliente": data.get("nombre_cliente", ""),
            "direccion":      direccion,
            "lat":            lat,
            "lon":            lon,
            "time_start":     ts,
            "time_end":       te,
            "demand":         1
        })
    return out

# ===================== PÁGINA “Ver Ruta Optimizada” =====================

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        tipo  = st.radio("Tipo Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)

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

    # Si aún no se resolvió para esta fecha/tipo, calculo todo
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, tipo)
        if not pedidos:
            st.info("No hay pedidos para esa fecha/tipo.")
            return

        # 1) DataFrame original con todos los pedidos (incluye 'direccion')
        df_original = pd.DataFrame(pedidos)

        # 2) Agrupo con AgglomerativeClustering (umbral 300 m)
        df_clusters, df_etiquetado = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"]  = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_etiquetado.copy()

        # 3) Construyo DataFrame final que voy a pasar al solver (DEPÓSITO + centroides)
        DEP = {
            "id":             "DEP",
            "operacion":      "Depósito",
            "nombre_cliente": "Depósito",
            "direccion":      "Planta Lavandería",
            "lat":            -16.40904,
            "lon":            -71.53745,
            "time_start":     "08:00",
            "time_end":       "18:00",
            "demand":         0
        }
        df_final = pd.concat([pd.DataFrame([DEP]), df_clusters], ignore_index=True)
        st.session_state["df_final"] = df_final.copy()

        # 4) Crear modelo de datos para VRPTW
        data = _crear_data_model(df_final, vehiculos=1, capacidad_veh=None)

        # 5) Resolver VRPTW
        t0 = tiempo.time()
        res = optimizar_ruta_algoritmo22(data, tiempo_max_seg=120)
        solve_t = tiempo.time() - t0
        if not res:
            st.error("😕 Sin solución factible. Usando aproximación euclidiana.")
            return

        st.session_state["res"] = res
        st.metric("⏱️ Tiempo de cómputo", f"{solve_t:.2f} s")
        st.metric("📏 Distancia total (km)", f"{res['distance_total_m'] / 1000:.2f}")

        # 6) Construir tabla de ruta optimizada incluyendo “direccion”
        ruta = res["routes"][0]["route"]
        arr   = res["routes"][0]["arrival_sec"]

        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ETA"]   = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

        # 7) Guardar ruta en Firestore (solo una vez)
        if not st.session_state["ruta_guardada"]:
            doc = {
                "fecha": fecha.strftime("%Y-%m-%d"),
                "tipo_servicio": tipo,
                "creado_en": firestore.SERVER_TIMESTAMP,
                "vehiculos": 1,
                "distancia_total_m": res["distance_total_m"],
                "paradas": []
            }
            for idx, n in enumerate(ruta):
                doc["paradas"].append({
                    "orden":    idx,
                    "pedidoId": df_final.loc[n, "id"],
                    "nombre":   df_final.loc[n, "nombre_cliente"],
                    "direccion": df_final.loc[n, "direccion"],
                    "lat":      df_final.loc[n, "lat"],
                    "lon":      df_final.loc[n, "lon"],
                    "ETA":      datetime.utcfromtimestamp(arr[idx]).strftime("%H:%M")
                })
            db.collection("rutas").add(doc)
            st.session_state["ruta_guardada"] = True

    # -------------------- MOSTRAR RESULTADOS --------------------

    df_r   = st.session_state["df_ruta"]
    df_f   = st.session_state["df_final"]      # depósito + centroides
    df_cl  = st.session_state["df_clusters"]   # sólo centroides
    df_et  = st.session_state["df_etiquetado"] # pedidos individuales (con columna 'cluster')
    res    = st.session_state["res"]
    ruta   = res["routes"][0]["route"]

    # 1) Mostrar la tabla con orden de visitas, incluyendo “direccion”
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(
        df_r[["orden", "ETA", "nombre_cliente", "direccion", "time_start", "time_end"]],
        use_container_width=True
    )

    # 2) Botón para reiniciar tramos
    if st.button("🔄 Reiniciar Tramos"):
        st.session_state["leg_0"] = 0

    leg = st.session_state["leg_0"]
    if leg >= len(ruta) - 1:
        st.success("✅ Todas las paradas completadas")
        return

    # Nodo de origen y destino del tramo actual
    n_origen = ruta[leg]
    n_dest   = ruta[leg + 1]
    nombre_dest   = df_f.loc[n_dest, "nombre_cliente"]
    direccion_dest = df_f.loc[n_dest, "direccion"]
    ETA_dest      = df_r.loc[df_r["orden"] == leg + 1, "ETA"].values[0]

    # Mostrar nombre y ETA, y agregar el botón con “Ya llegué a [nombre_dest]”
    st.markdown(f"### Próximo → **{nombre_dest}**<br>📍 {direccion_dest} (ETA {ETA_dest})",
                unsafe_allow_html=True)
    if st.button(f"Ya llegué a {nombre_dest}"):
        st.session_state["leg_0"] += 1
        st.rerun()

    # Construir lista de coordenadas en orden de ruta
    coords_final = [(df_f.loc[i, "lat"], df_f.loc[i, "lon"]) for i in ruta]

    # Intentar obtener segmento con Directions API (con tráfico)
    orig = f"{coords_final[leg][0]},{coords_final[leg][1]}"
    dest = f"{coords_final[leg+1][0]},{coords_final[leg+1][1]}"
    try:
        directions = gmaps.directions(
            orig, dest,
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
        segmento = [coords_final[leg], coords_final[leg+1]]

    # -------------------- MOSTRAR MAPA --------------------
    t1, t2 = st.tabs(["🗺 Tramo", "ℹ️ Info"])
    with t1:
        # 1) Crear mapa centrado en el punto de inicio del tramo
        m = folium.Map(location=segmento[0], zoom_start=14)

        # 2) Pintar todos los centroides de clusters (ÍNDICES >=1 en df_f) con icono naranja
        for idx_cluster, fila in df_f.iloc[1:].iterrows():
            folium.Marker(
                (fila["lat"], fila["lon"]),
                popup=(
                    f"<b>{fila['nombre_cliente']}</b><br>"
                    f"Dirección: {fila['direccion']}<br>"
                    f"Ventana: {fila['time_start']} - {fila['time_end']}<br>"
                    f"Demanda (nº pedidos): {fila['demand']}"
                ),
                icon=folium.Icon(color="orange", icon="users", prefix="fa")
            ).add_to(m)

        # 3) Pintar cada pedido individual (df_et) con CircleMarker gris,
        #    de modo que se vean sus ubicaciones exactas (incluso si forman parte de un cluster).
        for _, fila_p in df_et.iterrows():
            folium.CircleMarker(
                location=(fila_p["lat"], fila_p["lon"]),
                radius=5,
                color="gray",
                fill=True,
                fill_color="gray",
                fill_opacity=0.6,
                popup=(
                    f"<b>{fila_p['nombre_cliente']}</b><br>"
                    f"Dirección: {fila_p['direccion']}<br>"
                    f"Cluster: {fila_p['cluster']}<br>"
                    f"Ventana: {fila_p['time_start']} - {fila_p['time_end']}"
                )
            ).add_to(m)

        # 4) Dibujar la línea del tramo actual (azul)
        folium.PolyLine(
            segmento,
            color="blue",
            weight=5,
            opacity=0.8,
            tooltip=f"⏱ {tiempo_traffic}" if tiempo_traffic else None
        ).add_to(m)

        # 5) Marcar origen (ícono verde) y destino (ícono azul) del tramo
        folium.Marker(
            coords_final[leg],
            popup="Origen tramo",
            icon=folium.Icon(color="green", icon="play", prefix="fa")
        ).add_to(m)
        folium.Marker(
            coords_final[leg+1],
            popup=f"{nombre_dest}<br>{direccion_dest}",
            icon=folium.Icon(color="blue", icon="map-marker", prefix="fa")
        ).add_to(m)

        # 6) Mostrar mapa
        st_folium(m, width=700, height=400)

    with t2:
        st.write(f"**Tiempo estimado (tráfico):** {tiempo_traffic or '--'}")
