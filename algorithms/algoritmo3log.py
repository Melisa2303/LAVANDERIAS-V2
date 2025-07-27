from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60  # 10 min
TOLERANCIA_RETRASO = 30 * 60    # 30 min
JORNADA_INICIO = 9 * 3600       # 09:00
JORNADA_FIN = 16 * 3600 + 15 * 60  # 16:15

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]

    # Flujo: entrada/salida única (salvo depósito)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)

    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo y retraso permitido
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Restricción temporal secuencial
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtour eliminations (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Penalización proporcional al ancho de la ventana
    penalizaciones = []
    for i in range(n):
        ini, fin = ventanas[i]
        ancho = max(1, fin - ini)
        peso = int(100000 / ancho)
        penalizaciones.append(retraso[i] * peso)

    # Penalización por empezar jornada antes o después del horario permitido
    exceso_inicio = model.NewIntVar(0, 24 * 3600, "exceso_inicio")
    exceso_fin = model.NewIntVar(0, 24 * 3600, "exceso_fin")
    model.AddMaxEquality(exceso_inicio, [0, JORNADA_INICIO - t[1]])
    model.AddMaxEquality(exceso_fin, [0, t[-1] - JORNADA_FIN])

    # Función objetivo
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(penalizaciones) +
        exceso_inicio * 100 +
        exceso_fin * 100
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstrucción de la ruta
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

    # 🚨 Fallback si no encuentra solución
    ruta = list(range(n))
    llegada = [ventanas[i][0] + service_times[i] for i in ruta]
    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
