# algorithms/algoritmo2.py
# CW + Tabu Search mejorado para respetar estrictamente ventanas de tiempo

import time
from typing import List, Dict, Any, Tuple

# Importa desde tu módulo (ajusta si cambió la ruta)
from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC


def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))


def _check_feasible_and_time(route: List[int], data: Dict[str, Any]) -> Tuple[bool, List[int], int]:
    """
    Verifica si la ruta es factible considerando ventanas de tiempo.
    Retorna: (es_factible, lista de tiempos de llegada, total de espera en segundos)
    """
    T = data["duration_matrix"]
    windows = data["time_windows"]
    depot = data["depot"]
    t = SHIFT_START_SEC
    arrivals = [t]
    total_wait = 0

    for u, v in zip(route, route[1:]):
        t += T[u][v]
        if u != depot:
            t += SERVICE_TIME
        w0, w1 = windows[v]
        if t > w1:
            return False, [], 0
        wait = max(w0 - t, 0)
        total_wait += wait
        t = max(t, w0)
        arrivals.append(t)

    return True, arrivals, total_wait


def optimizar_ruta_cw_tabu(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any]:
    depot = data["depot"]
    n = len(data["distance_matrix"])
    nodes = [i for i in range(n) if i != depot]

    # Paso 1: Clarke–Wright Savings
    D = data["distance_matrix"]
    savings = [(D[depot][i] + D[depot][j] - D[i][j], i, j)
               for i in nodes for j in nodes if i < j]
    savings.sort(reverse=True)

    parent = {i: i for i in nodes}
    start_map = {i: i for i in nodes}
    end_map = {i: i for i in nodes}
    route_map = {i: [depot, i, depot] for i in nodes}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for _, i, j in savings:
        ri, rj = find(i), find(j)
        if ri != rj and end_map[ri] == i and start_map[rj] == j:
            merged = route_map[ri][:-1] + route_map[rj][1:]
            feas, _, _ = _check_feasible_and_time(merged, data)
            if feas:
                parent[rj] = ri
                end_map[ri] = end_map[rj]
                route_map[ri] = merged

    roots = {find(i) for i in nodes}
    initial_routes = [route_map[r] for r in roots]

    # Paso 2: Tabu Search
    final_routes = []
    start_ts = time.time()

    for init in initial_routes:
        best_route = init[:]
        feas, _, wait = _check_feasible_and_time(best_route, data)
        best_cost = _route_distance(best_route, data) + 0.01 * wait
        tabu_list = []
        tabu_size = 50

        while time.time() - start_ts < tiempo_max_seg:
            improved = False
            for a in range(1, len(best_route) - 2):
                for b in range(a + 1, len(best_route) - 1):
                    move = (a, b)
                    if move in tabu_list:
                        continue
                    cand = best_route[:]
                    cand[a], cand[b] = cand[b], cand[a]
                    feas, _, wait = _check_feasible_and_time(cand, data)
                    if feas:
                        cost = _route_distance(cand, data) + 0.01 * wait
                        if cost < best_cost:
                            best_route = cand
                            best_cost = cost
                            tabu_list.append(move)
                            if len(tabu_list) > tabu_size:
                                tabu_list.pop(0)
                            improved = True
                            break
                if improved:
                    break
            if not improved:
                break

        _, arrival, _ = _check_feasible_and_time(best_route, data)
        final_routes.append((best_route, arrival))

    # Paso 3: Unir todas en una sola ruta
    ruta_final = [depot] + [
        node for rt, _ in final_routes for node in rt if node != depot
    ]
    feas, llegada_final, _ = _check_feasible_and_time(ruta_final, data)

    if not feas or len(ruta_final) != len(llegada_final):
        llegada_final = [SHIFT_START_SEC + i * 60 for i in range(len(ruta_final))]

    dist_final = _route_distance(ruta_final, data)

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta_final,
            "arrival_sec": llegada_final
        }],
        "distance_total_m": dist_final
    }
