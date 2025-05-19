# Lógico para el Algoritmo 2: 
import streamlit as st
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import math
import pandas as pd
from datetime import datetime, timedelta, time
import time as tiempo
import pytz
import requests  # Importar requests

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
