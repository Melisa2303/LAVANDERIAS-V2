# algorithms/algoritmo3.py

from ortools.sat.python import cp_model
import math

# --------------------------------------
#  CONSTANTES DE JORNADA Y SERVICIO
# --------------------------------------
SERVICE_TIME_DEFAULT = 10 * 60      # 10 min en segundos
SHIFT_START_SEC      =  9 * 3600    # 09:00 h
SHIFT_END_SEC        = 16 * 3600 + 15*60  # 16:15 h
ALLOWED_LATE         =  30 * 60    # +30 min tolerados (hasta 16:45)

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    """
    data = {
      "distance_matrix": [[...], ...],  # metros
      "duration_matrix": [[...], ...],  # segundos
      "time_windows":    [(ini, fin), ...],  # segundos desde 00:00
      "service_times":   [s_i, ...],    # segundos
      "num_vehicles":    1,
      "vehicle_capacities": [...],      # no usadas aquí
      "depot":           0
    }
    """
    dist    = data["distance_matrix"]
    dur     = data["duration_matrix"]
    windows = data["time_windows"]
    service = data.get("service_times",
                       [SERVICE_TIME_DEFAULT]*len(windows))
    n = len(dist)

    model = cp_model.CpModel()

    # ---------------------
    # Variables de decisión
    # ---------------------
    # x[i,j] = 1 si vamos directamente de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i,j] = model.NewBoolVar(f"x_{i}_{j}")

    # t[i] = tiempo de llegada al nodo i
    horizon = SHIFT_END_SEC + ALLOWED_LATE
    t = [model.NewIntVar(0, horizon, f"t_{i}") for i in range(n)]

    # Variables MTZ para eliminar subtours
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]

    # ---------------------
    # Restricciones de flujo
    # ---------------------
    # Cada nodo (excepto depósito) tiene exactamente 1 entrada y 1 salida
    for j in range(1, n):
        model.Add(sum(x[i,j] for i in range(n) if i!=j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i,j] for j in range(n) if i!=j) == 1)

    # El depósito (0) arranca y cierra la ruta una sola vez
    model.Add(sum(x[0,j] for j in range(1,n)) == 1)
    model.Add(sum(x[i,0] for i in range(1,n)) == 1)

    # ---------------------
    # Restricciones de tiempo
    # ---------------------
    # No llegamos antes de la apertura de cada ventana
    for i, (start, _) in enumerate(windows):
        model.Add(t[i] >= start)

    # Fijamos la salida del depósito a SHIFT_START_SEC
    model.Add(t[0] == SHIFT_START_SEC)

    # Si hacemos i→j, entonces t[j] ≥ t[i] + service[i] + travel[i][j]
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(
                    t[j] >= t[i] + service[i] + dur[i][j]
                ).OnlyEnforceIf(x[i,j])

    # --------------------------------------
    # Eliminación de subtours: formulario MTZ
    # --------------------------------------
    # u[0] == 0
    model.Add(u[0] == 0)
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                # Si x[i,j]=1 entonces u[i]+1 <= u[j]
                model.Add(u[i] + 1 <= u[j] + n*(1 - x[i,j]))

    # ---------------------
    # Objetivo: minimizar distancia
    # ---------------------
    model.Minimize(
        sum(dist[i][j] * x[i,j] for (i,j) in x)
    )

    # ---------------------
    # Solver
    # ---------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Fallback: ruta natural sin optimizar
        ruta = list(range(n))
        llegada = []
        current = SHIFT_START_SEC
        for i in ruta:
            # respetar apertura de ventana, al menos start_i
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

    # ---------------------
    # Reconstrucción de la ruta
    # ---------------------
    ruta = [0]
    actual = 0
    visitados = {0}
    while True:
        siguiente = None
        for j in range(n):
            if j != actual and solver.Value(x[actual,j]) == 1:
                if j in visitados:
                    # ciclo detectado
                    siguiente = None
                else:
                    siguiente = j
                break
        if siguiente is None:
            break
        ruta.append(siguiente)
        visitados.add(siguiente)
        actual = siguiente

    # Cálculo de llegadas
    llegada = [solver.Value(t[i]) for i in ruta]

    # Distancia total
    distancia = 0
    for a,b in zip(ruta, ruta[1:]):
        distancia += dist[a][b]

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia
    }
