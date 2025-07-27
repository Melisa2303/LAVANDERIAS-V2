# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT   = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO     = 45 * 60       # 45 minutos
SHIFT_START_SEC        = 9 * 3600      # 09:00
SHIFT_END_SEC          = 16 * 3600 + 15 * 60  # 16:15
PESO_RETRASO           = 10
PESO_EXTENDIDO         = 100

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]

    # Variables para jornada extendida
    jornada_max = model.NewIntVar(0, 24*3600, "jornada_max")
    delta_ext = model.NewIntVar(0, 24*3600, "delta_ext")
    exceso_bool = model.NewBoolVar("ext")

    # Flujo (sin subtours)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo (con retraso)
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= max(SHIFT_START_SEC, ini))
        model.Add(t[i] <= fin + retraso[i])

    # Restricción temporal: secuencia con duraciones + servicio
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Evitar subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Jornada extendida: máxima llegada
    for i in range(n):
        model.Add(jornada_max >= t[i])

    # Penalización por jornada fuera de hora
    model.Add(delta_ext == jornada_max - SHIFT_END_SEC)
    model.Add(delta_ext >= 1).OnlyEnforceIf(exceso_bool)
    model.Add(delta_ext <= 0).OnlyEnforceIf(exceso_bool.Not())

    penalizacion_ext = model.NewIntVar(0, PESO_EXTENDIDO * 3600 * 4, "penalizacion_ext")
    model.AddMultiplicationEquality(penalizacion_ext, [delta_ext, exceso_bool])

    # Función objetivo
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * PESO_RETRASO for i in range(n)) +
        penalizacion_ext
    )

    # Solución
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstruir la ruta desde 0
        ruta = [0]
        actual = 0
        visitados = set(ruta)
        while True:
            siguiente = None
            for j in range(n):
                if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                    siguiente = j
                    break
            if siguiente is None or siguiente in visitados:
                break
            ruta.append(siguiente)
            visitados.add(siguiente)
            actual = siguiente

        llegada = [solver.Value(t[i]) for i in ruta]
        distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta,
                "arrival_sec": llegada
            }],
            "distance_total_m": distancia_total
        }

    # 🚨 Fallback ordenado por prioridad temporal (ventana más temprana)
    orden_prioridad = sorted(
        range(n), key=lambda i: (ventanas[i][1], ventanas[i][0])
    )
    llegada = []
    tiempo_actual = max(SHIFT_START_SEC, ventanas[orden_prioridad[0]][0])
    for i in orden_prioridad:
        llegada.append(tiempo_actual)
        tiempo_actual += service_times[i]

    distancia_total = sum(dist[orden_prioridad[i]][orden_prioridad[i+1]] for i in range(n - 1))

    return {
        "routes": [{
            "vehicle": 0,
            "route": orden_prioridad,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
