import pandas as pd
import math
import numpy as np
from ortools.sat.python import cp_model

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
            lat1, lon1 = map(math.radians, coords[i])
            lat2, lon2 = map(math.radians, coords[j])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
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
            fin = min(24*3600, fin + MARGEN)
        ventanas.append((ini, fin))
    return ventanas

def optimizar_ruta_cp_sat_puro(df, tiempo_max_seg=60):
    coords = list(zip(df["lat"], df["lon"]))
    n = len(coords)
    dist, dur = _haversine_dist_dur(coords)
    ventanas = _expandir_ventanas(df)
    demandas = df["demand"].fillna(1).astype(int).tolist()

    model = cp_model.CpModel()
    x = {(i, j): model.NewBoolVar(f'x_{i}_{j}') for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 86400, f't_{i}') for i in range(n)]

    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    for i, (ini, fin) in enumerate(ventanas):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + SERVICE_TIME + dur[i][j]).OnlyEnforceIf(x[i, j])

    model.Minimize(sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return {"routes": [], "distance_total_m": 0, "arrival_sec_all_nodes": []}

    route = [0]
    actual = 0
    while True:
        siguiente = None
        for j in range(n):
            if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                siguiente = j
                break
        if siguiente is None or siguiente == 0:
            break
        route.append(siguiente)
        actual = siguiente

    llegada = [solver.Value(t[i]) for i in route]
    llegada_full = [solver.Value(t[i]) for i in range(n)]

    total_dist = sum(
        dist[route[i]][route[i + 1]]
        for i in range(len(route) - 1)
    )

    return {
        "routes": [{"vehicle": 0, "route": route, "arrival_sec": llegada}],
        "distance_total_m": total_dist,
        "arrival_sec_all_nodes": llegada_full
    }
