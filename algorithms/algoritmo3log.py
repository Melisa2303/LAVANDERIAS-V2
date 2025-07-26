# algorithms/algoritmo3log.py
from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 10 * 60  # 10 minutos

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=60):
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(dist)
    depot = data.get("depot", 0)

    model = cp_model.CpModel()

    # Variables de decisión
    x = {
        (i, j): model.NewBoolVar(f"x_{i}_{j}")
        for i in range(n) for j in range(n)
        if i != j
    }

    t = [model.NewIntVar(0, 86400, f"t_{i}") for i in range(n)]

    # Flujo: cada nodo excepto depósito tiene una entrada y salida
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    # Flujo en depósito (inicio/fin)
    model.Add(sum(x[depot, j] for j in range(n) if j != depot) == 1)
    model.Add(sum(x[i, depot] for i in range(n) if i != depot) == 1)

    # Ventanas de tiempo
    for i, (ini, fin) in enumerate(ventanas):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    # Restricciones de tiempo de llegada
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + dur[i][j] + SERVICE_TIME).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar distancia
    model.Minimize(sum(dist[i][j] * x[i, j] for i, j in x))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # Reconstruir ruta
    actual = depot
    ruta = [actual]
    llegada = [solver.Value(t[actual])]
    visitados = set([actual])

    while True:
        siguiente = None
        for j in range(n):
            if j != actual and (actual, j) in x and solver.Value(x[actual, j]):
                siguiente = j
                break
        if siguiente is None or siguiente in visitados:
            break
        ruta.append(siguiente)
        llegada.append(solver.Value(t[siguiente]))
        visitados.add(siguiente)
        actual = siguiente

    return {
        "routes": [
            {
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }
        ],
        "distance_total_m": sum(dist[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1)),
        "arrival_sec_all_nodes": [solver.Value(t[i]) if i in ruta else None for i in range(n)],
    }
