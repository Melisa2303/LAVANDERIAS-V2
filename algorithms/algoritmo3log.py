# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO = 45 * 60         # 45 minutos
SHIFT_START = 9 * 3600               # 09:00
SHIFT_END = 16 * 3600 + 15 * 60      # 16:15
PESO_DISTANCIA = 1
PESO_RETRASO = 10
PESO_ANTICIPO = 2
PESO_EXTENDIDO = 15
PESO_ESPERA = 1

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
    anticipo = [model.NewIntVar(0, 12 * 3600, f"ant_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, 12 * 3600, f"espera_{i}") for i in range(n)]

    # Ventanas de tiempo con penalización por retraso y anticipo excesivo
    for i in range(n):
        ini, fin = ventanas[i]
        medio = (ini + fin) // 2
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(anticipo[i] >= medio - t[i])
        model.Add(anticipo[i] >= 0)

    # Flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Restricción de tiempo entre nodos y espera innecesaria
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j] - espera[j]).OnlyEnforceIf(x[i, j])

    # Subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Jornada laboral: penaliza extensión
    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, [t[i] for i in range(n)])
    delta_ext = model.NewIntVar(0, 8 * 3600, "delta_ext")
    model.Add(delta_ext >= end_time - SHIFT_END)
    model.Add(delta_ext >= 0)
    ext_bool = model.NewBoolVar("ext_bool")
    model.Add(delta_ext > 0).OnlyEnforceIf(ext_bool)
    model.Add(delta_ext == 0).OnlyEnforceIf(ext_bool.Not())
    ext_penal = model.NewIntVar(0, 8 * 3600 * PESO_EXTENDIDO, "ext_penal")
    model.AddMultiplicationEquality(ext_penal, [delta_ext, ext_bool])

    # Objetivo compuesto
    distancia_total = sum(dist[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j)
    obj = PESO_DISTANCIA * distancia_total
    for i in range(n):
        win_dur = max(1, ventanas[i][1] - ventanas[i][0])
        peso_retraso_i = PESO_RETRASO * 60 // win_dur
        obj += peso_retraso_i * retraso[i] + PESO_ANTICIPO * anticipo[i] + PESO_ESPERA * espera[i]
    obj += ext_penal
    model.Minimize(obj)

    # Solver
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

    # 🔁 Fallback si no hay solución
    ruta = list(range(n))
    llegada = [ventanas[i][0] + service_times[i] for i in ruta]
    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
