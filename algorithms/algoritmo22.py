#################################################################################################################
# demoapp6.py  –  Streamlit App Integrado:
#   → GLS + PCA + OR-Tools
#   → Firebase Firestore (usando service account JSON)
#   → Google Maps Distance Matrix & Directions
#   → OR-Tools VRP-TW con servicio, ventanas, tráfico real
#   → Se empleó el algoritmo de agrupación: Agglomerative Clustering para agrupar pedidos cercanos en 300m a la redonda.
#   → Página única: Ver Ruta Optimizada
#   → En caso el algoritmo no dé respuesta, usa distancias euclidianas
##################################################################################################################

import os
import math
import time as tiempo
from datetime import datetime

import streamlit as st
import pandas as pd
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore
import googlemaps
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from sklearn.cluster import AgglomerativeClustering
import folium
from streamlit_folium import st_folium

# -------------------- INICIALIZAR FIREBASE --------------------
# Usa el JSON de servicio: 'lavanderia_key.json'
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- CONFIG GOOGLE MAPS --------------------
# En su caso se implemente con st.secrets
GOOGLE_MAPS_API_KEY = "AIzaSyC80b7603zMwdhktzXzEbFqoyRNivR5Dvw"

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------- CONSTANTES VRP --------------------
SERVICE_TIME    = 10 * 60        # 10 minutos de servicio en cada parada (excepto depósito)
MAX_ELEMENTS    = 100            # límite de celdas por petición Distance Matrix API
SHIFT_START_SEC =  9 * 3600      # 09:00 en segundos
SHIFT_END_SEC   = 16*3600 +30*60 # 16:30 en segundos
# 100 kg <------------------------------------------------ #Preguntar
# ===================== FUNCIONES AUXILIARES =====================

def _hora_a_segundos(hhmm):
    """Convierte 'HH:MM' a segundos desde medianoche. Si es None o inválido, retorna None."""
    if hhmm is None or pd.isna(hhmm) or hhmm == "":
        return None
    try:
        h, m = map(int, str(hhmm).split(":"))
        return h*3600 + m*60
    except:
        return None

def _haversine_dist_dur(coords, vel_kmh=40.0):
    """
    Calcula matrices de distancias (en metros) y duraciones (en segundos)
    basadas en fórmula de Haversine asumiendo velocidad vel_kmh para la duración.
    coords = [(lat1, lon1), (lat2, lon2), ...]
    """
    R = 6371e3  # radio terrestre en metros
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600  # convertir km/h a m/s
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lat1, lon1 = map(math.radians, coords[i])
            lat2, lon2 = map(math.radians, coords[j])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            d = 2 * R * math.asin(math.sqrt(a))
            dist[i][j] = int(d)
            dur[i][j]  = int(d / v_ms)
    return dist, dur

@st.cache_data(ttl=3600, show_spinner=False)
def _distancia_duracion_matrix(coords):
    """
    Llama a la Distance Matrix API de Google Maps para obtener distancias (m) y duraciones (s)
    entre cada par de coords = [(lat, lon), ...].
    Si falta clave de la API del archivo st.secrets, usa la aproximación Haversine.
    """
    if not GOOGLE_MAPS_API_KEY:
        return _haversine_dist_dur(coords)
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    # Dividimos en lotes para no exceder MAX_ELEMENTS celdas
    batch = max(1, min(n, MAX_ELEMENTS // n))
    for i0 in range(0, n, batch):
        resp = gmaps.distance_matrix(
            origins=coords[i0:i0+batch],
            destinations=coords,
            mode="driving",
            units="metric",
            departure_time=datetime.now(),
            traffic_model="best_guess"
        )
        for i, row in enumerate(resp["rows"]):
            for j, el in enumerate(row["elements"]):
                dist[i0 + i][j] = el.get("distance", {}).get("value", 1)
                dur[i0 + i][j]  = el.get("duration_in_traffic", {}).get(
                    "value",
                    el.get("duration", {}).get("value", 1)
                )
    return dist, dur

def _crear_data_model(df, vehiculos=1, capacidad_veh=None):
    """
    Construye el diccionario 'data' esperado por el resolver VRPTW:
      - distance_matrix: matriz de distancias (m)
      - duration_matrix: matriz de duraciones (s)
      - time_windows: lista de (inicio, fin) en segundos
      - demands: lista de demandas por nodo
      - num_vehicles, vehicle_capacities, depot
    df debe tener columnas ['lat', 'lon', 'time_start', 'time_end', 'demand'].
    """
    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _distancia_duracion_matrix(coords)
    time_windows = []
    demandas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row.get("time_start"))
        fin = _hora_a_segundos(row.get("time_end"))
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        time_windows.append((ini, fin))
        demandas.append(row.get("demand", 1))
    return {
        "distance_matrix":    dist_m,
        "duration_matrix":    dur_s,
        "time_windows":       time_windows,
        "demands":            demandas,
        "num_vehicles":       vehiculos,
        "vehicle_capacities": [capacidad_veh or 10**9] * vehiculos,
        "depot":              0,
    }
#
def optimizar_ruta_algoritmo1(data, tiempo_max_seg=120):
    """
    Resuelve un VRPTW de un ...solo vehículo... usando OR-Tools.
    data: diccionario creado por _crear_data_model.
    Retorna {'routes': [ { 'vehicle': v, 'route': [nodos], 'arrival_sec': [segundos] } , ... ],
             'distance_total_m': distancia_total_en_metros }
    o None si no hay solución factible.
    """
    manager = pywrapcp.RoutingIndexManager(
        len(data["distance_matrix"]),
        data["num_vehicles"],
        data["depot"]
    )
    routing = pywrapcp.RoutingModel(manager)

    def time_cb(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        travel = data["duration_matrix"][i][j]
        service = SERVICE_TIME if i != data["depot"] else 0
        return travel + service

    transit_cb_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    routing.AddDimension(
        transit_cb_idx,
        slack_max=24*3600,   # max tiempo de espera
        capacity=24*3600,    # duracion max ruta
        fix_start_cumul_to_zero=False,
        name="Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")
    depot_idx = manager.NodeToIndex(data["depot"])
    # Fijar la ventana del depósito
    time_dim.CumulVar(depot_idx).SetRange(SHIFT_START_SEC, SHIFT_START_SEC)
    # Aplicar ventanas de tiempo a cada nodo
    for node, (ini, fin) in enumerate(data["time_windows"]):
        if node == data["depot"]:
            continue
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(ini, fin)

    # Si hay demandas, agrego dimensión de capacidad
    if any(data["demands"]):
        def demand_callback(i_idx):
            return data["demands"][manager.IndexToNode(i_idx)]
        dem_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            dem_cb_idx, 0, data["vehicle_capacities"], True, "Capacity"
        )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.time_limit.FromSeconds(tiempo_max_seg)
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH

    sol = routing.SolveWithParameters(params)
    if not sol:
        return None

    rutas = []
    dist_total = 0
    for v in range(data["num_vehicles"]):
        idx = routing.Start(v)
        route, llegada = [], []
        while not routing.IsEnd(idx):
            n = manager.IndexToNode(idx)
            route.append(n)
            llegada.append(sol.Min(time_dim.CumulVar(idx)))
            nxt = sol.Value(routing.NextVar(idx))
            dist_total += routing.GetArcCostForVehicle(idx, nxt, v)
            idx = nxt
        rutas.append({"vehicle": v, "route": route, "arrival_sec": llegada})
    return {"routes": rutas, "distance_total_m": dist_total}

# ===================== FUNCIONES PARA CLUSTERING =====================


def _haversine_meters(lat1, lon1, lat2, lon2):
    """Retorna distancia en metros entre dos puntos (lat, lon) usando Haversine."""
    R = 6371e3  # metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def agrupar_puntos_aglomerativo(df, eps_metros=300):
    """
    Agrupa pedidos cercanos mediante AgglomerativeClustering. 
    eps_metros: umbral de distancia máxima en metros para que queden en el mismo cluster.
    Retorna (df_clusters, df_etiquetado), donde:
      - df_etiquetado = df original con columna 'cluster' indicando etiqueta de cluster.
      - df_clusters  = DataFrame de centroides con columnas ['id','operacion','nombre_cliente',
                        'dirección','lat','lon','time_start','time_end','demand'].
    """
    # Si no hay pedidos, retorno vacíos
    if df.empty:
        return pd.DataFrame(), df.copy()

    coords = df[["lat", "lon"]].to_numpy()
    n = len(coords)
    # 1) Construir matriz de distancias en metros
    dist_m = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            if i == j:
                dist_m[i, j] = 0.0
            else:
                dist_m[i, j] = _haversine_meters(
                    coords[i, 0], coords[i, 1],
                    coords[j, 0], coords[j, 1]
                )

    # 2) Aplicar AgglomerativeClustering con distancia precomputada
    clustering = AgglomerativeClustering(
        n_clusters=None, #1
        affinity="precomputed",
        linkage="average",
        distance_threshold=eps_metros
    )
    labels = clustering.fit_predict(dist_m)
    df_labeled = df.copy()
    df_labeled["cluster"] = labels

    # 3) Construir DataFrame de centroides
    agrupados = []
    for clus in sorted(np.unique(labels)):
        members = df_labeled[df_labeled["cluster"] == clus]
        centro_lat = members["lat"].mean()
        centro_lon = members["lon"].mean()
        # Nombre descriptivo: primeros dos clientes del cluster
        nombres = list(members["nombre_cliente"].unique())
        nombre_desc = ", ".join(nombres[:2]) + ("..." if len(nombres) > 2 else "")
        # Concatenar direcciones de los pedidos (hasta 2)
        direcciones = list(members["direccion"].unique())
        direccion_desc = ", ".join(direcciones[:2]) + ("..." if len(direcciones) > 2 else "")
        # Ventana: tomo min y max de time_start/time_end
        ts_vals = members["time_start"].tolist()
        te_vals = members["time_end"].tolist()
        ts_vals = [t for t in ts_vals if t]
        te_vals = [t for t in te_vals if t]
        inicio_cluster = min(ts_vals) if ts_vals else ""
        fin_cluster    = max(te_vals) if te_vals else ""
        demanda_total  = int(members["demand"].sum())
        agrupados.append({
            "id":             f"cluster_{clus}",
            "operacion":      "Agrupado",
            "nombre_cliente": f"Grupo {clus}: {nombre_desc}",
            "direccion":      direccion_desc,
            "lat":            centro_lat,
            "lon":            centro_lon,
            "time_start":     inicio_cluster,
            "time_end":       fin_cluster,
            "demand":         demanda_total
        })

    df_clusters = pd.DataFrame(agrupados)
    return df_clusters, df_labeled

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
        res = optimizar_ruta_algoritmo1(data, tiempo_max_seg=120)
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

