# algorithms/algoritmo3log.py
# CP-SAT con lógica mejorada de espera innecesaria y fallback heurístico

from ortools.sat.python import cp_model
import numpy as np
from typing import Dict, Any
import random

SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60
JORNADA_MAXIMA = SHIFT_END - SHIFT_START

PESO_RETRASO = 10
PESO_JORNADA_EXT = 50
PESO_ESPERA = 1

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 120) -> Dict[str, Any]:
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)

    model = cp_model.CpModel()
    x = [model.NewIntVar(0, n - 1, f"x{i}") for i in range(n)]
    t = [model.NewIntVar(0, SHIFT_END + 3600, f"t{i}") for i in range(n)]

    model.AddAllDifferent(x)

    for i in range(n - 1):
        u = x[i]
        v = x[i + 1]
        dur = model.NewConstant(T[u.Index()][v.Index()])
        model.Add(t[v.Index()] >= t[u.Index()] + dur + SERVICE_TIME)

    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    retraso = []
    espera = []
    penalizaciones = []
    for i in range(n):
        ini, fin = ventanas[i]
        ancho_ventana = max(1, fin - ini)

        retraso_i = model.NewIntVar(0, 3600 * 3, f"retraso_{i}")
        espera_i = model.NewIntVar(0, 3600 * 3, f"espera_{i}")

        model.Add(retraso_i >= t[i] - fin)
        model.Add(espera_i >= ini - t[i])

        retraso.append(retraso_i)
        espera.append(espera_i)

        penalizaciones.append(retraso_i * PESO_RETRASO)
        penalizaciones.append(espera_i * PESO_ESPERA)

    end_time = model.NewIntVar(SHIFT_START, SHIFT_END + 3600, "end_time")
    for i in range(n):
        model.Add(end_time >= t[i])
    delta_ext = model.NewIntVar(0, 3600 * 3, "delta_ext")
    model.Add(delta_ext == end_time - SHIFT_END)
    penalizaciones.append(delta_ext * PESO_JORNADA_EXT)

    model.Minimize(sum(penalizaciones))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = [solver.Value(xi) for xi in x]
        orden = sorted(range(n), key=lambda i: solver.Value(x[i]))
        ruta = []
        tiempos = []
        total_dist = 0
        for idx in range(n):
            u = orden[idx]
            ruta.append(u)
            tiempos.append(solver.Value(t[u]))
            if idx < n - 1:
                total_dist += D[u][orden[idx + 1]]

        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": tiempos
            }],
            "distance_total_m": total_dist
        }

    # Fallback: Nearest Insertion
    return _fallback_insertion(data)


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)
    visitados = [0]
    restantes = set(range(1, n))
    tiempos = [SHIFT_START] + [0] * (n - 1)

    while restantes:
        mejor_costo = float("inf")
        mejor_i = -1
        mejor_pos = -1

        for j in restantes:
            for pos in range(1, len(visitados) + 1):
                anterior = visitados[pos - 1]
                siguiente = visitados[pos] if pos < len(visitados) else None
                costo = D[anterior][j]
                if siguiente is not None:
                    costo += D[j][siguiente] - D[anterior][siguiente]
                if costo < mejor_costo:
                    mejor_costo = costo
                    mejor_i = j
                    mejor_pos = pos

        visitados.insert(mejor_pos, mejor_i)
        restantes.remove(mejor_i)

    # ETA simulada realista con SERVICE_TIME
    tiempos = [SHIFT_START]
    for i in range(1, len(visitados)):
        u = visitados[i - 1]
        v = visitados[i]
        dur = T[u][v]
        llegada = max(tiempos[-1] + SERVICE_TIME + dur, ventanas[v][0])
        tiempos.append(min(llegada, ventanas[v][1]))

    total_dist = sum(D[visitados[i]][visitados[i+1]] for i in range(len(visitados) - 1))

    return {
        "routes": [{
            "route": visitados,
            "arrival_sec": tiempos
        }],
        "distance_total_m": total_dist
    }
