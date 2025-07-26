from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60
BIG_M = 10**6
TOLERANCIA_RETRASO = 5 * 60  # Hasta 5 minutos fuera de la ventana permitida

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)

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

    # Ventanas de tiempo suaves con retraso permitido
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Restricciones de secuencia
    for i in range(n):
        for j in range(n):
            if i != j:
                travel = dur[i][j]
                model.Add(t[j] >= t[i] + service_times[i] + travel).OnlyEnforceIf(x[i, j])

    # Penalización por retrasos y saltos
    penalizacion = sum(x[i, j] * dur[i][j] for i in range(n) for j in range(n) if i != j)
    penalizacion += sum(retraso[i] * 100 for i in range(n))  # penaliza tardanza
    penalizacion += sum((1 - visited[i]) * BIG_M for i in range(1, n))  # evitar nodos no visitados

    model.Minimize(penalizacion)

    # Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

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

    llegada = [solver.Value(t[i]) for i in ruta]

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": int(sum(dist[i][j] for i, j in zip(ruta, ruta[1:])))
    }
