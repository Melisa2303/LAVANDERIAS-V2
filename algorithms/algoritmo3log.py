from ortools.sat.python import cp_model
import numpy as np
import math

SERVICE_TIME = 10 * 60
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 30 * 60
MARGEN = 15 * 60

def _hora_a_segundos(hora):
    try:
        h, m = map(int, str(hora).split(":"))
        return h * 3600 + m * 60
    except:
        return None

def _expandir_ventanas(df):
    ventanas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(86400, fin + MARGEN)
        ventanas.append((ini, fin))
    return ventanas

def _dist_dur_matrix(coords, vel_kmh=40):
    R = 6371e3
    v_ms = vel_kmh * 1000 / 3600
    n = len(coords)
    dist = np.zeros((n, n), dtype=int)
    dur = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(n):
            if i == j: continue
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

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    import pandas as pd

    df = data["df"]
    coords = list(zip(df["lat"], df["lon"]))
    n = len(coords)
    dist, dur = _dist_dur_matrix(coords)
    ventanas = _expandir_ventanas(df)

    model = cp_model.CpModel()

    x = {(i,j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 86400, f"t_{i}") for i in range(n)]
    visited = [model.NewBoolVar(f"visit_{i}") for i in range(n)]

    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i != j) == visited[j])
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if i != j) == visited[i])

    model.Add(sum(x[0,j] for j in range(1, n)) == 1)
    model.Add(sum(x[i,0] for i in range(1, n)) == 1)
    model.Add(visited[0] == 1)

    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + SERVICE_TIME + dur[i][j]).OnlyEnforceIf(x[i,j])

    BIG_M = 100000
    penalty_not_visited = BIG_M
    model.Minimize(
        sum(x[i,j] * dur[i][j] for i in range(n) for j in range(n) if i != j)
        + sum((1 - visited[i]) * penalty_not_visited for i in range(1, n))
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    ruta = [0]
    actual = 0
    while True:
        found = False
        for j in range(n):
            if actual != j and (actual,j) in x and solver.Value(x[actual,j]) == 1:
                ruta.append(j)
                actual = j
                found = True
                break
        if not found:
            break

    llegada = [solver.Value(t[i]) for i in ruta]

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": int(sum(dist[i][j] for i,j in zip(ruta, ruta[1:])))
    }
