# algorithms/algoritmo2.py
# CW + Tabu Search (siempre devuelve rutas, con o sin ajuste de ventanas)

import time
from typing import List, Dict, Any, Tuple

from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC


def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))


def _check_feasible_and_time(
    route: List[int], data: Dict[str, Any]
) -> Tuple[bool, List[int]]:
    T = data["duration_matrix"]
    windows = data["time_windows"]
    depot = data["depot"]
    t = SHIFT_START_SEC
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


def optimizar_ruta_cw_tabu(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any]:
    depot = data["depot"]
    n = len(data["distance_matrix"])
    nodes = [i for i in range(n) if i != depot]

    # 1. Savings
    D = data["distance_matrix"]
    savings = []
    for i in nodes:
        for j in nodes:
            if i < j:
                s = D[depot][i] + D[depot][j] - D[i][j]
                savings.append((s, i, j))
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
        if ri == rj:
            continue
        if end_map[ri] == i and start_map[rj] == j:
            merged = route_map[ri][:-1] + route_map[rj][1:]
            feas, _ = _check_feasible_and_time(merged, data)
            if not feas:
                continue
            parent[rj] = ri
            end_map[ri] = end_map[rj]
            route_map[ri] = merged

    roots = {find(i) for i in nodes}
    initial_routes = [route_map[r] for r in roots]

    # 2. Tabu Search
    final_routes = []
    total_dist = 0.0
    start_ts = time.time()

    for init in initial_routes:
        best_route = init[:]
        best_dist = _route_distance(best_route, data)
        tabu_list = []
        tabu_size = 50

        while time.time() - start_ts < tiempo_max_seg:
            improved = False
            L = len(best_route)
            for a in range(1, L - 2):
                for b in range(a + 1, L - 1):
                    move = (a, b)
                    if move in tabu_list:
                        continue
                    cand = best_route[:]
                    cand[a], cand[b] = cand[b], cand[a]
                    feas, _ = _check_feasible_and_time(cand, data)
                    if not feas:
                        continue
                    dist_c = _route_distance(cand, data)
                    if dist_c < best_dist - 1e-6:
                        best_route = cand
                        best_dist = dist_c
                        tabu_list.append(move)
                        if len(tabu_list) > tabu_size:
                            tabu_list.pop(0)
                        improved = True
                        break
                if improved:
                    break
            if not improved:
                break

        feas, arrival = _check_feasible_and_time(best_route, data)
        if not feas:
            # fallback si no cumple ventanas
            arrival = [SHIFT_START_SEC + i * 90 for i in range(len(best_route))]
        final_routes.append((best_route, arrival, best_dist))
        total_dist += best_dist

    # 3. Aplastar todas las rutas en una
    ruta_final = [depot]
    for rt, _, _ in final_routes:
        for node in rt:
            if node != depot and node not in ruta_final:
                ruta_final.append(node)

    feas, llegada_final = _check_feasible_and_time(ruta_final, data)
    dist_final = _route_distance(ruta_final, data)

    if feas:
        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta_final,
                "arrival_sec": llegada_final
            }],
            "distance_total_m": dist_final
        }
    else:
        # fallback: devolver rutas separadas si aplastada no es viable
        rutas = []
        for idx, (rt, arr, dist) in enumerate(final_routes):
            rutas.append({
                "vehicle": idx,
                "route": rt,
                "arrival_sec": arr
            })
        return {
            "routes": rutas,
            "distance_total_m": total_dist
        }
