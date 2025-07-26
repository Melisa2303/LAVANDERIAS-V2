# algorithms/algoritmo3log.py

from ortools.sat.python import cp_model
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore
import os
from datetime import datetime
import math

# Inicializar Firebase (si aún no está inicializado)
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")  # ruta válida
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Constantes globales
SERVICE_TIME_DEFAULT = 10 * 60  # segundos
TOLERANCIA_RETRASO = 30 * 60    # 30 minutos
SHIFT_START_SEC = 9 * 3600
SHIFT_END_SEC = 16*3600 + 30*60
BIG_M = 10**6

# Convierte HH:MM a segundos
def _hora_a_segundos(hhmm):
    try:
        h, m = map(int, hhmm.strip().split(":"))
        return h * 3600 + m * 60
    except:
        return None

# Agrega ventana extendida al DataFrame
def agregar_ventana_margen(df, margen_seg=15*60):
    def expandir(row):
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            return "No especificado"
        ini = max(0, ini - margen_seg)
        fin = min(24*3600, fin + margen_seg)
        return f"{ini//3600:02}:{(ini%3600)//60:02} - {fin//3600:02}:{(fin%3600)//60:02} h"
    df["ventana_con_margen"] = df.apply(expandir, axis=1)
    return df

# ================= ALGORITMO CP-SAT =====================

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
    t = [model.NewIntVar(0, 24 * 3600, f"t_{i}") for i in range(n)]
    retraso = [model.NewIntVar(0, TOLERANCIA_RETRASO, f"ret_{i}") for i in range(n)]

    # Restricciones de flujo
    for j in range(1, n):
        model.Add(sum(x[i, j] for i in range(n) if i != j) == 1)
    for i in range(1, n):
        model.Add(sum(x[i, j] for j in range(n) if i != j) == 1)
    model.Add(sum(x[0, j] for j in range(1, n)) == 1)
    model.Add(sum(x[i, 0] for i in range(1, n)) == 1)

    # Ventanas de tiempo
    for i in range(n):
        ini, fin = ventanas[i]
        model.Add(t[i] >= ini)
        model.Add(t[i] <= fin + retraso[i])

    # Restricciones de precedencia temporal
    for i in range(n):
        for j in range(n):
            if i != j:
                model.Add(t[j] >= t[i] + service_times[i] + dur[i][j]).OnlyEnforceIf(x[i, j])

    # Función objetivo
    model.Minimize(
        sum(dur[i][j] * x[i, j] for i in range(n) for j in range(n) if i != j) +
        sum(retraso[i] * 10 for i in range(n))
    )

    # Resolución
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = tiempo_max_seg
    status = solver.Solve(model)

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        return {"routes": [], "distance_total_m": 0}

    # Reconstrucción de la ruta
    ruta = [0]
    actual = 0
    while True:
        found = False
        for j in range(n):
            if actual != j and (actual, j) in x and solver.Value(x[actual, j]) == 1:
                ruta.append(j)
                actual = j
                found = True
                break
        if not found or actual == 0:
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
