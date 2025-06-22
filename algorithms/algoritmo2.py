# algorithms/algoritmo2.py

import time
from typing import List, Dict, Any, Tuple

# Importamos las constantes del algoritmo principal (algoritmo1.py)
from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC


def _route_distance(
    route: List[int],
    data: Dict[str, Any]
) -> float:
    """Suma de distancias (m) a lo largo de un route (lista de nodos)."""
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))


def _check_feasible_and_time(
    route: List[int],
    data: Dict[str, Any]
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
        # Añadimos tiempo de servicio si no es el depósito
        if u != depot:
            t += SERVICE_TIME
        w0, w1 = windows[v]
        # Si llegamos después de la ventana, no es factible
        if t > w1:
            return False, []
        # Esperamos hasta el inicio de ventana si llegamos antes
        t = max(t, w0)
        arrivals.append(t)

    return True, arrivals


def optimizar_ruta_cw_tabu(
    data: Dict[str, Any],
    tiempo_max_seg: int = 60
) -> Dict[str, Any]:
    """
    1) Clarke–Wright Savings para generar rutas iniciales (una por cada cliente).
    2) Tabu Search (swap de dos nodos) para refinar cada ruta respetando VRPTW.
    Devuelve todas las rutas factibles y la distancia total.
    """
    depot = data["depot"]
    n     = len(data["distance_matrix"])
    # nodos excluyendo el depósito
    nodes = [i for i in range(n) if i != depot]

    # 1) Savings de Clarke–Wright
    D = data["distance_matrix"]
    savings = []
    for i in nodes:
        for j in nodes:
            if i < j:
                s = D[depot][i] + D[depot][j] - D[i][j]
                savings.append((s, i, j))
    savings.sort(reverse=True, key=lambda x: x[0])

    # Inicial: cada cliente en su propia ruta [depot, i, depot]
    parent    = {i: i for i in nodes}
    start_map = {i: i for i in nodes}
    end_map   = {i: i for i in nodes}
    route_map = {i: [depot, i, depot] for i in nodes}

    def find(i: int) -> int:
        """Find con path-compression para union-find."""
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Merge de rutas según savings
    for _, i, j in savings:
        ri = find(i)
        rj = find(j)
        if ri == rj:
            continue
        # Solo unimos si i está al final de ri y j al inicio de rj
        if end_map[ri] == i and start_map[rj] == j:
            merged = route_map[ri][:-1] + route_map[rj][1:]
            parent[rj]       = ri
            end_map[ri]      = end_map[rj]
            route_map[ri]    = merged

    # Extraemos todas las rutas finales de los distintos conjuntos
    unique_roots   = {find(i) for i in nodes}
    initial_routes = [route_map[r] for r in unique_roots]

    # 2) Tabu Search sobre cada ruta
    final_routes = []
    total_dist   = 0.0
    start_ts     = time.time()

    for init in initial_routes:
        best_route = init[:]
        best_dist  = _route_distance(best_route, data)
        tabu_list  = []
        tabu_size  = 50

        # Búsqueda hasta agotar tiempo o sin mejoras
        while time.time() - start_ts < tiempo_max_seg:
            improved = False
            L = len(best_route)
            # Considera swaps de posición entre nodos interiores
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
                    # Aceptamos mejora estricta
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

        # Reconstruimos los tiempos de llegada
        _, arrival = _check_feasible_and_time(best_route, data)
        final_routes.append((best_route, arrival, best_dist))
        total_dist += best_dist

    # Empaquetamos la salida
    return {
        "routes": [
            {"vehicle": vid, "route": rt, "arrival_sec": arr}
            for vid, (rt, arr, _) in enumerate(final_routes)
        ],
        "distance_total_m": total_dist
    }
