# algorithms/algoritmo2.py
# CW + Tabu Search + Exclusión de clientes no compatibles con ventana de tiem po

import time
from typing import List, Dict, Any, Tuple
from heapq import heappush, heappop
from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC
import streamlit as st

def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))

def _check_feasible_and_time(route: List[int], data: Dict[str, Any]) -> Tuple[bool, List[int]]:
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


def build_route_greedy_force_all(data, nodes, depot, tolerancia_seg=900):
    from heapq import heappush, heappop
    from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC
    import streamlit as st

    visited = set()
    current = depot
    t_now = SHIFT_START_SEC
    route = [depot]
    arrival = [t_now]

    # Ordenar todos los nodos por apertura de ventana (primero los que abren más temprano),
    # y luego por duración de ventana (más corta = más urgente)
    nodes = sorted(
        nodes,
        key=lambda n: (
            data["time_windows"][n][0],                           # apertura de ventana
            (data["time_windows"][n][1] - data["time_windows"][n][0])  # duración
        )
    )

    while len(visited) < len(nodes):
        heap = []
        for nxt in nodes:
            if nxt in visited:
                continue

            # Tiempo estimado de llegada
            t_travel = data["duration_matrix"][current][nxt]
            t_temp = t_now + t_travel
            if current != depot:
                t_temp += SERVICE_TIME

            w0, w1 = data["time_windows"][nxt]

            # Penalizaciones por restricciones temporales
            wait = max(0, w0 - t_temp)
            lateness = max(0, t_temp - (w1 + tolerancia_seg))
            idle_time = wait if wait > 0 else 0

            # Urgencia: ventanas cortas tienen más peso
            dur_ventana = w1 - w0
            urgencia = 1 / (dur_ventana + 1)
            urgencia *= 0.2  # para evitar sobrepriorización

            # Prioridad extra si la ventana abre temprano (antes de 11:00am)
            prioridad_temprana = max(0, 11*3600 - w0) / 3600

            # Penalización total
            lateness_penalty = 30 * lateness + 0.5 * max(0, t_temp - w0)
            idle_penalty = 10 * idle_time

            score = (
                t_temp
                + wait
                + lateness_penalty
                + 300 * urgencia
                + 50 * prioridad_temprana
                + idle_penalty
            )

            # Advertencia si está fuera de ventana
            if lateness > 0:
                st.warning(
                    f"⚠️ Cliente {nxt} será atendido fuera de ventana "
                    f"({int(t_temp/60)} min > {int(w1/60)} min + {int(tolerancia_seg/60)} min)"
                )

            heappush(heap, (score, nxt, max(t_temp, w0)))

        if not heap:
            st.warning("No se pudo asignar más clientes (heap vacío).")
            break

        _, chosen, t_arrival = heappop(heap)
        route.append(chosen)
        arrival.append(t_arrival)
        visited.add(chosen)
        current = chosen
        t_now = t_arrival

    return route, arrival, visited



def optimizar_ruta_cw_tabu(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any]:
    depot = data["depot"]
    n = len(data["distance_matrix"])
    nodes = [i for i in range(n) if i != depot]

    # 1) Clarke–Wright Savings
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

    # 2) Tabu Search
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

        _, arrival = _check_feasible_and_time(best_route, data)
        final_routes.append((best_route, arrival, best_dist))
        total_dist += best_dist

    # 3) Reconstrucción final
    todos_los_clientes = [n for rt, _, _ in final_routes for n in rt if n != depot]
    #ruta_final, llegada_final, usados = build_route_greedy(data, todos_los_clientes, depot, tolerancia_seg=0)
    ruta_final, llegada_final, usados = build_route_greedy_force_all(data, todos_los_clientes, depot, tolerancia_seg=0)
    no_asignados = [i for i in todos_los_clientes if i not in usados]

    if no_asignados:
        st.warning(f"Clientes no asignados por ventanas incompatibles: {no_asignados}")

    dist_final = _route_distance(ruta_final, data)

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta_final,
            "arrival_sec": llegada_final
        }],
        "distance_total_m": dist_final,
        "clientes_excluidos": no_asignados
    }
