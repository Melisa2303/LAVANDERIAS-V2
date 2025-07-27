from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60         # 10 minutos
TOLERANCIA_RETRASO = 30 * 60           # 30 minutos
SHIFT_START = 9 * 3600                 # 09:00 am
SHIFT_END = 16 * 3600 + 15 * 60        # 16:15 pm

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

    # Penalización por salirse de la jornada
    exceso_jornada = [model.NewIntVar(0, 3600, f"exceso_{i}") for i in range(n)]
    antes_jornada = [model.NewIntVar(0, SHIFT_START, f"antes_{i}") for i in range(n)]

    for i in range(1, n):  # No aplica a la cochera
        model.AddMaxEquality(exceso_jornada[i], [t[i] - SHIFT_END, 0])
        model.AddMaxEquality(antes_jornada[i], [SHIFT_START - t[i], 0])

    # Flujo
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

    # Restricción temporal: si x[i,j] entonces t[j] ≥ t[i] + dur + service
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

    # Objetivo
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) + 
        sum(retraso[i] * 50 for i in range(1, n)) +
        sum(exceso_jornada[i] * 100 for i in range(1, n)) +
        sum(antes_jornada[i] * 100 for i in range(1, n))
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstrucción de ruta
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

    # 🔁 Fallback: secuencia directa ordenada por ventana de fin
    orden = sorted(range(n), key=lambda i: (ventanas[i][1], ventanas[i][0]))
    ruta = orden
    llegada = []
    tiempo = max(ventanas[ruta[0]][0], SHIFT_START)
    for i in ruta:
        llegada.append(tiempo)
        tiempo += service_times[i]
    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
