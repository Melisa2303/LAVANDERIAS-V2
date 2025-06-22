#Algoritmo 4: ALNS
import os
import math
import time as tiempo
from datetime import datetime
from io import BytesIO

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import googlemaps
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import folium
from streamlit_folium import st_folium
from core.constants import GOOGLE_MAPS_API_KEY

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


# -------------------- CONSTANTES VRP --------------------
SERVICE_TIME    = 10 * 60        # 10 minutos de servicio
MAX_ELEMENTS    = 100            # límite de celdas por petición DM API
SHIFT_START_SEC =  9 * 3600      # 09:00
SHIFT_END_SEC   = 16*3600 +30*60 # 16:30

# ===================== AUXILIARES VRP =====================
db = firestore.client()

def _hora_a_segundos(hhmm):
    """Convierte 'HH:MM' o 'HH:MM:SS' a segundos desde medianoche."""
    if hhmm is None or pd.isna(hhmm) or hhmm == "":
        return None
    try:
        parts = str(hhmm).split(":")
        h = int(parts[0])
        m = int(parts[1])
        return h*3600 + m*60
    except:
        return None

#Distancia euclidiana - Drones - Emergencia - Botar sí o sí una tabla ordenada considerando distancias, 
# no tiempo real, sino estimación
def _haversine_dist_dur(coords, vel_kmh=40.0):
    R = 6371e3
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600
    for i in range(n):
        for j in range(n):
            if i==j: continue
            la1,lo1 = map(math.radians, coords[i])
            la2,lo2 = map(math.radians, coords[j])
            dlat = la2-la1; dlon=lo2-lo1
            a = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
            d = 2*R*math.asin(math.sqrt(a))
            dist[i][j] = int(d)
            dur [i][j] = int(d/v_ms)
    return dist, dur

#Tomar los puntos de la API - Matriz para el algoritmo las reciba 
@st.cache_data(ttl="1h", show_spinner=False)
def _distancia_duracion_matrix(coords):
    if not GOOGLE_MAPS_API_KEY:
        return _haversine_dist_dur(coords)
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    batch = max(1, min(n, MAX_ELEMENTS//n))
    for i0 in range(0, n, batch):
        resp = gmaps.distance_matrix(
            origins=coords[i0:i0+batch],
            destinations=coords,
            mode="driving",
            units="metric",
            departure_time=datetime.now(),
            traffic_model="best_guess" #pessimistic / optimistic
        )
        for i,row in enumerate(resp["rows"]):
            for j,el in enumerate(row["elements"]):
                dist[i0+i][j] = el.get("distance",{}).get("value",1)
                dur [i0+i][j] = el.get("duration_in_traffic",{}).get("value",
                                      el.get("duration",{}).get("value",1))
    return dist, dur

#Datos para la visualización del usuario + Consideraciones del algoritmo
def _crear_data_model(df, vehiculos=1, capacidad_veh=None):
    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _distancia_duracion_matrix(coords)
    time_windows, demandas = [], []
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


#Algoritmos diversos

# optimizar_ruta_algoritmo4: ALNS multivehicular con soporte para restricciones
import random

SERVICE_TIME = 10 * 60        # 10 minutos de servicio
SHIFT_START_SEC = 9 * 3600    # 09:00

import time as tiempo


def optimizar_ruta_algoritmo4(data, tiempo_max_seg=120):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    def calcular_arrival_times(route):
        arrival = []
        t = SHIFT_START_SEC
        for i in range(len(route)):
            curr = route[i]
            if i == 0:
                arrival.append(t)
                continue
            prev = route[i - 1]
            travel = data["duration_matrix"][prev][curr]
            t += travel
            start, end = data["time_windows"][curr]
            t = max(t, start)
            arrival.append(t)
            t += SERVICE_TIME
        return arrival

    def es_ruta_factible(route):
        t = SHIFT_START_SEC
        for i in range(1, len(route)):
            prev, curr = route[i - 1], route[i]
            travel = data["duration_matrix"][prev][curr]
            t += travel
            start, end = data["time_windows"][curr]
            if not (start <= t <= end):
                return False
            t = max(t, start) + SERVICE_TIME
        return True

    # ========= Paso 1: Solución inicial con OR-Tools =========
    manager = pywrapcp.RoutingIndexManager(
        len(data["duration_matrix"]),
        data["num_vehicles"],
        data["depot"]
    )
    routing = pywrapcp.RoutingModel(manager)

    def time_cb(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        travel = data["duration_matrix"][i][j]
        service = SERVICE_TIME
        return travel + service

    transit_cb_index = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_index)

    routing.AddDimension(
        transit_cb_index, 3600, 24 * 3600, False, "Time"
    )
    time_dimension = routing.GetDimensionOrDie("Time")
    for v in range(data["num_vehicles"]):
        time_dimension.CumulVar(routing.Start(v)).SetRange(SHIFT_START_SEC, SHIFT_START_SEC)

    for i, (ini, fin) in enumerate(data["time_windows"]):
        time_dimension.CumulVar(manager.NodeToIndex(i)).SetRange(ini, fin)

    if any(data["demands"]):
        def demand_cb(index):
            return data["demands"][manager.IndexToNode(index)]

        demand_cb_index = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_cb_index, 0, data["vehicle_capacities"], True, "Capacity"
        )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.time_limit.seconds = 10

    solution = routing.SolveWithParameters(search_parameters)
    if not solution:
        return None

    def extract_routes():
        rutas = []
        dist_total = 0
        for v in range(data["num_vehicles"]):
            idx = routing.Start(v)
            route = []
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                route.append(node)
                next_idx = solution.Value(routing.NextVar(idx))
                dist_total += routing.GetArcCostForVehicle(idx, next_idx, v)
                idx = next_idx
            if route:
                arrival = calcular_arrival_times(route)
                rutas.append({
                    "vehicle": v,
                    "route": route,
                    "arrival_sec": arrival
                })
        return rutas, dist_total

    # ========= Paso 2: ALNS =========
    def safe_copy_rutas(rutas):
        return [
            {
                "vehicle": r["vehicle"],
                "route": list(r["route"]),
                "arrival_sec": list(r["arrival_sec"])
            }
            for r in rutas
        ]

    def random_removal(rutas, num_remove):
        flat_nodes = [
            (r_idx, i, n)
            for r_idx, ruta in enumerate(rutas)
            for i, n in enumerate(ruta["route"])
        ]
        to_remove = random.sample(flat_nodes, min(num_remove, len(flat_nodes)))
        removed_nodes = [n for _, _, n in to_remove]

        new_rutas = safe_copy_rutas(rutas)
        for r_idx, i, _ in sorted(to_remove, key=lambda x: -x[1]):
            del new_rutas[r_idx]["route"][i]
            del new_rutas[r_idx]["arrival_sec"][i]
        return new_rutas, removed_nodes

    def greedy_repair(rutas, removed):
        for node in removed:
            best_cost = float("inf")
            best_r = -1
            best_pos = -1
            for r_idx, ruta in enumerate(rutas):
                for i in range(1, len(ruta["route"])):
                    test_route = ruta["route"][:i] + [node] + ruta["route"][i:]
                    if not es_ruta_factible(test_route):
                        continue
                    cost = 0
                    for j in range(len(test_route)-1):
                        cost += data["distance_matrix"][test_route[j]][test_route[j+1]]
                    if cost < best_cost:
                        best_cost = cost
                        best_r = r_idx
                        best_pos = i
            if best_r != -1:
                rutas[best_r]["route"].insert(best_pos, node)
                rutas[best_r]["arrival_sec"] = calcular_arrival_times(rutas[best_r]["route"])
        return rutas

    def calcular_costo_total(rutas):
        total = 0
        for ruta in rutas:
            for i in range(len(ruta["route"])-1):
                total += data["distance_matrix"][ruta["route"][i]][ruta["route"][i+1]]
        return total

    rutas, dist_total = extract_routes()
    best_rutas = safe_copy_rutas(rutas)
    best_cost = dist_total

    start = tiempo.time()
    while tiempo.time() - start < tiempo_max_seg:
        rutas_tmp, eliminados = random_removal(best_rutas, num_remove=3)
        rutas_tmp = greedy_repair(rutas_tmp, eliminados)
        new_cost = calcular_costo_total(rutas_tmp)

        if new_cost < best_cost:
            best_cost = new_cost
            best_rutas = safe_copy_rutas(rutas_tmp)

    return {
        "routes": best_rutas,
        "distance_total_m": best_cost
    }

# ============= CARGAR PEDIDOS DESDE FIRESTORE =============

@st.cache_data(ttl=300)
def cargar_pedidos(fecha, tipo):
    col = db.collection('recogidas')
    docs = []
    docs += col.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()
    docs += col.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream()
    if tipo != "Todos":
        tf = "Sucursal" if tipo == "Sucursal" else "Cliente Delivery"
        docs = [d for d in docs if d.to_dict().get("tipo_solicitud")==tf]
    out = []
    for d in docs:
        data = d.to_dict()
        is_recojo = data.get("fecha_recojo")==fecha.strftime("%Y-%m-%d")
        op = "Recojo" if is_recojo else "Entrega"
        coords = data.get(f"coordenadas_{'recojo' if is_recojo else 'entrega'}",{})
        lat, lon = coords.get("lat"), coords.get("lon")
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}","")
        ts, te = (hs,hs) if hs else ("09:00","16:00")
        out.append({
            "id":d.id,
            "operacion":op,
            "nombre_cliente":data.get("nombre_cliente",""),
            "lat":lat, "lon":lon,
            "time_start":ts, "time_end":te,
            "demand":1
        })
    return out
