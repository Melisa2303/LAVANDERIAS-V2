# algorithms/algoritmo3log.py
from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 600
SHIFT_START = 9 * 3600      # 09:00
SHIFT_END = 16 * 3600 + 15 * 60  # 16:15
PESO_RETRASO = 10
PESO_ANTICIPO = 6
PESO_ESPERA = 4
PESO_JORNADA_EXT = 20
FALLBACK_TIEMPO_ESPERA = 600

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    n = len(data["locations"])
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME] * n)

    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    arrival = [model.NewIntVar(0, 24 * 3600, f"arrival_{i}") for i in range(n)]

    for i in range(n):
        model.Add(arrival[i] >= ventanas[i][0])
        model.Add(arrival[i] <= ventanas[i][1])

    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
        model.Add(sum(x[j, i] for j in range(n) if i != j) == 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                t_ij = dur[i][j] + service_times[i]
                model.Add(arrival[j] >= arrival[i] + t_ij).OnlyEnforceIf(x[i, j])

    retraso, anticipo, espera = [], [], []
    for i in range(n):
        ret = model.NewIntVar(0, 24 * 3600, f"retraso_{i}")
        ant = model.NewIntVar(0, 24 * 3600, f"anticipo_{i}")
        esp = model.NewIntVar(0, 24 * 3600, f"espera_{i}")
        model.Add(ret >= arrival[i] - ventanas[i][1])
        model.Add(ant >= (ventanas[i][0] + ventanas[i][1]) // 2 - arrival[i])
        model.Add(esp >= (ventanas[i][0] - arrival[i]))
        retraso.append(ret)
        anticipo.append(ant)
        espera.append(esp)

    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, arrival)
    delta_ext = model.NewIntVar(0, 24 * 3600, "delta_ext")
    model.Add(delta_ext >= end_time - SHIFT_END)
    penal_ext = delta_ext

    total_retraso = sum(
        model.NewIntVar(0, 24 * 3600, f"wret_{i}") for i in range(n)
    )
    total_anticipo = sum(anticipo)
    total_espera = sum(espera)

    weighted_retraso = []
    for i in range(n):
        ventana_size = max(1, ventanas[i][1] - ventanas[i][0])
        mult = model.NewIntVar(0, 24 * 3600 * PESO_RETRASO, f"penret_{i}")
        model.AddMultiplicationEquality(mult, [retraso[i], PESO_RETRASO])
        peso = model.NewIntVar(0, 24 * 3600 * PESO_RETRASO, f"peso_ret_{i}")
        model.AddDivisionEquality(peso, mult, ventana_size)
        weighted_retraso.append(peso)

    obj = (
        sum(weighted_retraso) +
        PESO_ANTICIPO * total_anticipo +
        PESO_ESPERA * total_espera +
        PESO_JORNADA_EXT * penal_ext
    )
    model.Minimize(obj)

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        ruta = [0]
        actual = 0
        while True:
            next_nodes = [j for j in range(n) if j != actual and solver.Value(x[actual, j])]
            if not next_nodes:
                break
            actual = next_nodes[0]
            ruta.append(actual)
            if actual == 0:
                break
        llegada = [solver.Value(arrival[i]) for i in ruta]

        if len(ruta) < n:
            # Fallback heurístico si no cubrió todos
            return fallback_heuristica(data)
        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": calcular_distancia_total(ruta, dist),
        }
    else:
        return fallback_heuristica(data)

def fallback_heuristica(data):
    from heapq import heappush, heappop

    n = len(data["locations"])
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME] * n)

    visitado = [False] * n
    ruta = [0]
    llegada = [SHIFT_START]
    visitado[0] = True

    actual = 0
    tiempo_actual = SHIFT_START

    while len(ruta) < n:
        mejor = None
        mejor_eta = None
        for j in range(1, n):
            if visitado[j]:
                continue
            travel = dur[actual][j] + service_times[actual]
            eta = tiempo_actual + travel
            ini, fin = ventanas[j]
            eta_corr = max(eta, ini)
            if eta_corr <= fin:
                if mejor is None or eta_corr < mejor_eta:
                    mejor = j
                    mejor_eta = eta_corr
        if mejor is None:
            break
        actual = mejor
        tiempo_actual = mejor_eta
        llegada.append(tiempo_actual)
        ruta.append(actual)
        visitado[actual] = True

    return {
        "routes": [{
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": calcular_distancia_total(ruta, dist),
    }

def calcular_distancia_total(ruta, dist):
    return sum(dist[ruta[i]][ruta[i + 1]] for i in range(len(ruta) - 1))
