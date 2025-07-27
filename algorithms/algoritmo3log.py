# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO = 45 * 60         # 45 minutos
SHIFT_START = 9 * 3600               # 9:00 a.m.
SHIFT_END   = 16 * 3600 + 15 * 60    # 4:15 p.m.

# Pesos de penalización
PESO_RETRASO = 20
PESO_ANTICIPO = 5
PESO_ESPERA = 1
PESO_JORNADA_EXT = 10

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

    # Variables auxiliares para penalizaciones
    retraso = []
    anticipo = []
    espera = []
    for i in range(n):
        ini, fin = ventanas[i]
        r = model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}")
        a = model.NewIntVar(0, fin - ini, f"ant_{i}")
        w = model.NewIntVar(0, 3 * 3600, f"esp_{i}")  # máximo 3h espera
        retraso.append(r)
        anticipo.append(a)
        espera.append(w)

        # Retraso: t > fin
        is_late = model.NewBoolVar(f"is_late_{i}")
        model.Add(t[i] > fin).OnlyEnforceIf(is_late)
        model.Add(t[i] <= fin).OnlyEnforceIf(is_late.Not())
        model.Add(r == t[i] - fin).OnlyEnforceIf(is_late)
        model.Add(r == 0).OnlyEnforceIf(is_late.Not())

        # Anticipo: t < (ini + fin)//2
        mid = (ini + fin) // 2
        is_early = model.NewBoolVar(f"is_early_{i}")
        model.Add(t[i] < mid).OnlyEnforceIf(is_early)
        model.Add(t[i] >= mid).OnlyEnforceIf(is_early.Not())
        model.Add(a == mid - t[i]).OnlyEnforceIf(is_early)
        model.Add(a == 0).OnlyEnforceIf(is_early.Not())

        # Espera: t < ini
        is_wait = model.NewBoolVar(f"is_wait_{i}")
        model.Add(t[i] < ini).OnlyEnforceIf(is_wait)
        model.Add(t[i] >= ini).OnlyEnforceIf(is_wait.Not())
        model.Add(w == ini - t[i]).OnlyEnforceIf(is_wait)
        model.Add(w == 0).OnlyEnforceIf(is_wait.Not())

    # Flujo de visitas
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Restricción de tiempo entre nodos
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtour elimination (MTZ)
    u = [model.NewIntVar(0, n-1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Penalizar extensión de jornada
    end_time = model.NewIntVar(0, 24*3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 4 * 3600, "delta_ext")
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(end_time > SHIFT_END)
    model.Add(delta_ext == 0).OnlyEnforceIf(end_time <= SHIFT_END)

    # Objetivo: minimizar distancia + penalizaciones
    obj_terms = [dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j]
    for i in range(n):
        w_r = max(1, ventanas[i][1] - ventanas[i][0])
        obj_terms.append(PESO_RETRASO * retraso[i] // w_r)
        obj_terms.append(PESO_ANTICIPO * anticipo[i])
        obj_terms.append(PESO_ESPERA * espera[i])
    obj_terms.append(PESO_JORNADA_EXT * delta_ext)

    model.Minimize(sum(obj_terms))

    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstruir ruta
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

    # Fallback
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
