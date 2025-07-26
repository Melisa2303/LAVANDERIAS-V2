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
    n = len(data["locations"])
    dur = np.array(data["duration_matrix"])
    dist = np.array(data["distance_matrix"])
    ventanas = data["time_windows"]

    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f'x_{i}_{j}') for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 86400, f't_{i}') for i in range(n)]
    visitado = [model.NewBoolVar(f'visit_{i}') for i in range(n)]

    # Restricciones de flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == visitado[j])
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == visitado[i])
    model.Add(visitado[0] == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo con tolerancia
    tolerancia = 5 * 60  # 5 minutos de tolerancia
    for i, (ini, fin) in enumerate(ventanas):
        model.Add(t[i] >= max(0, ini - tolerancia))
        model.Add(t[i] <= min(86400, fin + tolerancia))

    # Secuenciación temporal
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + SERVICE_TIME + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar duración + penalización por no visitar
    penalidad = sum((1 - visitado[i]) * BIG_M for i in range(1, n))
    duracion_total = sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j)
    model.Minimize(duracion_total + penalidad)

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # Reconstruir ruta
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

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": int(sum(dist[i][j] for i, j in zip(ruta, ruta[1:])))
    }
