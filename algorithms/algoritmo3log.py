# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------
# CONSTANTES DE JORNADA & COSTES
# ----------------------------
SERVICE_TIME   = 10 * 60           # 10 min en segundos
SHIFT_START    =  9 * 3600         # 09:00
SHIFT_END      = 16 * 3600 + 15*60 # 16:15
ALLOWED_LATE   = 30 * 60           # hasta 16:45
MAX_TRAVEL     = 40 * 60           # bloquear arcos > 40 min

SLACK_LIMIT    = 20 * 60           # solo penalizar hasta 20 min de espera
WAIT_WEIGHT    = 1                 # costo por segundo de espera temprana
LATE_WEIGHT    = 10                # costo por segundo de tardanza a la ventana


def optimizar_ruta_cp_sat_hybrid(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Nearest Insertion
    2) CP-SAT puro con hint
    3) Fallback Nearest Insertion
    """
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n = len(D)

    # --- 1) ruta inicial pelo Nearest Insertion ---
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best, bj, pos = float("inf"), None, None
        for j in restantes:
            for p in range(1, len(visitados)+1):
                a = visitados[p-1]
                b = visitados[p] if p < len(visitados) else None
                cost = D[a][j] + (D[j][b] if b is not None else 0) - (D[a][b] if b is not None else 0)
                if cost < best:
                    best, bj, pos = cost, j, p
        visitados.insert(pos, bj)
        restantes.remove(bj)
    init_route = visitados

    # --- 2) Construir modelo CP-SAT ---
    model = cp_model.CpModel()
    # x[i,j] = 1 si voy de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            v = model.NewBoolVar(f"x_{i}_{j}")
            if T[i][j] > MAX_TRAVEL:
                model.Add(v == 0)
            x[i,j] = v
    # t[i] = tiempo de llegada a i
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]
    # subtour vars MTZ
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # grados de flujo
    for j in range(1,n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j)==1)
    for i in range(1,n):
        model.Add(sum(x[i,j] for j in range(n) if j!=i)==1)
    model.Add(sum(x[0,j] for j in range(1,n))==1)
    model.Add(sum(x[i,0] for i in range(1,n))==1)

    # ventana depósito
    model.Add(t[0] == SHIFT_START)

    # ventanas de tiempo (permitir tardanza hasta ALLOWED_LATE)
    for i,(ini,fin) in enumerate(windows):
        # t[i] >= ini - SLACK_LIMIT  → permitimos anticipación
        model.Add(t[i] >= ini - SLACK_LIMIT)
        # t[i] <= fin + ALLOWED_LATE → tardanza tolerada
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # secuencia temporal
    for i in range(n):
        for j in range(n):
            if i==j: continue
            model.Add(t[j] >= t[i] + service[i] + T[i][j]).OnlyEnforceIf(x[i,j])

    # MTZ subtours
    model.Add(u[0]==0)
    for i in range(1,n):
        for j in range(1,n):
            if i!=j:
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # --- Variables de slack y tardanza para penalizar ---
    slack = []
    late  = []
    for i,(ini,fin) in enumerate(windows):
        si = model.NewIntVar(0, SLACK_LIMIT, f"slack_{i}")
        li = model.NewIntVar(0, ALLOWED_LATE, f"late_{i}")
        # si = max(0, ini - t[i])
        model.Add(si >= ini - t[i])
        # li = max(0, t[i] - fin)
        model.Add(li >= t[i] - fin)
        slack.append(si)
        late.append(li)

    # --- 3) Objetivo: distancia + penal slack + penal tardanza ---
    model.Minimize(
        sum(D[i][j]*x[i,j] for i,j in x)
      + WAIT_WEIGHT  * sum(slack)
      + LATE_WEIGHT  * sum(late)
    )

    # --- 4) Inyectar hint desde ruta inicial ---
    for a,b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
    for pos,node in enumerate(init_route):
        model.AddHint(u[node], pos)
    # hint de tiempos (ETA realista)
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev,curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # --- 5) Resolver ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    sol = solver.Solve(model)

    if sol not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Fallback si no encuentra nada
        return _fallback_insertion(data)

    # --- 6) Extraer ruta y ETAs ---
    ruta, llegada = [0], [solver.Value(t[0])]
    cur = 0
    seen = {0}
    while True:
        nxt = next((j for j in range(n)
                    if j not in seen and solver.Value(x[cur,j])==1),
                   None)
        if nxt is None: break
        ruta.append(nxt)
        llegada.append(solver.Value(t[nxt]))
        seen.add(nxt)
        cur = nxt

    total_dist = sum(D[a][b] for a,b in zip(ruta, ruta[1:]))

    return {
        "routes":[{"vehicle":0,"route":ruta,"arrival_sec":llegada}],
        "distance_total_m": total_dist
    }


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """Nearest Insertion puro + ETA realista."""
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n = len(D)

    visitados = [0]
    restantes = set(range(1,n))
    while restantes:
        best,bj,pos = float("inf"),None,None
        for j in restantes:
            for p in range(1,len(visitados)+1):
                a = visitados[p-1]
                b = visitados[p] if p<len(visitados) else None
                cost = D[a][j] + (D[j][b] if b else 0) - (D[a][b] if b else 0)
                if cost < best: best,bj,pos = cost,j,p
        visitados.insert(pos,bj)
        restantes.remove(bj)

    llegada = []
    t_now = SHIFT_START
    for idx,node in enumerate(visitados):
        if idx>0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        # respetar ventana
        t_now = max(t_now, windows[node][0])
        llegada.append(t_now)

    total_dist = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes":[{"vehicle":0,"route":visitados,"arrival_sec":llegada}],
        "distance_total_m": total_dist
    }
