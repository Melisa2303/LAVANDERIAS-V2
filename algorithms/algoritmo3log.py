from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO = 45 * 60         # 45 minutos

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))
    n = len(ventanas)

    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]

    # Restricciones de flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo con retraso
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Restricción de secuencia temporal
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Objetivo: minimizar tiempo total + retrasos penalizados
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * 20 for i in range(n))  # Penalización fuerte por retraso
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    def reconstruir_ruta(solver, ruta_vars):
        ruta = [0]
        actual = 0
        visitados = {0}
        while True:
            siguiente = None
            for j in range(n):
                if actual != j and (actual, j) in ruta_vars and solver.Value(ruta_vars[actual, j]) == 1:
                    siguiente = j
                    break
            if siguiente is None or siguiente in visitados:
                break
            ruta.append(siguiente)
            visitados.add(siguiente)
            actual = siguiente
        return ruta

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        ruta_cp = reconstruir_ruta(solver, x)
        llegada_cp = [solver.Value(t[i]) for i in ruta_cp]
        penalizacion_cp = sum(max(0, llegada_cp[i] - ventanas[ruta_cp[i]][1]) for i in range(len(ruta_cp)))
        distancia_cp = sum(dist[i][j] for i, j in zip(ruta_cp, ruta_cp[1:]))

    else:
        ruta_cp = []
        penalizacion_cp = float('inf')

    # Fallback heurístico: ordenar por fin de ventana
    def fallback():
        indices = list(range(1, n))
        indices.sort(key=lambda i: ventanas[i][1])  # Ordenar por fin de ventana
        orden = [0] + indices
        llegada = [ventanas[0][0]]
        for idx in range(1, len(orden)):
            i, j = orden[idx - 1], orden[idx]
            llegada.append(max(ventanas[j][0], llegada[-1] + service_times[i] + dur[i][j]))
        penalizacion = sum(max(0, llegada[i] - ventanas[orden[i]][1]) for i in range(len(orden)))
        distancia = sum(dist[orden[i]][orden[i+1]] for i in range(len(orden)-1))
        return orden, llegada, penalizacion, distancia

    ruta_fb, llegada_fb, penal_fb, dist_fb = fallback()

    # Decidir cuál usar
    if penal_fb < penalizacion_cp:
        return {
            "routes": [{
                "vehicle": 0,
                "route": ruta_fb,
                "arrival_sec": llegada_fb
            }],
            "distance_total_m": dist_fb
        }

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta_cp,
            "arrival_sec": [solver.Value(t[i]) for i in ruta_cp]
        }],
        "distance_total_m": sum(dist[i][j] for i, j in zip(ruta_cp, ruta_cp[1:]))
    }
