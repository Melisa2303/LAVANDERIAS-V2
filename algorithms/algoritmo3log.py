# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 15 * 60
PESO_RETRASO = 10
PESO_ESPERA = 1
PESO_EXTENDIDO = 20
PESO_ANTICIPO = 3
PESO_NO_VISITADO = 1000  # Muy alto para evitar soluciones triviales

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    n = len(data["time_windows"])
    duraciones = data["duration_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [600] * n)
    depot = data["depot"]

    model = cp_model.CpModel()
    horizon = 24 * 3600

    start_vars = [model.NewIntVar(0, horizon, f'start_{i}') for i in range(n)]
    end_vars = [model.NewIntVar(0, horizon, f'end_{i}') for i in range(n)]
    visited = [model.NewBoolVar(f'visited_{i}') for i in range(n)]

    for i in range(n):
        model.Add(end_vars[i] == start_vars[i] + service_times[i]).OnlyEnforceIf(visited[i])
        model.Add(start_vars[i] >= ventanas[i][0]).OnlyEnforceIf(visited[i])
        model.Add(start_vars[i] <= ventanas[i][1]).OnlyEnforceIf(visited[i])

    arcs = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                arcs[i, j] = model.NewBoolVar(f'arc_{i}_{j}')

    for i in range(n):
        model.Add(sum(arcs[i, j] for j in range(n) if i != j) == visited[i])
        model.Add(sum(arcs[j, i] for j in range(n) if i != j) == visited[i])

    for i in range(n):
        for j in range(n):
            if i != j:
                travel = duraciones[i][j]
                model.Add(start_vars[j] >= end_vars[i] + travel).OnlyEnforceIf(arcs[i, j])

    retraso = [model.NewIntVar(0, horizon, f"retraso_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, horizon, f"espera_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, horizon, f"anticipado_{i}") for i in range(n)]
    no_visitado = [model.NewIntVar(0, 1, f"novisit_{i}") for i in range(n)]

    for i in range(n):
        win_ini, win_fin = ventanas[i]
        mid_win = (win_ini + win_fin) // 2
        model.Add(retraso[i] >= start_vars[i] - win_fin).OnlyEnforceIf(visited[i])
        model.Add(retraso[i] == 0).OnlyEnforceIf(visited[i].Not())

        model.Add(espera[i] >= win_ini - start_vars[i]).OnlyEnforceIf(visited[i])
        model.Add(espera[i] == 0).OnlyEnforceIf(visited[i].Not())

        model.Add(anticipo[i] >= mid_win - start_vars[i]).OnlyEnforceIf(visited[i])
        model.Add(anticipo[i] == 0).OnlyEnforceIf(visited[i].Not())

        model.Add(no_visitado[i] == 1 - visited[i])

    # Jornada extendida
    end_time = model.NewIntVar(0, horizon, "fin_jornada")
    model.AddMaxEquality(end_time, [end_vars[i] for i in range(n)])
    jornada_ext = model.NewIntVar(0, horizon, "jornada_ext")
    model.Add(jornada_ext >= end_time - SHIFT_END_SEC)

    # Función objetivo con penalizaciones ponderadas
    obj = sum(
        retraso[i] * PESO_RETRASO // max(1, ventanas[i][1] - ventanas[i][0])
        for i in range(n)
    )
    obj += sum(espera[i] * PESO_ESPERA for i in range(n))
    obj += sum(anticipo[i] * PESO_ANTICIPO for i in range(n))
    obj += PESO_EXTENDIDO * jornada_ext
    obj += PESO_NO_VISITADO * sum(no_visitado)

    model.Minimize(obj)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.FEASIBLE, cp_model.OPTIMAL]:
        orden = []
        tiempos = []
        current = depot
        visitado_set = set()
        while True:
            orden.append(current)
            tiempos.append(solver.Value(start_vars[current]))
            visitado_set.add(current)
            siguiente = None
            for j in range(n):
                if current != j and solver.Value(arcs[current, j]) == 1 and j not in visitado_set:
                    siguiente = j
                    break
            if siguiente is None:
                break
            current = siguiente
        return {
            "routes": [{
                "route": orden,
                "arrival_sec": tiempos
            }],
            "distance_total_m": 0
        }
    return None
