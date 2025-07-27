from ortools.sat.python import cp_model
import numpy as np
from typing import Dict, Any

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 120) -> Dict[str, Any]:
    n = len(data["time_windows"])
    dur = data["duration_matrix"]
    win = data["time_windows"]
    service = data["service_times"]

    SHIFT_START = 9 * 3600
    SHIFT_END   = 16 * 3600 + 15 * 60
    PESO_RETRASO = 4
    PESO_ANTICIPO = 1
    PESO_JORNADA_EXT = 10
    PESO_ESPERA = 1

    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso  = [model.NewIntVar(0, 12*3600, f"ret_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 12*3600, f"ant_{i}") for i in range(n)]
    espera   = [model.NewIntVar(0, 12*3600, f"espera_{i}") for i in range(n)]

    for i in range(n):
        ini, fin = win[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + 3600)

        model.Add(retraso[i] >= t[i] - fin)
        model.Add(anticipo[i] >= ini - t[i])
        model.Add(espera[i] >= ini - t[i])

    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) <= 1)
        model.Add(sum(x[j, i] for j in range(n) if j != i) <= 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    total_retraso = model.NewIntVar(0, n * 3600, "total_retraso")
    total_anticipo = model.NewIntVar(0, n * 3600, "total_anticipo")
    total_espera = model.NewIntVar(0, n * 3600, "total_espera")

    model.Add(total_retraso == sum(
        model.NewIntVarFromDomain(cp_model.Domain.FromFlatIntervals([0, 10000]),
        f"wr_{i}") for i in range(n)))

    model.Add(total_anticipo == sum(anticipo))
    model.Add(total_espera == sum(espera))

    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    penal_ext = model.NewIntVar(0, 8 * 3600, "delta_ext")
    model.Add(penal_ext >= end_time - SHIFT_END)
    model.Add(penal_ext >= 0)

    obj = (
        PESO_RETRASO * total_retraso +
        PESO_ANTICIPO * total_anticipo +
        PESO_ESPERA * total_espera +
        PESO_JORNADA_EXT * penal_ext
    )
    model.Minimize(obj)

    status = solver.Solve(model)
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = []
        tiempos = []
        visitado = [False] * n
        actual = np.argmin([solver.Value(t[i]) for i in range(n)])
        while not visitado[actual]:
            orden.append(actual)
            tiempos.append(solver.Value(t[actual]))
            visitado[actual] = True
            siguiente = None
            for j in range(n):
                if (actual, j) in x and solver.BooleanValue(x[actual, j]):
                    siguiente = j
                    break
            if siguiente is None:
                break
            actual = siguiente

        return {
            "routes": [{
                "route": orden,
                "arrival_sec": tiempos
            }],
            "distance_total_m": 0
        }

    # --------- Fallback: orden híbrido por heurística ---------
    penalidades = []
    for i in range(n):
        ventana = win[i][1] - win[i][0]
        penal = ventana + sum(dur[i]) // n
        penalidades.append((penal, i))
    penalidades.sort()
    orden = [i for _, i in penalidades]
    tiempos = [SHIFT_START]
    for k in range(1, len(orden)):
        prev = orden[k - 1]
        curr = orden[k]
        llegada = tiempos[-1] + service[prev] + dur[prev][curr]
        tiempos.append(max(win[curr][0], llegada))

    return {
        "routes": [{
            "route": orden,
            "arrival_sec": tiempos
        }],
        "distance_total_m": 0
    }
