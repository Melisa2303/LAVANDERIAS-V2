import streamlit as st
from core.auth import login, logout
          
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

from features.boletas import ingresar_boleta, datos_boletas
from features.sucursales import ingresar_sucursal
from features.recogidas import solicitar_recogida
from features.rutas import datos_ruta, ver_ruta_optimizada
from features.tracking import seguimiento_vehiculo
          
    # Navegación principal
    if choice == "Ingresar Boleta":
        ingresar_boleta()
    elif choice == "Ingresar Sucursal":
        ingresar_sucursal()
    elif choice == "Solicitar Recogida":
        solicitar_recogida()
    elif choice == "Datos de Ruta":
        datos_ruta()
    elif choice == "Datos de Boletas":
        datos_boletas()
    elif choice == "Ver Ruta Optimizada":
        ver_ruta_optimizada()
    elif choice == "Seguimiento al Vehículo":
        seguimiento_vehiculo()
