# algorithms/algoritmo3_hybrid.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 8 * 60           # 10 minutos de servicio
SHIFT_START    =  9 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   = 15 * 60           # hasta 10-15 minutos
MAX_TRAVEL     = 35 * 60           # descartar arcos 40min de viaje
MAX_WAIT       = 45 * 60           # penalizar esperas 45 minutos

# pesos
WAIT_WEIGHT    = 100                # 1 segundo de espera = 1 unidad de penalización

def optimizar_ruta_cp_sat(
    data: Dict[str, Any],
    tiempo_max_seg: int = 120
) -> Dict[str, Any]:
    
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

     
    visitados = [0]
    restantes = set(range(1, n))
    while restantes:
        best_cost, best_j, best_pos = float('inf'), None, None
        for j in restantes:
            for pos in range(1, len(visitados)+1):
                a = visitados[pos-1]
                b = visitados[pos] if pos < len(visitados) else None

                 
                t_acc = SHIFT_START
                for idx,node in enumerate(visitados[:pos]):
                    if idx>0:
                        prev = visitados[idx-1]
                        t_acc += service[prev] + T[prev][node]

                 
                t_arr0 = t_acc + service[a] + T[a][j]

                ini, fin = windows[j]
                 
                if t_arr0 < ini:
                    wait_time = ini - t_arr0
                    t_arr = ini
                else:
                    wait_time = 0
                    t_arr = t_arr0

                # si llega después de la franja horaria, descartar
                if t_arr > fin + ALLOWED_LATE:
                    continue

                # coste  : distancia + tiempo + penalización por espera
                penalty = min(wait_time, MAX_WAIT) * WAIT_WEIGHT
                score = t_arr + D[a][j] + penalty

                
                if b is not None:
                    score += D[j][b] - D[a][b]

                if score < best_cost:
                    best_cost, best_j, best_pos = score, j, pos

        if best_j is None:
            # no quedan nodos que visitar
            break

        visitados.insert(best_pos, best_j)
        restantes.remove(best_j)

    init_route = visitados

    #Modelo CP-SAT
    model = cp_model.CpModel()

    # Bool x[i,j] = 1 si voy de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j: continue
            b = model.NewBoolVar(f"x_{i}_{j}")
            # bloqueo de arcos muy largos
            if T[i][j] > MAX_TRAVEL:
                model.Add(b == 0)
            x[i,j] = b

    # Tiempo de llegada t[i]
    horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # MTZ para subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # flujos de grado
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if j!=i) == 1)
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # ventana del depósito
    model.Add(t[0] == SHIFT_START)

    # ventanas de tiempo (con tardanza hasta ALLOWED_LATE)
    for i, (ini, fin) in enumerate(windows):
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + ALLOWED_LATE)

    # secuencia temporal si x[i,j]==1
    for i in range(n):
        for j in range(n):
            if i==j: continue
            model.Add(
                t[j] >= t[i] + service[i] + T[i][j]
            ).OnlyEnforceIf(x[i,j])

    # MTZ subtours
    model.Add(u[0] == 0)
    for i in range(1,n):
        for j in range(1,n):
            if i!=j:
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # objetivo: distancia + penalización por tiempo total (esperas + tardanzas)
    model.Minimize(
        sum(D[i][j] * x[i,j] for (i,j) in x)
        + WAIT_WEIGHT * sum(t[i] for i in range(n))
    )

    
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

    # 5) Si falla, se reintenta
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _fallback_insertion(data)

    # 6) Extraer la ruta
    ruta, llegada = [0], [solver.Value(t[0])]
    cur = 0
    seen = {0}
    while True:
        nxt = next(
            (j for j in range(n)
             if j not in seen and solver.Value(x[cur,j])==1),
            None
        )
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
   
    D        = data["distance_matrix"]
    T        = data["duration_matrix"]
    windows  = data["time_windows"]
    service  = data.get("service_times", [SERVICE_TIME] * len(windows))
    n        = len(D)

    visitados = [0]
    llegada   = [SHIFT_START]
    restantes = set(range(1, n))

    t_actual = SHIFT_START
    nodo_act = 0

    AJUSTADA_MAX   = 30*60   # 30 minutos
    INSERCION_MAX  = 30*60   # puede esperar 30 min si falta poco para que abra

    while restantes:
        # 1. Buscar ventana ajustada más próxima aún no visitada
        ajustadas_pendientes = []
        for j in restantes:
            ini, fin = windows[j]
            if fin - ini <= AJUSTADA_MAX:
                ajustadas_pendientes.append((ini, j))
        ajustadas_pendientes.sort()

        if ajustadas_pendientes:
            ini_v, j_v = ajustadas_pendientes[0]
            travel_v   = T[nodo_act][j_v]
            eta_v      = t_actual + service[nodo_act] + travel_v
            espera_v   = ini_v - eta_v

            # Si falta poco para que abra (≤45 min), la visito directamente
            if espera_v <= INSERCION_MAX:
                t_llegada = max(eta_v, ini_v)
                visitados.append(j_v)
                llegada.append(t_llegada)
                restantes.remove(j_v)
                t_actual = t_llegada
                nodo_act = j_v
                continue  # saltamos el resto de lógica

        # 2. Evaluar todos los candidatos
        candidatos = []
        for j in restantes:
            travel     = T[nodo_act][j]
            eta        = t_actual + service[nodo_act] + travel
            ini, fin   = windows[j]
            t_llegada  = max(eta, ini)
            retraso    = max(0, eta - fin)
            espera     = max(0, ini - eta)
            ventana_dur = fin - ini
            prioridad = 10000 // (1 + ventana_dur)
            score = retraso * 10 + espera * 2 + D[nodo_act][j] + prioridad

            candidatos.append((score, j, t_llegada))

        if not candidatos:
            # último recurso
            for j in restantes:
                eta = t_actual + service[nodo_act] + T[nodo_act][j]
                t_llegada = max(eta, windows[j][0])
                best_j = j
                break
        else:
            candidatos.sort()
            _, best_j, t_llegada = candidatos[0]

        visitados.append(best_j)
        llegada.append(t_llegada)
        restantes.remove(best_j)
        t_actual = t_llegada
        nodo_act = best_j

    # recalcular llegada final robusta
    llegada_final = []
    t_now = SHIFT_START
    for idx, node in enumerate(visitados):
        if idx > 0:
            prev = visitados[idx - 1]
            t_now += service[prev] + T[prev][node]
        t_now = max(t_now, windows[node][0])
        llegada_final.append(t_now)

    dist_total = sum(
        D[visitados[i]][visitados[i + 1]]
        for i in range(len(visitados) - 1)
    )

    return {
        "routes": [{"vehicle": 0, "route": visitados, "arrival_sec": llegada_final}],
        "distance_total_m": dist_total
    }

