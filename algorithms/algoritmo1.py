#################################################################################################################
# :) –  Streamlit App Integrado:
#   → GLS + PCA + OR-Tools
#   → Firebase Firestore (usando service account JSON)
#   → Google Maps Distance Matrix & Directions
#   → OR-Tools VRP-TW con servicio, ventanas, tráfico real
#   → Se empleó el algoritmo de agrupación: Agglomerative Clustering para agrupar pedidos cercanos.
#   → Página única: Ver Ruta Optimizada
#   → En caso el algoritmo no dé respuesta, usa distancias euclidianas
##################################################################################################################

import os
import math
import time as tiempo
from datetime import datetime
import logging

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
## Usa el JSON de servicio: 'lavanderia_key.json'
#if not firebase_admin._apps:
#    cred = credentials.Certificate("lavanderia_key.json")
#    firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- CONFIG GOOGLE MAPS --------------------
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps", {}).get("api_key") or os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------- CONSTANTES VRP --------------------
SERVICE_TIME    = 10 * 60             # 10 minutos de servicio por defecto (clientes)
MAX_ELEMENTS    = 100                 # límite de celdas por petición Distance Matrix API
SHIFT_START_SEC =  8 * 3600 + 30*60   # 08:30 en segundos
SHIFT_END_SEC   = 17*3600             # 17:00 en segundos
MARGEN          = 15 * 60             # 15 minutos en segundos

# ------------------------------------------------------------------
# COCHERA (DEPÓSITO) – si quieres otra hora de salida cambia "hora".
# ------------------------------------------------------------------
COCHERA = {
    "lat": -16.4141434959913,
    "lon": -71.51839574233342,
    "direccion": "Cochera",
    "hora": "08:30",
}

# ===================== FUNCIONES AUXILIARES =====================

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


def _haversine_dist_dur(coords, vel_kmh=40.0):
    """
    Calcula matrices de distancias (m) y duraciones (s)
    basadas en Haversine asumiendo velocidad vel_kmh para la duración.
    coords = [(lat1, lon1), (lat2, lon2), ...]
    """
    R = 6371e3  # radio terrestre en metros
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600  # km/h → m/s
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
    Llama a la Distance Matrix API de Google Maps para obtener distancias (m) y duraciones (s).
    Si falta la clave de API, usa Haversine como aproximación.
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

# ===================== COCHERA → INSERTAR COMO NODO 0 =====================

def insertar_cochera(df: pd.DataFrame, cochera: dict, start="08:30", end="17:00") -> pd.DataFrame:
    """
    Inserta la cochera como primera fila del DataFrame.
    'cochera' debe tener: lat, lon, direccion (opcional: hora).
    """
    fila = {
        "id":             "depot_0",
        "operacion":      "Depósito",
        "nombre_cliente": "Cochera",
        "direccion":      cochera.get("direccion", "Cochera"),
        "lat":            cochera["lat"],
        "lon":            cochera["lon"],
        "time_start":     start,
        "time_end":       end,
        "demand":         0,
        "tipo":           "Depósito",
    }
    df_depot = pd.DataFrame([fila])
    return pd.concat([df_depot, df], ignore_index=True)

# ===================== DATA MODEL (con cochera en índice 0) =====================

def _crear_data_model(df, vehiculos=1, capacidad_veh=None, cochera=None):
    """
    Si 'cochera' (dict) se pasa, se inserta como primer nodo.
    Garantiza depot=0, service_times[0]=0 y ventana fija (salida) en SHIFT_START_SEC.
    """
    if cochera is not None:
        df = insertar_cochera(
            df,
            cochera,
            start=cochera.get("hora", "08:30"),
            end="17:00"
        )

    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _distancia_duracion_matrix(coords)

    time_windows = []
    demandas = []
    service_times = []

    for _, row in df.iterrows():
        ini = _hora_a_segundos(row.get("time_start"))
        fin = _hora_a_segundos(row.get("time_end"))
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(24*3600, fin + MARGEN)
        time_windows.append((ini, fin))
        demandas.append(int(row.get("demand", 1)))

        # tiempos de servicio por tipo
        tipo = (row.get("tipo") or "").strip()
        if tipo == "Depósito":
            service_times.append(0)            # depósito sin servicio
        elif tipo == "Sucursal":
            service_times.append(5 * 60)       # 5 min
        elif tipo == "Planta":
            service_times.append(60 * 60)      # 60 min (ajusta a 30*60 si deseas)
        else:
            service_times.append(10 * 60)      # Cliente Delivery / indefinido

    # Asegurar depósito = índice 0
    depot = 0
    service_times[depot] = 0
    time_windows[depot]  = (SHIFT_START_SEC, SHIFT_START_SEC)  # salida fija exacta (llegada=salida)

    return {
        "distance_matrix": dist_m,
        "duration_matrix": dur_s,
        "time_windows": time_windows,
        "demands": demandas,
        "num_vehicles": vehiculos,
        "vehicle_capacities": [capacidad_veh or 10**9] * vehiculos,
        "depot": depot,
        "service_times": service_times
    }

# ===================== SOLVER OR-TOOLS (arrival_sec solo clientes) =====================

def optimizar_ruta_algoritmo22(data, tiempo_max_seg=60, reintento=False):
    """
    Resuelve VRPTW con OR-Tools.
    Salida:
      {
        "routes": [
          {
            "vehicle": v,
            "route": [nodos_sin_deposito],
            "arrival_sec": [llegadas_a_cada_cliente_incluyendo_servicio_previo]
          },
          ...
        ],
        "distance_total_m": dist_total
      }
    """
    manager = pywrapcp.RoutingIndexManager(
        len(data["distance_matrix"]),
        data["num_vehicles"],
        data["depot"]
    )
    routing = pywrapcp.RoutingModel(manager)

    # Tiempo: travel(i->j) + service(i). (service(depot)=0)
    def time_cb(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        travel  = data["duration_matrix"][i][j]
        service = 0 if i == data["depot"] else data["service_times"][i]
        return travel + service

    transit_cb_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    # Dimensión de tiempo (Cumul = hora de LLEGADA al nodo)
    routing.AddDimension(
        transit_cb_idx,
        24 * 3600,   # slack
        24 * 3600,   # horizon
        False,
        "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")
    time_dim.SetGlobalSpanCostCoefficient(1000)

    # Ventanas
    for node, (ini, fin) in enumerate(data["time_windows"]):
        idx = manager.NodeToIndex(node)
        time_dim.CumulVar(idx).SetRange(ini, fin)

    # Depósito: salida fija a SHIFT_START_SEC (llegada en depósito == salida)
    depot_idx = manager.NodeToIndex(data["depot"])
    time_dim.CumulVar(depot_idx).SetRange(SHIFT_START_SEC, SHIFT_START_SEC)

    # Capacidad (si aplica)
    if any(data["demands"]):
        def demand_cb(from_index):
            return data["demands"][manager.IndexToNode(from_index)]
        demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_cb_idx, 0, data["vehicle_capacities"], True, "Capacity"
        )

    # Parámetros de búsqueda
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.time_limit.FromSeconds(tiempo_max_seg)
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH

    sol = routing.SolveWithParameters(params)
    if not sol:
        st.warning("❌ No se encontró solución con OR-Tools.")
        return None

    rutas = []
    dist_total_m = 0

    for v in range(data["num_vehicles"]):
        idx = routing.Start(v)
        nodos = []
        arrivals = []

        while not routing.IsEnd(idx):
            n = manager.IndexToNode(idx)
            nodos.append(n)
            arrivals.append(sol.Min(time_dim.CumulVar(idx)))

            nxt = sol.Value(routing.NextVar(idx))
            if not routing.IsEnd(nxt):
                dest = manager.IndexToNode(nxt)
                dist_total_m += data["distance_matrix"][n][dest]
            idx = nxt

        # Indices de clientes (todo excepto el depot)
        depot = data["depot"]
        cliente_pos = [k for k, n in enumerate(nodos) if n != depot]

        # Ruta/arrivals ya alineados por posición (no se pierde el primero)
        ruta_clientes     = [nodos[k]    for k in cliente_pos]
        arrivals_clientes = [arrivals[k] for k in cliente_pos]

        rutas.append({
            "vehicle": v,
            "route": ruta_clientes,          # solo clientes (sin depósito)
            "arrival_sec": arrivals_clientes # llegada real a cada cliente
        })

    st.success("✅ Ruta encontrada con éxito.")
    return {
        "routes": rutas,
        "distance_total_m": dist_total_m
    }

# ===================== UTILIDAD: mostrar ventana con margen =====================

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

# ===================== FUNCIONES PARA CLUSTERING =====================

def _haversine_meters(lat1, lon1, lat2, lon2):
    """Retorna distancia en metros entre dos puntos (lat, lon) usando Haversine."""
    R = 6371e3  # metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def agrupar_puntos_aglomerativo(df, eps_metros=5):
    """
    Agrupa pedidos cercanos mediante AgglomerativeClustering. 
    eps_metros: umbral de distancia máxima en metros para que queden en el mismo cluster.
    Retorna (df_clusters, df_etiquetado).
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

    # 2) AgglomerativeClustering con distancia precomputada
    clustering = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="average",
        distance_threshold=eps_metros
    )
    labels = clustering.fit_predict(dist_m)
    df_labeled = df.copy()
    df_labeled["cluster"] = labels

    # 3) Centroides
    agrupados = []
    for clus in sorted(np.unique(labels)):
        members = df_labeled[df_labeled["cluster"] == clus]
        centro_lat = members["lat"].mean()
        centro_lon = members["lon"].mean()
        # Nombre descriptivo: primeros dos clientes del cluster
        nombres = list(members["nombre_cliente"].unique())
        nombre_desc = ", ".join(nombres[:2]) + ("..." if len(nombres) > 2 else "")
        # Direcciones (hasta 2)
        direcciones = list(members["direccion"].unique())
        direccion_desc = ", ".join(direcciones[:2]) + ("..." if len(direcciones) > 2 else "")
        # Ventana: min start y max end
        ts_vals = [t for t in members["time_start"].tolist() if t]
        te_vals = [t for t in members["time_end"].tolist() if t]
        inicio_cluster = min(ts_vals) if ts_vals else ""
        fin_cluster    = max(te_vals) if te_vals else ""
        demanda_total  = int(members["demand"].sum())
        agrupados.append({
            "id":             f"cluster_{clus}",
            "operacion":      "Agrupado",
            "nombre_cliente": nombre_desc,
            "direccion":      direccion_desc,
