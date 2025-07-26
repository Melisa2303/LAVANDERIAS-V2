# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 10 * 60
SLACK_TOLERANCIA = 5 * 60

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=120):
    n = len(data["distance_matrix"])
    dist = np.array(data["distance_matrix"])
    dur = np.array(data["duration_matrix"])
    ventanas = data["time_windows"]
    demandas = data["demands"]
    capacidad = data.get("vehicle_capacities", [999])[0]

    model = cp_model.CpModel()
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]

    # Entradas y salidas únicas
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    # Depósito
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo con tolerancia
    for i, (ini, fin) in enumerate(ventanas):
        if ini is not None and fin is not None:
            model.Add(t[i] >= ini)
            model.Add(t[i] <= fin + SLACK_TOLERANCIA)

    # Restricción de tiempo de llegada
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + SERVICE_TIME + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar duración total
    model.Minimize(sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j))

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

    rutas = [{
        "vehicle": 0,
        "route": ruta,
        "arrival_sec": llegada
    }]

    return {
        "routes": rutas,
        "distance_total_m": int(sum(dist[i][j] for i, j in zip(ruta[:-1], ruta[1:]))),
        "arrival_sec_all_nodes": [solver.Value(t[i]) for i in range(n)]
    }
