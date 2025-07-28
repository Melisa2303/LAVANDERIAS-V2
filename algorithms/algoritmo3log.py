# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos de servicio
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 30 * 60           # hasta 16:45
MAX_TRAVEL     = 40 * 60           # arcos de más de 40 min bloqueados

def optimizar_ruta_cp_sat(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Nearest Insertion para ruta inicial
    2) CP-SAT refinado usando AddHint(...) para partir de la solución inicial
    3) Fallback puro Nearest Insertion si CP-SAT no encuentra nada.
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # ---------- 1) Ruta inicial por Nearest Insertion ----------
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                ant = visitados[pos-1]
                sig = visitados[pos] if pos < len(visitados) else None
                # costo de insertar j entre ant y sig
                delta = D[ant][j] + (D[j][sig] if sig is not None else 0)
                delta -= (D[ant][sig] if sig is not None else 0)
                if delta < best_cost:
                    best_cost, best_j, best_pos = delta, j, pos
        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)
    init_route = visitados

    # ---------- 2) Modelo CP-SAT ----------
    model = cp_model.CpModel()

    # Variables booleanas x[i,j]
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            v = model.NewBoolVar(f"x_{i}_{j}")
            # bloquea los viajes muy largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(v == 0)
            x[i, j] = v

    # Variables de tiempo de llegada t[i]
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # Variables MTZ para subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # Flujo (in/out) y grado del depósito
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo (hasta ALLOWED_LATE tarde)
    model.Add(t[0] == SHIFT_START)
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # Conexión tiempos de viaje + servicio
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(
                    t[j] >= t[i] + service[i] + T[i][j]
                ).OnlyEnforceIf(x[i, j])

    # Subtour elimination (MTZ)
    model.Add(u[0] == 0)
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + n * (1 - x[i, j]))

    # Objetivo: minimizar distancia total
    model.Minimize(
        sum(D[i][j] * x[i, j] for (i, j) in x)
    )

    # ---------- 3) Hints desde init_route ----------
    # Hint de arcos
    for a, b in zip(init_route, init_route[1:]):
        model.AddHint(x[a, b], 1)
    # Hint de orden MTZ
    for pos, node in enumerate(init_route):
        model.AddHint(u[node], pos)
    # Hint de tiempos ETA
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev, curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # ---------- 4) Resolver CP-SAT ----------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # cae en fallback si no hay solución
        return _fallback_insertion(data)

    # ---------- 5) Extraer solución ----------
    ruta, llegada = [0], [solver.Value(t[0])]
    cur = 0
    seen = {0}
    while True:
        nxt = None
        for j in range(n):
            if j != cur and solver.Value(x[cur, j]) == 1 and j not in seen:
                nxt = j
                break
        if nxt is None:
            break
        ruta.append(nxt)
        llegada.append(solver.Value(t[nxt]))
        seen.add(nxt)
        cur = nxt

    dist_total = sum(D[a][b] for a, b in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle":     0,
            "route":       ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": dist_total
    }


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion puro + cálculo de ETA realista como fallback.
    """
    D        = data["distance_matrix"]
    T        = data["duration_matrix"]
    windows  = data["time_windows"]
    service  = data.get("service_times", [SERVICE_TIME]*len(windows))
    n        = len(D)

    # construir ruta
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                ant = visitados[pos-1]
                sig = visitados[pos] if pos < len(visitados) else None
                cost = D[ant][j] + (D[j][sig] if sig is not None else 0) \
                     - (D[ant][sig] if sig is not None else 0)
                if cost < best_cost:
                    best_cost, best_j, best_pos = cost, j, pos
        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)

    # calcular ETA respetando ventanas
    llegada = []
    t_curr  = SHIFT_START
    for idx, node in enumerate(visitados):
        if idx == 0:
            t_curr = SHIFT_START
        else:
            prev = visitados[idx-1]
            t_curr = t_curr + service[prev] + T[prev][node]
        # esperar si es antes de ventana
        t_curr = max(t_curr, windows[node][0])
        llegada.append(t_curr)

    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes": [{
            "vehicle":     0,
            "route":       visitados,
            "arrival_sec": llegada
        }],
        "distance_total_m": dist_total
    }
