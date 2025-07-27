# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
TOLERANCIA_RETRASO   = 45 * 60       # 45 minutos
SHIFT_START          = 9 * 3600      # 09:00
SHIFT_END            = 16 * 3600 + 15 * 60  # 16:15

PESO_RETRASO     = 15
PESO_ANTICIPO    = 10
PESO_ESPERA      = 8
PESO_JORNADA_EXT = 50

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
    retraso  = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 12 * 3600, f"anti_{i}") for i in range(n)]
    espera   = [model.NewIntVar(0, 12 * 3600, f"espera_{i}") for i in range(n)]

    # Flujo (exactamente una entrada/salida para cada nodo)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas con retraso y anticipo
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini - anticipo[i])
        model.Add(t[i] <= fin + retraso[i])
        model.Add(espera[i] == ini - t[i]).OnlyEnforceIf(t[i] < ini)
        model.Add(espera[i] == 0).OnlyEnforceIf(t[i] >= ini)

    # Restricción temporal entre visitas
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Subtour elimination (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Penalización por extensión de jornada
    end_time = model.NewIntVar(0, 24 * 3600, "end_time")
    model.AddMaxEquality(end_time, t)
    exceso_jornada = model.NewIntVar(0, 6 * 3600, "delta_ext")
    model.Add(exceso_jornada == end_time - SHIFT_END).OnlyEnforceIf(end_time > SHIFT_END)
    model.Add(exceso_jornada == 0).OnlyEnforceIf(end_time <= SHIFT_END)

    # Penalización dinámica por ancho de ventana
    obj_terms = []
    for i in range(n):
        w_r = ventanas[i][1] - ventanas[i][0]
        w_r_safe = max(1, w_r)

        # Variables de penalización individuales escaladas
        ret_div   = model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_div_{i}")
        anti_div  = model.NewIntVar(0, 12 * 3600, f"anti_div_{i}")
        espera_div= model.NewIntVar(0, 12 * 3600, f"esp_div_{i}")

        model.AddDivisionEquality(ret_div, retraso[i], w_r_safe)
        model.AddDivisionEquality(anti_div, anticipo[i], w_r_safe)
        model.AddDivisionEquality(espera_div, espera[i], w_r_safe)

        obj_terms.append(ret_div   * PESO_RETRASO)
        obj_terms.append(anti_div  * PESO_ANTICIPO)
        obj_terms.append(espera_div* PESO_ESPERA)

    obj_terms.append(exceso_jornada * PESO_JORNADA_EXT)

    model.Minimize(sum(obj_terms))

    # Solución
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstrucción de ruta
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

    # Fallback heurístico
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
