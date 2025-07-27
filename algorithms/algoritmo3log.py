# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60  # 10 minutos
TOLERANCIA_RETRASO = 45 * 60    # 45 minutos
SHIFT_START = 9 * 3600          # 09:00
SHIFT_END = 16 * 3600 + 15 * 60 # 16:15

PESO_DISTANCIA   = 1
PESO_RETRASO     = 15
PESO_ANTICIPO    = 10
PESO_ESPERA      = 5
PESO_EXTENDIDO   = 20

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso  = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 4 * 3600, f"anti_{i}") for i in range(n)]
    espera   = [model.NewIntVar(0, 4 * 3600, f"espera_{i}") for i in range(n)]

    # Flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo y penalizaciones
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(anticipo[i] >= (ini + fin) // 2 - t[i])
        model.Add(anticipo[i] >= 0)

    # Restricciones de secuencia y espera
    for i in range(n):
        for j in range(n):
            if i != j:
                tij = t[j]
                ti = t[i]
                travel = dur[i][j]
                serv = service_times[i]
                model.Add(tij >= ti + serv + travel).OnlyEnforceIf(x[i, j])
                model.Add(espera[j] >= tij - (ti + serv + travel)).OnlyEnforceIf(x[i, j])

    # Jornada extendida
    end_time = model.NewIntVar(0, 24*3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    jornada_ext = model.NewIntVar(0, 24*3600, "delta_ext")
    model.Add(jornada_ext >= end_time - SHIFT_END)
    model.Add(jornada_ext >= 0)

    # Objetivo compuesto
    obj = 0
    obj += sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) * PESO_DISTANCIA
    obj += sum(retraso[i] * PESO_RETRASO // max(1, ventanas[i][1] - ventanas[i][0]) for i in range(n))
    obj += sum(anticipo[i] * PESO_ANTICIPO for i in range(n))
    obj += sum(espera[i] * PESO_ESPERA for i in range(n))
    obj += jornada_ext * PESO_EXTENDIDO
    model.Minimize(obj)

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
        if len(ruta) >= int(n * 0.8):
            distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))
            return {
                "routes": [{
                    "vehicle": 0,
                    "route": ruta,
                    "arrival_sec": llegada
                }],
                "distance_total_m": distancia_total
            }

    orden = sorted(range(n), key=lambda i: (ventanas[i][0], sum(dur[i]) + sum(dur[j][i] for j in range(n))))
    llegada = []
    hora_actual = SHIFT_START
    for i in orden:
        ini, _ = ventanas[i]
        hora_actual = max(hora_actual, ini)
        llegada.append(hora_actual)
        hora_actual += service_times[i]

    distancia_total = sum(dist[i][j] for i, j in zip(orden, orden[1:]))
    return {
        "routes": [{
            "vehicle": 0,
            "route": orden,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
