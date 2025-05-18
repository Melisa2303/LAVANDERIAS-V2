import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app, auth
import os
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta, time
import requests  # Importar requests
import pydeck as pdk
from streamlit_folium import st_folium
import folium
from geopy.geocoders import Nominatim  # Usaremos esto para obtener la dirección desde coordenadas
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import math
import pandas as pd
from io import BytesIO
import time as tiempo
import pytz
from googlemaps.convert import decode_polyline

from core.auth import login, logout
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
          
def obtener_sucursales_mapa():
    """Versión optimizada para mapas que solo necesita coordenadas"""
    if 'sucursales_mapa' not in st.session_state:
        sucursales = obtener_sucursales()  # Usa la caché principal
        st.session_state.sucursales_mapa = [
            {
                'nombre': suc['nombre'],
                'lat': suc['coordenadas'].get('lat'),
                'lon': suc['coordenadas'].get('lon'),
                'direccion': suc['direccion']
            }
            for suc in sucursales
            if suc.get('coordenadas') and isinstance(suc['coordenadas'], dict)
        ]
    return st.session_state.sucursales_mapa
    


# Función para obtener matriz de distancias reales con Google Maps API
@st.cache_data(ttl=300)  # Cache de 5 minutos (el tráfico cambia frecuentemente)
def obtener_matriz_tiempos(puntos, considerar_trafico=True):
    """
    Obtiene los tiempos reales de viaje entre puntos, considerando tráfico actual.
    
    Args:
        puntos: Lista de puntos con coordenadas {lat, lon}
        considerar_trafico: Si True, usa datos de tráfico en tiempo real
    
    Returns:
        Matriz de tiempos en segundos entre cada par de puntos
    """
    if not GOOGLE_MAPS_API_KEY:
        st.error("❌ Se requiere API Key de Google Maps")
        return [[0]*len(puntos) for _ in puntos]
    
    # 1. Preparar parámetros para la API
    locations = [f"{p['lat']},{p['lon']}" for p in puntos]
    params = {
        'origins': '|'.join(locations),
        'destinations': '|'.join(locations),
        'key': GOOGLE_MAPS_API_KEY,
        'units': 'metric'
    }
    
    # 2. Añadir parámetros de tráfico si está activado
    if considerar_trafico:
        params.update({
            'departure_time': 'now',  # Usar hora actual
            'traffic_model': 'best_guess'  # Modelo: best_guess/pessimistic/optimistic
        })
    
    # 3. Hacer la petición a la API
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['status'] != 'OK':
            st.error(f"⚠️ Error en API: {data.get('error_message', 'Código: '+data['status'])}")
            return [[0]*len(puntos) for _ in puntos]
        
        # 4. Procesar respuesta
        matriz = []
        for row in data['rows']:
            fila_tiempos = []
            for elemento in row['elements']:
                # Priorizar 'duration_in_traffic' si existe
                tiempo = elemento.get('duration_in_traffic', elemento['duration'])
                fila_tiempos.append(tiempo['value'])  # Tiempo en segundos
            matriz.append(fila_tiempos)
        
        return matriz
        
    except Exception as e:
        st.error(f"🚨 Error al conectar con API: {str(e)}")
        return [[0]*len(puntos) for _ in puntos]

# Función para obtener geometría de ruta con Directions API
@st.cache_data(ttl=3600)
def obtener_geometria_ruta(puntos):
    """Versión segura para Directions API usando API key global"""
    if not GOOGLE_MAPS_API_KEY:
        st.error("API key de Google Maps no configurada")
        return {}
    
    waypoints = "|".join([f"{p['lat']},{p['lon']}" for p in puntos[1:-1]])
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={puntos[0]['lat']},{puntos[0]['lon']}&destination={puntos[-1]['lat']},{puntos[-1]['lon']}&waypoints=optimize:true|{waypoints}&key={GOOGLE_MAPS_API_KEY}"
    return requests.get(url).json()

# Funciones auxiliares para obtener puntos fijos específicos
def obtener_puntos_fijos_inicio():
    """Devuelve solo los puntos fijos de la mañana (orden >= 0)"""
    return [p for p in PUNTOS_FIJOS_COMPLETOS if p['orden'] >= 0]

def obtener_puntos_fijos_fin():
    """Devuelve solo los puntos fijos de la tarde (orden < 0)"""
    return [p for p in PUNTOS_FIJOS_COMPLETOS if p['orden'] < 0]

def optimizar_ruta_algoritmo1(puntos_intermedios, puntos_con_hora, considerar_trafico=True):
    """
    Optimiza la ruta utilizando el Algoritmo 1 y devuelve los puntos en el orden optimizado.
    Incluye puntos fijos al inicio y al final de la ruta.
    """
    try:
        # 1. OBTENER PUNTOS FIJOS
        puntos_fijos_inicio = obtener_puntos_fijos_inicio()  # Puntos iniciales (Cochera, Planta, etc.)
        puntos_fijos_fin = obtener_puntos_fijos_fin()        # Puntos finales (Planta, Cochera, etc.)

        # 2. VALIDAR PUNTOS INTERMEDIOS
        puntos_validos = []
        for punto in puntos_intermedios:
            p = punto.copy()
            # Validar y convertir coordenadas
            if isinstance(p.get('coordenadas', {}), dict):
                p['lat'] = p['coordenadas'].get('lat')
                p['lon'] = p['coordenadas'].get('lon')
            if 'lat' in p and 'lon' in p:  # Asegurar que las coordenadas sean válidas
                p.setdefault('tipo', 'intermedio')  # Tipo por defecto
                puntos_validos.append(p)

        if not puntos_validos:
            # Si no hay puntos intermedios válidos, solo mostrar puntos fijos
            st.warning("No hay suficientes puntos intermedios para optimizar. Mostrando solo puntos fijos.")
            return puntos_fijos_inicio + puntos_fijos_fin

        # 3. OBTENER MATRIZ DE TIEMPOS
        time_matrix = obtener_matriz_tiempos(puntos_validos, considerar_trafico)

        # 4. CONFIGURAR MODELO DE OPTIMIZACIÓN
        manager = pywrapcp.RoutingIndexManager(len(puntos_validos), 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def time_callback(from_index, to_index):
            """Devuelve el tiempo entre dos puntos."""
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return time_matrix[from_node][to_node]

        transit_idx = routing.RegisterTransitCallback(time_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

        # 5. CONFIGURAR PARÁMETROS DE BÚSQUEDA
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_params.time_limit.seconds = 15  # Tiempo límite para la optimización

        # 6. SOLUCIONAR EL MODELO
        solution = routing.SolveWithParameters(search_params)

        if solution:
            # Obtener el orden optimizado de puntos
            index = routing.Start(0)
            ruta_optimizada_idx = []
            while not routing.IsEnd(index):
                ruta_optimizada_idx.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))

            # Combinar puntos fijos con los intermedios optimizados
            return (
                puntos_fijos_inicio +
                [puntos_validos[i] for i in ruta_optimizada_idx] +
                puntos_fijos_fin
            )

        # Si no hay solución, devolver el orden original
        st.warning("No se encontró una solución optimizada. Mostrando orden original.")
        return puntos_fijos_inicio + puntos_validos + puntos_fijos_fin

    except Exception as e:
        st.error(f"Error en Algoritmo 1: {str(e)}")
        return puntos_intermedios
        
# Algoritmo 2: Google OR-Tools (LNS + GLS)
def optimizar_ruta_algoritmo2(puntos_intermedios, puntos_con_hora, considerar_trafico=True):
    try:
        time_matrix = obtener_matriz_tiempos(puntos_intermedios, considerar_trafico)
        manager = pywrapcp.RoutingIndexManager(len(time_matrix), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        
        transit_callback_index = routing.RegisterTransitCallback(
            lambda from_idx, to_idx: time_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]
        )
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Restricción de tiempo
        horizon = 9 * 3600  # 9 horas en segundos
        routing.AddDimension(
            transit_callback_index,
            3600,  # Slack máximo
            horizon,
            False,
            'Time'
        )
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Ventanas temporales
        for idx, punto in enumerate(puntos_con_hora):
            if punto.get('hora'):
                hh, mm = map(int, punto['hora'].split(':'))
                time_min = (hh - 8) * 3600 + mm * 60
                time_max = time_min + 1800  # 30 minutos de ventana
                index = manager.NodeToIndex(idx)
                time_dimension.CumulVar(index).SetRange(time_min, time_max)
        
        # Configuración LNS + GLS CORREGIDA
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
        
        # Configuración LNS correcta
        search_parameters.local_search_operators.use_path_lns = True
        search_parameters.local_search_operators.use_inactive_lns = True
        search_parameters.time_limit.seconds = 15
        
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            index = routing.Start(0)
            route_order = []
            while not routing.IsEnd(index):
                route_order.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
            
            # Verificar que la solución es diferente a la original
            if route_order == list(range(len(puntos_intermedios))):
                st.warning("El algoritmo no mejoró el orden original. Probando con más tiempo...")
                search_parameters.time_limit.seconds = 30
                solution = routing.SolveWithParameters(search_parameters)
                if solution:
                    index = routing.Start(0)
                    route_order = []
                    while not routing.IsEnd(index):
                        route_order.append(manager.IndexToNode(index))
                        index = solution.Value(routing.NextVar(index))
            
            return [puntos_intermedios[i] for i in route_order]
        else:
            st.warning("No se encontró solución con LNS+GLS, usando orden original")
            return puntos_intermedios
            
    except Exception as e:
        return puntos_intermedios

# Algoritmo 3: CP-SAT
def optimizar_ruta_algoritmo3(puntos_intermedios, puntos_con_hora, considerar_trafico=True):
    """Versión con Constraint Programming (CP-SAT)"""
    try:
        from ortools.sat.python import cp_model
        
        num_locations = len(puntos_intermedios)
        time_matrix = obtener_matriz_tiempos(puntos_intermedios, considerar_trafico)
        
        model = cp_model.CpModel()
        
        # Variables de decisión
        x = {}
        for i in range(num_locations):
            for j in range(num_locations):
                if i != j:
                    x[i, j] = model.NewBoolVar(f'x_{i}_{j}')
        
        # Restricciones
        # Cada ubicación es visitada exactamente una vez
        for i in range(num_locations):
            model.Add(sum(x[i, j] for j in range(num_locations) if i != j) == 1)
            model.Add(sum(x[j, i] for j in range(num_locations) if i != j) == 1)
        
        # Eliminar subtours
        u = [model.NewIntVar(0, num_locations-1, f'u_{i}') for i in range(num_locations)]
        model.Add(u[0] == 0)
        for i in range(1, num_locations):
            model.Add(u[i] >= 1)
            model.Add(u[i] <= num_locations-1)
            for j in range(1, num_locations):
                if i != j:
                    model.Add(u[i] - u[j] + num_locations * x[i, j] <= num_locations - 1)
        
        # Función objetivo
        objective_terms = []
        for i in range(num_locations):
            for j in range(num_locations):
                if i != j:
                    objective_terms.append(time_matrix[i][j] * x[i, j])
        model.Minimize(sum(objective_terms))
        
        # Resolver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 15.0
        status = solver.Solve(model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            route_order = [0]
            current = 0
            while len(route_order) < num_locations:
                for j in range(num_locations):
                    if current != j and solver.Value(x[current, j]) == 1:
                        route_order.append(j)
                        current = j
                        break
            return [puntos_intermedios[i] for i in route_order]
        else:
            st.warning("No se encontró solución con CP-SAT")
            return puntos_intermedios
            
    except Exception as e:
        return puntos_intermedios

# Algoritmo 4: Large Neighborhood Search (LNS)
def optimizar_ruta_algoritmo4(puntos_intermedios, puntos_con_hora, considerar_trafico=True):
    try:
        time_matrix = obtener_matriz_tiempos(puntos_intermedios, considerar_trafico)
        manager = pywrapcp.RoutingIndexManager(len(time_matrix), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        
        transit_callback_index = routing.RegisterTransitCallback(
            lambda from_idx, to_idx: time_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]
        )
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        # Restricción de tiempo
        horizon = 9 * 3600
        routing.AddDimension(
            transit_callback_index,
            3600,
            horizon,
            False,
            'Time'
        )
        time_dimension = routing.GetDimensionOrDie('Time')
        
        # Ventanas temporales
        for idx, punto in enumerate(puntos_con_hora):
            if punto.get('hora'):
                hh, mm = map(int, punto['hora'].split(':'))
                time_min = (hh - 8) * 3600 + mm * 60
                time_max = time_min + 1800
                index = manager.NodeToIndex(idx)
                time_dimension.CumulVar(index).SetRange(time_min, time_max)
        
        # Configuración LNS puro CORREGIDA
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        
        # Usar solamente operadores LNS (sin GLS)
        search_parameters.local_search_operators.use_path_lns = True
        search_parameters.local_search_operators.use_inactive_lns = True
        search_parameters.local_search_operators.use_lns = True  # Solo para versiones recientes de OR-Tools
        search_parameters.time_limit.seconds = 20
        
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            index = routing.Start(0)
            route_order = []
            while not routing.IsEnd(index):
                route_order.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
            
            return [puntos_intermedios[i] for i in route_order]
        else:
            st.warning("No se encontró solución con LNS puro, usando orden original")
            return puntos_intermedios
            
    except Exception as e:
        return puntos_intermedios

def obtener_puntos_del_dia(fecha):
    """Función principal con caché condicional"""
    # Determinar TTL basado en si es fecha histórica
    ttl = 3600 if fecha < datetime.now().date() else 300
    return _obtener_puntos_del_dia_cached(fecha, ttl)

@st.cache_data(ttl=3600)
def _obtener_puntos_del_dia_cached(fecha, _ttl=None):
    """Función interna con caché - Versión modificada mínima"""
    try:
        fecha_str = fecha.strftime("%Y-%m-%d")
        puntos = []
        recogidas_ref = db.collection('recogidas')
        
        # Consulta para recogidas
        recogidas = list(recogidas_ref.where('fecha_recojo', '==', fecha_str).stream())
        for doc in recogidas:
            data = doc.to_dict()
            if 'coordenadas_recojo' in data:
                punto = {
                    "id": doc.id,
                    "tipo": "recojo",
                    "nombre": data.get('nombre_cliente') or data.get('sucursal', 'Punto de recogida'),
                    "direccion": data.get('direccion_recojo', 'Dirección no especificada'),
                    "hora": data.get('hora_recojo'),
                    "duracion_estimada": 15
                }
                # Conversión segura de coordenadas
                coords = data['coordenadas_recojo']
                if hasattr(coords, 'latitude'):  # Si es GeoPoint
                    punto.update({
                        "lat": coords.latitude,
                        "lon": coords.longitude
                    })
                elif isinstance(coords, dict):  # Si es diccionario
                    punto.update({
                        "lat": coords.get('lat'),
                        "lon": coords.get('lon')
                    })
                puntos.append(punto)
        
        # Consulta para entregas (misma lógica que arriba)
        entregas = list(recogidas_ref.where('fecha_entrega', '==', fecha_str).stream())
        for doc in entregas:
            data = doc.to_dict()
            if 'coordenadas_entrega' in data:
                punto = {
                    "id": doc.id,
                    "tipo": "entrega",
                    "nombre": data.get('nombre_cliente') or data.get('sucursal', 'Punto de entrega'),
                    "direccion": data.get('direccion_entrega', 'Dirección no especificada'),
                    "hora": data.get('hora_entrega'),
                    "duracion_estimada": 15
                }
                # Conversión segura de coordenadas
                coords = data['coordenadas_entrega']
                if hasattr(coords, 'latitude'):
                    punto.update({
                        "lat": coords.latitude,
                        "lon": coords.longitude
                    })
                elif isinstance(coords, dict):
                    punto.update({
                        "lat": coords.get('lat'),
                        "lon": coords.get('lon')
                    })
                puntos.append(punto)
        
        return puntos
        
    except Exception as e:
        st.error(f"Error al obtener puntos: {str(e)}")
        return []
        
def construir_ruta_completa(puntos_fijos, puntos_intermedios_optimizados):
    """Combina puntos fijos con la ruta optimizada en el orden CORRECTO"""
    # Ordenar puntos fijos iniciales (orden >= 0)
    inicio = sorted([p for p in puntos_fijos if p['orden'] >= 0], key=lambda x: x['orden'])
    
    # Ordenar puntos fijos finales (orden < 0)
    fin = sorted([p for p in puntos_fijos if p['orden'] < 0], key=lambda x: x['orden'])
    
    return inicio + puntos_intermedios_optimizados + fin
    
# Función para mostrar ruta en mapa (completa con puntos fijos)
def mostrar_ruta_en_mapa(ruta_completa):
    """
    Muestra la ruta optimizada en un mapa interactivo considerando calles y puntos fijos.
    """
    try:
        # Validar que haya suficientes puntos en la ruta
        if len(ruta_completa) < 2:
            st.warning("Se necesitan al menos 2 puntos para mostrar la ruta")
            return None

        # Preparar los puntos para la solicitud a Google Maps Directions API
        waypoints = "|".join([f"{p['lat']},{p['lon']}" for p in ruta_completa[1:-1]])
        origin = f"{ruta_completa[0]['lat']},{ruta_completa[0]['lon']}"
        destination = f"{ruta_completa[-1]['lat']},{ruta_completa[-1]['lon']}"

        # Hacer la solicitud a la API de Google Maps Directions
        url = (
            f"https://maps.googleapis.com/maps/api/directions/json?"
            f"origin={origin}&destination={destination}"
            f"&waypoints={waypoints}&key={GOOGLE_MAPS_API_KEY}&mode=driving"
        )
        response = requests.get(url)
        data = response.json()

        if data.get("status") != "OK":
            st.error(f"Error al obtener la ruta: {data.get('error_message', 'Desconocido')}")
            return None

        # Decodificar la polilínea de la ruta
        polyline_points = decode_polyline(data["routes"][0]["overview_polyline"]["points"])
        route_coords = [(p["lat"], p["lng"]) for p in polyline_points]

        # Crear el mapa centrado en el primer punto
        m = folium.Map(location=[ruta_completa[0]['lat'], ruta_completa[0]['lon']], zoom_start=13)

        # Dibujar la ruta en el mapa
        folium.PolyLine(
            route_coords,
            color="#0066cc",
            weight=6,
            opacity=0.8,
            tooltip="Ruta optimizada completa"
        ).add_to(m)

        # Añadir marcadores para todos los puntos
        for i, punto in enumerate(ruta_completa):
            if i == 0:
                icon = folium.Icon(color='red', icon='flag', prefix='fa')  # Inicio
            elif i == len(ruta_completa) - 1:
                icon = folium.Icon(color='black', icon='flag-checkered', prefix='fa')  # Fin
            elif punto.get('tipo') == 'fijo':
                icon = folium.Icon(color='green', icon='building', prefix='fa')  # Puntos fijos
            else:
                icon = folium.Icon(color='blue', icon='map-pin', prefix='fa')  # Intermedios

            # Agregar marcador al mapa
            folium.Marker(
                location=[punto['lat'], punto['lon']],
                popup=folium.Popup(
                    f"{punto.get('direccion', 'Sin dirección')}<br>Hora: {punto.get('hora', 'N/A')}",
                    max_width=300
                ),
                icon=icon
            ).add_to(m)

        # Mostrar el mapa en Streamlit
        st_folium(m, width=700, height=500)

    except Exception as e:
        st.error(f"Error al generar el mapa: {e}")
        
def mostrar_metricas(ruta, time_matrix):
    """Métricas mejoradas con validación de restricciones"""
    if len(ruta) <= 1:
        st.warning("No hay suficientes puntos para calcular métricas")
        return
    
    # Calcular métricas basadas en la matriz de tiempos real
    tiempo_total = 0
    tiempo_con_restricciones = 0
    puntos_con_restriccion = 0
    
    for i in range(len(ruta)-1):
        tiempo_segmento = time_matrix[i][i+1]
        tiempo_total += tiempo_segmento
        
        if ruta[i].get('hora'):
            puntos_con_restriccion += 1
            tiempo_con_restricciones += tiempo_segmento
    
    # Convertir a horas/minutos
    horas_total = int(tiempo_total // 3600)
    minutos_total = int((tiempo_total % 3600) // 60)
    
    # Eficiencia
    eficiencia = (tiempo_con_restricciones / tiempo_total) * 100 if tiempo_total > 0 else 0
    
    # Mostrar en columnas con formato mejorado
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("📌 Total de paradas", len(ruta))
    col2.metric("⏱️ Tiempo total", f"{horas_total}h {minutos_total}m")
    col3.metric("⏳ Puntos con restricción", f"{puntos_con_restriccion}/{len(ruta)}")
    col4.metric("📊 Eficiencia", f"{eficiencia:.1f}%")
    
    # Gráfico de tiempo por segmento
    segmentos = [f"{i+1}-{i+2}" for i in range(len(ruta)-1)]
    tiempos = [time_matrix[i][i+1]/60 for i in range(len(ruta)-1)]  # En minutos
    
    df_tiempos = pd.DataFrame({
        'Segmento': segmentos,
        'Tiempo (min)': tiempos
    })
    
    st.bar_chart(df_tiempos.set_index('Segmento'))
    
    # Detalle de restricciones
    with st.expander("🔍 Ver detalles de restricciones"):
        for i, punto in enumerate(ruta):
            if punto.get('hora'):
                st.write(f"📍 **Punto {i+1}**: {punto.get('nombre', '')}")
                st.write(f"   - Hora requerida: {punto['hora']}")
                st.write(f"   - Dirección: {punto.get('direccion', '')}")


# --- Configuración del servidor Traccar ---
TRACCAR_URL = "https://traccar-docker-production.up.railway.app"
TRACCAR_USERNAME = "melisa.mezadelg@gmail.com"  # Cambia según tus credenciales
TRACCAR_PASSWORD = "lavanderias"  # Cambia según tus credenciales

# --- Obtener posiciones desde la API de Traccar ---
@st.cache_data(ttl=10)  # Actualiza cada 10 segundos
def obtener_posiciones():
    try:
        response = requests.get(
            f"{TRACCAR_URL}/api/positions",
            auth=(TRACCAR_USERNAME, TRACCAR_PASSWORD)
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error al obtener posiciones: {e}")
        return []

def obtener_historial(device_id):
    try:
        ahora = datetime.utcnow()
        inicio = ahora.replace(hour=7, minute=30, second=0, microsecond=0)
        fin = ahora.replace(hour=19, minute=0, second=0, microsecond=0)

        # Asegura que esté en formato ISO (UTC)
        inicio_str = inicio.isoformat() + "Z"
        fin_str = fin.isoformat() + "Z"

        url = f"{TRACCAR_URL}/api/positions?deviceId={device_id}&from={inicio_str}&to={fin_str}"

        response = requests.get(url, auth=(TRACCAR_USERNAME, TRACCAR_PASSWORD))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error al obtener historial: {e}")
        return []

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📍 Seguimiento de Vehículo")

    # --- Validación de horario permitido ---
    hora_actual = datetime.now().time()
    hora_inicio = time(7, 30)
    hora_fin = time(19, 0)

    if not (hora_inicio <= hora_actual <= hora_fin):
        st.warning("🚫 El seguimiento del vehículo solo está disponible de 7:30 a.m. a 7:00 p.m.")
        return
    
    # Obtener posiciones actuales desde la API
    posiciones = obtener_posiciones()
    if posiciones:
        # Suponiendo que obtenemos detalles del primer vehículo
        posicion = posiciones[0]  # Consideramos un solo vehículo
        lat, lon = posicion["latitude"], posicion["longitude"]
        device_id = posicion["deviceId"]
        velocidad = posicion.get("speed", 0)  # Velocidad en km/h
        ultima_actualizacion = posicion.get("fixTime", "No disponible")  # Hora de última posición
       
        # Convertir a hora local
        utc_dt = datetime.fromisoformat(ultima_actualizacion.replace("Z", "+00:00"))
        local_tz = pytz.timezone("America/Lima")
        local_dt = utc_dt.astimezone(local_tz)
        ultima_actualizacion_local = local_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Dividir en columnas para diseño
        col1, col2 = st.columns([2, 1])
        with col1:
            # Mapa interactivo
            m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)
            folium.Marker(
                location=[lat, lon],
                popup=f"Vehículo ID: {device_id}\nVelocidad: {velocidad} km/h",
                icon=folium.Icon(color="red", icon="car", prefix="fa")
            ).add_to(m)
            st_folium(m, width=700, height=500)

        with col2:
            # Panel de detalles
            st.markdown(f"""
                <div style='background-color: #f9f9f9; padding: 15px; border-radius: 5px;'>
                    <h4>🚗 <b>Detalles del Vehículo</b></h4>
                    <p><b>ID:</b> {device_id}</p>
                    <p><b>Velocidad:</b> {velocidad} km/h</p>
                    <p><b>Última Actualización:</b> {ultima_actualizacion_local}</p>
                </div>
            """, unsafe_allow_html=True)

        # --- Mostrar historial de ruta ---
        historial = obtener_historial(device_id)
        if historial and len(historial) > 1:
            ruta = [(p["latitude"], p["longitude"]) for p in historial]
            folium.PolyLine(ruta, color="blue", weight=2.5, opacity=0.8, tooltip="Ruta del Día").add_to(m)
            
        #   VER DESPLEGABLE CON PUNTOS DEL DÍA
        #    with st.expander("📜 Ver puntos del historial"):
        #        for punto in historial:
        #            hora = punto.get("fixTime", "").replace("T", " ").split(".")[0]
        #            st.markdown(f"🕒 {hora} - 📍 ({punto['latitude']:.5f}, {punto['longitude']:.5f})")

        # Botón para actualizar manualmente (sin filtro dinámico)
        st.button("🔄 Actualizar Datos")
    else:
        st.warning("No hay posiciones disponibles en este momento.")

# Inicializar 'logged_in', 'usuario_actual' y 'menu' en session_state
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'usuario_actual' not in st.session_state:
    st.session_state['usuario_actual'] = None
if 'menu' not in st.session_state:
    st.session_state['menu'] = []

# Navegación de la aplicación
if not st.session_state['logged_in']:
    login()
else:
    usuario = st.session_state['usuario_actual']
    if not st.session_state['menu']:
        if usuario == "administrador":
            st.session_state['menu'] = ["Ingresar Boleta", "Ingresar Sucursal", "Solicitar Recogida", "Datos de Ruta", "Datos de Boletas", "Ver Ruta Optimizada", "Seguimiento al Vehículo"]
        elif usuario == "conductor":
            st.session_state['menu'] = ["Ver Ruta Optimizada", "Datos de Ruta"]
        elif usuario == "sucursal":
            st.session_state['menu'] = ["Solicitar Recogida", "Seguimiento al Vehículo"]
   
    with st.sidebar:
        # Botón de actualización solo para admin
        if usuario == "administrador":              
            if st.button("🔄 Actualizar datos maestros"):
                # Limpiar cachés
                if 'articulos' in st.session_state:
                    del st.session_state.articulos
                if 'sucursales' in st.session_state:
                    del st.session_state.sucursales
                if 'boletas_verificadas' in st.session_state:
                    del st.session_state.boletas_verificadas
            
                st.success("Datos actualizados. Refresca la página.")
                st.rerun()

        # Elementos comunes del menú
        st.title("Menú")
        if st.button("🔓 Cerrar sesión"):
            logout()

        choice = st.selectbox("Selecciona una opción", st.session_state['menu'])

    # Navegación principal
    if choice == "Ingresar Boleta":
        from features.boletas import ingresar_boleta
        ingresar_boleta()
        pass
    elif choice == "Ingresar Sucursal":
        from features.sucursales import ingresar_sucursal
        ingresar_sucursal()
        pass
    elif choice == "Solicitar Recogida":
        from features.recogidas import solicitar_recogida
        solicitar_recogida()
        pass
    elif choice == "Datos de Ruta":
        from features.rutas import datos_ruta
        datos_ruta()
        pass
    elif choice == "Datos de Boletas":
        from features.boletas import datos_boletas
        datos_boletas()
        pass
    elif choice == "Ver Ruta Optimizada":
        from features.rutas import ver_ruta_optimizada
        ver_ruta_optimizada()
        pass
    elif choice == "Seguimiento al Vehículo":
        seguimiento_vehiculo()
