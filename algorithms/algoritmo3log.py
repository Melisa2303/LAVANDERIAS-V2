from ortools.sat.python import cp_model
import pandas as pd
import math
import numpy as np
import googlemaps
import os
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import ace_tools as tools

# Inicializar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")
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

def _hora_a_segundos(hhmm):
    try:
        h, m = map(int, hhmm.split(":"))
        return h * 3600 + m * 60
    except:
        return None

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
            lat1, lon1 = math.radians(coords[i][0])
            lon1 = math.radians(coords[i][1])
            lat2 = math.radians(coords[j][0])
            lon2 = math.radians(coords[j][1])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            c = 2 * math.asin(math.sqrt(a))
            d = R * c
            dist[i][j] = int(d)
            dur[i][j] = int(d / v_ms)
    return dist, dur

def _expandir_ventanas(df):
    ventanas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(24 * 3600, fin + MARGEN)
        ventanas.append((ini, fin))
    return ventanas

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    df = data["df"]
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

    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    for i, (ini, fin) in enumerate(ventanas):
        slack_inf = model.NewIntVar(0, 3600, f'slack_inf_{i}')
        slack_sup = model.NewIntVar(0, 3600, f'slack_sup_{i}')
        model.Add(t[i] >= ini - slack_inf)
        model.Add(t[i] <= fin + slack_sup)

    for i in range(n):
        for j in range(n):
            if i != j:
                travel = dur[i][j]
                model.Add(t[j] >= t[i] + SERVICE_TIME + travel).OnlyEnforceIf(x[i, j])

    model.Minimize(
        sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
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

    salida = []
    for i, idx in enumerate(ruta):
        item = df.iloc[idx].to_dict()
        item.update({
            "orden": i,
            "llegada_seg": llegada[i],
            "llegada_hora": f"{llegada[i]//3600:02}:{(llegada[i]%3600)//60:02}"
        })
        salida.append(item)

    for item in salida:
        db.collection("rutas_cp_sat").add(item)

    df_resultado = pd.DataFrame(salida)
    tools.display_dataframe_to_user(name="Ruta optimizada CP-SAT", dataframe=df_resultado)
    return {"routes": [{"vehicle": 0, "route": ruta, "arrival_sec": llegada}], "distance_total_m": int(np.sum(dist))}

