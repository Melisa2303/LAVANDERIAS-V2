# algorithms/algoritmo3log.py
from ortools.sat.python import cp_model
import pandas as pd
import numpy as np

SERVICE_TIME = 600  # 10 minutos
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 1800

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=120):
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    demandas = data.get("demands", [1] * len(dist))
    n = len(dist)

    model = cp_model.CpModel()

    # Variables binarias de recorrido
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f'x_{i}_{j}')

    # Variables de tiempo de llegada
    t = [model.NewIntVar(0, 86400, f't_{i}') for i in range(n)]

    # Cada nodo tiene una entrada y una salida
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    # Salida y retorno desde depósito
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo como restricciones suaves
    penalidad = 1000  # peso de penalización
    penalizaciones = []

    for i, (ini, fin) in enumerate(ventanas):
        earliness = model.NewIntVar(0, 86400, f'early_{i}')
        lateness = model.NewIntVar(0, 86400, f'late_{i}')

        model.Add(earliness >= ini - t[i])
        model.Add(earliness >= 0)

        model.Add(lateness >= t[i] - fin)
        model.Add(lateness >= 0)

        penalizaciones.append(earliness)
        penalizaciones.append(lateness)

    # Restricciones de tiempo de llegada según las rutas
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + dur[i][j] + SERVICE_TIME).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar duración total y penalizaciones
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j)
        + penalidad * sum(penalizaciones)
    )

    # Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # Reconstruir la ruta
    ruta = [0]
    actual = 0
    visitados = set(ruta)
    while len(ruta) < n:
        siguiente = None
        for j in range(n):
            if j != actual and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                siguiente = j
                break
        if siguiente is None or siguiente in visitados:
            break
        ruta.append(siguiente)
        visitados.add(siguiente)
        actual = siguiente

    llegada = [solver.Value(t[i]) for i in ruta]

    # Formato de respuesta compatible con rutas3.py
    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": sum(dist[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1)),
        "arrival_sec_all_nodes": [solver.Value(t[i]) for i in range(n)],
    }
