# algorithms/algoritmo3log.py
from ortools.sat.python import cp_model
import pandas as pd
import numpy as np

SERVICE_TIME = 600  # 10 minutos

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=180):
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(dist)

    model = cp_model.CpModel()
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    t = [model.NewIntVar(0, 86400, f"t_{i}") for i in range(n)]
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]  # para subtour elimination (MTZ)

    # Ventanas como penalización suave
    penalties = []
    for i, (start, end) in enumerate(ventanas):
        early = model.NewIntVar(0, 86400, f"early_{i}")
        late = model.NewIntVar(0, 86400, f"late_{i}")
        model.Add(early >= start - t[i])
        model.Add(late >= t[i] - end)
        penalties.append(early)
        penalties.append(late)

    # Restricciones de tiempo
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + dur[i][j] + SERVICE_TIME).OnlyEnforceIf(x[i, j])

    # MTZ subtour elimination
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n * (1 - x[i, j])))

    # Depósito (0) tiene solo una salida
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)

    # Cada cliente tiene a lo más una entrada
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) <= 1)

    # Objetivo: distancia + penalización
    PENALIDAD_TIEMPO = 1000
    model.Minimize(
        sum(dist[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j)
        + PENALIDAD_TIEMPO * sum(penalties)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # Reconstruir ruta
    ruta = [0]
    actual = 0
    while True:
        next_node = None
        for j in range(n):
            if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                next_node = j
                break
        if next_node is None or next_node in ruta:
            break
        ruta.append(next_node)
        actual = next_node

    llegada = [solver.Value(t[i]) for i in ruta]
    total_dist = sum(dist[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": total_dist,
        "arrival_sec_all_nodes": [solver.Value(t[i]) for i in range(n)],
    }
