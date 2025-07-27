# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END   = 16 * 3600 + 15 * 60

PESO_RETRASO       = 20
PESO_ANTICIPO      = 3
PESO_ESPERA        = 1
PESO_JORNADA_EXT   = 15
PESO_NO_VISITAR    = 5000

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    try:
        D = data["duration_matrix"]
        ventanas = data["time_windows"]
        n = len(D)
        model = cp_model.CpModel()

        t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
        x = {(i,j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
        visited = [model.NewBoolVar(f"visited_{i}") for i in range(n)]

        for i in range(n):
            model.Add(sum(x[i,j] for j in range(n) if j != i) == visited[i])
            model.Add(sum(x[j,i] for j in range(n) if j != i) == visited[i])
            model.Add(t[i] >= ventanas[i][0]).OnlyEnforceIf(visited[i])
            model.Add(t[i] <= ventanas[i][1]).OnlyEnforceIf(visited[i])

        for i in range(n):
            for j in range(n):
                if i != j:
                    M = 24*3600
                    model.Add(t[j] >= t[i] + SERVICE_TIME + D[i][j]).OnlyEnforceIf(x[i,j])
                    model.Add(t[j] >= 0)

        # Penalizaciones
        anticipo = [model.NewIntVar(0, 12*3600, f"anticipo_{i}") for i in range(n)]
        retraso  = [model.NewIntVar(0, 12*3600, f"retraso_{i}")  for i in range(n)]
        espera   = [model.NewIntVar(0, 12*3600, f"espera_{i}")   for i in range(n)]

        for i in range(n):
            ini, fin = ventanas[i]
            model.Add(anticipo[i] == ini - t[i]).OnlyEnforceIf(t[i] < ini)
            model.Add(anticipo[i] == 0).OnlyEnforceIf(t[i] >= ini)
            model.Add(retraso[i] == t[i] - fin).OnlyEnforceIf(t[i] > fin)
            model.Add(retraso[i] == 0).OnlyEnforceIf(t[i] <= fin)
            model.Add(espera[i] == ini - t[i]).OnlyEnforceIf(t[i] < ini)
            model.Add(espera[i] == 0).OnlyEnforceIf(t[i] >= ini)

        # Jornada extendida
        end_time = model.NewIntVar(0, 24*3600, "end_time")
        model.AddMaxEquality(end_time, t)
        delta_ext = model.NewIntVar(0, 8*3600, "delta_ext")
        ext_bool = model.NewBoolVar("ext_bool")
        model.Add(end_time > SHIFT_END).OnlyEnforceIf(ext_bool)
        model.Add(end_time <= SHIFT_END).OnlyEnforceIf(ext_bool.Not())
        model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(ext_bool)
        model.Add(delta_ext == 0).OnlyEnforceIf(ext_bool.Not())

        penal_ext = model.NewIntVar(0, 100000, "penal_ext")
        model.AddMultiplicationEquality(penal_ext, [delta_ext, ext_bool])

        # Penalización proporcional al ancho de ventana
        obj_terms = []
        for i in range(n):
            ventana_i = ventanas[i][1] - ventanas[i][0] or 1
            peso_ret_i = model.NewIntVar(1, PESO_RETRASO, f"peso_ret_{i}")
            model.AddDivisionEquality(peso_ret_i, PESO_RETRASO, ventana_i)
            pen_ret = model.NewIntVar(0, 100000, f"pen_ret_{i}")
            model.AddMultiplicationEquality(pen_ret, [retraso[i], peso_ret_i])
            obj_terms.append(pen_ret)

        obj_terms += [
            PESO_ANTICIPO * anticipo[i] + 
            PESO_ESPERA * espera[i] for i in range(n)
        ]
        obj_terms.append(PESO_JORNADA_EXT * penal_ext)

        for i in range(n):
            obj_terms.append((1 - visited[i]) * PESO_NO_VISITAR)

        model.Minimize(sum(obj_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = tiempo_max_seg
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            orden = [i for i in range(n) if solver.Value(visited[i])]
            tiempos = [solver.Value(t[i]) for i in orden]
            return {
                "routes": [{
                    "route": orden,
                    "arrival_sec": tiempos
                }],
                "distance_total_m": 0
            }
        else:
            return _fallback_heuristica(data)

    except Exception as e:
        print("⚠️ Error en modelo CP-SAT:", e)
        return _fallback_heuristica(data)


def _fallback_heuristica(data):
    """Fallback basado en Nearest Insertion."""
    D = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)
    nodos = list(range(n))
    visitados = [0]  # inicia en planta
    restantes = set(nodos) - {0}
    llegada = {0: max(ventanas[0][0], SHIFT_START)}

    while restantes:
        mejor = None
        mejor_tiempo = float("inf")
        for nuevo in restantes:
            for i in visitados:
                t_llegada = llegada[i] + SERVICE_TIME + D[i][nuevo]
                if t_llegada < ventanas[nuevo][0]:
                    t_llegada = ventanas[nuevo][0]
                if t_llegada <= ventanas[nuevo][1] and t_llegada < mejor_tiempo:
                    mejor = nuevo
                    mejor_tiempo = t_llegada
        if mejor is None:
            mejor = restantes.pop()
            llegada[mejor] = SHIFT_END
        else:
            restantes.remove(mejor)
            llegada[mejor] = mejor_tiempo
        visitados.append(mejor)

    tiempos = [llegada[i] for i in visitados]
    return {
        "routes": [{
            "route": visitados,
            "arrival_sec": tiempos
        }],
        "distance_total_m": 0
    }
