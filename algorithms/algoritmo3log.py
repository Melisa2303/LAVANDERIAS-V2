# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60

PESO_RETRASO = 5
PESO_ANTICIPO = 2
PESO_ESPERA = 1
PESO_JORNADA_EXT = 10

def optimizar_ruta_cp_sat(data, tiempo_max_seg=60):
    n = len(data["time_windows"])
    D = data["duration_matrix"]

    model = cp_model.CpModel()
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]

    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) <= 1)
        model.Add(sum(x[j, i] for j in range(n) if j != i) <= 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + D[i][j] + SERVICE_TIME).OnlyEnforceIf(x[i, j])

    for i in range(n):
        ini, fin = data["time_windows"][i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    retraso = [model.NewIntVar(0, 3600 * 8, f"retraso_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 3600 * 8, f"anticipo_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, 3600 * 8, f"espera_{i}") for i in range(n)]

    for i in range(n):
        ini, fin = data["time_windows"][i]
        model.Add(retraso[i] == t[i] - fin).OnlyEnforceIf(model.NewBoolVar(f"r_on_{i}"))
        model.Add(anticipo[i] == ini - t[i]).OnlyEnforceIf(model.NewBoolVar(f"a_on_{i}"))
        model.Add(espera[i] == t[i] - ini)

    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    penal_ext = model.NewIntVar(0, 3600 * 4, "delta_ext")
    ext_bool = model.NewBoolVar("ext_bool")
    model.Add(penal_ext == end_time - SHIFT_END).OnlyEnforceIf(ext_bool)
    model.Add(penal_ext == 0).OnlyEnforceIf(ext_bool.Not())
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(ext_bool)

    obj_terms = []
    for i in range(n):
        w_i = max(1, data["time_windows"][i][1] - data["time_windows"][i][0])
        retraso_i = retraso[i]
        anticipo_i = anticipo[i]
        espera_i = espera[i]
        model.AddDivisionEquality(retraso_i, retraso_i, 1)
        model.AddDivisionEquality(anticipo_i, anticipo_i, 1)
        model.AddDivisionEquality(espera_i, espera_i, 1)
        obj_terms.append(PESO_RETRASO * retraso_i)
        obj_terms.append(PESO_ANTICIPO * anticipo_i)
        obj_terms.append(PESO_ESPERA * espera_i)

    obj_terms.append(PESO_JORNADA_EXT * penal_ext)
    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        secuencia = [0]
        visitado = set(secuencia)
        while len(secuencia) < n:
            ult = secuencia[-1]
            for j in range(n):
                if j not in visitado and (ult, j) in x and solver.Value(x[ult, j]):
                    secuencia.append(j)
                    visitado.add(j)
                    break
            else:
                break

        if len(secuencia) < n:
            print("Solución parcial encontrada, usando fallback.")
            return _fallback_cheapest_insertion(data)

        arrival_sec = [solver.Value(t[i]) for i in secuencia]

        distance_total_m = 0
        for i in range(len(secuencia) - 1):
            distance_total_m += data["distance_matrix"][secuencia[i]][secuencia[i + 1]]

        return {
            "routes": [{
                "route": secuencia,
                "arrival_sec": arrival_sec
            }],
            "distance_total_m": distance_total_m
        }

    else:
        print("No se encontró solución CP-SAT, usando fallback.")
        return _fallback_cheapest_insertion(data)

def _fallback_cheapest_insertion(data):
    n = len(data["duration_matrix"])
    visitados = set([0])
    ruta = [0]

    arrival_sec = [data["time_windows"][0][0]]
    while len(visitados) < n:
        mejor = None
        mejor_costo = float("inf")
        for i in range(1, n):
            if i in visitados:
                continue
            for j in range(1, len(ruta) + 1):
                previa = ruta[j - 1]
                sig = ruta[j] if j < len(ruta) else 0
                costo = (data["duration_matrix"][previa][i] +
                         data["duration_matrix"][i][sig] -
                         data["duration_matrix"][previa][sig])
                if costo < mejor_costo:
                    mejor = (i, j)
                    mejor_costo = costo
        if mejor is None:
            break
        nodo, pos = mejor
        ruta.insert(pos, nodo)
        visitados.add(nodo)

    arrival_sec = [data["time_windows"][0][0]]
    for i in range(1, len(ruta)):
        prev = ruta[i - 1]
        curr = ruta[i]
        prev_arrival = arrival_sec[-1]
        travel = data["duration_matrix"][prev][curr]
        earliest = data["time_windows"][curr][0]
        arrival = max(prev_arrival + SERVICE_TIME + travel, earliest)
        arrival_sec.append(arrival)

    distance_total_m = 0
    for i in range(len(ruta) - 1):
        distance_total_m += data["distance_matrix"][ruta[i]][ruta[i + 1]]

    return {
        "routes": [{
            "route": ruta,
            "arrival_sec": arrival_sec
        }],
        "distance_total_m": distance_total_m
    }
