from ortools.sat.python import cp_model

SERVICE_TIME_DEFAULT = 10 * 60       # 10 minutos
SHIFT_START = 9 * 3600               # 09:00
SHIFT_END   = 16 * 3600 + 15 * 60    # 16:15
BIG_M = 10**6

# Pesos de penalización
PESO_DISTANCIA = 1
PESO_RETRASO = 300
PESO_ANTICIPO = 100
PESO_ESPERA = 80
PESO_JORNADA_EXT = 400

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

    retraso, anticipo, espera = [], [], []
    penalizaciones = []

    for i in range(n):
        ini, fin = ventanas[i]
        dur_vent = max(1, fin - ini)
        r = model.NewIntVar(0, 4*3600, f"retraso_{i}")
        a = model.NewIntVar(0, 4*3600, f"anticipo_{i}")
        w = model.NewIntVar(0, 4*3600, f"espera_{i}")
        model.Add(r >= t[i] - fin)
        model.Add(r >= 0)
        model.Add(a >= ini - t[i])
        model.Add(a >= 0)
        model.Add(w >= ini - t[i])
        model.Add(w >= 0)
        retraso.append((r, dur_vent))
        anticipo.append((a, dur_vent))
        espera.append(w)

    # Jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    penal_ext = model.NewIntVar(0, 8*3600, "delta_ext")
    model.Add(penal_ext >= end_time - SHIFT_END)
    model.Add(penal_ext >= 0)

    # Flujo
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

    # Subtours (MTZ)
    u = [model.NewIntVar(0, n - 1, f"u_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + (n - 1) * (1 - x[i, j]))

    # Función objetivo robusta
    obj_terms = []

    obj_terms += [PESO_DISTANCIA * dist[i][j] * x[i, j]
                  for i in range(n) for j in range(n) if i != j]

    for i in range(n):
        r, w_r = retraso[i]
        a, w_a = anticipo[i]
        obj_terms.append(PESO_RETRASO * r // w_r)
        obj_terms.append(PESO_ANTICIPO * a // w_a)
        obj_terms.append(PESO_ESPERA * espera[i])

    obj_terms.append(PESO_JORNADA_EXT * penal_ext)

    model.Minimize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        ruta = [0]
        actual = 0
        visitados = set(ruta)
        while True:
            found = False
            for j in range(n):
                if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                    if j in visitados:
                        break
                    ruta.append(j)
                    visitados.add(j)
                    actual = j
                    found = True
                    break
            if not found:
                break
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

    # Fallback heurístico si no se encuentra solución
    penal = [(ventanas[i][0] + 3*dist[0][i], i) for i in range(1, n)]
    penal.sort()
    ruta = [0] + [i for _, i in penal]
    llegada = [SHIFT_START]
    for i in range(1, len(ruta)):
        prev = ruta[i - 1]
        curr = ruta[i]
        start = llegada[-1] + service_times[prev] + dur[prev][curr]
        llegada.append(start)
    distancia_total = sum(dist[i][j] for i, j in zip(ruta, ruta[1:]))

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia_total
    }
