# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 15 * 60           # 10 minutos de servicio
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 30 * 60           # hasta 16:45 permitidos
MAX_TRAVEL     = 45 * 60           # descartar arcos >40min de viaje

# pesos por segundo de espera / tardanza
WAIT_WEIGHT    = 1000              # penaliza fuerte la espera temprana
TARDY_WEIGHT   = 1                 # penaliza débil la tardanza

def optimizar_ruta_cp_sat(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Construye solución inicial con Nearest Insertion
    2) Refina con CP-SAT, usando AddHint(...) para partir de la ruta inicial
    3) Si CP-SAT no encuentra solución, cae en Nearest Insertion puro (fallback)
    """
    # Matrices y parámetros
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # -------------------------
    # 1) Ruta inicial heurística
    # -------------------------
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

    # -------------------------
    # 2) Modelo CP-SAT
    # -------------------------
    model = cp_model.CpModel()

    # Variables de arco x[i,j]
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            # prohibir arcos demasiado largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(b == 0)
            x[i, j] = b

    # Tiempo de llegada t[i]
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # Variables MTZ para subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # Grados de entrada/salida
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if j != i) == 1)
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # Ventana del depósito
    model.Add(t[0] == SHIFT_START)

    # Ventanas de tiempo con tardanza permitida
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # Secuencia temporal: si x[i,j]==1 entonces t[j] ≥ t[i] + servicio + viaje
    for i in range(n):
        for j in range(n):
            if i == j: continue
            model.Add(t[j] >= t[i] + service[i] + T[i][j]).OnlyEnforceIf(x[i,j])

    # MTZ para eliminar subtours
    model.Add(u[0] == 0)
    for i in range(1,n):
        for j in range(1,n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + n * (1 - x[i,j]))

    # Variables espera y tardanza
    wait  = [model.NewIntVar(0, ALLOWED_LATE, f"wait_{i}")  for i in range(n)]
    tardy = [model.NewIntVar(0, ALLOWED_LATE, f"tardy_{i}") for i in range(n)]
    for i, (ini, fin) in enumerate(windows):
        # espera = max(0, ini - t[i])
        model.Add(wait[i]  >= ini - t[i])
        # tardanza = max(0, t[i] - fin)
        model.Add(tardy[i] >= t[i]   - fin)

    # Objetivo combinado: distancia + penalizaciones
    model.Minimize(
        sum(D[i][j] * x[i,j] for (i,j) in x)
      + WAIT_WEIGHT  * sum(wait)
      + TARDY_WEIGHT * sum(tardy)
    )

    # -------------------------
    # 3) Hint desde heurística
    # -------------------------
    # insertar indicios de la ruta inicial
    for a,b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
    for pos, node in enumerate(init_route):
        model.AddHint(u[node], pos)
    # tiempos iniciales aproximados
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev, curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # -------------------------
    # 4) Solve
    # -------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 5) Fallback a Nearest Insertion puro
        return _fallback_insertion(data)

    # -------------------------
    # 6) Extraer solución CP-SAT
    # -------------------------
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
        "routes":[{"vehicle":0, "route":ruta, "arrival_sec":llegada}],
        "distance_total_m": dist_total
    }

def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion puro + ETA realista respetando ventanas.
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
                if delta < best_cost:
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
        # si llego antes de la apertura, espero hasta ini
        t_now = max(t_now, windows[node][0])
        # si llego muy tarde, capear a fin+ALLOWED_LATE
        t_now = min(t_now, windows[node][1] + ALLOWED_LATE)
        llegada.append(t_now)

    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes":[{"vehicle":0, "route":visitados, "arrival_sec":llegada}],
        "distance_total_m": dist_total
    }
