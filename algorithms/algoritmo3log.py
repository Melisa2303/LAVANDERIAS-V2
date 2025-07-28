# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos en segundos
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 30 * 60           # permite llegar hasta 16:45
MAX_WAIT       = 20 * 60           # max 20 min de espera anticipada
MAX_TRAVEL     = 40 * 60           # descartar arcos >40min de viaje

# pesos en la función objetivo
DIST_WEIGHT    = 1     # por metro recorrido
WAIT_WEIGHT    = 100   # por segundo de espera

def optimizar_ruta_cp_sat_hybrid(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    """
    1) Nearest Insertion para ruta inicial
    2) CP-SAT afinado con AddHint(...) partiendo de esa ruta
    3) Fallback mejorado que respeta ventanas y slack
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # -------------------------
    # 1) Solución Nearest Insertion
    # -------------------------
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_delta, best_j, best_pos = float("inf"), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None
                delta = D[a][j] + (D[j][b] if b is not None else 0)
                delta -= (D[a][b] if b is not None else 0)
                if delta < best_delta:
                    best_delta, best_j, best_pos = delta, j, pos
        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)
    init_route = visitados

    # -------------------------
    # 2) Modelo CP-SAT
    # -------------------------
    model = cp_model.CpModel()

    # Bool x[i,j] = 1 si viajo de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            if T[i][j] > MAX_TRAVEL:
                # bloquea viajes demasiado largos
                model.Add(b == 0)
            x[(i,j)] = b

    # tiempo de llegada t[i]
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # MTZ subtour
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # grados
    for j in range(1, n):
        model.Add(sum(x[(i,j)] for i in range(n) if i!=j) == 1)
    for i in range(1, n):
        model.Add(sum(x[(i,j)] for j in range(n) if j!=i) == 1)
    model.Add(sum(x[(0,j)] for j in range(1,n)) == 1)
    model.Add(sum(x[(i,0)] for i in range(1,n)) == 1)

    # ventanas de tiempo con tardanza
    model.Add(t[0] == SHIFT_START)
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # secuencia + límite espera anticipada
    for i in range(n):
        for j in range(n):
            if i == j: continue
            # t[j] ≥ t[i]+servicio+T[i,j] si x[i,j]
            model.Add(
                t[j] >= t[i] + service[i] + T[i][j]
            ).OnlyEnforceIf(x[(i,j)])
            # no más de MAX_WAIT de espera antes de ventana
            model.Add(
                t[j] <= t[i] + service[i] + T[i][j] + MAX_WAIT
            ).OnlyEnforceIf(x[(i,j)])

    # MTZ para subtours
    model.Add(u[0] == 0)
    for i in range(1,n):
        for j in range(1,n):
            if i!=j:
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[(i,j)]))

    # objetivo: distancia + espera muy penalizada
    model.Minimize(
        DIST_WEIGHT * sum(D[i][j] * x[(i,j)] for (i,j) in x)
        + WAIT_WEIGHT * sum(t[i] for i in range(n))
    )

    # hints desde la heurística
    for a,b in zip(init_route, init_route[1:]):
        if (a,b) in x:
            model.AddHint(x[(a,b)], 1)
    for pos,node in enumerate(init_route):
        model.AddHint(u[node], pos)
    eta = SHIFT_START
    model.AddHint(t[0], eta)
    for prev,curr in zip(init_route, init_route[1:]):
        eta = max(eta + service[prev] + T[prev][curr], windows[curr][0])
        model.AddHint(t[curr], eta)

    # resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        ruta = [0]
        llegada = [solver.Value(t[0])]
        cur = 0
        seen = {0}
        for _ in range(n-1):
            nxt = next((j for j in range(n)
                        if j not in seen and solver.Value(x[(cur,j)])==1),
                       None)
            if nxt is None:
                break
            ruta.append(nxt)
            llegada.append(solver.Value(t[nxt]))
            seen.add(nxt)
            cur = nxt

        dist_total = sum(D[a][b] for a,b in zip(ruta, ruta[1:]))

        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": dist_total
        }

    # -------------------------
    # 3) Fallback mejorado
    # -------------------------
    return _fallback_insertion(data)


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion + ETA realista que:
      - respeta ventanas [ini, fin]
      - espera hasta MAX_WAIT antes
      - tolera tardanza hasta ALLOWED_LATE
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    # reconstruir la misma ruta heurística
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_score, bj, bpos = float("inf"), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None
                # calculamos ETA provisional al insertar j en pos
                # partimos del tiempo acumulado hasta a:
                t_acc = SHIFT_START
                for idx,node in enumerate(visitados[:pos]):
                    if idx>0:
                        prev = visitados[idx-1]
                        t_acc += service[prev] + T[prev][node]
                # luego viajamos de a → j
                t_arr = t_acc + service[a] + T[a][j]
                # si llegamos antes de ini, esperamos (pero no más de MAX_WAIT)
                ini, fin = windows[j]
                if t_arr < ini:
                    t_arr = min(ini, t_arr + MAX_WAIT)
                # si tardamos > fin+ALLOWED_LATE, descartamos
                if t_arr > fin + ALLOWED_LATE:
                    continue
                # coste: tiempo total tras insertar j más delta distancia
                score = t_arr + D[a][j]
                # si hay siguiente b en la ruta, ajustar
                if b is not None:
                    # restamos el arco original a→b y añadimos j→b
                    score += D[j][b] - D[a][b]
                if score < best_score:
                    best_score, bj, bpos = score, j, pos
        # si no encontramos candidato, rompe
        if bj is None:
            break
        visitados.insert(bpos, bj)
        restantes.remove(bj)

    # reconstruir ETA final
    llegada = []
    t_now = SHIFT_START
    for idx,node in enumerate(visitados):
        if idx>0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        ini, fin = windows[node]
        if t_now < ini:
            t_now = min(ini, t_now + MAX_WAIT)
        if t_now > fin + ALLOWED_LATE:
            t_now = fin + ALLOWED_LATE
        llegada.append(t_now)

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
