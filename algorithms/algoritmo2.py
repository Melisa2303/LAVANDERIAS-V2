import os
import math
import time as tiempo
from datetime import datetime
import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import googlemaps
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import folium
from streamlit_folium import st_folium

# -------------------- INICIALIZAR FIREBASE --------------------
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- CONFIG GOOGLE MAPS --------------------
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps", {}).get("api_key") or os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------- CONSTANTES VRP --------------------
SERVICE_TIME    = 10 * 60
MAX_ELEMENTS    = 100
SHIFT_START_SEC =  9 * 3600
SHIFT_END_SEC   = 16*3600 +30*60

# -------------------- FUNCIONES AUXILIARES --------------------

def _hora_a_segundos(hhmm):
    if hhmm is None or pd.isna(hhmm) or hhmm == "":
        return None
    try:
        h, m = map(int, str(hhmm).split(":"))
        return h*3600 + m*60
    except:
        return None

def _haversine_dist_dur(coords, vel_kmh=40.0):
    R = 6371e3
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600
    for i in range(n):
        for j in range(n):
            if i == j: continue
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
    if not GOOGLE_MAPS_API_KEY:
        return _haversine_dist_dur(coords)
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
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
                dist[i0+i][j] = el.get("distance", {}).get("value", 1)
                dur[i0+i][j]  = el.get("duration_in_traffic", {}).get("value",
                                 el.get("duration", {}).get("value", 1))
    return dist, dur

def _crear_data_model(df):
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
        "num_vehicles":       1,
        "vehicle_capacities": [10**9],
        "depot":              0,
    }

def optimizar_ruta(data, tiempo_max_seg=120):
    manager = pywrapcp.RoutingIndexManager(len(data["distance_matrix"]), 1, data["depot"])
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
        if node == data["depot"]: continue
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(ini, fin)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.time_limit.FromSeconds(tiempo_max_seg)
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    sol = routing.SolveWithParameters(params)
    if not sol:
        return None

    ruta, llegada, dist_total = [], [], 0
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        n = manager.IndexToNode(idx)
        ruta.append(n)
        llegada.append(sol.Min(time_dim.CumulVar(idx)))
        nxt = sol.Value(routing.NextVar(idx))
        dist_total += data["distance_matrix"][n][manager.IndexToNode(nxt)] if not routing.IsEnd(nxt) else 0
        idx = nxt
    return {"route": ruta, "arrival": llegada, "distance_total_m": dist_total}

@st.cache_data(ttl=300)
def cargar_pedidos(fecha):
    col = db.collection('recogidas')
    docs = []
    docs += col.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()
    docs += col.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream()
    out = []
    for d in docs:
        data = d.to_dict()
        is_recojo = data.get("fecha_recojo") == fecha.strftime("%Y-%m-%d")
        op = "Recojo" if is_recojo else "Entrega"
        key_coord = f"coordenadas_{'recojo' if is_recojo else 'entrega'}"
        key_dir   = f"direccion_{'recojo' if is_recojo else 'entrega'}"
        coords = data.get(key_coord, {})
        lat, lon = coords.get("lat"), coords.get("lon")
        direccion = data.get(key_dir, "") or ""
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}", "")
        ts, te = (hs, hs) if hs else ("08:00", "18:00")
        out.append({
            "id": d.id, "operacion": op, "nombre_cliente": data.get("nombre_cliente", ""),
            "direccion": direccion, "lat": lat, "lon": lon, "time_start": ts, "time_end": te, "demand": 1
        })
    return out
