# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np

SERVICE_TIME_DEFAULT = 10 * 60
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60
TOLERANCIA_RETRASO = 30 * 60

# Pesos relativos
PESO_RETRASO = 15
PESO_ANTICIPO = 6
PESO_ESPERA = 2
PESO_JORNADA_EXT = 8

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))
    n = len(ventanas)

    model = cp_model.CpModel()

    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]

    retraso = []
    anticipo = []
    espera = []

    for i in range(n):
        ini, fin = ventanas[i]
        retraso_i = model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}")
        anticipo_i = model.NewIntVar(0, 3600, f"ant_{i}")
        espera_i = model.NewIntVar(0, 3600 * 2, f"esp_{i}")
        retraso.append(retraso_i)
        anticipo.append(anticipo_i)
        espera.append(espera_i)

        # Retraso = max(0, t[i] - fin)
        diff_ret = model.NewIntVar(-86400, 86400, f"diff_ret_{i}")
        model.Add(diff_ret == t[i] - fin)
        model.AddMaxEquality(retraso_i, [diff_ret, 0])

        # Anticipo = max(0, ini - t[i])
        diff_ant = model.NewIntVar(-86400, 86400, f"diff_ant_{i}")
        model.Add(diff_ant == ini - t[i])
        model.AddMaxEquality(anticipo_i, [diff_ant, 0])

        # Espera = max(0, ini - t[i]) cuando se llega antes
        model.Add(espera_i == anticipo_i)

    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Penalización por jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 12 * 3600, "delta_ext")
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(end_time > SHIFT_END)
    model.Add(delta_ext == 0).OnlyEnforceIf(end_time <= SHIFT_END)
    penal_ext = delta_ext

    obj_terms = []

    for i in range(n):
        w_r = max(1, ventanas[i][1] - ventanas[i][0])
        obj_terms.append(retraso[i] * PESO_RETRASO // w_r)
        obj_terms.append(anticipo[i] * PESO_ANTICIPO)
        obj_terms.append(espera[i] * PESO_ESPERA)

    obj_terms.append(penal_ext * PESO_JORNADA_EXT)
    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
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

        if len(ruta) < n:
            # Fallback si no visitó suficientes puntos
            return _fallback_nearest_insertion(dur, dist, ventanas, service_times)

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

    # Fallback directo
    return _fallback_nearest_insertion(dur, dist, ventanas, service_times)


def _fallback_nearest_insertion(dur, dist, ventanas, service_times):
    n = len(dur)
    visitados = set([0])
    ruta = [0]
    llegada = [ventanas[0][0]]
    actual = 0

    while len(visitados) < n:
        mejor = None
        mejor_idx = -1
        mejor_penal = float("inf")

        for j in range(1, n):
            if j in visitados:
                continue
            llegada_est = llegada[-1] + service_times[actual] + dur[actual][j]
            ini_j, fin_j = ventanas[j]

            espera = max(0, ini_j - llegada_est)
            retraso = max(0, llegada_est - fin_j)
            penal = retraso * 100 + espera

            if penal < mejor_penal:
                mejor_penal = penal
                mejor = j
                mejor_idx = j

        if mejor is None:
            break
        llegada_est = max(ventanas[mejor_idx][0], llegada[-1] + service_times[actual] + dur[actual][mejor_idx])
        ruta.append(mejor_idx)
        llegada.append(llegada_est)
        visitados.add(mejor_idx)
        actual = mejor_idx

    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
