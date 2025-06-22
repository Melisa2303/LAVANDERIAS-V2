import math
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.cluster import AgglomerativeClustering
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import googlemaps
import os

# -------------------- API KEY GOOGLE MAPS --------------------
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY) if GOOGLE_MAPS_API_KEY else None

# -------------------- Parámetros --------------------
SERVICE_TIME = 10 * 60
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 30 * 60
MARGEN = 15 * 60
MAX_ELEMENTS = 100

# -------------------- Funciones auxiliares --------------------

def _hora_a_segundos(hhmm):
    if hhmm is None or pd.isna(hhmm) or hhmm == "":
        return None
    try:
        h, m = map(int, str(hhmm).split(":"))
        return h * 3600 + m * 60
    except:
        return None

def _haversine_dist_dur(coords, vel_kmh=40.0):
    R = 6371e3
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600
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
            dur[i][j] = int(d / v_ms)
    return dist, dur

def _distancia_duracion_matrix(coords):
    if not gmaps:
        return _haversine_dist_dur(coords)
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur = [[0]*n for _ in range(n)]
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
                dur[i0 + i][j] = el.get("duration_in_traffic", {}).get("value", el.get("duration", {}).get("value", 1))
    return dist, dur

# -------------------- Funciones exportables --------------------

def agregar_ventana_margen(df, margen_segundos=15*60):
    def expandir_fila(row):
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            return "No especificado"
        ini = max(0, ini - margen_segundos)
        fin = min(24*3600, fin + margen_segundos)
        h_ini = f"{ini//3600:02}:{(ini%3600)//60:02}"
        h_fin = f"{fin//3600:02}:{(fin%3600)//60:02}"
        return f"{h_ini} - {h_fin} h"
    df["ventana_con_margen"] = df.apply(expandir_fila, axis=1)
    return df

def _crear_data_model(df, vehiculos=1, capacidad_veh=None):
    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _distancia_duracion_matrix(coords)
    time_windows = []
    demandas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row.get("time_start"))
        fin = _hora_a_segundos(row.get("time_end"))
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(24*3600, fin + MARGEN)
        time_windows.append((ini, fin))
        demandas.append(row.get("demand", 1))
    return {
        "distance_matrix": dist_m,
        "duration_matrix": dur_s,
        "time_windows": time_windows,
        "demands": demandas,
        "num_vehicles": vehiculos,
        "vehicle_capacities": [capacidad_veh or 10**9] * vehiculos,
        "depot": 0,
    }

def optimizar_ruta_algoritmo22(data, tiempo_max_seg=60):
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
        slack_max=24*3600,
        capacity=24*3600,
        fix_start_cumul_to_zero=False,
        name="Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")
    depot_idx = manager.NodeToIndex(data["depot"])
    time_dim.CumulVar(depot_idx).SetRange(SHIFT_START_SEC, SHIFT_START_SEC)

    for node, (ini, fin) in enumerate(data["time_windows"]):
        if node == data["depot"]:
            continue
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(ini, fin)

    if any(data["demands"]):
        def demand_callback(i_idx):
            return data["demands"][manager.IndexToNode(i_idx)]
        dem_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            dem_cb_idx, 0, data["vehicle_capacities"], True, "Capacity"
        )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.time_limit.FromSeconds(tiempo_max_seg)
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
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

def agrupar_puntos_aglomerativo(df, eps_metros=300):
    def _haversine_meters(lat1, lon1, lat2, lon2):
        R = 6371e3
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return 2 * R * math.asin(math.sqrt(a))

    if df.empty:
        return pd.DataFrame(), df.copy()

    coords = df[["lat", "lon"]].to_numpy()
    n = len(coords)
    dist_m = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            dist_m[i, j] = _haversine_meters(coords[i][0], coords[i][1], coords[j][0], coords[j][1])

    clustering = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="average",
        distance_threshold=eps_metros
    )
    labels = clustering.fit_predict(dist_m)
    df_labeled = df.copy()
    df_labeled["cluster"] = labels
    agrupados = []
    for clus in sorted(np.unique(labels)):
        members = df_labeled[df_labeled["cluster"] == clus]
        centro_lat = members["lat"].mean()
        centro_lon = members["lon"].mean()
        nombres = list(members["nombre_cliente"].unique())
        nombre_desc = ", ".join(nombres[:2]) + ("..." if len(nombres) > 2 else "")
        direcciones = list(members["direccion"].unique())
        direccion_desc = ", ".join(direcciones[:2]) + ("..." if len(direcciones) > 2 else "")
        ts_vals = [t for t in members["time_start"].tolist() if t]
        te_vals = [t for t in members["time_end"].tolist() if t]
        inicio_cluster = min(ts_vals) if ts_vals else ""
        fin_cluster = max(te_vals) if te_vals else ""
        demanda_total = int(members["demand"].sum())
        agrupados.append({
            "id": f"cluster_{clus}",
            "operacion": "Agrupado",
            "nombre_cliente": f"Grupo {clus}: {nombre_desc}",
            "direccion": direccion_desc,
            "lat": centro_lat,
            "lon": centro_lon,
            "time_start": inicio_cluster,
            "time_end": fin_cluster,
            "demand": demanda_total
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

        # Extraer nombre del cliente o sucursal
        nombre = data.get("nombre_cliente")
        if not nombre:
            nombre = data.get("sucursal", "") or "Sin nombre"

        # Hora de servicio
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}", "")
        ts, te = (hs, hs) if hs else ("08:00", "18:00")

        out.append({
            "id":             d.id,
            "operacion":      op,
            "nombre_cliente": nombre,
            "direccion":      direccion,
            "lat":            lat,
            "lon":            lon,
            "time_start":     ts,
            "time_end":       te,
            "demand":         1
        })

    return out
