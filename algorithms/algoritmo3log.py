# algorithms/algoritmo3.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60         # 10 minutos
TOLERANCIA_RETRASO   = 45 * 60         # 45 minutos
PESO_RETRASO         = 15
PESO_TIEMPO_TOTAL    = 1
PESO_ESPERA          = 1

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, 24 * 3600, f"espera_{i}") for i in range(n)]

    # Restricciones de flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas y retrasos permitidos
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(espera[i] >= t[i] - ini)

    # Secuencia temporal
    for i in range(n):
        for j in range(n):
            if i != j:
                travel = dur[i][j]
                model.Add(t[j] >= t[i] + service_times[i] + travel).OnlyEnforceIf(x[i, j])

    # Subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Objetivo
    model.Minimize(
        sum(dur[i][j] * x[i, j] * PESO_TIEMPO_TOTAL for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * PESO_RETRASO for i in range(n)) +
        sum(espera[i] * PESO_ESPERA for i in range(n))
    )

    # Solución
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        ruta = [0]
        actual = 0
        visitados = set(ruta)
        while True:
            siguiente = None
            for j in range(n):
                if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                    siguiente = j
                    break
            if siguiente is None or siguiente in visitados:
                break
            ruta.append(siguiente)
            visitados.add(siguiente)
            actual = siguiente

        llegada = [solver.Value(t[i]) for i in ruta]
        distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": distancia_total
        }

    # Fallback greedy si el solver falla
    return fallback_greedy(data, dur, dist, ventanas, service_times)

# -------------------------------------------------------

def fallback_greedy(data, dur, dist, ventanas, service_times):
    n = len(ventanas)
    nodos = list(range(1, n))
    secuencia = [0]  # iniciar en depósito
    actual = 0
    tiempo_actual = ventanas[0][0]

    pendientes = nodos.copy()
    llegada = [tiempo_actual]

    while pendientes:
        def prioridad(j):
            ini, fin = ventanas[j]
            margen = fin - ini
            dist_travel = dur[actual][j]
            delta_tiempo = max(0, ini - (tiempo_actual + service_times[actual] + dist_travel))
            return (
                margen + delta_tiempo + dist_travel
            )

        siguiente = min(pendientes, key=prioridad)
        travel = dur[actual][siguiente]
        t_llegada = max(ventanas[siguiente][0], tiempo_actual + service_times[actual] + travel)
        llegada.append(t_llegada)
        secuencia.append(siguiente)
        tiempo_actual = t_llegada
        actual = siguiente
        pendientes.remove(siguiente)

    distancia_total = sum(dist[i][j] for i, j in zip(secuencia, secuencia[1:]))
    return {
        "routes": [{
            "vehicle": 0,
            "route": secuencia,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
