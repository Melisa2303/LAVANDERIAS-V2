def build_route_greedy_force_all(data, nodes, depot, tolerancia_seg=900):
    from heapq import heappush, heappop
    from algorithms.algoritmo1 import SERVICE_TIME, SHIFT_START_SEC
    import streamlit as st

    # — 1. Priorización de clientes con ventanas que abren más temprano (<11:00 am) —
    prioritarios = [n for n in nodes if data["time_windows"][n][0] < 11 * 3600]
    resto = [n for n in nodes if n not in prioritarios]
    nodes = sorted(prioritarios, key=lambda n: data["time_windows"][n][0]) + resto

    visited = set()
    current = depot
    t_now = SHIFT_START_SEC
    route = [depot]
    arrival = [t_now]

    while len(visited) < len(nodes):
        heap = []
        for nxt in nodes:
            if nxt in visited:
                continue

            t_temp = t_now + data["duration_matrix"][current][nxt]
            if current != depot:
                t_temp += SERVICE_TIME

            w0, w1 = data["time_windows"][nxt]

            wait = max(0, w0 - t_temp)
            lateness = max(0, t_temp - (w1 + tolerancia_seg))
            prioridad_temprana = max(0, 11*3600 - w0) / 3600  # más peso si empieza más temprano
            urgencia = 1 / (w1 - w0 + 1)  # ventanas cortas = más prioridad

            lateness_penalty = 30 * lateness + 0.5 * max(0, t_temp - w0)

            score = (
                t_temp
                + wait
                + lateness_penalty
                + 300 * urgencia
                + 50 * prioridad_temprana
            )

            if lateness > 0:
                st.warning(f"⚠️ Cliente {nxt} será atendido fuera de ventana ({t_temp}s > {w1}s + tolerancia {tolerancia_seg}s)")

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
