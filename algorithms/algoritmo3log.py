from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO = 45 * 60         # 45 minutos

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

    # Flujo: exactamente una entrada y salida por nodo (excepto depósito)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo con tolerancia
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Secuencia temporal: si voy de i a j, entonces t[j] ≥ t[i] + service + travel
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Penalización proporcional al tamaño de la ventana (más peso a ventanas pequeñas)
    pesos_ventana = [max(1, 14400 // (vent[1] - vent[0])) for vent in ventanas]

    # Objetivo: minimizar distancia + retraso ponderado
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * pesos_ventana[i] for i in range(n))
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

    # ------------------------ 🔁 Fallback: Ruta aproximada ------------------------

    # Heurística: ordenar por inicio de ventana y cercanía
    restantes = set(range(1, n))
    ruta = [0]
    llegada = [ventanas[0][0]]
    actual = 0
    t_actual = ventanas[0][0]

    while restantes:
        candidatos = sorted(
            list(restantes),
            key=lambda j: (ventanas[j][0], dur[actual][j])
        )
        siguiente = candidatos[0]
        t_llegada = t_actual + service_times[actual] + dur[actual][siguiente]
        ruta.append(siguiente)
        llegada.append(t_llegada)
        t_actual = t_llegada
        actuales = siguientes = siguiente
        restantes.remove(siguiente)
        actual = siguiente

    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
