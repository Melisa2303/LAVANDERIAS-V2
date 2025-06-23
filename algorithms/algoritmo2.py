# algorithms/algoritmo2.py

import time
from typing import List, Dict, Any, Tuple

# Importamos las constantes del algoritmo principal (algoritmo1.py)
from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC


def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    """Suma de distancias (m) a lo largo de un route (lista de nodos)."""
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))


def _check_feasible_and_time(
    route: List[int], data: Dict[str, Any]
) -> Tuple[bool, List[int]]:
    """
    Comprueba factibilidad de un route bajo time_windows y SERVICE_TIME.
    Devuelve (es_factible, tiempos_de_llegada).
    """
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
    """
    1) Clarke–Wright Savings para generar rutas iniciales.
    2) Tabu Search (swap de dos nodos) para refinar cada mini-ruta.
    3) Finalmente aplasta TODO en una sola ruta:
       → [0, ...clientes..., 0]
    """
    depot = data["depot"]
    n     = len(data["distance_matrix"])
    nodes = [i for i in range(n) if i != depot]

    # 1) Savings
    D = data["distance_matrix"]
    savings = []
    for i in nodes:
        for j in nodes:
            if i < j:
                s = D[depot][i] + D[depot][j] - D[i][j]
                savings.append((s, i, j))
    savings.sort(reverse=True, key=lambda x: x[0])

    # Inicialmente cada cliente en su mini-ruta [0, i, 0]
    parent    = {i: i for i in nodes}
    start_map = {i: i for i in nodes}
    end_map   = {i: i for i in nodes}
    route_map = {i: [depot, i, depot] for i in nodes}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Merge según savings, sin violar time-windows
    for _, i, j in savings:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        # sólo si i al final de ri y j al inicio de rj
        if end_map[ri] == i and start_map[rj] == j:
            cand = route_map[ri][:-1] + route_map[rj][1:]
            feas, _ = _check_feasible_and_time(cand, data)
            if not feas:
                continue
            # hago el merge
            parent[rj]      = ri
            end_map[ri]     = end_map[rj]
            route_map[ri]   = cand

    # Extraer las mini-rutas resultantes
    roots = {find(i) for i in nodes}
    initial_routes = [route_map[r] for r in roots]

    # 2) Tabu Search por cada mini-ruta
    final_routes: List[Tuple[List[int], List[int], float]] = []
    total_dist = 0.0
    t_start = time.time()

    for init in initial_routes:
        best_route = init[:]
        best_dist  = _route_distance(best_route, data)
        tabu_list  = []
        tabu_size  = 50

        while time.time() - t_start < tiempo_max_seg:
            improved = False
            L = len(best_route)
            for a in range(1, L-2):
                for b in range(a+1, L-1):
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
                        best_dist  = dist_c
                        tabu_list.append(move)
                        if len(tabu_list) > tabu_size:
                            tabu_list.pop(0)
                        improved = True
                        break
                if improved:
                    break
            if not improved:
                break

        _, arrival = _check_feasible_and_time(best_route, data)
        final_routes.append((best_route, arrival, best_dist))
        total_dist += best_dist

    # 3) Aplasto TODO en una sola ruta secuencial
    all_nodes, all_arrs = [], []
    for rt, arr, _ in final_routes:
        all_nodes += rt
        all_arrs  += arr

    # Quitar ceros consecutivos intermedios
    flat_nodes, flat_arrs = [all_nodes[0]], [all_arrs[0]]
    for u, t in zip(all_nodes[1:], all_arrs[1:]):
        if not (u == depot and flat_nodes[-1] == depot):
            flat_nodes.append(u)
            flat_arrs.append(t)
    # Asegurar que termina en depósito
    if flat_nodes[-1] != depot:
        flat_nodes.append(depot)
        flat_arrs.append(flat_arrs[-1])

    return {
        "routes": [{
            "vehicle":      0,
            "route":        flat_nodes,
            "arrival_sec":  flat_arrs,
        }],
        "distance_total_m": total_dist
    }
