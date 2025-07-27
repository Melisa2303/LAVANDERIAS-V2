# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import math

SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60

PESO_RETRASO     = 5
PESO_ESPERA      = 1
PESO_JORNADA_EXT = 8

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    D = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)

    model = cp_model.CpModel()
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    # Restricciones de flujo
    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) <= 1)
        model.Add(sum(x[j, i] for j in range(n) if j != i) <= 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                travel = D[i][j] + SERVICE_TIME
                model.Add(t[j] >= t[i] + travel).OnlyEnforceIf(x[i, j])

    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    # Penalizaciones
    retraso = []
    espera = []
    for i in range(n):
        ini, fin = ventanas[i]
        retraso_i = model.NewIntVar(0, 24 * 3600, f"retraso_{i}")
        espera_i = model.NewIntVar(0, 24 * 3600, f"espera_{i}")
        model.Add(retraso_i == t[i] - fin).OnlyEnforceIf(model.NewBoolVar(f"r_on_{i}")).OnlyEnforceIf(t[i] > fin)
        model.Add(espera_i == ini - t[i]).OnlyEnforceIf(model.NewBoolVar(f"w_on_{i}")).OnlyEnforceIf(t[i] < ini)
        retraso.append(retraso_i)
        espera.append(espera_i)

    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    for i in range(n):
        model.AddMaxEquality(end_time, t)

    delta_ext = model.NewIntVar(0, 24 * 3600, "delta_ext")
    over_ext = model.NewBoolVar("over_ext")
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(over_ext)
    model.Add(delta_ext == 0).OnlyEnforceIf(over_ext.Not())
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(over_ext)

    # Función objetivo
    obj_terms = []
    for i in range(n):
        w_i = max(1, ventanas[i][1] - ventanas[i][0])
        obj_terms.append(retraso[i] * PESO_RETRASO // w_i)
        obj_terms.append(espera[i] * PESO_ESPERA // w_i)

    obj_terms.append(delta_ext * PESO_JORNADA_EXT)
    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        route = [0]
        arrival = [solver.Value(t[0])]
        visited = set(route)
        current = 0
        while True:
            next_nodes = [j for j in range(n) if j not in visited and current != j and solver.Value(x[current, j])]
            if not next_nodes:
                break
            nxt = next_nodes[0]
            route.append(nxt)
            arrival.append(solver.Value(t[nxt]))
            visited.add(nxt)
            current = nxt
        if len(route) < n:
            return _fallback_heuristica(data)
        return {"routes": [{"route": route, "arrival_sec": arrival}], "distance_total_m": _distancia_total(route, data)}
    else:
        return _fallback_heuristica(data)

def _distancia_total(route, data):
    D = data["distance_matrix"]
    total = 0
    for i in range(len(route)-1):
        total += D[route[i]][route[i+1]]
    return total

def _fallback_heuristica(data):
    D = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)
    no_visitados = set(range(1, n))
    ruta = [0]
    llegada = [max(ventanas[0][0], SHIFT_START)]

    while no_visitados:
        mejor = None
        mejor_pos = None
        mejor_eta = None
        for k in no_visitados:
            mejor_costo = math.inf
            mejor_index = -1
            mejor_hora = -1
            for i in range(1, len(ruta)+1):
                previa = ruta[i-1]
                dur = D[previa][k] + SERVICE_TIME
                eta = llegada[i-1] + dur
                ini, fin = ventanas[k]
                if eta > fin:
                    continue
                penal = max(0, ini - eta)
                if penal < mejor_costo:
                    mejor_costo = penal
                    mejor_index = i
                    mejor_hora = max(eta, ini)
            if mejor_index != -1:
                mejor = k
                mejor_pos = mejor_index
                mejor_eta = mejor_hora
        if mejor is None:
            break
        ruta.insert(mejor_pos, mejor)
        llegada.insert(mejor_pos, mejor_eta)
        no_visitados.remove(mejor)

    return {
        "routes": [{"route": ruta, "arrival_sec": llegada}],
        "distance_total_m": _distancia_total(ruta, data)
    }
