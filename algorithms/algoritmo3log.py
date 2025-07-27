# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import math

SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60
SERVICE_TIME = 600  # 10 minutos

PESO_RETRASO = 1000
PESO_ANTICIPO = 500
PESO_ESPERA = 200
PESO_JORNADA_EXT = 3000

def optimizar_ruta_cp_sat(data, tiempo_max_seg=60):
    n = len(data["time_windows"])
    model = cp_model.CpModel()

    # Variables
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = [[model.NewBoolVar(f"x_{i}_{j}") for j in range(n)] for i in range(n)]

    M = 24 * 3600
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + data["duration_matrix"][i][j] + SERVICE_TIME).OnlyEnforceIf(x[i][j])

    # Cada nodo tiene exactamente una entrada y una salida (excepto depósito)
    for i in range(1, n):
        model.Add(sum(x[j][i] for j in range(n) if j != i) == 1)
        model.Add(sum(x[i][j] for j in range(n) if j != i) == 1)

    # No permitir bucles
    for i in range(n):
        model.Add(x[i][i] == 0)

    # Ventanas de tiempo
    for i in range(n):
        ini, fin = data["time_windows"][i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    # Penalizaciones proporcionales
    penalizaciones = []
    for i in range(1, n):
        ini, fin = data["time_windows"][i]
        ventana_i = max(1, fin - ini)

        # Retraso
        retraso_i = model.NewIntVar(0, M, f"retraso_{i}")
        bool_retraso = model.NewBoolVar(f"bool_retraso_{i}")
        model.Add(t[i] > fin).OnlyEnforceIf(bool_retraso)
        model.Add(t[i] <= fin).OnlyEnforceIf(bool_retraso.Not())
        model.Add(retraso_i == t[i] - fin).OnlyEnforceIf(bool_retraso)
        model.Add(retraso_i == 0).OnlyEnforceIf(bool_retraso.Not())

        div_retraso = model.NewIntVar(0, PESO_RETRASO, f"div_retraso_{i}")
        model.AddDivisionEquality(div_retraso, retraso_i, ventana_i)
        penalizaciones.append(PESO_RETRASO * div_retraso)

        # Anticipo
        anticipo_i = model.NewIntVar(0, M, f"anticipo_{i}")
        bool_anticipo = model.NewBoolVar(f"bool_anticipo_{i}")
        model.Add(t[i] < ini).OnlyEnforceIf(bool_anticipo)
        model.Add(t[i] >= ini).OnlyEnforceIf(bool_anticipo.Not())
        model.Add(anticipo_i == ini - t[i]).OnlyEnforceIf(bool_anticipo)
        model.Add(anticipo_i == 0).OnlyEnforceIf(bool_anticipo.Not())

        div_anticipo = model.NewIntVar(0, PESO_ANTICIPO, f"div_anticipo_{i}")
        model.AddDivisionEquality(div_anticipo, anticipo_i, ventana_i)
        penalizaciones.append(PESO_ANTICIPO * div_anticipo)

        # Espera innecesaria
        espera_i = model.NewIntVar(0, M, f"espera_{i}")
        bool_espera = model.NewBoolVar(f"bool_espera_{i}")
        mid = (ini + fin) // 2
        model.Add(t[i] < mid).OnlyEnforceIf(bool_espera)
        model.Add(t[i] >= mid).OnlyEnforceIf(bool_espera.Not())
        model.Add(espera_i == mid - t[i]).OnlyEnforceIf(bool_espera)
        model.Add(espera_i == 0).OnlyEnforceIf(bool_espera.Not())

        div_espera = model.NewIntVar(0, PESO_ESPERA, f"div_espera_{i}")
        model.AddDivisionEquality(div_espera, espera_i, ventana_i)
        penalizaciones.append(PESO_ESPERA * div_espera)

    # Jornada extendida
    end_time = model.NewIntVar(0, M, "end_time")
    for i in range(n):
        model.AddMaxEquality(end_time, t)

    delta_ext = model.NewIntVar(0, M, "delta_ext")
    bool_ext = model.NewBoolVar("bool_ext")
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(bool_ext)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(bool_ext.Not())
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(bool_ext)
    model.Add(delta_ext == 0).OnlyEnforceIf(bool_ext.Not())
    penalizaciones.append(PESO_JORNADA_EXT * delta_ext)

    # Función objetivo
    model.Minimize(sum(penalizaciones))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = []
        llegada = []
        actual = 0
        visitado = set([actual])
        while True:
            orden.append(actual)
            llegada.append(solver.Value(t[actual]))
            siguiente = None
            for j in range(n):
                if j not in visitado and solver.Value(x[actual][j]) == 1:
                    siguiente = j
                    break
            if siguiente is None:
                break
            actual = siguiente
            visitado.add(actual)
        return {
            "routes": [
                {
                    "route": orden,
                    "arrival_sec": llegada
                }
            ]
        }
    else:
        # Fallback heurístico: nearest insertion
        return fallback_nearest_insertion(data)

def fallback_nearest_insertion(data):
    from heapq import heappush, heappop
    n = len(data["distance_matrix"])
    no_visitados = set(range(1, n))
    ruta = [0]
    llegada = [SHIFT_START]
    actual = 0
    tiempo_actual = SHIFT_START

    while no_visitados:
        candidatos = []
        for j in no_visitados:
            dur = data["duration_matrix"][actual][j]
            arr = max(tiempo_actual + SERVICE_TIME + dur, data["time_windows"][j][0])
            if arr <= data["time_windows"][j][1]:
                heappush(candidatos, (arr, j))
        if not candidatos:
            break
        arr_j, j = heappop(candidatos)
        ruta.append(j)
        llegada.append(arr_j)
        no_visitados.remove(j)
        actual = j
        tiempo_actual = arr_j

    return {
        "routes": [
            {
                "route": ruta,
                "arrival_sec": llegada
            }
        ]
    }
