# algorithms/algoritmo3log.py
from ortools.sat.python import cp_model
import numpy as np
import time

# Constantes del problema
SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 30 * 60
SHIFT_HARD_LIMIT = 16 * 3600 + 45 * 60  # 16:45

# Pesos para penalizaciones
PESO_RETRASO = 3
PESO_JORNADA_EXT = 6
PESO_ESPERA = 1

def optimizar_ruta_cp_sat(data, tiempo_max_seg=60):
    n = len(data["time_windows"])
    D = data["duration_matrix"]

    model = cp_model.CpModel()

    x = [model.NewIntVar(0, n - 1, f"x_{i}") for i in range(n)]
    t = [model.NewIntVar(SHIFT_START, SHIFT_HARD_LIMIT, f"t_{i}") for i in range(n)]

    model.AddAllDifferent(x)

    for i in range(n - 1):
        u = x[i]
        v = x[i + 1]
        dur = D[u.Index()][v.Index()]
        model.Add(t[v.Index()] >= t[u.Index()] + SERVICE_TIME + dur)

    # Ventanas de tiempo
    retraso = []
    espera = []
    penalizaciones = []

    for i in range(n):
        ini, fin = data["time_windows"][i]
        retraso_i = model.NewIntVar(0, SHIFT_HARD_LIMIT, f"retraso_{i}")
        espera_i = model.NewIntVar(0, SHIFT_HARD_LIMIT, f"espera_{i}")
        ancho = max(1, fin - ini)

        # t[i] > fin ⇒ retraso = t[i] - fin
        late = model.NewBoolVar(f"late_{i}")
        model.Add(t[i] > fin).OnlyEnforceIf(late)
        model.Add(t[i] <= fin).OnlyEnforceIf(late.Not())
        diff_late = model.NewIntVar(0, SHIFT_HARD_LIMIT, f"diff_late_{i}")
        model.Add(diff_late == t[i] - fin)
        model.Add(retraso_i == diff_late).OnlyEnforceIf(late)
        model.Add(retraso_i == 0).OnlyEnforceIf(late.Not())

        # t[i] < ini ⇒ espera = ini - t[i]
        early = model.NewBoolVar(f"early_{i}")
        model.Add(t[i] < ini).OnlyEnforceIf(early)
        model.Add(t[i] >= ini).OnlyEnforceIf(early.Not())
        diff_early = model.NewIntVar(0, SHIFT_HARD_LIMIT, f"diff_early_{i}")
        model.Add(diff_early == ini - t[i])
        model.Add(espera_i == diff_early).OnlyEnforceIf(early)
        model.Add(espera_i == 0).OnlyEnforceIf(early.Not())

        retraso.append(retraso_i)
        espera.append(espera_i)

        # Penalización proporcional a ancho de ventana
        model.AddDivisionEquality(model.NewIntVar(0, 1000, ""), retraso_i, ancho)
        penalizaciones.append(PESO_RETRASO * retraso_i // ancho)
        penalizaciones.append(PESO_ESPERA * espera_i // 60)

    # Penalización por extender jornada más allá de 16:30
    end_time = model.NewIntVar(SHIFT_START, SHIFT_HARD_LIMIT, "end_time")
    model.AddMaxEquality(end_time, [t[i] for i in range(n)])
    jornada_ext = model.NewIntVar(0, SHIFT_HARD_LIMIT, "jornada_ext")
    model.Add(jornada_ext == end_time - SHIFT_END)
    jornada_bool = model.NewBoolVar("jornada_extiende")
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(jornada_bool)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(jornada_bool.Not())
    model.Add(jornada_ext == 0).OnlyEnforceIf(jornada_bool.Not())
    penalizaciones.append(PESO_JORNADA_EXT * jornada_ext // 60)

    # Función objetivo
    model.Minimize(sum(penalizaciones))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = [solver.Value(x[i]) for i in range(n)]
        tiempos = [solver.Value(t[i]) for i in range(n)]
        orden_final = sorted(zip(orden, range(n)))
        route = [idx for _, idx in orden_final]
        arrival_sec = [tiempos[idx] for idx in route]
        distance_total_m = sum(data["distance_matrix"][route[i]][route[i + 1]] for i in range(len(route) - 1))
        return {
            "routes": [{
                "route": route,
                "arrival_sec": arrival_sec
            }],
            "distance_total_m": distance_total_m
        }

    # Fallback: retorna None si no hay solución
    return None
