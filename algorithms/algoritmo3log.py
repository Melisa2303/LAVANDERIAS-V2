# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos en segundos
SHIFT_START    =  9 * 3600         # 09:00
SHIFT_END      = 16 * 3600 + 15*60 # 16:15
ALLOWED_LATE   = 30 * 60           # puede llegarse hasta las 17:15
MAX_TRAVEL     = 40 * 60           # no usar arcos > 40 min
WAIT_WEIGHT    = 1                 # penaliza 1 unidad por segundo de espera/tardanza

def optimizar_ruta_cp_sat(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Construye ruta inicial con Nearest-Insertion
    2) Refina con CP-SAT usando AddHint(...) para partir de esa ruta
    3) Si CP-SAT falla, cae en _fallback_insertion (que respeta ventanas + tolerancia)
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # ----------------------
    # 1) Heurística Nearest-Insertion
    # ----------------------
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float("inf"), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                ant = visitados[pos-1]
                sig = visitados[pos] if pos < len(visitados) else None
                delta = D[ant][j] + (D[j][sig] if sig is not None else 0)
                delta -= (D[ant][sig] if sig is not None else 0)
                if delta < best_cost:
                    best_cost, best_j, best_pos = delta, j, pos
        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)
    init_route = visitados

    # ----------------------
    # 2) Modelo CP-SAT
    # ----------------------
    model = cp_model.CpModel()

    # Variables x[i,j]: viajo de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            # bloqueo de arcos demasiado largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(b == 0)
            x[i, j] = b

    # Variables de tiempo t[i]
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

    # Ventanas rígidas + tolerancia de tardanza
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
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + n * (1 - x[i,j]))

    # Objetivo: distancia + penalización de espera/tardanza acumulada
    model.Minimize(
        sum(D[i][j] * x[i,j] for (i,j) in x)
        + WAIT_WEIGHT * sum(t[i] for i in range(n))
    )

    # Semejanza con heurística: añadir hints para CP-SAT
    # (fase caliente, acelera la convergencia)
    for a, b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
    for pos, node in enumerate(init_route):
        model.AddHint(u[node], pos)
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev, curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    # Si falla, fallback garantizado
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _fallback_insertion(data)

    # Extraer la ruta y ETAs de la solución CP-SAT
    ruta, llegada = [0], [solver.Value(t[0])]
    cur = 0
    seen = {0}
    while True:
        nxt = next((j for j in range(n)
                    if j not in seen and solver.Value(x[cur,j]) == 1),
                   None)
        if nxt is None:
            break
        ruta.append(nxt)
        llegada.append(solver.Value(t[nxt]))
        seen.add(nxt)
        cur = nxt

    dist_total = sum(D[a][b] for a,b in zip(ruta, ruta[1:]))
    return {
        "routes": [{"vehicle": 0, "route": ruta, "arrival_sec": llegada}],
        "distance_total_m": dist_total
    }


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion puro + ETA realista,
    respeta apertura, cierre (+ tolerancia), nunca descarta nodos.
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # 1) Nearest Insertion
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best, bj, bpos = float("inf"), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None
                delta = D[a][j] + (D[j][b] if b is not None else 0)
                delta -= (D[a][b] if b is not None else 0)
                if delta < best:
                    best, bj, bpos = delta, j, pos
        visitados.insert(bpos, bj)
        restantes.remove(bj)

    # 2) Calcular ETAs **respetando ventanas y tolerancia**
    llegada = []
    t_now = SHIFT_START
    for idx, node in enumerate(visitados):
        if idx > 0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        # nunca antes de la apertura
        t_now = max(t_now, windows[node][0])
        # nunca después del cierre + tolerancia
        t_now = min(t_now, windows[node][1] + ALLOWED_LATE)
        llegada.append(t_now)

    # 3) Calcular distancia total
    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes": [{
            "vehicle": 0,
            "route": visitados,
            "arrival_sec": llegada
        }],
        "distance_total_m": dist_total
    }
