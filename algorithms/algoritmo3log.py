# algorithms/algoritmo3log.py
# CP-SAT puro con penalización de jornada extendida y fallback robusto

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME = 600  # 10 minutos
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60

PESO_RETRASO = 15
PESO_ANTICIPO = 5
PESO_ESPERA = 1
PESO_JORNADA_EXT = 20

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)

    model = cp_model.CpModel()
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
        model.Add(sum(x[j, i] for j in range(n) if i != j) == 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + T[i][j] + SERVICE_TIME).OnlyEnforceIf(x[i, j])

    espera = []
    anticipo = []
    retraso = []
    for i in range(n):
        ini, fin = ventanas[i]
        ini = max(SHIFT_START, ini)
        fin = min(SHIFT_END, fin)
        ventana_i = max(1, fin - ini)

        # Variables de espera, anticipo y retraso
        espera_i = model.NewIntVar(0, 6 * 3600, f"espera_{i}")
        anticipo_i = model.NewIntVar(0, 6 * 3600, f"anticipo_{i}")
        retraso_i = model.NewIntVar(0, 6 * 3600, f"retraso_{i}")
        espera.append(espera_i)
        anticipo.append(anticipo_i)
        retraso.append(retraso_i)

        b_espera = model.NewBoolVar(f"b_espera_{i}")
        b_retraso = model.NewBoolVar(f"b_retraso_{i}")

        model.Add(t[i] < ini).OnlyEnforceIf(b_espera)
        model.Add(t[i] >= ini).OnlyEnforceIf(b_espera.Not())
        model.Add(anticipo_i == ini - t[i]).OnlyEnforceIf(b_espera)
        model.Add(anticipo_i == 0).OnlyEnforceIf(b_espera.Not())

        model.Add(t[i] > fin).OnlyEnforceIf(b_retraso)
        model.Add(t[i] <= fin).OnlyEnforceIf(b_retraso.Not())
        model.Add(retraso_i == t[i] - fin).OnlyEnforceIf(b_retraso)
        model.Add(retraso_i == 0).OnlyEnforceIf(b_retraso.Not())

        model.Add(espera_i == anticipo_i)

    # Jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 8 * 3600, "delta_ext")
    ext_bool = model.NewBoolVar("ext_bool")
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(ext_bool)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(ext_bool.Not())
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(ext_bool)
    model.Add(delta_ext == 0).OnlyEnforceIf(ext_bool.Not())

    # Objetivo
    obj_terms = []
    for i in range(n):
        ini, fin = ventanas[i]
        ventana_i = max(1, fin - ini)
        obj_terms.append(PESO_RETRASO * retraso[i] // ventana_i)
        obj_terms.append(PESO_ANTICIPO * anticipo[i] // ventana_i)
        obj_terms.append(PESO_ESPERA * espera[i] // ventana_i)
    obj_terms.append(PESO_JORNADA_EXT * delta_ext)
    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # reconstrucción de ruta
        llegada = [solver.Value(t[i]) for i in range(n)]
        visitados = set()
        ruta = [0]
        while len(ruta) < n:
            ult = ruta[-1]
            for j in range(n):
                if ult != j and (ult, j) in x and solver.Value(x[ult, j]):
                    if j not in visitados:
                        ruta.append(j)
                        visitados.add(j)
                        break
            else:
                break

        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": [llegada[i] for i in ruta]
            }],
            "distance_total_m": sum(D[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1))
        }

    # Fallback básico (no optimal)
    return {
        "routes": [{
            "route": list(range(n)),
            "arrival_sec": [SHIFT_START + sum(T[i][i+1] + SERVICE_TIME for i in range(j)) for j in range(n)]
        }],
        "distance_total_m": sum(D[i][i+1] for i in range(n-1))
    }
