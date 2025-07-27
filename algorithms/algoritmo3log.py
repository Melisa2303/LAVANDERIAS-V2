from ortools.sat.python import cp_model

SERVICE_TIME_DEFAULT = 10 * 60
TOLERANCIA_RETRASO = 45 * 60
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16 * 3600 + 15 * 60

PESO_RETRASO   = 20
PESO_ANTICIPO  = 2
PESO_EXTENDIDO = 1000
PESO_ESPERA    = 1

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    dur = data["duration_matrix"]
    dist = data["distance_matrix"]
    ventanas = data["time_windows"]
    service_times = data.get("service_times", [SERVICE_TIME_DEFAULT] * len(ventanas))

    n = len(ventanas)
    model = cp_model.CpModel()

    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}")
         for i in range(n) for j in range(n) if i != j}
    t = [model.NewIntVar(0, 24*3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]
    espera = [model.NewIntVar(0, 12*3600, f"espera_{i}") for i in range(n)]
    anticipo = [model.NewIntVar(0, 12*3600, f"anticipo_{i}") for i in range(n)]

    for i in range(n):
        ini, fin = ventanas[i]
        mid = (ini + fin) // 2
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])
        model.Add(espera[i] == t[i] - ini)
        model.Add(anticipo[i] == model.NewIntVar(0, mid, f"max0_{i}"))
        model.AddMaxEquality(anticipo[i], [mid - t[i], 0])

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

    jornada_fin = model.NewIntVar(0, 24*3600, "jornada_fin")
    model.AddMaxEquality(jornada_fin, [t[i] + service_times[i] for i in range(n)])
    delta_ext = model.NewIntVar(0, 3600*4, "delta_ext")
    model.Add(delta_ext == model.NewIntVar(0, 3600*4, "max0_ext"))
    model.AddMaxEquality(delta_ext, [jornada_fin - SHIFT_END_SEC, 0])

    obj = sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j)
    obj += sum(retraso[i] * PESO_RETRASO // max(1, ventanas[i][1] - ventanas[i][0]) for i in range(n))
    obj += sum(espera[i] * PESO_ESPERA for i in range(n))
    obj += sum(anticipo[i] * PESO_ANTICIPO for i in range(n))
    obj += PESO_EXTENDIDO * delta_ext

    model.Minimize(obj)

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
                if actual != j and (actual, j) in x and solver.Value(x[actual, j]):
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

    # fallback
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
