# algorithms/algoritmo3.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos por cliente
TOLERANCIA_RETRASO = 30 * 60         # 30 minutos máximo
PESO_RETRASO = 100                   # penalización por segundo de retraso
PESO_ESPERA = 1                      # penalización por segundo de espera
PESO_EXTENDIDO = 1000                # penalización por exceder jornada
SHIFT_START = 9 * 3600               # 09:00:00 en segundos
SHIFT_END = 16 * 3600 + 15 * 60      # 16:15:00 en segundos

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
    t = [model.NewIntVar(SHIFT_START, SHIFT_END + TOLERANCIA_RETRASO, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, SHIFT_END, f"espera_{i}") for i in range(n)]
    jornada_ext = model.NewIntVar(0, 3600*12, "jornada_ext")

    # Flujo de nodos
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo flexibles con penalización por retraso
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(espera[i] >= t[i] - ini)

    # Restricciones temporales por viaje
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtours: MTZ (aunque es VRP de 1 solo vehículo)
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Tiempo de fin de jornada
    model.AddMaxEquality(jornada_ext, [t[i] + service_times[i] for i in range(n)])

    # Penalización final: distancia + retraso + espera + jornada extendida
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(PESO_RETRASO * retraso[i] for i in range(n)) +
        sum(PESO_ESPERA * espera[i] for i in range(n)) +
        PESO_EXTENDIDO * model.NewIntVar(0, 1, "ext") * model.NewIntVar(0, 3600*4, "delta_ext")
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstrucción
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

    # Fallback robusto: secuencia de IDs + ETA simulada
    ruta = list(range(n))
    llegada = []
    tiempo_actual = max(ventanas[0][0], SHIFT_START)
    for i in ruta:
        llegada.append(tiempo_actual)
        tiempo_actual += service_times[i] + (dur[i][ruta[ruta.index(i)+1]] if ruta.index(i)+1 < n else 0)

    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
