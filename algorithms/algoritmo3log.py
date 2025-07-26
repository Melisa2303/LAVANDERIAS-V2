from ortools.sat.python import cp_model
import pandas as pd
import math
import numpy as np
from datetime import datetime
import googlemaps
import firebase_admin
from firebase_admin import credentials, firestore
import os

# Inicializar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")  # Actualiza la ruta a tu key
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Clave API
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

 

# Conversión HH:MM -> segundos
def _hora_a_segundos(hhmm):
    try:
        h, m = map(int, hhmm.split(":"))
        return h * 3600 + m * 60
    except:
        return None

# Cálculo haversine
def _haversine_dist_dur(coords, vel_kmh=40.0):
    R = 6371e3
    n = len(coords)
    dist = np.zeros((n, n), dtype=int)
    dur = np.zeros((n, n), dtype=int)
    v_ms = vel_kmh * 1000 / 3600
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lat1, lon1 = math.radians(coords[i][0]), math.radians(coords[i][1])
            lat2, lon2 = math.radians(coords[j][0]), math.radians(coords[j][1])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            c = 2 * math.asin(math.sqrt(a))
            d = R * c
            dist[i][j] = int(d)
            dur[i][j] = int(d / v_ms)
    return dist, dur

# Expandir ventanas de tiempo
def _expandir_ventanas(df):
    ventanas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(24*3600, fin + MARGEN)
        ventanas.append((ini, fin))
    return ventanas

SERVICE_TIME_DEFAULT = 10 * 60
BIG_M = 100*6
TOLERANCIA_RETRASO = 15 * 60  # 30 minutos

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]

    # Flujo: entrar y salir una vez de cada nodo (excepto depósito)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)

    # Flujo del depósito
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo con retraso tolerado
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Secuencia de tiempo: si voy de i a j, entonces t[j] ≥ t[i] + travel + service
    for i in range(n):
        for j in range(n):
            if i != j:
                travel = dur[i][j]
                model.Add(t[j] >= t[i] + service_times[i] + travel).OnlyEnforceIf(x[i, j])

    # Función objetivo: minimizar duración + retraso + evitar saltos largos
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * 10 for i in range(n))  # Penalización por llegar tarde
    )

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return {
            "routes": [],
            "distance_total_m": 0
        }

    # Reconstruir la ruta desde el depósito
    ruta = [0]
    actual = 0
    while True:
        siguiente = None
        for j in range(n):
            if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                siguiente = j
                break
        if siguiente is None or siguiente == 0:
            break
        ruta.append(siguiente)
        actual = siguiente

    llegada = [solver.Value(t[i]) for i in ruta]
    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }

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












# algoritmo3_cp_sat.py
# Algoritmo 3: Implementación 100% CP-SAT pura (sin RoutingModel)

import math
from ortools.sat.python import cp_model
import streamlit as st
from core.constants import GOOGLE_MAPS_API_KEY
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import firebase_admin
import os
from firebase_admin import credentials, firestore
import math
import pandas as pd
import datetime
from datetime import timedelta
import time
import googlemaps
import numpy as np
from sklearn.cluster import AgglomerativeClustering
import folium
from streamlit_folium import st_folium

db = firestore.client()

# -------------------- CONFIG GOOGLE MAPS --------------------
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps", {}).get("api_key") or os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------- INICIALIZAR FIREBASE --------------------
#if not firebase_admin._apps:
 #   cred = credentials.Certificate("lavanderia_key.json")
 #   firebase_admin.initialize_app(cred)
#db = firestore.client()
SERVICE_TIME    = 10 * 60        # 10 minutos en segundos
SHIFT_START_SEC =  9 * 3600      # 09:00 h
SHIFT_END_SEC   = 16*3600 +30*60 # 16:30 h
MARGEN = 15 * 60                 # 15 min

def _hora_a_segundos(hhmm):
    if hhmm is None or hhmm == "" or isinstance(hhmm, float):
        return None
    try:
        parts = str(hhmm).split(":")
        h = int(parts[0])
        m = int(parts[1])
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

def _crear_data_model(df, vehiculos=1, capacidad_veh=None):
    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _haversine_dist_dur(coords)

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

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    manager = pywrapcp.RoutingIndexManager(len(data["duration_matrix"]), data["num_vehicles"], data["depot"])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["distance_matrix"][from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["duration_matrix"][from_node][to_node] + data["service_times"][from_node]

    time_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(
        time_callback_index,
        12 * 3600,
        30 * 3600,
        False,
        "Time"
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    index_depot = manager.NodeToIndex(data["depot"])
    time_dimension.CumulVar(index_depot).SetRange(SHIFT_START_SEC, SHIFT_START_SEC + 900)

    for i, (start, end) in enumerate(data["time_windows"]):
        index = manager.NodeToIndex(i)
        time_dimension.CumulVar(index).SetRange(start, end)
        time_dimension.SetCumulVarSoftLowerBound(index, start, 1000)
        time_dimension.SetCumulVarSoftUpperBound(index, end, 1000)

    for i in range(len(data["duration_matrix"])):
        index = manager.NodeToIndex(i)
        routing.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(index))
        routing.AddVariableMinimizedByFinalizer(time_dimension.SlackVar(index))

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.time_limit.seconds = tiempo_max_seg
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.AUTOMATIC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.log_search = True

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        st.error("🚫 No se encontró una solución factible.")
        return None

    rutas = []
    dist_total = 0
    arrival_sec_all_nodes = [None] * len(data["distance_matrix"])

    for v in range(data["num_vehicles"]):
        idx = routing.Start(v)
        route, llegada = [], []
        while not routing.IsEnd(idx):
            n = manager.IndexToNode(idx)
            nxt = solution.Value(routing.NextVar(idx))
            dest = manager.IndexToNode(nxt)
            dist_total += data["distance_matrix"][n][dest]
            arrival = solution.Value(time_dimension.CumulVar(idx))
            arrival_sec_all_nodes[n] = arrival
            route.append(n)
            llegada.append(arrival)
            idx = nxt
        rutas.append({"vehicle": v, "route": route, "arrival_sec": llegada})

    return {
        "routes": rutas,
        "distance_total_m": dist_total,
        "arrival_sec_all_nodes": arrival_sec_all_nodes
    }
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
