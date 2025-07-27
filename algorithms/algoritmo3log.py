# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 10 * 60
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60
PESO_RETRASO = 15
PESO_JORNADA_EXT = 20
PESO_ESPERA = 1

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME] * len(ventanas))
    n = len(ventanas)

    model = cp_model.CpModel()

    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, 3600, f"ret_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, 3600, f"wait_{i}") for i in range(n)]

    # Flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo + penalizaciones
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

        # Espera modelada correctamente
        bool_on_time = model.NewBoolVar(f"on_time_{i}")
        model.Add(t[i] >= ini).OnlyEnforceIf(bool_on_time)
        model.Add(t[i] < ini).OnlyEnforceIf(bool_on_time.Not())

        temp_wait = model.NewIntVar(-24*3600, 24*3600, f"temp_wait_{i}")
        model.Add(temp_wait == t[i] - ini)
        model.Add(espera[i] == temp_wait).OnlyEnforceIf(bool_on_time)
        model.Add(espera[i] == 0).OnlyEnforceIf(bool_on_time.Not())

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
    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)

    delta_ext = model.NewIntVar(0, 3600 * 4, "delta_ext")
    ext_bool = model.NewBoolVar("extendida")
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(ext_bool)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(ext_bool.Not())
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(ext_bool)
    model.Add(delta_ext == 0).OnlyEnforceIf(ext_bool.Not())

    # Objetivo
    obj_terms = []
    for i in range(n):
        w_i = max(1, ventanas[i][1] - ventanas[i][0])
        obj_terms.append(PESO_RETRASO * retraso[i] // w_i)
        obj_terms.append(PESO_ESPERA * espera[i] // 60)
    obj_terms.append(PESO_JORNADA_EXT * delta_ext // 60)

    dist_total = sum(dist[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j)
    model.Minimize(dist_total + sum(obj_terms))

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

        if len(ruta) < n:
            print("⚠️ Solución incompleta: fallback activado.")
        else:
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

    # Fallback: Nearest Insertion
    print("⚠️ No se encontró solución CP-SAT. Usando fallback...")

    def insertion_fallback():
        remaining = set(range(1, n))
        ruta = [0]
        llegada = [ventanas[0][0]]
        while remaining:
            best, best_eta, best_pos = None, None, None
            for cand in remaining:
                for pos in range(1, len(ruta) + 1):
                    prev = ruta[pos - 1]
                    eta = llegada[pos - 1] + service_times[prev] + dur[prev][cand]
                    if eta < ventanas[cand][0]:
                        eta = ventanas[cand][0]
                    if eta > ventanas[cand][1]:
                        continue
                    if best is None or eta < best_eta:
                        best, best_eta, best_pos = cand, eta, pos
            if best is None:
                break
            ruta.insert(best_pos, best)
            llegada.insert(best_pos, best_eta)
            remaining.remove(best)
        distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))
        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": distancia_total
        }

    return insertion_fallback()
