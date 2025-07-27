# algorithms/algoritmo3log.py
# CP-SAT puro con penalización de espera innecesaria y fallback híbrido

from ortools.sat.python import cp_model
import numpy as np
from typing import Dict, Any
import math

# Constantes de penalización
PESO_RETRASO = 5
PESO_ESPERA = 1
PESO_JORNADA_EXT = 20

# Jornada
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any]:
    n = len(data["locations"])
    D = data["duration_matrix"]
    ventanas = data["time_windows"]
    service_times = data["service_times"]

    model = cp_model.CpModel()

    # Variables
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = [[model.NewBoolVar(f"x_{i}_{j}") for j in range(n)] for i in range(n)]
    espera = [model.NewIntVar(0, 12 * 3600, f"espera_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, 12 * 3600, f"retraso_{i}") for i in range(n)]

    M = 24 * 3600

    # Restricciones de flujo
    for i in range(n):
        model.Add(sum(x[i][j] for j in range(n) if j != i) == 1)
        model.Add(sum(x[j][i] for j in range(n) if j != i) == 1)
        model.Add(x[i][i] == 0)

    # Restricciones de tiempo
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + D[i][j] + service_times[i] - M * (1 - x[i][j]))

    # Ventanas de tiempo + penalizaciones
    penalizaciones = []
    for i in range(n):
        ini, fin = ventanas[i]

        model.Add(espera[i] == ini - t[i]).OnlyEnforceIf(model.NewBoolVar(f"b_espera_{i}"))
        model.Add(espera[i] == 0).OnlyEnforceIf(model.NewBoolVar(f"b_no_espera_{i}"))

        model.Add(retraso[i] == t[i] - fin).OnlyEnforceIf(model.NewBoolVar(f"b_retraso_{i}"))
        model.Add(retraso[i] == 0).OnlyEnforceIf(model.NewBoolVar(f"b_no_retraso_{i}"))

        ventana_i = max(1, fin - ini)
        penalizaciones.append(model.NewIntVar(0, 10000, f"pen_retraso_{i}"))
        model.AddDivisionEquality(penalizaciones[-1], PESO_RETRASO * retraso[i], ventana_i)

    # Penalización por jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 24 * 3600, "delta_ext")
    model.Add(delta_ext == end_time - SHIFT_END)
    penal_ext = model.NewIntVar(0, 10000, "pen_ext")
    model.AddMaxEquality(penal_ext, [delta_ext, model.NewConstant(0)])

    # Función objetivo
    obj = (
        sum(penalizaciones) +
        PESO_ESPERA * sum(espera) +
        PESO_JORNADA_EXT * penal_ext
    )
    model.Minimize(obj)

    # Solución
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        ruta = []
        tiempos = []
        usados = set()

        actual = 0
        while True:
            ruta.append(actual)
            tiempos.append(solver.Value(t[actual]))
            usados.add(actual)
            siguiente = -1
            for j in range(n):
                if j != actual and solver.BooleanValue(x[actual][j]) and j not in usados:
                    siguiente = j
                    break
            if siguiente == -1:
                break
            actual = siguiente

        if len(ruta) < n:
            return _fallback_nearest_insertion(data)

        dist_total = sum(data["distance_matrix"][ruta[i]][ruta[i+1]] for i in range(len(ruta)-1))
        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": tiempos
            }],
            "distance_total_m": dist_total
        }

    # Fallback si no hay solución
    return _fallback_nearest_insertion(data)

def _fallback_nearest_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    n = len(data["locations"])
    remaining = set(range(1, n))
    route = [0]
    arrival = [SHIFT_START]
    curr = 0

    while remaining:
        best_j, best_incr, best_eta = None, float('inf'), None
        for j in remaining:
            travel = data["duration_matrix"][curr][j]
            eta = arrival[-1] + data["service_times"][curr] + travel
            ini, fin = data["time_windows"][j]
            wait = max(0, ini - eta)
            penalty = wait + max(0, eta - fin) * 10
            if penalty < best_incr:
                best_j = j
                best_incr = penalty
                best_eta = eta + wait
        if best_j is None:
            break
        route.append(best_j)
        arrival.append(best_eta)
        remaining.remove(best_j)
        curr = best_j

    dist_total = sum(data["distance_matrix"][route[i]][route[i+1]] for i in range(len(route)-1))
    return {
        "routes": [{
            "route": route,
            "arrival_sec": arrival
        }],
        "distance_total_m": dist_total
    }
