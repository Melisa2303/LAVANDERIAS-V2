from ortools.sat.python import cp_model
import math

SHIFT_START = 9 * 3600       # 9:00
SHIFT_END   = 16 * 3600 + 15 * 60  # 16:15
PESO_RETRASO       = 4
PESO_ANTICIPO      = 2
PESO_ESPERA        = 1
PESO_JORNADA_EXT   = 10_000
PESO_NO_VISITADO   = 100_000

def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    W = data["time_windows"]
    S = data["service_times"]
    n = len(D)

    model = cp_model.CpModel()
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    x = [[model.NewBoolVar(f"x_{i}_{j}") for j in range(n)] for i in range(n)]
    u = [model.NewIntVar(0, n, f"u_{i}") for i in range(n)]  # secuencia para subciclos

    retraso, anticipo, espera = [], [], []
    penalizaciones = []

    for i in range(n):
        ini, fin = W[i]
        s_i = S[i]
        retraso_i = model.NewIntVar(0, 24 * 3600, f"retraso_{i}")
        anticipo_i = model.NewIntVar(0, 24 * 3600, f"anticipo_{i}")
        espera_i   = model.NewIntVar(0, 24 * 3600, f"espera_{i}")

        # Penalización dinámica por ancho de ventana
        ancho_ventana = max(1, fin - ini)
        bool_retraso  = model.NewBoolVar(f"r_on_{i}")
        bool_anticipo = model.NewBoolVar(f"a_on_{i}")
        bool_espera   = model.NewBoolVar(f"w_on_{i}")

        model.Add(t[i] > fin).OnlyEnforceIf(bool_retraso)
        model.Add(t[i] <= fin).OnlyEnforceIf(bool_retraso.Not())
        model.Add(t[i] < ini).OnlyEnforceIf(bool_anticipo)
        model.Add(t[i] >= ini).OnlyEnforceIf(bool_anticipo.Not())
        model.Add(t[i] >= ini).OnlyEnforceIf(bool_espera)
        model.Add(t[i] < ini).OnlyEnforceIf(bool_espera.Not())

        model.Add(retraso_i == t[i] - fin).OnlyEnforceIf(bool_retraso)
        model.Add(retraso_i == 0).OnlyEnforceIf(bool_retraso.Not())
        model.Add(anticipo_i == ini - t[i]).OnlyEnforceIf(bool_anticipo)
        model.Add(anticipo_i == 0).OnlyEnforceIf(bool_anticipo.Not())
        model.Add(espera_i == ini - t[i]).OnlyEnforceIf(bool_espera)
        model.Add(espera_i == 0).OnlyEnforceIf(bool_espera.Not())

        retraso.append(retraso_i)
        anticipo.append(anticipo_i)
        espera.append(espera_i)

        # Penalizaciones
        model.AddDivisionEquality(model.NewIntVar(0, 100_000, ""), retraso_i, ancho_ventana)
        model.AddDivisionEquality(model.NewIntVar(0, 100_000, ""), anticipo_i, ancho_ventana)

        penalizaciones.append(PESO_RETRASO * retraso_i // ancho_ventana)
        penalizaciones.append(PESO_ANTICIPO * anticipo_i // ancho_ventana)
        penalizaciones.append(PESO_ESPERA * espera_i)

    # Ruta: visitamos exactamente n nodos
    for i in range(n):
        model.Add(sum(x[i][j] for j in range(n) if j != i) == 1)
        model.Add(sum(x[j][i] for j in range(n) if j != i) == 1)

    # Subciclos
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(u[i] + 1 <= u[j] + n * (1 - x[i][j]))

    # Tiempo de llegada
    for i in range(n):
        for j in range(n):
            if i != j:
                travel = T[i][j]
                model.Add(t[j] >= t[i] + S[i] + travel).OnlyEnforceIf(x[i][j])

    # Jornada extendida
    end_time = model.NewIntVar(0, 24 * 3600, "fin_jornada")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, 24 * 3600, "delta_ext")
    is_ext    = model.NewBoolVar("es_jornada_ext")
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(is_ext)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(is_ext.Not())
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(is_ext)
    model.Add(delta_ext == 0).OnlyEnforceIf(is_ext.Not())
    penalizaciones.append(PESO_JORNADA_EXT * delta_ext)

    # Objetivo
    model.Minimize(sum(penalizaciones))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    status = solver.Solve(model)
    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return fallback_nearest_insertion(data)

    # Reconstruir ruta
    ruta = []
    actual = 0
    visitados = set([0])
    while True:
        for j in range(n):
            if j != actual and solver.BooleanValue(x[actual][j]):
                ruta.append(j)
                actual = j
                visitados.add(j)
                break
        else:
            break
    if len(ruta) < n - 1:
        return fallback_nearest_insertion(data)

    ruta = [0] + ruta
    arr = [solver.Value(t[i]) for i in ruta]
    distancia = sum(D[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1))

    return {
        "routes": [{
            "route": ruta,
            "arrival_sec": arr
        }],
        "distance_total_m": distancia
    }

# === Fallback ===
def fallback_nearest_insertion(data):
    from heapq import heappush, heappop
    D = data["distance_matrix"]
    T = data["duration_matrix"]
    W = data["time_windows"]
    S = data["service_times"]
    n = len(D)

    ruta = [0]
    arr = [SHIFT_START]
    no_visitados = set(range(1, n))

    while no_visitados:
        mejor = None
        for i in range(1, len(ruta)+1):
            for j in no_visitados:
                previa = ruta[i-1]
                travel = T[previa][j]
                llegada = arr[i-1] + S[previa] + travel
                ini, fin = W[j]
                if llegada > fin:
                    continue
                espera = max(0, ini - llegada)
                penal = espera + (fin - llegada if llegada < ini else 0)
                heappush(mejor := mejor or [], (penal, i, j, llegada + espera))

        if not mejor:
            break

        _, i, j, eta = heappop(mejor)
        ruta.insert(i, j)
        arr.insert(i, eta)
        no_visitados.remove(j)

        # Recalcular ETA desde ahí
        for k in range(i+1, len(ruta)):
            prev = ruta[k-1]
            curr = ruta[k]
            arr[k] = max(arr[k-1] + S[prev] + T[prev][curr], W[curr][0])

    distancia = sum(D[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1))
    return {
        "routes": [{
            "route": ruta,
            "arrival_sec": arr
        }],
        "distance_total_m": distancia
    }
