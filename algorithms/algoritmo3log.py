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

# Constantes
SERVICE_TIME = 10 * 60
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 30 * 60
MARGEN = 15 * 60

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

# CP-SAT puro
def optimizar_ruta_cp_sat_puro(df, vehiculos=1, capacidad=999, timeout=60):
    coords = list(zip(df["lat"], df["lon"]))
    n = len(coords)
    dist, dur = _haversine_dist_dur(coords)
    ventanas = _expandir_ventanas(df)
    demandas = df["demand"].fillna(1).astype(int).tolist()

    model = cp_model.CpModel()

    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f'x_{i}_{j}')

    t = [model.NewIntVar(0, 86400, f't_{i}') for i in range(n)]

    # Restricción: cada nodo entrante y saliente (excepto depósito)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    # Depósito
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo
    for i, (ini, fin) in enumerate(ventanas):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    for i in range(n):
        for j in range(n):
            if i != j:
                travel = dur[i][j]
                model.Add(t[j] >= t[i] + SERVICE_TIME + travel).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar tiempo total
    model.Minimize(sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

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

    # Enviar a Firebase
    salida = []
    for i, idx in enumerate(ruta):
        item = df.iloc[idx].to_dict()
        item.update({
            "orden": i,
            "llegada_seg": llegada[i],
            "llegada_hora": f"{llegada[i]//3600:02}:{(llegada[i]%3600)//60:02}"
        })
        salida.append(item)

    # Guardar en colección
    for item in salida:
        db.collection("rutas_cp_sat").add(item)

    return pd.DataFrame(salida)
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
