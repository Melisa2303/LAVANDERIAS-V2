# algorithms/algoritmo3log.py
# CP-SAT con lógica mejorada de espera innecesaria y fallback heurístico

from ortools.sat.python import cp_model
import numpy as np
from typing import Dict, Any
import random

SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60
JORNADA_MAXIMA = SHIFT_END - SHIFT_START

PESO_RETRASO = 10
PESO_JORNADA_EXT = 50
PESO_ESPERA = 1

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 120) -> Dict[str, Any]:
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)

    model = cp_model.CpModel()
    x = [model.NewIntVar(0, n - 1, f"x{i}") for i in range(n)]
    t = [model.NewIntVar(0, SHIFT_END + 3600, f"t{i}") for i in range(n)]

    model.AddAllDifferent(x)

    for i in range(n - 1):
        u = x[i]
        v = x[i + 1]
        dur = model.NewConstant(T[u.Index()][v.Index()])
        model.Add(t[v.Index()] >= t[u.Index()] + dur + SERVICE_TIME)

    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin)

    retraso = []
    espera = []
    penalizaciones = []
    for i in range(n):
        ini, fin = ventanas[i]
        ancho_ventana = max(1, fin - ini)

        retraso_i = model.NewIntVar(0, 3600 * 3, f"retraso_{i}")
        espera_i = model.NewIntVar(0, 3600 * 3, f"espera_{i}")

        model.Add(retraso_i >= t[i] - fin)
        model.Add(espera_i >= ini - t[i])

        retraso.append(retraso_i)
        espera.append(espera_i)

        penalizaciones.append(retraso_i * PESO_RETRASO)
        penalizaciones.append(espera_i * PESO_ESPERA)

    end_time = model.NewIntVar(SHIFT_START, SHIFT_END + 3600, "end_time")
    for i in range(n):
        model.Add(end_time >= t[i])
    delta_ext = model.NewIntVar(0, 3600 * 3, "delta_ext")
    model.Add(delta_ext == end_time - SHIFT_END)
    penalizaciones.append(delta_ext * PESO_JORNADA_EXT)

    model.Minimize(sum(penalizaciones))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        orden = [solver.Value(xi) for xi in x]
        orden = sorted(range(n), key=lambda i: solver.Value(x[i]))
        ruta = []
        tiempos = []
        total_dist = 0
        for idx in range(n):
            u = orden[idx]
            ruta.append(u)
            tiempos.append(solver.Value(t[u]))
            if idx < n - 1:
                total_dist += D[u][orden[idx + 1]]

        return {
            "routes": [{
                "route": ruta,
                "arrival_sec": tiempos
            }],
            "distance_total_m": total_dist
        }

    # Fallback: Nearest Insertion
    return _fallback_insertion(data)


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    ventanas = data["time_windows"]
    n = len(D)
    visitados = [0]
    restantes = set(range(1, n))
    tiempos = [SHIFT_START] + [0] * (n - 1)

    while restantes:
        mejor_costo = float("inf")
        mejor_i = -1
        mejor_pos = -1

        for j in restantes:
            for pos in range(1, len(visitados) + 1):
                anterior = visitados[pos - 1]
                siguiente = visitados[pos] if pos < len(visitados) else None
                costo = D[anterior][j]
                if siguiente is not None:
                    costo += D[j][siguiente] - D[anterior][siguiente]
                if costo < mejor_costo:
                    mejor_costo = costo
                    mejor_i = j
                    mejor_pos = pos

        visitados.insert(mejor_pos, mejor_i)
        restantes.remove(mejor_i)

    # ETA simulada realista con SERVICE_TIME
    tiempos = [SHIFT_START]
    for i in range(1, len(visitados)):
        u = visitados[i - 1]
        v = visitados[i]
        dur = T[u][v]
        llegada = max(tiempos[-1] + SERVICE_TIME + dur, ventanas[v][0])
        tiempos.append(min(llegada, ventanas[v][1]))

    total_dist = sum(D[visitados[i]][visitados[i+1]] for i in range(len(visitados) - 1))

    return {
        "routes": [{
            "route": visitados,
            "arrival_sec": tiempos
        }],
        "distance_total_m": total_dist
    }


 
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
