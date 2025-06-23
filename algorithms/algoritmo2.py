# algorithms/algoritmo2.py

import time
from typing import List, Dict, Any, Tuple

from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC


def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))


def _check_feasible_and_time(
    route: List[int], data: Dict[str, Any]
) -> Tuple[bool, List[int]]:
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    depot   = data["depot"]
    t       = SHIFT_START_SEC
    arrivals = [t]

    for u, v in zip(route, route[1:]):
        t += T[u][v]
        if u != depot:
            t += SERVICE_TIME
        w0, w1 = windows[v]
        if t > w1:
            return False, []
        t = max(t, w0)
        arrivals.append(t)

    return True, arrivals


def optimizar_ruta_cw_tabu(
    data: Dict[str, Any], tiempo_max_seg: int = 60
) -> Dict[str, Any]:
    depot = data["depot"]
    n     = len(data["distance_matrix"])
    clientes = [i for i in range(n) if i != depot]

    # 1) Clarke–Wright Savings
    D = data["distance_matrix"]
    savings = [
        (D[depot][i] + D[depot][j] - D[i][j], i, j)
        for i in clientes for j in clientes if i < j
    ]
    savings.sort(reverse=True, key=lambda x: x[0])

    # Mini‐rutas iniciales: SOLO clientes (sin depot al final)
    parent    = {i: i for i in clientes}
    start_map = {i: i for i in clientes}
    end_map   = {i: i for i in clientes}
    route_map = {i: [i] for i in clientes}

    def find(i:int):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Merge respetando ventanas
    for _, i, j in savings:
        ri, rj = find(i), find(j)
        if ri == rj: 
            continue
        if end_map[ri] == i and start_map[rj] == j:
            cand = route_map[ri] + route_map[rj]
            # chequeo factibilidad temporal introduciendo depot al inicio y fin
            test_route = [depot] + cand + [depot]
            feas, _ = _check_feasible_and_time(test_route, data)
            if not feas:
                continue
            parent[rj]     = ri
            end_map[ri]    = end_map[rj]
            route_map[ri]  = cand

    # Extraer las mini‐rutas finales
    roots = {find(i) for i in clientes}
    initial_routes = [route_map[r] for r in roots]

    # 2) Tabu Search en cada mini‐ruta (SIN depot dentro)
    final_customers = []
    t0 = time.time()
    for init in initial_routes:
        best = init[:]
        best_d = _route_distance([depot]+best+[depot], data)
        tabu = []
        while time.time() - t0 < tiempo_max_seg:
            improved = False
            L = len(best)
            for a in range(L):
                for b in range(a+1, L):
                    if (a,b) in tabu: 
                        continue
                    cand = best[:]
                    cand[a], cand[b] = cand[b], cand[a]
                    test_route = [depot] + cand + [depot]
                    feas, _ = _check_feasible_and_time(test_route, data)
                    if not feas:
                        continue
                    dc = _route_distance(test_route, data)
                    if dc < best_d - 1e-6:
                        best, best_d = cand, dc
                        tabu.append((a,b))
                        if len(tabu) > 50:
                            tabu.pop(0)
                        improved = True
                        break
                if improved:
                    break
            if not improved:
                break
        final_customers.extend(best)

    # 3) Construir ruta única con depot al inicio y final
    ruta_final = [depot] + final_customers + [depot]
    feas, llegada = _check_feasible_and_time(ruta_final, data)
    dist_final    = _route_distance(ruta_final, data)

    return {
        "routes": [{
            "vehicle":     0,
            "route":       ruta_final,
            "arrival_sec": llegada
        }],
        "distance_total_m": dist_final
    }
