# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 600  # 10 minutos
SHIFT_START = 9 * 3600
SHIFT_END   = 16 * 3600 + 15 * 60
TOL_RETRASO = 45 * 60

PESO_RETRASO       = 30
PESO_ANTICIPO      = 5
PESO_ESPERA        = 2
PESO_JORNADA_EXT   = 50

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso  = [model.NewIntVar(0, TOL_RETRASO, f"ret_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 3600, f"ant_{i}") for i in range(n)]
    espera   = [model.NewIntVar(0, 3600, f"espera_{i}") for i in range(n)]

    # Flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas y penalizaciones
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(espera[i] == ini - t[i]).OnlyEnforceIf(model.NewBoolVar(f"espera_b_{i}"))
        model.Add(anticipo[i] == ini - t[i]).OnlyEnforceIf(t[i] < ini)
        model.Add(retraso[i] == t[i] - fin).OnlyEnforceIf(t[i] > fin)

    # Restricción temporal
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

    # Jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 3600 * 4, "delta_ext")
    extendida = model.NewBoolVar("es_jornada_ext")
    model.Add(delta_ext == end_time - SHIFT_END)
    model.Add(delta_ext > 0).OnlyEnforceIf(extendida)
    model.Add(delta_ext <= 0).OnlyEnforceIf(extendida.Not())

    # Objetivo
    obj_terms = []
    for i in range(n):
        ancho = max(1, ventanas[i][1] - ventanas[i][0])
        obj_terms.append(PESO_RETRASO * retraso[i] // ancho)
        obj_terms.append(PESO_ANTICIPO * anticipo[i])
        obj_terms.append(PESO_ESPERA * espera[i])

    obj_terms.append(PESO_JORNADA_EXT * delta_ext)
    model.Minimize(sum(obj_terms))

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

        if len(ruta) >= n // 2:
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

    # --- Fallback Nearest Insertion ---
    def fallback_ni():
        nodos = list(range(n))
        ruta = [0]
        llegada = [ventanas[0][0]]

        pendientes = set(nodos) - {0}
        while pendientes:
            best_node = None
            best_idx = None
            best_eta = None
            best_delta = float("inf")
            for u in pendientes:
                for i in range(len(ruta)):
                    for j in range(i + 1, len(ruta) + 1):
                        temp_ruta = ruta[:i+1] + [u] + ruta[j:]
                        temp_eta = [ventanas[temp_ruta[0]][0]]
                        ok = True
                        for k in range(1, len(temp_ruta)):
                            prev = temp_ruta[k - 1]
                            curr = temp_ruta[k]
                            t_est = temp_eta[-1] + service_times[prev] + dur[prev][curr]
                            ini, fin = ventanas[curr]
                            if t_est > fin + TOL_RETRASO:
                                ok = False
                                break
                            temp_eta.append(max(ini, t_est))
                        if ok:
                            costo = sum(dist[temp_ruta[k]][temp_ruta[k+1]] for k in range(len(temp_ruta)-1))
                            if costo < best_delta:
                                best_node = u
                                best_idx = j
                                best_eta = temp_eta
                                best_delta = costo
            if best_node is None:
                break
            ruta.insert(best_idx - 1, best_node)
            llegada = best_eta
            pendientes.remove(best_node)

        distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))
        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": distancia_total
        }

    return fallback_ni()
