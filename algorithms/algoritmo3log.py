from ortools.sat.python import cp_model

def optimizar_ruta_cp_sat_puro(data, tiempo_max_seg=120):
    n = len(data["duration_matrix"])
    dist = data["distance_matrix"]
    dur = data["duration_matrix"]
    ventanas = data["time_windows"]
    demandas = data["demands"]
    capacidad = data["vehicle_capacities"][0]
    depot = data["depot"]

    model = cp_model.CpModel()

    # Variables de decisión: x[i][j] = 1 si se va de i a j
    x = {}
    for i in range(n):
        for j in range(n):
            if i != j:
                x[i, j] = model.NewBoolVar(f'x_{i}_{j}')

    # Tiempos de llegada a cada nodo
    t = [model.NewIntVar(0, 86400, f"t_{i}") for i in range(n)]

    # Flujo para subtour elimination
    u = [model.NewIntVar(0, capacidad, f"u_{i}") for i in range(n)]

    # Restricciones de flujo (subtour + demanda)
    model.Add(u[depot] == 0)
    for i in range(n):
        for j in range(n):
            if i != j and (i, j) in x:
                model.Add(u[j] >= u[i] + demandas[j] - capacidad * (1 - x[i, j]))

    # Cada nodo se visita una vez (excepto depósito que puede tener múltiples)
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if j != i) == 1)

    # Salida y llegada al depósito
    model.Add(sum(x[depot, j] for j in range(n) if j != depot) == 1)
    model.Add(sum(x[i, depot] for i in range(n) if i != depot) == 1)

    # Restricciones de tiempo
    penalizaciones = []
    for i in range(n):
        ini, fin = ventanas[i]
        dentro = model.NewBoolVar(f"dentro_{i}")
        model.Add(t[i] >= ini).OnlyEnforceIf(dentro)
        model.Add(t[i] <= fin).OnlyEnforceIf(dentro)
        penal = model.NewIntVar(0, 3600, f"penal_{i}")
        model.AddAbsEquality(penal, t[i] - min(max(ini, 0), fin))
        penalizaciones.append(penal)

    for i in range(n):
        for j in range(n):
            if i != j and (i, j) in x:
                model.Add(t[j] >= t[i] + SERVICE_TIME + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Objetivo: minimizar distancia total + penalización por ventanas
    model.Minimize(
        sum(x[i, j] * dist[i][j] for i in range(n) for j in range(n) if i != j) +
        sum(penalizaciones)
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return None

    # Reconstrucción de ruta
    ruta = [depot]
    actual = depot
    while True:
        next_node = None
        for j in range(n):
            if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                next_node = j
                break
        if next_node is None or next_node == depot:
            break
        ruta.append(next_node)
        actual = next_node

    llegada = [solver.Value(t[i]) for i in ruta]

    return {
        "routes": [{
            "vehicle": 0,
            "route": ruta,
            "arrival_sec": llegada
        }],
        "distance_total_m": sum(dist[ruta[i]][ruta[i+1]] for i in range(len(ruta)-1)),
        "arrival_sec_all_nodes": [solver.Value(t[i]) for i in range(n)],
    }
