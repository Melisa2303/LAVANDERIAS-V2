from ortools.sat.python import cp_model
import numpy as np

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [600] * len(ventanas))

    SHIFT_START = 9 * 3600
    SHIFT_END   = 16 * 3600 + 15 * 60

    PESO_RETRASO = 4
    PESO_ANTICIPO = 1
    PESO_JORNADA_EXT = 10
    PESO_ESPERA = 1

    n = len(ventanas)
    model = cp_model.CpModel()

    # Variables
    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso  = [model.NewIntVar(0, 12*3600, f"ret_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 12*3600, f"ant_{i}") for i in range(n)]
    espera   = [model.NewIntVar(0, 12*3600, f"espera_{i}") for i in range(n)]

    # Restricciones de ventanas de tiempo y penalizaciones
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + 3600)

        model.Add(retraso[i] >= t[i] - fin)
        model.Add(anticipo[i] >= ini - t[i])
        model.Add(espera[i] >= ini - t[i])

    # Flujo
    for i in range(n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) <= 1)
        model.Add(sum(x[j, i] for j in range(n) if j != i) <= 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Fin de jornada (tiempo máximo entre todos los clientes)
    end_time = model.NewIntVar(0, 24*3600, "end_time")
    model.AddMaxEquality(end_time, t)
    jornada_extra = model.NewIntVar(0, 12*3600, "jornada_extra")
    model.Add(jornada_extra >= end_time - SHIFT_END)
    model.Add(jornada_extra >= 0)

    # Objetivo: minimizar penalidades
    obj = model.NewIntVar(0, 10000000, "obj")
    terms = []

    for i in range(n):
        ventana_duracion = max(1, ventanas[i][1] - ventanas[i][0])
        peso_ret = PESO_RETRASO * 3600 // ventana_duracion
        terms.append(retraso[i] * peso_ret)
        terms.append(anticipo[i] * PESO_ANTICIPO)
        terms.append(espera[i] * PESO_ESPERA)

    terms.append(jornada_extra * PESO_JORNADA_EXT)

    model.Add(obj == sum(terms))
    model.Minimize(obj)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Reconstrucción de la ruta
        ruta = []
        visitado = set()
        actual = np.argmin([solver.Value(t[i]) for i in range(n)])
        while True:
            if actual in visitado:
                break
            ruta.append(actual)
            visitado.add(actual)
            siguiente = None
            for j in range(n):
                if actual != j and (actual, j) in x and solver.BooleanValue(x[actual, j]):
                    siguiente = j
                    break
            if siguiente is None:
                break
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

    # Fallback: heurística híbrida por ventana ajustada + cercanía
    penalidades = []
    for i in range(n):
        duracion = max(1, ventanas[i][1] - ventanas[i][0])
        penal = duracion + sum(dur[i]) // n
        penalidades.append((penal, i))
    penalidades.sort()
    orden = [i for _, i in penalidades]
    llegada = [ventanas[orden[0]][0]]
    for k in range(1, len(orden)):
        prev = orden[k - 1]
        curr = orden[k]
        llegada.append(max(ventanas[curr][0], llegada[-1] + service_times[prev] + dur[prev][curr]))

    distancia_total = sum(dist[i][j] for i, j in zip(orden, orden[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": orden,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
