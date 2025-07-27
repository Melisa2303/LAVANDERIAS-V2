# algorithms/algoritmo3log.py
# CP-SAT puro con penalizaciones y fallback por Nearest Insertion

from ortools.sat.python import cp_model
import numpy as np

# ---------------------- CONSTANTES ------------------------
SERVICE_TIME = 600
SHIFT_START = 9 * 3600
SHIFT_END = 16 * 3600 + 15 * 60

PESO_RETRASO       = 15
PESO_ANTICIPO      = 8
PESO_ESPERA        = 4
PESO_JORNADA_EXT   = 20
PESO_NO_VISITAR    = 1000

# ---------------------- ALGORITMO ------------------------
def optimizar_ruta_cp_sat(data, tiempo_max_seg=120):
    n = len(data["duration_matrix"])
    duraciones = data["duration_matrix"]
    ventanas = data["time_windows"]
    demandas = data["demands"]
    servicio = data["service_times"]

    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg

    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    visit = [model.NewBoolVar(f"visit_{i}") for i in range(n)]
    order = [model.NewIntVar(0, n - 1, f"order_{i}") for i in range(n)]

    M = 24 * 3600

    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini).OnlyEnforceIf(visit[i])
        model.Add(t[i] <= fin).OnlyEnforceIf(visit[i])

    for i in range(n):
        for j in range(n):
            if i != j:
                b = model.NewBoolVar(f"path_{i}_{j}")
                model.Add(order[j] == order[i] + 1).OnlyEnforceIf(b)
                model.Add(t[j] >= t[i] + duraciones[i][j] + servicio[i]).OnlyEnforceIf(b)
                model.AddImplication(b, visit[i])
                model.AddImplication(b, visit[j])

    model.Add(order[0] == 0)
    model.Add(visit[0] == 1)

    retraso = []
    anticipo = []
    espera = []
    for i in range(n):
        ini, fin = ventanas[i]
        ancho = max(1, fin - ini)

        retraso_i = model.NewIntVar(0, M, f"retraso_{i}")
        anticipo_i = model.NewIntVar(0, M, f"anticipo_{i}")
        espera_i = model.NewIntVar(0, M, f"espera_{i}")

        model.Add(retraso_i == t[i] - fin).OnlyEnforceIf(t[i] > fin)
        model.Add(retraso_i == 0).OnlyEnforceIf(t[i] <= fin)

        medio = ini + ancho // 2
        model.Add(anticipo_i == medio - t[i]).OnlyEnforceIf(t[i] < medio)
        model.Add(anticipo_i == 0).OnlyEnforceIf(t[i] >= medio)

        model.Add(espera_i == t[i] - ini).OnlyEnforceIf(t[i] >= ini)
        model.Add(espera_i == 0).OnlyEnforceIf(t[i] < ini)

        retraso.append(retraso_i)
        anticipo.append(anticipo_i)
        espera.append(espera_i)

    end_time = model.NewIntVar(0, M, "end_time")
    model.AddMaxEquality(end_time, t)
    delta_ext = model.NewIntVar(0, M, "delta_ext")

    jornada_ext = model.NewBoolVar("extiende_jornada")
    model.Add(delta_ext == end_time - SHIFT_END)
    model.Add(delta_ext > 0).OnlyEnforceIf(jornada_ext)
    model.Add(delta_ext <= 0).OnlyEnforceIf(jornada_ext.Not())

    penal_ext = model.NewIntVar(0, M, "penal_ext")
    model.AddMultiplicationEquality(penal_ext, [delta_ext, jornada_ext])

    obj_terms = []

    for i in range(n):
        ini, fin = ventanas[i]
        ancho = max(1, fin - ini)

        r = retraso[i]
        a = anticipo[i]
        w = espera[i]

        model.AddDivisionEquality(f"r_scaled_{i}", r, ancho)
        model.AddDivisionEquality(f"a_scaled_{i}", a, ancho)
        model.AddDivisionEquality(f"w_scaled_{i}", w, ancho)

        obj_terms.append(PESO_RETRASO * model.GetVarFromProtoName(f"r_scaled_{i}"))
        obj_terms.append(PESO_ANTICIPO * model.GetVarFromProtoName(f"a_scaled_{i}"))
        obj_terms.append(PESO_ESPERA * model.GetVarFromProtoName(f"w_scaled_{i}"))

    for i in range(1, n):
        obj_terms.append(PESO_NO_VISITAR * (1 - visit[i]))

    obj_terms.append(PESO_JORNADA_EXT * penal_ext)

    model.Minimize(sum(obj_terms))

    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        secuencia = sorted(
            [(int(solver.Value(order[i])), i) for i in range(n) if solver.Value(visit[i])],
            key=lambda x: x[0]
        )
        route = [i for _, i in secuencia]
        arrival = [int(solver.Value(t[i])) for i in route]

        distance = sum(
            data["distance_matrix"][route[i]][route[i + 1]] for i in range(len(route) - 1)
        )

        return {
            "routes": [{
                "route": route,
                "arrival_sec": arrival
            }],
            "distance_total_m": distance
        }

    # Fallback Nearest Insertion
    return fallback_heuristica_insertion(data)


# ------------------ Fallback: Nearest Insertion ------------------
def fallback_heuristica_insertion(data):
    n = len(data["duration_matrix"])
    duraciones = data["duration_matrix"]
    ventanas = data["time_windows"]
    servicio = data["service_times"]

    no_visitados = set(range(1, n))
    ruta = [0]
    llegada = [SHIFT_START]

    while no_visitados:
        mejor_i, mejor_pos, mejor_costo = None, None, float('inf')
        for i in no_visitados:
            for pos in range(1, len(ruta) + 1):
                anterior = ruta[pos - 1]
                llegada_prev = llegada[pos - 1]
                t_llegada = llegada_prev + servicio[anterior] + duraciones[anterior][i]
                ini, fin = ventanas[i]
                if t_llegada <= fin:
                    costo = max(0, ini - t_llegada)
                    if costo < mejor_costo:
                        mejor_i, mejor_pos, mejor_costo = i, pos, costo

        if mejor_i is None:
            break
        ruta.insert(mejor_pos, mejor_i)
        anterior = ruta[mejor_pos - 1]
        llegada_prev = llegada[mejor_pos - 1]
        t_llegada = max(ventanas[mejor_i][0], llegada_prev + servicio[anterior] + duraciones[anterior][mejor_i])
        llegada.insert(mejor_pos, t_llegada)
        no_visitados.remove(mejor_i)

    distancia = sum(data["distance_matrix"][ruta[i]][ruta[i+1]] for i in range(len(ruta) - 1))

    return {
        "routes": [{
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": distancia
    }
