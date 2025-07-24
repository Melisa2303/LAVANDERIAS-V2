
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
    n = len(data["distance_matrix"])
    depot = data["depot"]
    service_times = data.get("service_times", [SERVICE_TIME] * n)
    time_windows = data["time_windows"]
    duration_matrix = data["duration_matrix"]

    model = cp_model.CpModel()

    # Variables binarias: visita de i a j
    visit = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                visit[i, j] = model.NewBoolVar(f"visit_{i}_{j}")

    # Tiempos de llegada
    horizon = SHIFT_END_SEC + SERVICE_TIME
    arrival = [model.NewIntVar(0, horizon, f"arrival_{i}") for i in range(n)]

    # Entrada/salida única (flujo)
    for j in range(1, n):
        model.Add(sum(visit[i, j] for i in range(n) if i != j) == 1)
        model.Add(sum(visit[j, k] for k in range(n) if k != j) == 1)

    # Ventanas de tiempo
    for i in range(n):
        ini, fin = time_windows[i]
        model.Add(arrival[i] >= ini)
        model.Add(arrival[i] <= fin)

    # Restricciones de tiempo acumulado
    for i in range(n):
        for j in range(n):
            if i != j:
                travel = duration_matrix[i][j]
                service = service_times[i]
                model.Add(arrival[j] >= arrival[i] + travel + service).OnlyEnforceIf(visit[i, j])

    # Eliminar subtours
    order = [model.NewIntVar(0, n - 1, f"order_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(order[i] + 1 <= order[j]).OnlyEnforceIf(visit[i, j])

    # Objetivo: minimizar duración total
    total_dist = model.NewIntVar(0, sum(sum(row) for row in duration_matrix), "total_distance")
    model.Add(total_dist == sum(
        visit[i, j] * duration_matrix[i][j]
        for i in range(n) for j in range(n) if i != j
    ))
    model.Minimize(total_dist)

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return {"routes": [], "distance_total_m": None, "arrival_sec_all_nodes": []}

    # Reconstruir solución
    route = [depot]
    arrival_times = [solver.Value(arrival[depot])]
    current = depot
    while True:
        next_node = None
        for j in range(n):
            if j != current and (current, j) in visit and solver.Value(visit[current, j]):
                next_node = j
                break
        if next_node is None or next_node == depot:
            break
        route.append(next_node)
        arrival_times.append(solver.Value(arrival[next_node]))
        current = next_node

    return {
        "routes": [{
            "vehicle": 0,
            "route": route,
            "arrival_sec": arrival_times
        }],
        "distance_total_m": solver.Value(total_dist),
        "arrival_sec_all_nodes": [solver.Value(arrival[i]) for i in range(n)]
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
