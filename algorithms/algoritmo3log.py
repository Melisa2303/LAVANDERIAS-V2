# algorithms/algoritmo3.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos de servicio
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 30 * 60           # hasta 16:45
MAX_TRAVEL     = 40 * 60           # descartar arcos >40min de viaje

# peso que damos a cada segundo de llegada tardía
WAIT_WEIGHT    = 1                 # 1 segundo = 1 unidad de penalización

def optimizar_ruta_cp_sat(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Nearest Insertion para ruta inicial
    2) CP-SAT refinado usando AddHint(...) para partir de la solución inicial
    3) Fallback puro Nearest Insertion si CP-SAT no halla solución
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # 1) Ruta inicial: Nearest Insertion
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
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

    # 2) Modelo CP-SAT
    model = cp_model.CpModel()

    # Bool x[i,j] = 1 si viajo de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            # bloqueo de arcos muy largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(b == 0)
            x[i, j] = b

    # Tiempo de llegada t[i]
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # MTZ para eliminar subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # Grados e inicio
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if j!=i) == 1)
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # Ventanas (permitiendo llegar hasta ALLOWED_LATE tarde)
    model.Add(t[0] == SHIFT_START)
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # Secuencia de tiempos: t[j] ≥ t[i]+servicio+viaje  si x[i,j]==1
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
            if i!=j:
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # -------------------
    # Objetivo combinado:
    #    distancia + WAIT_WEIGHT * sum(t[i])
    # -------------------
    model.Minimize(
        sum(D[i][j] * x[i,j] for (i,j) in x)
        + WAIT_WEIGHT * sum(t[i] for i in range(n))
    )

    # 3) Hint desde la ruta heurística
    for a,b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
    for pos, node in enumerate(init_route):
        model.AddHint(u[node], pos)
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev, curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # 4) Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 5) Fallback 
        return _fallback_insertion(data)

    # 6) Extraer la ruta
    ruta, llegada = [0], [solver.Value(t[0])]
    cur = 0
    seen = {0}
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


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion puro + ETA realista.
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    visitados = [0]
    restantes = set(range(1,n))
    while restantes:
        best_cost,bj,bpos = float('inf'),None,None
        for j in restantes:
            for pos in range(1,len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos<len(visitados) else None
                delta = D[a][j] + (D[j][b] if b is not None else 0)
                delta -= (D[a][b] if b is not None else 0)
                if delta<best_cost:
                    best_cost,bj,bpos = delta,j,pos
        visitados.insert(bpos,bj)
        restantes.remove(bj)

    # calcular ETA respetando ventanas
    llegada = []
    t_now   = SHIFT_START
    for idx,node in enumerate(visitados):
        if idx>0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        t_now = max(t_now, windows[node][0])
        llegada.append(t_now)

    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes":[{"vehicle":0,"route":visitados,"arrival_sec":llegada}],
        "distance_total_m": dist_total
    }
