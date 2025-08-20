# algorithms/algoritmo2.py
# CW + Tabu Search + "Appointments-first" (ventanas duras) + inserción de flexibles
# Incluye servicio en el DEPÓSITO (suma servicio del nodo origen en cada arco)

import time
from typing import List, Dict, Any, Tuple
from heapq import heappush, heappop
import streamlit as st
from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC  # ambos en segundos

# ===================== Config servicio depósito / helper =====================

#Service time primer nodo
DEPOT_SERVICE_SEC = 10 * 60  # 10 minutos

def _svc(data: Dict[str, Any], node: int) -> int:
    """
    Devuelve el tiempo de servicio en segundos para 'node'.
    Prioriza data["service_times"] si existe; si no, usa SERVICE_TIME y un valor especial para depósito.
    """
    if "service_times" in data and data["service_times"] is not None:
        return int(data["service_times"][node])
    return DEPOT_SERVICE_SEC if node == data["depot"] else SERVICE_TIME


# ===================== Utilidades de tiempo/ruta =====================

def _route_distance(route: List[int], data: Dict[str, Any]) -> float:
    D = data["distance_matrix"]
    return sum(D[u][v] for u, v in zip(route, route[1:]))

def _check_feasible_and_time(route: List[int], data: Dict[str, Any]) -> Tuple[bool, List[int]]:
    """
    Comprueba factibilidad con ventanas duras.
    Convención:
      - t inicia en SHIFT_START_SEC en el depósito.
      - Antes de viajar de u->v se suma SIEMPRE el servicio del nodo u.
      - Luego se suma duración de viaje.
      - Si llegada > w1 => infactible.
      - Si llegada < w0 => espera hasta w0.
    """
    T = data["duration_matrix"]
    windows = data["time_windows"]

    t = SHIFT_START_SEC
    arrivals = [t]  # llegada al depósito (inicio)

    for u, v in zip(route, route[1:]):
        t += _svc(data, u)       # servicio del nodo origen
        t += T[u][v]             # viaje u->v

        w0, w1 = windows[v]
        if t > w1:
            return False, []
        t = max(t, w0)           
        arrivals.append(t)

    return True, arrivals


# ===================== Greedy con ventanas duras =====================

def _greedy_step(current: int, t_now: int, candidates: List[int], data: Dict[str, Any]) -> Tuple[int, int]:
    """
    Elige el siguiente candidato factible (ventanas duras), priorizando
    cierres próximos y ventanas cortas. Devuelve (nodo_elegido, t_llegada_efectiva).
    Si ninguno es factible, devuelve (-1, t_now).
    """
    T = data["duration_matrix"]
    W = data["time_windows"]
    heap = []

    for nxt in candidates:
        t_depart = t_now + _svc(data, current)       # servicio en current
        t_arrive = t_depart + T[current][nxt]
        w0, w1 = W[nxt]
        if t_arrive > w1:  # ventana dura
            continue

        t_eff = max(t_arrive, w0)
        wait = max(0, w0 - t_arrive)
        ventana = max(1, w1 - w0)
        urgencia = 1 / ventana
        score = t_eff + wait + 300 * urgencia
        heappush(heap, (score, nxt, t_eff))

    if not heap:
        return -1, t_now
    _, chosen, t_eff = heappop(heap)
    return chosen, t_eff


def _insert_flexibles_between(anchor_a: int, t_at_a: int, anchor_b: int, data: Dict[str, Any], flex_pool: List[int]) -> Tuple[List[int], List[int], int]:
    """
    Inserta clientes 'flexibles' entre dos anclas (citas) SIN romper la llegada a la segunda ancla.
    Devuelve (subruta, subarrivals, t_en_anchor_b_previsto).
    Si anchor_b == depot (o no hay siguiente), inserta tantos como quepan sin restricción a b.
    """
    T = data["duration_matrix"]
    W = data["time_windows"]
    depot = data["depot"]

    sub_route = [anchor_a]
    sub_arr = [t_at_a]
    current = anchor_a
    t_now = t_at_a

    # Si hay siguiente ancla real (no depósito), respetar su ventana
    limit_to_b = (anchor_b is not None and anchor_b != depot)

    # Greedy local mientras haya flexibles factibles
    while True:
        if not flex_pool:
            break

        # Candidatos factibles desde 'current'
        cand_heap = []
        for nxt in flex_pool:
            t_depart = t_now + _svc(data, current)    # servicio en current (incluye depósito)
            t_arrive = t_depart + T[current][nxt]
            w0, w1 = W[nxt]
            if t_arrive > w1:
                continue
            t_eff = max(t_arrive, w0)
            wait = max(0, w0 - t_arrive)
            ventana = max(1, w1 - w0)
            urgencia = 1 / ventana
            score = t_eff + wait + 50 * urgencia  # menor peso que en anclas
            heappush(cand_heap, (score, nxt, t_eff))

        if not cand_heap:
            break

        assigned = False
        while cand_heap:
            _, chosen, t_eff = heappop(cand_heap)

            if limit_to_b:
                # Llegada a anchor_b luego de chosen: servicio en chosen + viaje chosen->b
                t_after_chosen_depart = t_eff + _svc(data, chosen)
                t_arrive_b = t_after_chosen_depart + T[chosen][anchor_b]
                w0b, w1b = W[anchor_b]
                if t_arrive_b > w1b:
                    # no cabe; intentamos otro flexible
                    continue

            # Aceptamos 'chosen'
            sub_route.append(chosen)
            sub_arr.append(t_eff)
            flex_pool.remove(chosen)
            current = chosen
            t_now = t_eff
            assigned = True
            break

        if not assigned:
            break

    # Devolvemos subruta (desde anchor_a) y el t_now alcanzado
    return sub_route, sub_arr, t_now


# ===================== Algoritmo principal =====================

def optimizar_ruta_cw_tabu(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any]:
    """
    Pipeline:
      1) Clark–Wright + Tabu para obtener subrutas (solo como buen set inicial).
      2) Extraer todos los clientes y construir UNA ruta atendiendo primero 'citas' (ventanas estrechas).
      3) Insertar flexibles entre citas sin romperlas.

    Resultado: no excluye clientes; si algo no cabe, reubica flexibles.
    """
    depot = data["depot"]
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    W = data["time_windows"]

    n = len(D)
    nodes = [i for i in range(n) if i != depot]

    # ---------- 1) Savings + Tabu (con chequeo de ventanas) ----------
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

    def _feasible_route(rt: List[int]) -> bool:
        feas, _ = _check_feasible_and_time(rt, data)
        return feas

    for _, i, j in savings:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if end_map[ri] == i and start_map[rj] == j:
            merged = route_map[ri][:-1] + route_map[rj][1:]
            if not _feasible_route(merged):
                continue
            parent[rj] = ri
            end_map[ri] = end_map[rj]
            route_map[ri] = merged

    roots = {find(i) for i in nodes}
    initial_routes = [route_map[r] for r in roots]

    # Pequeño Tabu local
    start_ts = time.time()
    final_routes = []
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
                    if not _feasible_route(cand):
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

    # ---------- 2) Construcción "appointments-first" ----------
    # Consideramos "cita" si la ventana es estrecha (< 60 min)
    APPOINTMENT_THRESHOLD = 60 * 60  # 60 minutos
    all_clients = [n for rt, _, _ in final_routes for n in rt if n != depot] or nodes

    appointments = []
    flexibles = []
    for n in all_clients:
        w0, w1 = W[n]
        if (w1 - w0) <= APPOINTMENT_THRESHOLD:
            appointments.append(n)
        else:
            flexibles.append(n)

    # Ordena citas por cierre de ventana (EDD)
    appointments.sort(key=lambda u: W[u][1])

    # Empieza la ruta en el depósito
    route: List[int] = [depot]
    arrivals: List[int] = [SHIFT_START_SEC]
    current = depot
    t_now = SHIFT_START_SEC

    # Recorre citas en orden y va rellenando huecos con flexibles
    for idx, appt in enumerate(appointments):
        next_appt = appointments[idx + 1] if idx + 1 < len(appointments) else None

        # Inserta flexibles antes de esta cita (si cabe)
        if flexibles:
            sub_route, sub_arr, t_now = _insert_flexibles_between(current, t_now, appt, data, flexibles)
            # concatena (evitando duplicar el primer nodo)
            route += sub_route[1:]
            arrivals += sub_arr[1:]
            if route[-1] != current:
                current = route[-1]

        # Viajar a la cita respetando su ventana: servicio en current + viaje
        t_now += _svc(data, current)               # servicio del nodo origen  
        t_arr_appt = t_now + T[current][appt]
        w0, w1 = W[appt]
        if t_arr_appt > w1:
            # En principio no debería pasar por el filtro previo, pero dejamos aviso
            st.warning(f"Reajuste: cita {appt} quedaría fuera de ventana.")
        t_now = max(t_arr_appt, w0)
        route.append(appt)
        arrivals.append(t_now)
        current = appt

        # Entre esta cita y la siguiente, intenta meter flexibles
        if next_appt and flexibles:
            sub_route, sub_arr, t_now = _insert_flexibles_between(current, t_now, next_appt, data, flexibles)
            route += sub_route[1:]
            arrivals += sub_arr[1:]
            current = route[-1]

    # ---------- 3) Inserta los flexibles restantes después de la última cita ----------
    while flexibles:
        chosen, t_eff = _greedy_step(current, t_now, flexibles, data)
        if chosen == -1:
            # Reintento simple: probar cada flexible individualmente
            assigned = False
            for cand in list(flexibles):
                t_depart = t_now + _svc(data, current)
                t_arr = t_depart + T[current][cand]
                w0, w1 = W[cand]
                if t_arr > w1:
                    continue
                t_eff2 = max(t_arr, w0)
                route.append(cand)
                arrivals.append(t_eff2)
                flexibles.remove(cand)
                current = cand
                t_now = t_eff2
                assigned = True
                break
            if not assigned:
                st.warning("No fue posible insertar algunos flexibles sin romper ventanas; considera ampliar sus ventanas.")
                break
        else:
            route.append(chosen)
            arrivals.append(t_eff)
            flexibles.remove(chosen)
            current = chosen
            t_now = t_eff

    # (Opcional) cerrar en depósito:
    # t_now += _svc(data, current)
    # t_now += T[current][depot]
    # w0d, w1d = W[depot]
    # t_now = max(t_now, w0d) 
    # route.append(depot)
    # arrivals.append(t_now)

    # Validación final
    feas, arrival_chk = _check_feasible_and_time(route, data)
    if not feas:
        st.warning("La ruta resultante violaría alguna ventana; revisa ventanas o SHIFT_START_SEC.")
        if arrival_chk:
            arrivals = arrival_chk

    dist_final = _route_distance(route, data)

    return {
        "routes": [{
            "vehicle": 0,
            "route": route,
            "arrival_sec": arrivals
        }],
        "distance_total_m": dist_final,
        "clientes_excluidos": []  # no excluimos: reacomodamos
    }
