from ortools.sat.python import cp_model
import numpy as np
import math

SERVICE_TIME_DEFAULT = 10 * 60
BIG_M = 10**6
TOLERANCIA_RETRASO = 15 * 60  # 15 minutos
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 30 * 60
MARGEN = 15 * 60  # márgenes para extender ventana

def _hora_a_segundos(hora):
    try:
        h, m = map(int, str(hora).split(":"))
        return h * 3600 + m * 60
    except:
        return None

def _expandir_ventanas(ventanas_raw):
    ventanas = []
    for ini, fin in ventanas_raw:
        ini = ini if ini is not None else SHIFT_START_SEC
        fin = fin if fin is not None else SHIFT_END_SEC
        ventanas.append((
            max(0, ini - MARGEN),
            min(86400, fin + MARGEN)
        ))
    return ventanas

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas_raw = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas_raw))

    n = len(ventanas_raw)
    ventanas = _expandir_ventanas(ventanas_raw)

    model = cp_model.CpModel()

    # Variables
    x = {(i,j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 86400, f"t_{i}") for i in range(n)]
    visited = [model.NewBoolVar(f"visit_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"retraso_{i}") for i in range(n)]

    # Flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == visited[j])
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == visited[i])

    # Depósito
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)
    model.Add(visited[0] == 1)

    # Ventanas de tiempo con retraso suave
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Secuencias con tiempo de viaje y servicio
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Función objetivo
    model.Minimize(
        sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j)
        + sum(retraso[i] * 100 for i in range(n))
        + sum((1 - visited[i]) * BIG_M for i in range(1, n))
    )

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # No se halló solución, devolver algo no vacío
        return {
            "routes": [{
                "vehicle": 0,
                "route": [0],
                "arrival_sec": [SHIFT_START_SEC]
            }],
            "distance_total_m": 0
        }

    # Reconstrucción de ruta
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

    if len(ruta) == 1:
        # No se visitó ningún nodo más allá del depósito
        return {
            "routes": [{
                "vehicle": 0,
                "route": [0],
                "arrival_sec": [solver.Value(t[0])]
            }],
            "distance_total_m": 0
        }

    llegada = [solver.Value(t[i]) for i in ruta]

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": int(sum(dist[i][j] for i, j in zip(ruta, ruta[1:])))
    }
