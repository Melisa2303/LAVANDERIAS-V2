from ortools.sat.python import cp_model
import numpy as np

SHIFT_START = 9 * 3600      # 09:00
SHIFT_END   = 16 * 3600 + 15 * 60  # 16:15
SERVICE_TIME = 600          # 10 minutos
PESO_RETRASO = 5
PESO_ANTICIPO = 1
PESO_ESPERA = 1
PESO_JORNADA_EXT = 20

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    n = len(data["time_windows"])
    D = data["duration_matrix"]
    ventanas = data["time_windows"]

    model = cp_model.CpModel()

    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = [[model.NewBoolVar(f"x_{i}_{j}") for j in range(n)] for i in range(n)]

    M = 99999
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + D[i][j] + SERVICE_TIME - M * (1 - x[i][j]))

    # Cada nodo tiene un predecessor y un successor (salvo cochera)
    for i in range(1, n):
        model.Add(sum(x[i][j] for j in range(n) if j != i) == 1)
        model.Add(sum(x[j][i] for j in range(n) if j != i) == 1)
    model.Add(sum(x[0][j] for j in range(1, n)) == 1)  # salida de cochera
    model.Add(sum(x[j][0] for j in range(1, n)) == 0)  # cochera no tiene entrada

    retraso, anticipo, espera = [], [], []
    penalizaciones = []

    for i in range(n):
        ini, fin = ventanas[i]
        retraso_i = model.NewIntVar(0, fin, f"retraso_{i}")
        anticipo_i = model.NewIntVar(0, fin, f"anticipo_{i}")
        espera_i = model.NewIntVar(0, fin, f"espera_{i}")
        model.Add(retraso_i >= t[i] - fin)
        model.Add(anticipo_i >= ini - t[i])
        model.Add(espera_i >= ini - t[i])
        model.AddMaxEquality(retraso_i, [t[i] - fin, 0])
        model.AddMaxEquality(anticipo_i, [ini - t[i], 0])
        model.AddMaxEquality(espera_i, [ini - t[i], 0])
        retraso.append(retraso_i)
        anticipo.append(anticipo_i)
        espera.append(espera_i)

        w_i = max(1, fin - ini)
        penalizaciones.append(PESO_RETRASO * retraso_i // w_i)

    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 8 * 3600, "delta_ext")
    bool_ext = model.NewBoolVar("ext_flag")
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(bool_ext)
    model.Add(delta_ext == 0).OnlyEnforceIf(bool_ext.Not())
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(bool_ext)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(bool_ext.Not())

    obj_terms = penalizaciones + [
        PESO_ANTICIPO * a for a in anticipo
    ] + [
        PESO_ESPERA * w for w in espera
    ] + [
        PESO_JORNADA_EXT * delta_ext
    ]
    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = [0]
        current = 0
        while True:
            nexts = [j for j in range(n) if j != current and solver.BooleanValue(x[current][j])]
            if not nexts:
                break
            current = nexts[0]
            orden.append(current)
        eta = [int(solver.Value(t[i])) for i in orden]

        return {
            "routes": [{
                "route": orden,
                "arrival_sec": eta
            }]
        }

    # --------------------- FALLBACK Nearest Insertion ---------------------
    def fallback_nearest_insertion():
        visited = [False] * n
        visited[0] = True
        route = [0]
        arrival = [SHIFT_START]
        current_time = SHIFT_START
        current_node = 0

        while sum(visited) < n:
            best = None
            best_score = float("inf")
            for j in range(1, n):
                if visited[j]:
                    continue
                travel = D[current_node][j]
                arr = current_time + SERVICE_TIME + travel
                ini, fin = ventanas[j]
                delay = max(0, arr - fin)
                advance = max(0, ini - arr)
                wait = max(0, ini - arr)
                width = max(1, fin - ini)
                score = (
                    PESO_RETRASO * delay // width +
                    PESO_ANTICIPO * advance +
                    PESO_ESPERA * wait
                )
                if score < best_score:
                    best_score = score
                    best = j
                    best_arrival = max(arr, ini)

            if best is None:
                break

            route.append(best)
            arrival.append(best_arrival)
            visited[best] = True
            current_node = best
            current_time = best_arrival

        return {
            "routes": [{
                "route": route,
                "arrival_sec": arrival
            }]
        }

    return fallback_nearest_insertion()
