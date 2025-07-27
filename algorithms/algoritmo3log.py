# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

# Constantes
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 30 * 60
SERVICE_TIME = 600  # 10 minutos

# Penalizaciones
PESO_RETRASO = 100
PESO_ESPERA = 1
PESO_JORNADA_EXT = 1000

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    from time import time
    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    n = len(data["time_windows"])
    D = data["duration_matrix"]

    # Variables de orden y tiempo de llegada
    x = [model.NewIntVar(0, n - 1, f"x_{i}") for i in range(n)]
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]

    # Restricciones de orden único
    model.AddAllDifferent(x)

    # Mapear posición -> nodo
    x_inv = [model.NewIntVar(0, n - 1, f"xinv_{i}") for i in range(n)]
    for i in range(n):
        model.AddElement(x[i], x_inv, i)

    # Tiempo de servicio
    for i in range(n - 1):
        orig = x[i]
        dest = x[i + 1]
        dur = model.NewIntVar(0, 24 * 3600, f"dur_{i}")
        model.AddElement(orig * n + dest, sum(D, []), dur)
        model.Add(t[x[i + 1]] >= t[x[i]] + SERVICE_TIME + dur)

    # Ventanas de tiempo
    retraso = []
    espera = []
    penalizaciones = []
    for i in range(n):
        ini, fin = data["time_windows"][i]
        ancho = max(1, fin - ini)

        retraso_i = model.NewIntVar(0, 3600 * 12, f"retraso_{i}")
        espera_i = model.NewIntVar(0, 3600 * 12, f"espera_{i}")
        model.Add(retraso_i >= t[i] - fin)
        model.Add(retraso_i >= 0)
        model.Add(espera_i >= ini - t[i])
        model.Add(espera_i >= 0)

        # Penalización proporcional al ancho de ventana
        model.AddDivisionEquality(retraso_i, retraso_i, ancho)
        penalizaciones.append(PESO_RETRASO * retraso_i)

        espera.append(espera_i)
        retraso.append(retraso_i)

    # Jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 3600 * 12, "delta_ext")
    model.Add(delta_ext >= end_time - SHIFT_END)
    model.Add(delta_ext >= 0)
    penalizaciones.append(PESO_JORNADA_EXT * delta_ext)

    # Espera
    total_espera = model.NewIntVar(0, 3600 * 24, "total_espera")
    model.Add(total_espera == sum(espera))
    penalizaciones.append(PESO_ESPERA * total_espera)

    model.Minimize(sum(penalizaciones))

    # Solucionar
    status = solver.Solve(model)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = [solver.Value(x[i]) for i in range(n)]
        ruta = [None] * n
        for i, nodo in enumerate(orden):
            ruta[nodo] = i
        arrival = [solver.Value(t[i]) for i in ruta]
        distancia_total = sum(D[ruta[i]][ruta[i + 1]] for i in range(n - 1))
        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": arrival,
            }],
            "distance_total_m": distancia_total
        }

    # ---------------- FALLBACK: Nearest Insertion ----------------
    def fallback_nearest_insertion():
        from heapq import heappush, heappop
        unvisited = set(range(1, n))
        route = [0]
        arrival = [SHIFT_START]
        while unvisited:
            best_cost = float('inf')
            best_node = None
            best_pos = None
            for node in unvisited:
                for i in range(len(route) + 1):
                    new_route = route[:i] + [node] + route[i:]
                    cost = sum(D[new_route[j]][new_route[j + 1]] for j in range(len(new_route) - 1))
                    if cost < best_cost:
                        best_cost = cost
                        best_node = node
                        best_pos = i
            route.insert(best_pos, best_node)
            unvisited.remove(best_node)
        # ETA
        eta = [SHIFT_START]
        for i in range(1, len(route)):
            eta.append(eta[-1] + D[route[i - 1]][route[i]] + SERVICE_TIME)
        distancia_total = sum(D[route[i]][route[i + 1]] for i in range(len(route) - 1))
        return {
            "routes": [{
                "route": route,
                "arrival_sec": eta,
            }],
            "distance_total_m": distancia_total
        }

    return fallback_nearest_insertion()
