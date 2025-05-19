# Lógico para el Algoritmo 1: PCA + GLS OR TOOLS
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
from googlemaps.convert import decode_polyline
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import math
import pandas as pd
from datetime import datetime, timedelta, time
import time as tiempo
import pytz

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
