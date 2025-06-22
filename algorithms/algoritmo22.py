#################################################################################################################
# :) –  Streamlit App Integrado:
#   → GLS + PCA + OR-Tools
#   → Firebase Firestore (usando service account JSON)
#   → Google Maps Distance Matrix & Directions
#   → OR-Tools VRP-TW con servicio, ventanas, tráfico real
#   → Se empleó el algoritmo de agrupación: Agglomerative Clustering para agrupar pedidos cercanos en 300m a la redonda.
#   → Página única: Ver Ruta Optimizada
#   → En caso el algoritmo no dé respuesta, usa distancias euclidianas
##################################################################################################################

import os
import math
import time as tiempo
from datetime import datetime

import streamlit as st
import pandas as pd
import numpy as np
import firebase_admin
from firebase_admin import credentials, firestore
import googlemaps
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from sklearn.cluster import AgglomerativeClustering
import folium
from streamlit_folium import st_folium

# -------------------- INICIALIZAR FIREBASE --------------------
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- CONFIG GOOGLE MAPS --------------------
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps", {}).get("api_key") or os.getenv("GOOGLE_MAPS_API_KEY")
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------- CONSTANTES VRP --------------------
SERVICE_TIME    = 10 * 60
MAX_ELEMENTS    = 100
SHIFT_START_SEC =  9 * 3600
SHIFT_END_SEC   = 16*3600 + 30*60
MARGEN = 15 * 60  # 15 minutos

# -------------------- FUNCIONES AUXILIARES --------------------
def _hora_a_segundos(hhmm):
    if hhmm is None or pd.isna(hhmm) or hhmm == "":
        return None
    try:
        h, m = map(int, str(hhmm).split(":"))
        return h*3600 + m*60
    except:
        return None

def _haversine_dist_dur(coords, vel_kmh=40.0):
    R = 6371e3
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    v_ms = vel_kmh * 1000 / 3600
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            lat1, lon1 = map(math.radians, coords[i])
            lat2, lon2 = map(math.radians, coords[j])
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            d = 2 * R * math.asin(math.sqrt(a))
            dist[i][j] = int(d)
            dur[i][j]  = int(d / v_ms)
    return dist, dur

@st.cache_data(ttl=3600, show_spinner=False)
def _distancia_duracion_matrix(coords):
    if not GOOGLE_MAPS_API_KEY:
        return _haversine_dist_dur(coords)
    n = len(coords)
    dist = [[0]*n for _ in range(n)]
    dur  = [[0]*n for _ in range(n)]
    batch = max(1, min(n, MAX_ELEMENTS // n))
    for i0 in range(0, n, batch):
        resp = gmaps.distance_matrix(
            origins=coords[i0:i0+batch],
            destinations=coords,
            mode="driving",
            units="metric",
            departure_time=datetime.now(),
            traffic_model="best_guess"
        )
        for i, row in enumerate(resp["rows"]):
            for j, el in enumerate(row["elements"]):
                dist[i0 + i][j] = el.get("distance", {}).get("value", 1)
                dur[i0 + i][j]  = el.get("duration_in_traffic", {}).get("value", el.get("duration", {}).get("value", 1))
    return dist, dur

def _crear_data_model(df, vehiculos=1, capacidad_veh=None):
    coords = list(zip(df["lat"], df["lon"]))
    dist_m, dur_s = _distancia_duracion_matrix(coords)

    time_windows = []
    demandas = []
    for _, row in df.iterrows():
        ini = _hora_a_segundos(row.get("time_start"))
        fin = _hora_a_segundos(row.get("time_end"))
        if ini is None or fin is None:
            ini, fin = SHIFT_START_SEC, SHIFT_END_SEC
        else:
            ini = max(0, ini - MARGEN)
            fin = min(24*3600, fin + MARGEN)
        time_windows.append((ini, fin))
        demandas.append(row.get("demand", 1))

    return {
        "distance_matrix": dist_m,
        "duration_matrix": dur_s,
        "time_windows": time_windows,
        "demands": demandas,
        "num_vehicles": vehiculos,
        "vehicle_capacities": [capacidad_veh or 10**9] * vehiculos,
        "depot": 0,
    }

def agregar_ventana_margen(df, margen_segundos=15*60):
    def expandir_fila(row):
        ini = _hora_a_segundos(row["time_start"])
        fin = _hora_a_segundos(row["time_end"])
        if ini is None or fin is None:
            return "No especificado"
        ini = max(0, ini - margen_segundos)
        fin = min(24*3600, fin + margen_segundos)
        h_ini = f"{ini//3600:02}:{(ini%3600)//60:02}"
        h_fin = f"{fin//3600:02}:{(fin%3600)//60:02}"
        return f"{h_ini} - {h_fin} h"
    df["ventana_con_margen"] = df.apply(expandir_fila, axis=1)
    return df

# -------------------- CARGAR PEDIDOS DESDE FIRESTORE --------------------
@st.cache_data(ttl=300)
def cargar_pedidos(fecha, tipo):
    col = db.collection('recogidas')
    docs = []
    docs += col.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()
    docs += col.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream()
    if tipo != "Todos":
        tf = "Sucursal" if tipo == "Sucursal" else "Cliente Delivery"
        docs = [d for d in docs if d.to_dict().get("tipo_solicitud") == tf]
    out = []
    for d in docs:
        data = d.to_dict()
        is_recojo = data.get("fecha_recojo") == fecha.strftime("%Y-%m-%d")
        op = "Recojo" if is_recojo else "Entrega"
        key_coord = f"coordenadas_{'recojo' if is_recojo else 'entrega'}"
        key_dir   = f"direccion_{'recojo' if is_recojo else 'entrega'}"
        coords = data.get(key_coord, {})
        lat, lon = coords.get("lat"), coords.get("lon")
        direccion = data.get(key_dir, "") or ""
        nombre = data.get("nombre_cliente")
        if not nombre:
            nombre = data.get("sucursal", "") or "Sin nombre"
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}", "")
        ts, te = (hs, hs) if hs else ("08:00", "18:00")
        out.append({
            "id":             d.id,
            "operacion":      op,
            "nombre_cliente": nombre,
            "direccion":      direccion,
            "lat":            lat,
            "lon":            lon,
            "time_start":     ts,
            "time_end":       te,
            "demand":         1
        })
    return out

# -------------------- BLOQUE PRINCIPAL STREAMLIT --------------------
st.title("Optimización de Rutas con Ventanas de Tiempo")

fecha = st.date_input("Selecciona la fecha de operación", value=datetime.today())
tipo = st.selectbox("Tipo de servicio", ["Todos", "Sucursal", "Cliente Delivery"])

# Cargar pedidos y mostrar con ventana extendida
pedidos = cargar_pedidos(fecha, tipo)
df = pd.DataFrame(pedidos)
if not df.empty:
    df = agregar_ventana_margen(df)
    st.dataframe(df[["nombre_cliente", "direccion", "time_start", "time_end", "ventana_con_margen", "lat", "lon"]])
else:
    st.warning("No se encontraron pedidos para la fecha y tipo seleccionados.")
