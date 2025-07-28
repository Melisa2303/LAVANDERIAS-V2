def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion secuencial con:
      - NO huecos > 1h
      - NO exclusión de clientes
      - Atención aunque haya que esperar o llegar tarde
    """
    D       = data["distance_matrix"]
    T       = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times", [SERVICE_TIME]*len(windows))
    n       = len(D)

    visitados = [0]
    llegada   = [SHIFT_START]
    restantes = set(range(1, n))

    t_actual = SHIFT_START
    nodo_act = 0
    MAX_WAIT = 1800  # espera deseada: 30min
    MAX_GAP  = 3600  # evitar huecos >1h

    while restantes:
        mejores_opciones = []

        for j in restantes:
            travel_time = T[nodo_act][j]
            eta         = t_actual + service[nodo_act] + travel_time
            ini_j, fin_j = windows[j]

            # ETA ajustada si hay que esperar
            t_llegada = max(eta, ini_j)
            espera    = max(0, ini_j - eta)
            tarde     = max(0, eta - fin_j)

            ventana_dur = fin_j - ini_j
            prioridad   = 10000 // (1 + ventana_dur)  # más prioridad a ventanas angostas

            # Penalización por:
            # - espera
            # - retraso
            # - distancia
            score = (
                espera * 1.5 +
                tarde * 5 +
                D[nodo_act][j] +
                prioridad
            )
            mejores_opciones.append((score, j, t_llegada))

        # Elegir el mejor (aunque implique espera o llegada tarde)
        mejores_opciones.sort()
        _, best_j, eta_real = mejores_opciones[0]

        # Agregar a la ruta
        visitados.append(best_j)
        llegada.append(eta_real)
        restantes.remove(best_j)

        t_actual = eta_real
        nodo_act = best_j

    # Recalcular llegada final (robusto)
    llegada_final = []
    t_now = SHIFT_START
    for idx, node in enumerate(visitados):
        if idx > 0:
            prev = visitados[idx-1]
            t_now += service[prev] + T[prev][node]
        t_now = max(t_now, windows[node][0])
        llegada_final.append(t_now)

    dist_total = sum(
        D[visitados[i]][visitados[i+1]]
        for i in range(len(visitados)-1)
    )

    return {
        "routes": [{"vehicle": 0, "route": visitados, "arrival_sec": llegada_final}],
        "distance_total_m": dist_total
    }
