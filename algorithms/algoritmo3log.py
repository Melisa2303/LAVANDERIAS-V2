# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model

# --------------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# --------------------------------------
SERVICE_TIME_DEFAULT = 10 * 60      # 10 min en segundos
SHIFT_START_SEC      =  9 * 3600    # 09:00
SHIFT_END_SEC        = 16 * 3600 + 15*60  # 16:15
ALLOWED_LATE         =  30 * 60    # hasta 16:45

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    """
    data dict con:
      - distance_matrix: [[m, …], …]
      - duration_matrix: [[s, …], …]
      - time_windows:    [(ini_s, fin_s), …]
      - service_times:   [s_i, …] (si falta, usa SERVICE_TIME_DEFAULT)
      - num_vehicles:    1
      - depot:           0
    Devuelve { "routes": [{ "vehicle":0, "route":[…], "arrival_sec":[…] }], 
               "distance_total_m": … }
    """

    dist    = data["distance_matrix"]
    dur     = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times",
                       [SERVICE_TIME_DEFAULT] * len(windows))
    n = len(dist)

    # Modelo CP-SAT
    model = cp_model.CpModel()

    # 1) Variables de arco x[i,j] si vamos i→j
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i,j] = model.NewBoolVar(f"x_{i}_{j}")

    # 2) Tiempo de llegada t[i]
    horizon = SHIFT_END_SEC + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # 3) Variables MTZ para eliminar subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # --- Restricciones de flujo ---
    # Cada nodo j≠0 tiene exactamente 1 entrada
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j) == 1)
    # Cada nodo i≠0 tiene exactamente 1 salida
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if i!=j) == 1)
    # El depósito 0 entra y sale 1 vez
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # --- Ventanas de tiempo (hard + lateness) ---
    # No llegamos antes de apertura
    for i, (start, _) in enumerate(windows):
        model.Add(t[i] >= start)
    # No llegamos demasiado tarde: fin + ALLOWED_LATE
    for i, (_, end) in enumerate(windows):
        model.Add(t[i] <= end + ALLOWED_LATE)
    # Salida depósito fija a las 09:00
    model.Add(t[0] == SHIFT_START_SEC)

    # --- Si x[i,j]=1 entonces t[j] ≥ t[i] + service[i] + dur[i][j] ---
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(
                    t[j] >= t[i] + service[i] + dur[i][j]
                ).OnlyEnforceIf(x[i,j])

    # --- Subtour elimination (MTZ) ---
    model.Add(u[0] == 0)
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                # u[i] + 1 ≤ u[j] + n * (1 - x[i,j])
                model.Add(u[i] + 1 <= u[j] + n * (1 - x[i,j]))

    # --- Objetivo: minimizar solo distancia ---
    model.Minimize(sum(dist[i][j] * x[i,j] for (i,j) in x))

    # --- Resolver ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    # --- Fallback si no encuentra nada ---
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Ruta natural de 0…n-1 respetando sólo apertura
        ruta = list(range(n))
        llegada = []
        current = SHIFT_START_SEC
        for i in ruta:
            current = max(current, windows[i][0])
            llegada.append(current)
            current += service[i]
        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": 0
        }

    # --- Reconstrucción de la ruta del solver ---
    ruta = [0]
    actual = 0
    seen = {0}
    while True:
        siguiente = None
        for j in range(n):
            if j != actual and solver.Value(x[actual,j]) == 1:
                if j in seen:
                    siguiente = None
                else:
                    siguiente = j
                break
        if siguiente is None:
            break
        ruta.append(siguiente)
        seen.add(siguiente)
        actual = siguiente

    # --- Cálculo de llegadas y distancia total ---
    llegada = [solver.Value(t[i]) for i in ruta]
    distancia = sum(dist[a][b] for a,b in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia
    }
