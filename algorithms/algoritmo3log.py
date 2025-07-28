# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos
SHIFT_START    =  9 * 3600         # 09:00
SHIFT_END      = 16 * 3600 + 15*60 # 16:15
ALLOWED_LATE   = 30 * 60           # hasta 16:45
MAX_TRAVEL     = 40 * 60           # no aceptamos arcos > 40min

def optimizar_ruta_cp_sat_hybrid(data: Dict[str, Any], tiempo_max_seg: int = 120) -> Dict[str, Any]:
    # 1) SOLUCIÓN INICIAL POR NEAREST INSERTION
    D        = data["distance_matrix"]
    T        = data["duration_matrix"]
    windows  = data["time_windows"]
    service  = data.get("service_times", [SERVICE_TIME]*len(windows))
    n        = len(D)

    # nearest insertion para obtener route0
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                ant = visitados[pos-1]
                sig = visitados[pos] if pos < len(visitados) else None
                cost = D[ant][j] + (D[j][sig] if sig is not None else 0) - (D[ant][sig] if sig is not None else 0)
                if cost < best_cost:
                    best_cost, best_j, best_pos = cost, j, pos
        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)
    init_route = visitados

    # 2) MODELO CP-SAT
    model = cp_model.CpModel()

    # variables arco x[i,j]
    x = {}
    for i in range(n):
        for j in range(n):
            if i==j: continue
            v = model.NewBoolVar(f"x_{i}_{j}")
            # bloqueo de arcos largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(v == 0)
            x[i,j] = v

    # tiempo de llegada
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # MTZ para subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # flujo
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j)==1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if j!=i)==1)
    model.Add(sum(x[0,j] for j in range(1,n))==1)
    model.Add(sum(x[i,0] for i in range(1,n))==1)

    # ventanas
    model.Add(t[0]==SHIFT_START)
    for i,(ini,fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # tiempos de viaje y servicio
    for i in range(n):
        for j in range(n):
            if i==j: continue
            model.Add(t[j] >= t[i] + service[i] + T[i][j])\
                 .OnlyEnforceIf(x[i,j])

    # MTZ
    model.Add(u[0]==0)
    for i in range(1,n):
        for j in range(1,n):
            if i==j: continue
            model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # objetivo: minimizar distancia
    model.Minimize(sum(D[i][j]*x[i,j] for (i,j) in x))

    # 3) AÑADIR HINTS para guiar al solver
    # indicamos al modelo que use init_route como punto de partida
    # para cada arco seleccionado en init_route
    for a,b in zip(init_route, init_route[1:]):
        model.AddHint(x[a,b], 1)
        # MTZ hint
    for pos,node in enumerate(init_route):
        model.AddHint(u[node], pos)
        # y un hint aproximado de t[node]:
        # asumimos ETA = max(prev_ETA + servicio+T, ventana_ini)
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for idx in range(1, len(init_route)):
        u0, u1 = init_route[idx-1], init_route[idx]
        eta = max(eta + service[u0] + T[u0][u1], windows[u1][0])
        model.AddHint(t[u1], eta)

    # 4) resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # si falla, devolvemos la heurística pura
        return _fallback_insertion(data)

    # 5) extraer solución
    ruta, llegada = [0], []
    cur = 0
    llegada.append(solver.Value(t[cur]))
    visit = {0}
    while True:
        nxt = None
        for j in range(n):
            if j!=cur and solver.Value(x[cur,j])==1:
                if j not in visit:
                    nxt = j
                break
        if nxt is None: break
        ruta.append(nxt)
        llegada.append(solver.Value(t[nxt]))
        visit.add(nxt)
        cur = nxt

    distancia = sum(D[a][b] for a,b in zip(ruta, ruta[1:]))
    return {
        "routes": [{
            "vehicle":     0,
            "route":       ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia
    }

def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    # ... simplemente copia aquí tu código de nearest insertion + cálculo de ETA
    # (igual que en la versión anterior)
    raise NotImplementedError("Copia tu fallback aquí")
