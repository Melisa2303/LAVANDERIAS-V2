# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
from typing import Dict, Any
import math

SHIFT_START = 9 * 3600
SHIFT_END   = 16 * 3600 + 30 * 60
SERVICE_TIME = 600

# Pesos para penalización
PESO_RETRASO      = 10
PESO_ANTICIPO     = 1
PESO_ESPERA       = 1
PESO_JORNADA_EXT  = 15
PESO_NO_VISITAR   = 9999

def optimizar_ruta_cp_sat(data: Dict[str, Any], tiempo_max_seg: int = 60) -> Dict[str, Any] | None:
    n = len(data["distance_matrix"])
    duraciones = data["duration_matrix"]
    ventanas = data["time_windows"]

    model = cp_model.CpModel()

    # Variables de secuencia
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    # Variables de tiempo de llegada
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]

    # Variables auxiliares para penalizaciones
    retraso      = [model.NewIntVar(0, 24 * 3600, f"retraso_{i}") for i in range(n)]
    anticipo     = [model.NewIntVar(0, 24 * 3600, f"anticipo_{i}") for i in range(n)]
    espera       = [model.NewIntVar(0, 24 * 3600, f"espera_{i}") for i in range(n)]
    visitado     = [model.NewBoolVar(f"visitado_{i}") for i in range(n)]

    # Flujo desde nodo 0 (Planta)
    for j in range(1, n):
        model.Add(sum(x[0, j] for j in range(1, n)) == 1)

    # Flujo hacia nodo 0 (no puede volver)
    for i in range(1, n):
        model.Add(x[i, 0] == 0)

    # Flujo de cada nodo
    for k in range(1, n):
        model.Add(sum(x[i, k] for i in range(n) if i != k) == visitado[k])
        model.Add(sum(x[k, j] for j in range(n) if j != k) == visitado[k])

    # Conectividad y subtour
    orden = [model.NewIntVar(0, n, f"orden_{i}") for i in range(n)]
    for i in range(1, n):
        for j in range(1, n):
            if i != j:
                model.Add(orden[i] + 1 <= orden[j]).OnlyEnforceIf(x[i, j])

    # Ventanas de tiempo y penalizaciones
    penalizaciones = []
    for i in range(1, n):
        ini, fin = ventanas[i]
        ancho = max(fin - ini, 1)

        b_retraso = model.NewBoolVar(f"b_r_{i}")
        b_anticipo = model.NewBoolVar(f"b_a_{i}")
        b_espera = model.NewBoolVar(f"b_e_{i}")

        # Restricciones de penalización según ventana
        model.Add(retraso[i] == t[i] - fin).OnlyEnforceIf(b_retraso)
        model.Add(retraso[i] == 0).OnlyEnforceIf(b_retraso.Not())
        model.Add(t[i] > fin).OnlyEnforceIf(b_retraso)
        model.Add(t[i] <= fin).OnlyEnforceIf(b_retraso.Not())

        model.Add(anticipo[i] == ini - t[i]).OnlyEnforceIf(b_anticipo)
        model.Add(anticipo[i] == 0).OnlyEnforceIf(b_anticipo.Not())
        model.Add(t[i] < ini).OnlyEnforceIf(b_anticipo)
        model.Add(t[i] >= ini).OnlyEnforceIf(b_anticipo.Not())

        model.Add(espera[i] == ini - t[i]).OnlyEnforceIf(b_espera)
        model.Add(espera[i] == 0).OnlyEnforceIf(b_espera.Not())
        model.Add(t[i] < ini).OnlyEnforceIf(b_espera)
        model.Add(t[i] >= ini).OnlyEnforceIf(b_espera.Not())

        # Penalizaciones proporcionales
        r_tmp = model.NewIntVar(0, PESO_RETRASO * 24 * 3600, f"r_peso_{i}")
        a_tmp = model.NewIntVar(0, PESO_ANTICIPO * 24 * 3600, f"a_peso_{i}")
        e_tmp = model.NewIntVar(0, PESO_ESPERA * 24 * 3600, f"e_peso_{i}")
        model.AddMultiplicationEquality(r_tmp, [retraso[i], PESO_RETRASO])
        model.AddMultiplicationEquality(a_tmp, [anticipo[i], PESO_ANTICIPO])
        model.AddMultiplicationEquality(e_tmp, [espera[i], PESO_ESPERA])
        penalizaciones += [r_tmp, a_tmp, e_tmp]

    # Tiempo de llegada entre nodos
    for i in range(n):
        for j in range(n):
            if i != j:
                dur = duraciones[i][j] + SERVICE_TIME
                model.Add(t[j] >= t[i] + dur).OnlyEnforceIf(x[i, j])

    # Jornada extendida
    end_time = model.NewIntVar(SHIFT_START, 24 * 3600, "fin_jornada")
    for i in range(1, n):
        model.AddMaxEquality(end_time, t[i])

    delta_ext = model.NewIntVar(0, 24 * 3600, "delta_ext")
    b_ext = model.NewBoolVar("b_ext")
    model.Add(delta_ext == end_time - SHIFT_END).OnlyEnforceIf(b_ext)
    model.Add(delta_ext == 0).OnlyEnforceIf(b_ext.Not())
    model.Add(end_time > SHIFT_END).OnlyEnforceIf(b_ext)
    model.Add(end_time <= SHIFT_END).OnlyEnforceIf(b_ext.Not())

    penal_ext = model.NewIntVar(0, PESO_JORNADA_EXT * 24 * 3600, "penal_jornada")
    model.AddMultiplicationEquality(penal_ext, [delta_ext, PESO_JORNADA_EXT])
    penalizaciones.append(penal_ext)

    # Función objetivo
    model.Minimize(sum(penalizaciones))

    # Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"routes": [{"route": [0], "arrival_sec": [SHIFT_START]}], "distance_total_m": 0}

    # Reconstruir ruta
    recorrido = [0]
    actual = 0
    while True:
        for j in range(n):
            if actual != j and solver.BooleanValue(x[actual, j]):
                recorrido.append(j)
                actual = j
                break
        else:
            break

    # ETA
    eta = [solver.Value(t[i]) for i in recorrido]
    distance_total = 0
    for i in range(len(recorrido) - 1):
        distance_total += data["distance_matrix"][recorrido[i]][recorrido[i + 1]]

    return {
        "routes": [{"route": recorrido, "arrival_sec": eta}],
        "distance_total_m": distance_total
    }
