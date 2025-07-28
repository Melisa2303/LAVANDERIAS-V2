# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
from typing import Dict, Any

# ----------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# ----------------------------------
SERVICE_TIME   = 10 * 60           # 10 minutos en segundos
SHIFT_START    =  8.5 * 3600         # 09:00 en segundos
SHIFT_END      = 16 * 3600 + 15*60 # 16:15 en segundos
ALLOWED_LATE   =  30 * 60          # se puede llegar hasta 16:45
MAX_TRAVEL     =  35 * 60          # no permitimos viajes > 40 min

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 120) -> Dict[str, Any]:
    """
    data debe contener:
      - distance_matrix: matriz de distancias (m)
      - duration_matrix: matriz de tiempos (s)
      - time_windows:    lista de tuplas (ini_s, fin_s)
      - service_times:   lista de servicio por nodo (s)
      - num_vehicles:    asumimos 1
      - depot:           índice del depósito (0)
    Devuelve dict con 'routes' y 'distance_total_m'.
    """

    D        = data["distance_matrix"]
    T        = data["duration_matrix"]
    windows  = data["time_windows"]
    service  = data.get("service_times", [SERVICE_TIME] * len(windows))
    n        = len(D)

    # --- Modelo CP-SAT ---
    model = cp_model.CpModel()

    # Arcos x[i,j]
    x = {}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            var = model.NewBoolVar(f"x_{i}_{j}")
             if T[i][j] > MAX_TRAVEL:
                model.Add(var == 0)
            x[i, j] = var

     horizon = SHIFT_END + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

     u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]

    # --- Restricciones de flujo ---
    # Cada nodo j≠0 entra una vez
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    # Cada nodo i≠0 sale una vez
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)
    # Depósito 0 entra y sale exactamente una vez
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # --- Ventanas de tiempo con lateness permitido ---
    # Salida fija depósito a las xx:xx (por el momento está a las 9:00 am)
    model.Add(t[0] == SHIFT_START)
    for i, (start, end) in enumerate(windows):
        model.Add(t[i] >= start)
        model.Add(t[i] <= end + ALLOWED_LATE)

     for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # si x[i,j]=1 entonces t[j] ≥ t[i]+service[i]+travel
            model.Add(
                t[j] >= t[i] + service[i] + T[i][j]
            ).OnlyEnforceIf(x[i, j])

     model.Add(u[0] == 0)
    for i in range(1, n):
        for j in range(1, n):
            if i == j:
                continue
            model.Add(u[i] + 1 <= u[j] + n * (1 - x[i, j]))

     model.Minimize(
        sum(D[i][j] * x[i, j] for (i, j) in x)
    )

    # --- Resolver ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

     if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _fallback_insertion(data)

    # --- Reconstruir la ruta ---
    ruta   = [0]
    actual = 0
    visit  = {0}
    while True:
        siguiente = None
        for j in range(n):
            if j != actual and solver.Value(x[actual, j]) == 1:
                if j in visit:
                    siguiente = None
                else:
                    siguiente = j
                break
        if siguiente is None:
            break
        ruta.append(siguiente)
        visit.add(siguiente)
        actual = siguiente

    # --- Calcular tiempos de llegada y distancia ---
    llegada   = [solver.Value(t[i]) for i in ruta]
    distancia = sum(D[a][b] for a, b in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle":      0,
            "route":        ruta,
            "arrival_sec":  llegada
        }],
        "distance_total_m": distancia
    }


def _fallback_insertion(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Nearest Insertion: garantiza que siempre se visite todo,
    respetando ventanas (ajustando llegada al slot).
    """
    D        = data["distance_matrix"]
    T        = data["duration_matrix"]
    windows  = data["time_windows"]
    service  = data.get("service_times", [SERVICE_TIME] * len(windows))
    n        = len(D)

    visitados  = [0]
    restantes  = set(range(1, n))
    tiempos    = [SHIFT_START] + [0] * (n - 1)

    # Insertar cada nodo en la posición de mínimo costo incremental
    while restantes:
        mejor_cost = float("inf")
        mejor_j    = None
        mejor_pos  = None

        for j in restantes:
            for pos in range(1, len(visitados) + 1):
                ant = visitados[pos - 1]
                sig = visitados[pos] if pos < len(visitados) else None
                cost = D[ant][j]
                if sig is not None:
                    cost += D[j][sig] - D[ant][sig]
                if cost < mejor_cost:
                    mejor_cost = cost
                    mejor_j    = j
                    mejor_pos  = pos

        visitados.insert(mejor_pos, mejor_j)
        restantes.remove(mejor_j)

    # Calcular ETA respetando ventana y tiempo de servicio
    times = [SHIFT_START]
    for idx in range(1, len(visitados)):
        u = visitados[idx - 1]
        v = visitados[idx]
        eta = times[-1] + service[u] + T[u][v]
        # si antes de ventana de v, esperamos (pero no más allá de fin+ALLOWED_LATE)
        ini, fin = windows[v]
        if eta < ini:
            eta = ini
        if eta > fin + ALLOWED_LATE:
            eta = fin + ALLOWED_LATE
        times.append(eta)

    distancia = sum(D[visitados[i]][visitados[i + 1]]
                    for i in range(len(visitados) - 1))

    return {
        "routes": [{
            "vehicle":      0,
            "route":        visitados,
            "arrival_sec":  times
        }],
        "distance_total_m": distancia
    }
