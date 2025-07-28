# algorithms/algoritmo3.py

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# Constantes de servicio y jornada
SERVICE_TIME = 10 * 60               # 10 min en segundos
SHIFT_START  =  9 * 3600             # 09:00 h
SHIFT_END    = 16 * 3600 + 15 * 60   # 16:15 h
MAX_WAIT     =  5 * 60               # slack máximo (5 min)

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    """
    data debe contener:
      - distance_matrix: matriz[n][n] de distancias en m
      - duration_matrix: matriz[n][n] de duraciones en s (incluye tráfico)
      - time_windows:   lista de n tuplas (start_s, end_s)
      - num_vehicles:   número de vehículos (aquí 1)
      - depot:          índice del depósito (0)
    """
    n = len(data["duration_matrix"])
    manager = pywrapcp.RoutingIndexManager(
        n,
        data["num_vehicles"],
        data["depot"]
    )
    routing = pywrapcp.RoutingModel(manager)

    # --- 1) Callback de tiempo (viaje + servicio) ---
    def time_cb(from_index, to_index):
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        travel = data["duration_matrix"][i][j]
        service = 0 if i == data["depot"] else SERVICE_TIME
        return travel + service

    transit_index = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_index)

    # --- 2) Dimensión de tiempo con slack (espera) ---
    routing.AddDimension(
        transit_index,
        MAX_WAIT,                   # slack máximo: 5 min
        SHIFT_END - SHIFT_START,    # límite total de ruta ~7h15m
        False,                      # no fijar hora inicial a 0
        "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # --- 3) Ventanas de tiempo (hard + soft) ---
    PENALTY_LATE = 1000  # costo por segundo tarde
    for node, (start, end) in enumerate(data["time_windows"]):
        idx = manager.NodeToIndex(node)
        # Hard window:
        time_dim.CumulVar(idx).SetRange(start, end)
        # Soft upper bound: permitir hasta end + MAX_WAIT con penalización
        time_dim.SetCumulVarSoftUpperBound(idx, end, PENALTY_LATE)

    # --- 4) Fijar salida del depósito a las 09:00 ---
    for veh in range(data["num_vehicles"]):
        idx_start = routing.Start(veh)
        time_dim.CumulVar(idx_start).SetRange(SHIFT_START, SHIFT_START)

    # --- 5) Parámetros de búsqueda CP-SAT + heurística ---
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.time_limit.seconds = tiempo_max_seg
    # Nearest/Cheapest Insertion como solución inicial
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.CHEAPEST_INSERTION
    )
    # Luego Guided Local Search para refinar
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )

    solution = routing.SolveWithParameters(search_params)
    if solution is None:
        return None

    # --- 6) Extraer rutas y ETAs reales ---
    rutas = []
    dist_total = 0
    for veh in range(data["num_vehicles"]):
        idx = routing.Start(veh)
        route, arr_times = [], []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            route.append(node)
            # Tiempo de llegada real:
            arr_times.append(solution.Value(time_dim.CumulVar(idx)))
            # acumular distancia
            nxt = solution.Value(routing.NextVar(idx))
            dist_total += data["distance_matrix"][node][
                manager.IndexToNode(nxt)
            ]
            idx = nxt
        rutas.append({
            "vehicle": veh,
            "route": route,
            "arrival_sec": arr_times
        })

    return {
        "routes": rutas,
        "distance_total_m": dist_total
    }
