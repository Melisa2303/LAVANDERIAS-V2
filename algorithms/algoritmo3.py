# Lógica para el Algoritmo 3:
import streamlit as st
from core.constants import GOOGLE_MAPS_API_KEY
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
import firebase_admin
from firebase_admin import credentials, firestore
import math
import pandas as pd
import datetime
from datetime import timedelta
import time
import googlemaps
from ortools.sat.python import cp_model
import numpy as np
import requests  # Importar requests
from sklearn.cluster import AgglomerativeClustering

# -------------------- INICIALIZAR FIREBASE --------------------
if not firebase_admin._apps:
    cred = credentials.Certificate("lavanderia_key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Función para obtener matriz de distancias reales con Google Maps API
@st.cache_data(ttl=300)  # Cache de 5 minutos (el tráfico cambia frecuentemente)

def _haversine_meters(lat1, lon1, lat2, lon2):
    """Retorna distancia en metros entre dos puntos (lat, lon) usando Haversine."""
    R = 6371e3  # metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def agrupar_puntos_aglomerativo(df, eps_metros=300):
    """
    Agrupa pedidos cercanos mediante AgglomerativeClustering. 
    eps_metros: umbral de distancia máxima en metros para que queden en el mismo cluster.
    Retorna (df_clusters, df_etiquetado), donde:
      - df_etiquetado = df original con columna 'cluster' indicando etiqueta de cluster.
      - df_clusters  = DataFrame de centroides con columnas ['id','operacion','nombre_cliente',
                        'dirección','lat','lon','time_start','time_end','demand'].
    """
    # Si no hay pedidos, retorno vacíos
    if df.empty:
        return pd.DataFrame(), df.copy()

    coords = df[["lat", "lon"]].to_numpy()
    n = len(coords)
    # 1) Construir matriz de distancias en metros
    dist_m = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            if i == j:
                dist_m[i, j] = 0.0
            else:
                dist_m[i, j] = _haversine_meters(
                    coords[i, 0], coords[i, 1],
                    coords[j, 0], coords[j, 1]
                )

    # 2) Aplicar AgglomerativeClustering con distancia precomputada
    clustering = AgglomerativeClustering(
        n_clusters=None, #1
        metric="precomputed",
        linkage="average",
        distance_threshold=eps_metros
    )
    labels = clustering.fit_predict(dist_m)
    df_labeled = df.copy()
    df_labeled["cluster"] = labels

    # 3) Construir DataFrame de centroides
    agrupados = []
    for clus in sorted(np.unique(labels)):
        members = df_labeled[df_labeled["cluster"] == clus]
        centro_lat = members["lat"].mean()
        centro_lon = members["lon"].mean()
        # Nombre descriptivo: primeros dos clientes del cluster
        nombres = list(members["nombre_cliente"].unique())
        nombre_desc = ", ".join(nombres[:2]) + ("..." if len(nombres) > 2 else "")
        # Concatenar direcciones de los pedidos (hasta 2)
        direcciones = list(members["direccion"].unique())
        direccion_desc = ", ".join(direcciones[:2]) + ("..." if len(direcciones) > 2 else "")
        # Ventana: tomo min y max de time_start/time_end
        ts_vals = members["time_start"].tolist()
        te_vals = members["time_end"].tolist()
        ts_vals = [t for t in ts_vals if t]
        te_vals = [t for t in te_vals if t]
        inicio_cluster = min(ts_vals) if ts_vals else ""
        fin_cluster    = max(te_vals) if te_vals else ""
        demanda_total  = int(members["demand"].sum())
        agrupados.append({
            "id":             f"cluster_{clus}",
            "operacion":      "Agrupado",
            "nombre_cliente": f"Grupo {clus}: {nombre_desc}",
            "direccion":      direccion_desc,
            "lat":            centro_lat,
            "lon":            centro_lon,
            "time_start":     inicio_cluster,
            "time_end":       fin_cluster,
            "demand":         demanda_total
        })

    df_clusters = pd.DataFrame(agrupados)
    return df_clusters, df_labeled

# Función para obtener geometría de ruta con Directions API
@st.cache_data(ttl=3600)

# Algoritmo 3: CP-SAT
def optimizar_ruta_cp_sat(data, tiempo_max_seg=60):
    # Si la matriz de tiempos tiene solo ceros, generarla a partir de la distancia
    if all(all(t == 0 for t in fila) for fila in data["time_matrix"]):
        st.write("⚠️ Matriz de tiempos vacía o con ceros. Generando nueva matriz basada en distancia...")

        # Suponiendo velocidad de 15 km/h = 4.17 m/s
        velocidad_mps = 15 * 1000 / 3600

        data["time_matrix"] = [
            [int(dist / velocidad_mps) for dist in fila]
            for fila in data["distance_matrix"]
        ]
    manager = pywrapcp.RoutingIndexManager(len(data["time_matrix"]), data["num_vehicles"], data["depot"])
    routing = pywrapcp.RoutingModel(manager)
    for node in range(1, manager.GetNumberOfNodes()):
        routing.AddDisjunction([manager.NodeToIndex(node)], 1000000)  # Penalidad alta por omitir

    # Costo: distancia
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["distance_matrix"][from_node][to_node]
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Ventanas de tiempo
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["time_matrix"][from_node][to_node]
    
    time_callback_index = routing.RegisterTransitCallback(time_callback)

    routing.AddDimension(
        time_callback_index,
        60 * 60,  # holgura: 60 minutos
        24 * 3600,  # tiempo máximo: 12 horas
        False,
        "Time"
    )
    time_dimension = routing.GetDimensionOrDie("Time")

    # st.write("Ventanas de tiempo:")
    for i, (start, end) in enumerate(data["time_windows"]):
        # st.write(f"Punto {i}: {start} - {end}")
        MIN_VENTANA = 2700 # 45 minutos mínimo
        if end - start < MIN_VENTANA:
            # st.write(f"🔧 Ampliando ventana estrecha en punto {i}: {start}-{end}")
            centro = (start + end) // 2
            start = max(0, centro - MIN_VENTANA // 2)
            end = centro + MIN_VENTANA // 2
            data["time_windows"][i] = (start, end)
        if start >= end:
            raise ValueError(f"Ventana inválida en punto {i}: ({start}, {end})")
        
    # Iniciar a las 9:00 AM
    start_depot = 9 * 3600
    index_depot = manager.NodeToIndex(data["depot"])
    time_dimension.CumulVar(index_depot).SetRange(start_depot, start_depot + 300)

    # Aplicar ventanas a cada nodo
    for location_idx, (start, end) in enumerate(data["time_windows"]):
        index = manager.NodeToIndex(location_idx)
        if location_idx != data["depot"]:
            time_dimension.CumulVar(index).SetRange(start, end)

    for i, (start, end) in enumerate(data["time_windows"]):
        service = data["service_times"][i]
        travel_posibles = data["time_matrix"][i]
        min_travel = min([t for t in travel_posibles if t > 0], default=0)
        if end - start < service + min_travel:
            st.error(f"🚫 La ventana de tiempo del punto {i} no es suficiente para llegar ({min_travel}s) y atender ({service}s)")

    # Asignar tiempo de servivio
    for location_idx, service_time in enumerate(data["service_times"]):
        index = manager.NodeToIndex(location_idx)
        time_dimension.SlackVar(index).SetValue(service_time)
        if service_time > (data["time_windows"][location_idx][1] - data["time_windows"][location_idx][0]):
            st.write(f"⚠️ Tiempo de servicio ({service_time}s) mayor que la ventana en punto {location_idx}")

    for i, (start, end) in enumerate(data["time_windows"]):
        min_travel = min(data["time_matrix"][i])
        service = data["service_times"][i]
        if (end - start) < (service + min_travel):
            st.write(f"❌ La ventana en el punto {i} es demasiado corta para cumplir viaje + servicio")

    # Parámetros de busqueda
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.time_limit.seconds = tiempo_max_seg
    search_parameters.first_solution_strategy = (
    routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION)
    search_parameters.local_search_metaheuristic = (
    routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    search_parameters.log_search = True

    solution = routing.SolveWithParameters(search_parameters)

    if solution:
        route = []
        arrival_sec = []
        distance_total = 0
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route.append(node)
            arrival = solution.Value(time_dimension.CumulVar(index))
            arrival_sec.append(arrival)
            previous_index = index
            index = solution.Value(routing.NextVar(index))

            # Distancia real según la matriz
            from_node = manager.IndexToNode(previous_index)
            to_node = manager.IndexToNode(index)
            segment_distance = data["distance_matrix"][from_node][to_node]
            distance_total += segment_distance

        # Último nodo
        node = manager.IndexToNode(index)
        route.append(node)
        arrival_sec.append(solution.Value(time_dimension.CumulVar(index)))

        # ETA en formato HH:MM
        fecha_base = datetime.datetime.now().date()
        eta = [
            (datetime.datetime.combine(fecha_base, datetime.time(0, 0)) + timedelta(seconds=t)).strftime("%H:%M")
            for t in arrival_sec
        ]

        st.write("🗺 Orden de visita y ETA:")
        for i, (nodo, h) in enumerate(zip(route, eta)):
            st.write(f"📍 Punto {nodo} → ETA: {h}")

        return {
            "routes": [{
                "route": route,
                "arrival_sec": arrival_sec
            }],
            "distance_total_m": distance_total
        }
    else:
        raise Exception("CP Solver fail: no se encontró solución factible.")
    
def corregir_ventanas_iguales(df, min_ventana_seg=1800):
    """
    Corrige filas donde time_start == time_end en el DataFrame, 
    expandiendo la ventana a ±30 minutos desde time_start.
    """
    def ajustar_ventana(row):
        start = hhmm_to_sec(row["time_start"])
        end = hhmm_to_sec(row["time_end"])

        if start == end:
            # Expandir a 30 minutos de ventana centrada en `start`
            nuevo_start = max(0, start - min_ventana_seg // 2)
            nuevo_end = start + min_ventana_seg // 2
            return pd.Series([sec_to_hhmm(nuevo_start), sec_to_hhmm(nuevo_end)])
        else:
            return pd.Series([row["time_start"], row["time_end"]])

    df[["time_start", "time_end"]] = df.apply(ajustar_ventana, axis=1)
    return df
    
def sec_to_hhmm(segundos):
    h = segundos // 3600
    m = (segundos % 3600) // 60
    return f"{h:02d}:{m:02d}"
    
def hhmm_to_sec(hora):
    if pd.isnull(hora) or hora is None:
        return 0

    if isinstance(hora, datetime.time):
        return hora.hour * 3600 + hora.minute * 60 + hora.second

    if isinstance(hora, (datetime.datetime, pd.Timestamp)):
        hora = hora.time()  # Convertir a time puro
        return hora.hour * 3600 + hora.minute * 60 + hora.second

    if isinstance(hora, int):
        # Ejemplo: 800 → "08:00"
        hora = f"{hora:04d}"
        hora = f"{hora[:2]}:{hora[2:]}"

    if isinstance(hora, str):
        partes = hora.strip().split(":")
        try:
            if len(partes) == 2:
                h, m = map(int, partes)
                s = 0
            elif len(partes) == 3:
                h, m, s = map(int, partes)
            else:
                raise ValueError
            return h * 3600 + m * 60 + s
        except:
            raise ValueError(f"Formato de hora inválido: {hora}")

    raise TypeError(f"Tipo de dato no soportado: {type(hora)} → {hora}")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
def get_time_matrix_with_traffic(df, modo='driving', max_chunk=25, delay_seg=1):
    n = len(df)
    coords = [f"{row['lat']},{row['lon']}" for _, row in df.iterrows()]
    matrix = np.zeros((n, n), dtype=int)
    now = datetime.datetime.now()

    for i in range(0, n, max_chunk):
        for j in range(0, n, max_chunk):
            origenes = coords[i:i+max_chunk]
            destinos = coords[j:j+max_chunk]
            try:
                result = gmaps.distance_matrix(
                    origins=origenes,
                    destinations=destinos,
                    mode=modo,
                    departure_time=now,
                    traffic_model="pessimistic"
                )
                for o_idx, row in enumerate(result['rows']):
                    for d_idx, elemento in enumerate(row['elements']):
                        if elemento.get("status") == "OK":
                            tiempo = elemento.get("duration_in_traffic", elemento.get("duration"))
                            matrix[i + o_idx][j + d_idx] = tiempo["value"]
                        else:
                            matrix[i + o_idx][j + d_idx] = 999999  # Penalización por error
            except Exception as e:
                print(f"Error en bloque [{i}:{i+max_chunk}] x [{j}:{j+max_chunk}]: {e}")
                # Esperar y reintentar si ocurre un fallo temporal
                time.sleep(delay_seg)
    return matrix.tolist()

def crear_data_model_cp(df, vehiculos=1):
    n = len(df)
    distancias = []
    tiempos = []

    for i in range(n):
        fila_d = []
        fila_t = []
        for j in range(n):
            lat1, lon1 = df.loc[i, "lat"], df.loc[i, "lon"]
            lat2, lon2 = df.loc[j, "lat"], df.loc[j, "lon"]
            d = _haversine_meters(lat1, lon1, lat2, lon2)
            fila_d.append(int(d))  # en metros
            fila_t.append(int(d / 5))  # asumiendo 5 m/s (~18 km/h)
        distancias.append(fila_d)
        tiempos.append(fila_t)
    tiempos = get_time_matrix_with_traffic(df)  # ahora sí incluye tráfico

    MIN_VENTANA = 1800  # 30 minutos
    ventanas = []
    for _, row in df.iterrows():
        start = max(0, hhmm_to_sec(row["time_start"]))
        end = hhmm_to_sec(row["time_end"])
        if start >= end:
            # Si hay error, amplía artificialmente
            centro = start
            start = max(0, centro - MIN_VENTANA // 2)
            end = centro + MIN_VENTANA // 2
        elif end - start < MIN_VENTANA:
            # Si la ventana es muy corta, ampliar un poco
            centro = (start + end) // 2
            start = max(0, centro - MIN_VENTANA // 2)
            end = centro + MIN_VENTANA // 2
        ventanas.append((start, end))
    
    tiempos_servicio = [300 for _ in range(len(df))]  # 5 min por punto

    return {
        "distance_matrix": distancias,
        "time_matrix": tiempos,
        "time_windows": ventanas,
        "service_times": tiempos_servicio,
        "num_vehicles": vehiculos,
        "depot": 0
    }

@st.cache_data(ttl=300)
def cargar_pedidos(fecha, tipo):
    """
    Lee de Firestore las colecciones 'recogidas' filtradas por fecha de recojo/entrega
    y tipo de servicio. Retorna una lista de dict con los campos necesarios:
      - id, operacion, nombre_cliente, direccion, lat, lon, time_start, time_end, demand
    """
    col = db.collection('recogidas')
    docs = []
    # Todas las recogidas cuya fecha_recojo coincida
    docs += col.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()
    # Todas las recogidas cuya fecha_entrega coincida
    docs += col.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream()
    if tipo != "Todos":
        tf = "Sucursal" if tipo == "Sucursal" else "Cliente Delivery"
        docs = [d for d in docs if d.to_dict().get("tipo_solicitud") == tf]

    out = []
    for d in docs:
        data = d.to_dict()
        is_recojo = data.get("fecha_recojo") == fecha.strftime("%Y-%m-%d")
        op = "Recojo" if is_recojo else "Entrega"
        # Extraer coordenadas y dirección según tipo
        key_coord = f"coordenadas_{'recojo' if is_recojo else 'entrega'}"
        key_dir   = f"direccion_{'recojo' if is_recojo else 'entrega'}"
        coords = data.get(key_coord, {})
        lat, lon = coords.get("lat"), coords.get("lon")
        direccion = data.get(key_dir, "") or ""
        hs = data.get(f"hora_{'recojo' if is_recojo else 'entrega'}", "")
        ts, te = (hs, hs) if hs else ("08:00", "18:00")
        out.append({
            "id":             d.id,
            "operacion":      op,
            "nombre_cliente": data.get("nombre_cliente", ""),
            "direccion":      direccion,
            "lat":            lat,
            "lon":            lon,
            "time_start":     ts,
            "time_end":       te,
            "demand":         1
        })
    return out
