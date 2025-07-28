# algorithms/algoritmo3_hybrid.py

from typing import Dict, Any
from ortools.sat.python import cp_model

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos de servicio
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 30 * 60           # hasta 16:45
MAX_TRAVEL     = 40 * 60           # descartar arcos >40min de viaje

# penalizaciones
DIST_WEIGHT    = 1                 # peso de la distancia
WAIT_WEIGHT    = 10                # peso por segundo de espera temprana
TARDY_WEIGHT   = 1                 # peso por segundo de tardanza


def optimizar_ruta_cp_sat_hybrid(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Heurística Nearest Insertion para ruta inicial
    2) CP-SAT refinado con hint desde la solución inicial
    3) Si CP-SAT no encuentra solución, fallback con penalizaciones
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # ------------------------------------------------------
    # 1) Construir ruta inicial por Nearest Insertion
    # ------------------------------------------------------
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None

                # coste distancia incremental
                delta = D[a][j]
                if b is not None:
                    delta += D[j][b] - D[a][b]

                # simular ETA hasta antes de j
                t_now = SHIFT_START
                for idx, node in enumerate(visitados[:pos]):
                    if idx > 0:
                        prev = visitados[idx-1]
                        t_now += service[prev] + T[prev][node]
                    t_now = max(t_now, windows[node][0])

                # llegada a j y penalizaciones
                t_j = max(t_now + service[visitados[pos-1]] + T[visitados[pos-1]][j],
                          windows[j][0])
                wait_j  = max(0, windows[j][0] - t_j)
                tardy_j = max(0, t_j - windows[j][1])

                # llegada a b tras j
                if b is not None:
                    t_next = max(t_j + service[j] + T[j][b],
                                 windows[b][0])
                    wait_b  = max(0, windows[b][0] - t_next)
                    tardy_b = max(0, t_next - windows[b][1])
                else:
                    wait_b = tardy_b = 0

                penalty = WAIT_WEIGHT*(wait_j + wait_b) + TARDY_WEIGHT*(tardy_j + tardy_b)
                cost = DIST_WEIGHT*delta + penalty

                if cost < best_cost:
                    best_cost, best_j, best_pos = cost, j, pos

        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)

    init_route = visitados

    # ------------------------------------------------------
    # 2) Construir y resolver modelo CP-SAT con hint
    # ------------------------------------------------------
    model = cp_model.CpModel()

    # Variables de arco
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            # bloquear arcos muy largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(b == 0)
            x[i, j] = b

    # Tiempo de llegada
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # Variables MTZ para subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # Grados de entrada/salida
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if j!=i) == 1)
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # Ventanas de tiempo (permitir tardanza hasta ALLOWED_LATE)
    model.Add(t[0] == SHIFT_START)
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # Secuencia de tiempos
    for i in range(n):
        for j in range(n):
            if i == j: continue
            model.Add(
                t[j] >= t[i] + service[i] + T[i][j]
            ).OnlyEnforceIf(x[i,j])

    # MTZ subtours
    model.Add(u[0] == 0)
    for i in range(1,n):
        for j in range(1,n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # Objetivo: distancia + sum(t[i]) penalizada
    model.Minimize(
        sum(D[i][j] * x[i,j] for (i,j) in x) +
        WAIT_WEIGHT * sum(t[i] for i in range(n))
    )

    # Hints desde init_route
    for a, b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
    for pos, node in enumerate(init_route):
        model.AddHint(u[node], pos)
    # ETA hints
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev, curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # reconstruir ruta
        ruta = [0]
        llegada = [solver.Value(t[0])]
        seen = {0}
        cur = 0
        while True:
            nxt = next((j for j in range(n)
                        if j not in seen and solver.Value(x[cur,j])==1),
                       None)
            if nxt is None:
                break
            ruta.append(nxt)
            llegada.append(solver.Value(t[nxt]))
            seen.add(nxt)
            cur = nxt

        dist_total = sum(D[a][b] for a,b in zip(ruta, ruta[1:]))
        return {
            "routes":[{"vehicle":0,"route":ruta,"arrival_sec":llegada}],
            "distance_total_m": dist_total
        }

    # ------------------------------------------------------
    # 3) Fallback si CP-SAT no halla solución
    # ------------------------------------------------------
    return _fallback_insertion(data)


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion + penalización de espera/tardanza al pie de la letra.
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    visitados = [0]
    restantes = set(range(1,n))

    while restantes:
        best_cost, bj, bpos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None

                # incremento de distancia
                delta_dist = D[a][j]
                if b is not None:
                    delta_dist += D[j][b] - D[a][b]

                # simular ETA
                t_now = SHIFT_START
                for idx,node in enumerate(visitados[:pos]):
                    if idx>0:
                        prev = visitados[idx-1]
                        t_now += service[prev] + T[prev][node]
                    t_now = max(t_now, windows[node][0])

                # llegada a j
                t_j = max(t_now + service[visitados[pos-1]] + T[visitados[pos-1]][j],
                          windows[j][0])
                wait_j  = max(0, windows[j][0] - t_j)
                tardy_j = max(0, t_j - windows[j][1])

                # llegada a b tras j
                if b is not None:
                    t_next = max(t_j + service[j] + T[j][b],
                                 windows[b][0])
                    wait_b  = max(0, windows[b][0] - t_next)
                    tardy_b = max(0, t_next - windows[b][1])
                else:
                    wait_b = tardy_b = 0

                penalty = WAIT_WEIGHT*(wait_j + wait_b) + TARDY_WEIGHT*(tardy_j + tardy_b)
                cost = DIST_WEIGHT*delta_dist + penalty

                if cost < best_cost:
                    best_cost, bj, bpos = cost, j, pos

        visitados.insert(bpos, bj)
        restantes.remove(bj)

    # calcular ETA final
    llegada = []
    t_now   = SHIFT_START
    for idx,node in enumerate(visitados):
        if idx>0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        t_now = max(t_now, windows[node][0])
        t_now = min(t_now, windows[node][1] + ALLOWED_LATE)
        llegada.append(t_now)

    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes":[{"vehicle":0,"route":visitados,"arrival_sec":llegada}],
        "distance_total_m": dist_total
    }
