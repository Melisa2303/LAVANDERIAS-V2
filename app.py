import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app, auth
import os
from dotenv import load_dotenv
import re
from datetime import datetime
import requests  # Importar requests
import pydeck as pdk
from streamlit_folium import st_folium
import folium
from geopy.geocoders import Nominatim  # Usaremos esto para obtener la dirección desde coordenadas
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# Cargar variables de entorno
load_dotenv()

# Configurar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate({
        "type": os.getenv("FIREBASE_TYPE"),
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    })
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Función de cierre de sesión
def logout():
    st.session_state['logged_in'] = False
    st.session_state['usuario_actual'] = None
    st.session_state['menu'] = []

# Leer datos de artículos desde Firestore
def obtener_articulos():
    articulos_ref = db.collection('articulos')
    docs = articulos_ref.stream()
    articulos = [doc.to_dict().get('Nombre', 'Nombre no disponible') for doc in docs]  # Usar 'Nombre' y agregar manejo de errores
    return articulos

# Leer datos de sucursales desde Firestore
def obtener_sucursales():
    sucursales_ref = db.collection('sucursales')
    docs = sucursales_ref.stream()
    sucursales = [
        {
            "nombre": doc.to_dict().get('nombre', 'Nombre no disponible'),
            "direccion": doc.to_dict().get('direccion', 'Dirección no disponible'),
            "coordenadas": doc.to_dict().get('coordenadas', {})  # Obtener todo el objeto coordenadas
        }
        for doc in docs
    ]
    return sucursales
    
# Verificar unicidad del número de boleta
def verificar_unicidad_boleta(numero_boleta, tipo_servicio, sucursal):
    boletas_ref = db.collection('boletas')
    query = boletas_ref.where('numero_boleta', '==', numero_boleta).where('tipo_servicio', '==', tipo_servicio)
    if tipo_servicio == 'sucursal':
        query = query.where('sucursal', '==', sucursal)
    docs = query.stream()
    return not any(docs)  # Retorna True si no hay documentos duplicados

# Páginas de la aplicación
def login():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    
    st.subheader("Inicia Tu Sesión")
    usuario = st.text_input("Usuario", key="login_usuario")
    password = st.text_input("Contraseña", type="password", key="login_password")
    
    if st.button("🔒 Ingresar"):
        if (usuario == "administrador" and password == "admin12") or \
           (usuario == "conductor" and password == "conductor12") or \
           (usuario == "sucursal" and password == "sucursal12"):
            st.session_state['usuario_actual'] = usuario
            st.session_state['logged_in'] = True
            if usuario == "administrador":
                st.session_state['menu'] = ["Ingresar Boleta", "Ingresar Sucursal", "Solicitar Recogida", "Datos de Ruta", "Datos de Boletas", "Ver Ruta Optimizada", "Seguimiento al Vehículo"]
            elif usuario == "conductor":
                st.session_state['menu'] = ["Ver Ruta Optimizada", "Datos de Ruta"]
            elif usuario == "sucursal":
                st.session_state['menu'] = ["Solicitar Recogida", "Seguimiento al Vehículo"]
        else:
            st.error("Usuario o contraseña incorrectos")

def ingresar_boleta():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Boleta")

    # Obtener datos necesarios
    articulos = obtener_articulos()  # Artículos lavados desde la base de datos
    sucursales = obtener_sucursales()  # Sucursales disponibles

    # Inicializar o actualizar cantidades en st.session_state
    if 'cantidades' not in st.session_state:
        st.session_state['cantidades'] = {}

    # Campos de entrada principales
    numero_boleta = st.text_input("Número de Boleta", max_chars=5)
    nombre_cliente = st.text_input("Nombre del Cliente")
    
    col1, col2 = st.columns(2)
    with col1:
        dni = st.text_input("Número de DNI (Opcional)", max_chars=8)
    with col2:
        telefono = st.text_input("Teléfono (Opcional)", max_chars=9)

    monto = st.number_input("Monto a Pagar", min_value=0.0, format="%.2f", step=0.01)

    nombres_sucursales = [sucursal['nombre'] for sucursal in sucursales]  # Extraer solo los nombres

    tipo_servicio = st.radio("Tipo de Servicio", ["🏢 Sucursal", "🚚 Delivery"], horizontal=True)
    if "Sucursal" in tipo_servicio:
        sucursal_seleccionada = st.selectbox("Sucursal", nombres_sucursales)
    else:
        sucursal = None

    # Sección de artículos: dinámico e inmediato
    st.markdown("<h3 style='margin-bottom: 10px;'>Seleccionar Artículos Lavados</h3>", unsafe_allow_html=True)
    articulo_seleccionado = st.selectbox("Agregar Artículo", [""] + articulos, index=0)

    # Manejar selección de artículos y cantidades dinámicamente
    if articulo_seleccionado and articulo_seleccionado not in st.session_state['cantidades']:
        st.session_state['cantidades'][articulo_seleccionado] = 1

    # Manejar selección de artículos y cantidades dinámicamente con opción de eliminar
    if st.session_state['cantidades']:
        st.markdown("<h4>Artículos Seleccionados</h4>", unsafe_allow_html=True)
        articulos_a_eliminar = []
        for articulo, cantidad in st.session_state['cantidades'].items():
            col1, col2, col3 = st.columns([2, 1, 0.3])
            with col1:
                st.markdown(f"<b>{articulo}</b>", unsafe_allow_html=True)
            with col2:
                nueva_cantidad = st.number_input(
                    f"Cantidad de {articulo}",
                    min_value=1,
                    value=cantidad,
                    key=f"cantidad_{articulo}"
                )
                st.session_state['cantidades'][articulo] = nueva_cantidad
            with col3:
                if st.button("🗑️", key=f"eliminar_{articulo}"):
                    articulos_a_eliminar.append(articulo)
                    st.session_state['update'] = True  # Bandera para forzar cambios

        # Eliminar los artículos seleccionados para borrar
        for articulo in articulos_a_eliminar:
            del st.session_state['cantidades'][articulo]

    # Si la bandera de actualización está activa, reiniciar después de la acción
    if 'update' in st.session_state and st.session_state['update']:
        st.session_state['update'] = False  # Reinicia la bandera después de actualizar

    # Selector de fecha
    fecha_registro = st.date_input("Fecha de Registro", value=datetime.now())

    # Botón para guardar boleta dentro de un formulario
    with st.form(key='form_boleta'):
        submit_button = st.form_submit_button(label="💾 Ingresar Boleta")

        if submit_button:
            # Validaciones
            if not re.match(r'^\d{4,5}$', numero_boleta):
                st.error("El número de boleta debe tener entre 4 y 5 dígitos.")
                return

            if not re.match(r'^[a-zA-Z\s]+$', nombre_cliente):
                st.error("El nombre del cliente solo debe contener letras.")
                return

            if dni and not re.match(r'^\d{8}$', dni):
                st.error("El número de DNI debe tener 8 dígitos.")
                return

            if telefono and not re.match(r'^\d{9}$', telefono):
                st.error("El número de teléfono debe tener 9 dígitos.")
                return

            if not st.session_state['cantidades']:
                st.error("Debe seleccionar al menos un artículo antes de ingresar la boleta.")
                return

            if not verificar_unicidad_boleta(numero_boleta, tipo_servicio, sucursal):
                st.error("Ya existe una boleta con este número en la misma sucursal o tipo de servicio.")
                return

            # Guardar los datos en Firestore
            boleta = {
                "numero_boleta": numero_boleta,
                "nombre_cliente": nombre_cliente,
                "dni": dni,
                "telefono": telefono,
                "monto": monto,
                "tipo_servicio": tipo_servicio,
                "sucursal": sucursal,
                "articulos": st.session_state['cantidades'],
                "fecha_registro": fecha_registro.strftime("%Y-%m-%d")
            }

            db.collection('boletas').add(boleta)
            st.success("Boleta ingresada correctamente.")

            # Limpiar el estado de cantidades después de guardar
            st.session_state['cantidades'] = {}

# Inicializar Geolocalizador
geolocator = Nominatim(user_agent="StreamlitApp/1.0")

# Función para obtener sugerencias de dirección
def obtener_sugerencias_direccion(direccion):
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={direccion}&addressdetails=1"
    headers = {"User-Agent": "StreamlitApp/1.0"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()  # Devuelve las sugerencias en formato JSON
        else:
            st.warning(f"Error al consultar API de direcciones: {response.status_code}")
    except Exception as e:
        st.error(f"Error al conectarse a la API: {e}")
    return []

# Función para obtener coordenadas específicas (opcional)
def obtener_coordenadas(direccion):
    """Extrae las coordenadas de una dirección usando la API de Nominatim."""
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={direccion}&addressdetails=1"
    headers = {"User-Agent": "StreamlitApp/1.0"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200 and response.json():
            data = response.json()[0]
            return float(data["lat"]), float(data["lon"])
        else:
            st.warning("No se encontraron coordenadas para la dirección ingresada.")
    except Exception as e:
        st.error(f"Error al conectarse a la API: {e}")
    return None, None

# Función para obtener la dirección desde coordenadas
def obtener_direccion_desde_coordenadas(lat, lon):
    """Usa Geopy para obtener una dirección a partir de coordenadas (latitud y longitud)."""
    try:
        location = geolocator.reverse((lat, lon), language="es")
        return location.address if location else "Dirección no encontrada"
    except Exception as e:
        st.error(f"Error al obtener dirección desde coordenadas: {e}")
        return "Dirección no encontrada"

# Función principal para ingresar sucursal
def ingresar_sucursal():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Sucursal")

    # Inicializar sesión para las coordenadas
    if "lat" not in st.session_state:
        st.session_state.lat, st.session_state.lon = -16.409047, -71.537451  # Coordenadas de Arequipa, Perú
    if "direccion" not in st.session_state:
        st.session_state.direccion = "Arequipa, Perú"

    # Campos de entrada
    nombre_sucursal = st.text_input("Nombre de la Sucursal")
    direccion_input = st.text_input("Dirección", value=st.session_state.direccion)

    # Buscar sugerencias de direcciones mientras se escribe
    sugerencias = []
    if direccion_input:
        sugerencias = obtener_sugerencias_direccion(direccion_input)
        opciones_desplegable = ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias]

    # Desplegable para seleccionar dirección
    direccion_seleccionada = st.selectbox(
        "Sugerencias de Direcciones:", opciones_desplegable if sugerencias else ["No hay sugerencias"]
    )

    # Actualizar coordenadas en función de la dirección seleccionada
    if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
        for sug in sugerencias:
            if direccion_seleccionada == sug["display_name"]:
                st.session_state.lat = float(sug["lat"])
                st.session_state.lon = float(sug["lon"])
                st.session_state.direccion = direccion_seleccionada
                break

    # Renderizar el mapa basado en las coordenadas actuales
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
    folium.Marker([st.session_state.lat, st.session_state.lon], tooltip="Punto seleccionado").add_to(m)
    mapa = st_folium(m, width=700, height=500)

    # Actualizar coordenadas en función de los clics en el mapa
    seleccion_usuario = mapa.get("last_clicked")  # Coordenadas del último clic en el mapa
    if seleccion_usuario:
        st.session_state.lat = seleccion_usuario["lat"]
        st.session_state.lon = seleccion_usuario["lng"]
        st.session_state.direccion = obtener_direccion_desde_coordenadas(
            st.session_state.lat, st.session_state.lon
        )
        # Renderizar mapa inmediatamente después de cambiar las coordenadas
        m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        folium.Marker([st.session_state.lat, st.session_state.lon], tooltip="Punto seleccionado").add_to(m)
        st_folium(m, width=700, height=500)

    # Mostrar la dirección final estilizada
    st.markdown(f"""
        <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
            <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
            <p style='color: #555; font-size: 16px;'>{st.session_state.direccion}</p>
        </div>
    """, unsafe_allow_html=True)

    # Otros campos opcionales
    col1, col2 = st.columns(2)
    with col1:
        encargado = st.text_input("Encargado (Opcional)")
    with col2:
        telefono = st.text_input("Teléfono (Opcional)")

    # Botón para guardar datos
    if st.button("💾 Ingresar Sucursal"):
        # Validaciones
        if telefono and not re.match(r"^\d{9}$", telefono):
            st.error("El número de teléfono debe tener exactamente 9 dígitos.")
            return

        if not st.session_state.direccion or not st.session_state.lat or not st.session_state.lon:
            st.error("La dirección no es válida. Por favor, ingrese una dirección existente y válida.")
            return

        # Crear el diccionario de datos para la sucursal
        sucursal = {
            "nombre": nombre_sucursal,
            "direccion": st.session_state.direccion,  # Usará la dirección actualizada
            "coordenadas": {
                "lat": st.session_state.lat,
                "lon": st.session_state.lon
            },
            "encargado": encargado if encargado else "",
            "telefono": telefono if telefono else "",
        }

        # Guardar en Firestore
        db.collection("sucursales").add(sucursal)
        st.success("Sucursal ingresada correctamente.")

# Función principal para solicitar recogida
def solicitar_recogida():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🛒 Solicitar Recogida")

    tipo_solicitud = st.radio("Tipo de Solicitud", ["Sucursal", "Cliente Delivery"], horizontal=True)

    if tipo_solicitud == "Sucursal":
        sucursales = obtener_sucursales()  # Supongo que esta función retorna una lista de diccionarios
        nombres_sucursales = [sucursal["nombre"] for sucursal in sucursales]
        nombre_sucursal = st.selectbox("Seleccionar Sucursal", nombres_sucursales)

        sucursal_seleccionada = next((sucursal for sucursal in sucursales if sucursal["nombre"] == nombre_sucursal), None)
        if sucursal_seleccionada and "coordenadas" in sucursal_seleccionada:
            lat = sucursal_seleccionada["coordenadas"].get("lat")
            lon = sucursal_seleccionada["coordenadas"].get("lon")
            direccion = sucursal_seleccionada["direccion"]
            if lat is None or lon is None:
                st.error("Las coordenadas de esta sucursal están incompletas.")
                return
            st.write(f"Dirección: {direccion}")
        else:
            st.error("La sucursal seleccionada no tiene coordenadas registradas.")
            return

        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())

        if st.button("💾 Solicitar Recogida"):
            fecha_entrega = fecha_recojo + timedelta(days=3)
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "sucursal": nombre_sucursal,
                "direccion": direccion,
                "coordenadas": {"lat": lat, "lon": lon},
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d")
            }
            db.collection('recogidas').add(solicitud)
            st.success(f"Recogida solicitada correctamente. La entrega se ha agendado para {fecha_entrega.strftime('%Y-%m-%d')}.")

    elif tipo_solicitud == "Cliente Delivery":
        # Inicializar sesión para las coordenadas
        if "lat" not in st.session_state:
            st.session_state.lat, st.session_state.lon = -16.409047, -71.537451  # Coordenadas de Arequipa, Perú
        if "direccion" not in st.session_state:
            st.session_state.direccion = "Arequipa, Perú"

        nombre_cliente = st.text_input("Nombre del Cliente")
        telefono = st.text_input("Teléfono", max_chars=9)

        # Dirección del cliente con sugerencias
        direccion_input = st.text_input("Dirección", value=st.session_state.direccion)

        sugerencias = []
        if direccion_input:
            sugerencias = obtener_sugerencias_direccion(direccion_input)
            opciones_desplegable = ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias]

        direccion_seleccionada = st.selectbox(
            "Sugerencias de Direcciones:", opciones_desplegable if sugerencias else ["No hay sugerencias"]
        )

        if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
            for sug in sugerencias:
                if direccion_seleccionada == sug["display_name"]:
                    st.session_state.lat = float(sug["lat"])
                    st.session_state.lon = float(sug["lon"])
                    st.session_state.direccion = direccion_seleccionada
                    break

        # Renderizar mapa basado en coordenadas actuales
        m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
        folium.Marker([st.session_state.lat, st.session_state.lon], tooltip="Punto seleccionado").add_to(m)
        mapa = st_folium(m, width=700, height=500)

        # Actualizar coordenadas según el clic en el mapa
        seleccion_usuario = mapa.get("last_clicked")
        if seleccion_usuario:
            st.session_state.lat = seleccion_usuario["lat"]
            st.session_state.lon = seleccion_usuario["lng"]
            st.session_state.direccion = obtener_direccion_desde_coordenadas(
                st.session_state.lat, st.session_state.lon
            )

        # Mostrar dirección final estilizada
        st.markdown(f"""
            <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
                <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
                <p style='color: #555; font-size: 16px;'>{st.session_state.direccion}</p>
            </div>
        """, unsafe_allow_html=True)

        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())

        # Botón para registrar solicitud
        if st.button("💾 Solicitar Recogida"):
            # Validaciones
            if not re.match(r'^\d{9}$', telefono):
                st.error("El número de teléfono debe tener exactamente 9 dígitos.")
                return

            fecha_entrega = fecha_recojo + timedelta(days=3)
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "nombre_cliente": nombre_cliente,
                "telefono": telefono,
                "direccion": st.session_state.direccion,
                "coordenadas": {
                    "lat": st.session_state.lat,
                    "lon": st.session_state.lon
                },
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d")
            }
            db.collection('recogidas').add(solicitud)
            st.success(f"Recogida solicitada correctamente. La entrega se ha agendado para {fecha_entrega.strftime('%Y-%m-%d')}.")

def datos_ruta():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Datos de Ruta")

    # Selección de fecha para el filtro
    fecha_filtrada = st.date_input("Seleccionar Fecha", min_value=datetime.now().date())

    # Leer datos de la base de datos 'recogidas'
    recojos_ref = db.collection('recogidas')  # Asume que esta es la colección donde se guardan las solicitudes
    docs = recojos_ref.stream()

    # Procesar datos para construir la tabla
    datos = []
    for doc in docs:
        solicitud = doc.to_dict()

        # Verificar si es un recojo o una entrega y si corresponde a la fecha filtrada
        if solicitud.get("fecha_recojo") == fecha_filtrada.strftime("%Y-%m-%d"):
            datos.append({
                "Nombre": solicitud.get("nombre_cliente", solicitud.get("sucursal", "N/A")),
                "Teléfono": solicitud.get("telefono", "N/A"),
                "Dirección": solicitud.get("direccion", "N/A"),
                "Tipo": "Recojo"
            })
        elif solicitud.get("fecha_entrega") == fecha_filtrada.strftime("%Y-%m-%d"):
            datos.append({
                "Nombre": solicitud.get("nombre_cliente", solicitud.get("sucursal", "N/A")),
                "Teléfono": solicitud.get("telefono", "N/A"),
                "Dirección": solicitud.get("direccion", "N/A"),
                "Tipo": "Entrega"
            })

    # Mostrar la tabla si hay datos filtrados
    if datos:
        st.write(f"📅 Datos para el día: {fecha_filtrada.strftime('%Y-%m-%d')}")
        st.table(datos)  # Muestra la tabla con los datos organizados
    else:
        st.info("No hay datos de recojo o entrega para la fecha seleccionada.")

def datos_boletas():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Datos de Boletas")

    # Filtro por tipo de servicio
    tipo_servicio = st.radio("Filtrar por Tipo de Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)

    # Filtro por sucursal (solo si se selecciona "Sucursal" en el filtro de tipo de servicio)
    nombre_sucursal = None
    if tipo_servicio == "Sucursal":
        sucursales = obtener_sucursales()  # Asume que esta función obtiene todas las sucursales con nombres
        nombres_sucursales = [sucursal["nombre"] for sucursal in sucursales]
        nombre_sucursal = st.selectbox("Seleccionar Sucursal", ["Todas"] + nombres_sucursales)

    # Filtro por rango de fechas
    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha de Inicio")
    with col2:
        fecha_fin = st.date_input("Fecha de Fin")

    # Leer datos de boletas desde Firestore
    boletas_ref = db.collection('boletas')  # Asume que esta es la colección donde se guardan las boletas
    docs = boletas_ref.stream()

    # Procesar datos para aplicar los filtros
    datos = []
    for doc in docs:
        boleta = doc.to_dict()
        fecha_boleta = datetime.strptime(boleta.get("fecha_registro", "1970-01-01"), "%Y-%m-%d").date()
        agregar = True

        # Aplicar filtro de rango de fechas
        if fecha_inicio and fecha_fin:
            if not (fecha_inicio <= fecha_boleta <= fecha_fin):
                agregar = False

        # Aplicar filtro de tipo de servicio
        if tipo_servicio == "Sucursal" and agregar:
            if nombre_sucursal and nombre_sucursal != "Todas" and boleta.get("sucursal") != nombre_sucursal:
                agregar = False
        elif tipo_servicio == "Delivery" and agregar:
            if boleta.get("tipo_servicio") != "🚚 Delivery":
                agregar = False

        # Agregar datos si cumplen con los filtros
        if agregar:
            # Preparar artículos lavados como una cadena de texto (artículo - cantidad)
            articulos = boleta.get("articulos", {})  # Espera un diccionario con artículos y cantidades
            articulos_lavados = ", ".join([f"{articulo} - {cantidad}" for articulo, cantidad in articulos.items()])

            datos.append({
                "Número de Boleta": boleta.get("numero_boleta", "N/A"),
                "Cliente/Sucursal": boleta.get("nombre_cliente", boleta.get("sucursal", "N/A")),
                "Teléfono": boleta.get("telefono", "N/A"),
                "Tipo de Servicio": boleta.get("tipo_servicio", "N/A"),
                "Fecha de Registro": boleta.get("fecha_registro", "N/A"),
                "Monto": f"S/. {boleta.get('monto', 0):.2f}",
                "Artículos Lavados": articulos_lavados  # Nueva columna con los artículos lavados y sus cantidades
            })

    # Mostrar tabla con los datos filtrados
    if datos:
        st.write("📋 Resultados Filtrados:")
        st.table(datos)  # Mostrar tabla con datos filtrados
    else:
        st.info("No hay boletas que coincidan con los filtros seleccionados.")

def ver_ruta_optimizada():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚐 Ver Ruta Optimizada")

    # Filtro por fecha
    fecha_seleccionada = st.date_input("Seleccionar Fecha")

    # Obtener solicitudes desde la base de datos
    solicitudes_ref = db.collection('recogidas')  # Colección donde se guardan las solicitudes
    docs = solicitudes_ref.stream()

    # Cargar solicitudes para la fecha seleccionada
    puntos_dia = []
    for doc in docs:
        solicitud = doc.to_dict()
        if solicitud.get("fecha_recojo") == fecha_seleccionada.strftime("%Y-%m-%d") or solicitud.get("fecha_entrega") == fecha_seleccionada.strftime("%Y-%m-%d"):
            puntos_dia.append({
                "lat": solicitud["coordenadas"]["lat"],
                "lon": solicitud["coordenadas"]["lon"],
                "direccion": solicitud["direccion"]
            })

    # Agregar puntos fijos (Inicio y Fin)
    puntos_fijos = [
        {"lat": -16.4141434959913, "lon": -71.51839574233342, "direccion": "Cochera"},
        {"lat": -16.398605226701633, "lon": -71.4376266111019, "direccion": "Planta"},
        {"lat": -16.43564123078658, "lon": -71.52216190495753, "direccion": "Sucursal Av Dolores"}
    ]

    # Rutas inicial y final con puntos fijos
    ruta_completa = puntos_fijos[:3] + puntos_dia + puntos_fijos[::-1][:3]

    # Calcular la ruta optimizada
    ruta_optimizada = calcular_ruta_respetando_calles(ruta_completa)

    # Mostrar el mapa con la ruta optimizada
    if ruta_optimizada:
        m = folium.Map(location=[-16.409047, -71.537451], zoom_start=13)  # Centrar en Arequipa
        for i, punto in enumerate(ruta_optimizada):
            folium.Marker(
                location=[punto["lat"], punto["lon"]],
                tooltip=f"{i+1}. {punto['direccion']}",
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)

        # Dibujar la ruta con flechas para indicar el sentido
        coords = [(p["lat"], p["lon"]) for p in ruta_optimizada]
        folium.PolyLine(coords, color="blue", weight=5).add_to(m)
        for j in range(len(coords) - 1):
            folium.Marker(
                location=[(coords[j][0] + coords[j + 1][0]) / 2,
                          (coords[j][1] + coords[j + 1][1]) / 2],
                icon=folium.DivIcon(html=f'<div style="font-size: 12px; color: green;">➡️</div>'),
            ).add_to(m)

        st_folium(m, width=700, height=500)
    else:
        st.error("No se pudo calcular la ruta optimizada. Por favor, verifica los datos.")

# Calcular la ruta respetando calles
def calcular_ruta_respetando_calles(puntos):
    api_key = "5b3ce3597851110001cf6248cf6ff2b70accf2d3eee345774426cde25c3bf8dcf3372529c468e27f"  # Coloca aquí tu API Key de OpenRouteService
    rutas_ordenadas = []

    for i in range(len(puntos) - 1):
        # Formar la URL de la solicitud (respetando lon, lat)
        url = f"https://api.openrouteservice.org/v2/directions/driving-car?api_key={api_key}&start={puntos[i]['lon']},{puntos[i]['lat']}&end={puntos[i + 1]['lon']},{puntos[i + 1]['lat']}"
        response = requests.get(url)

        if response.status_code == 200:
            # Obtener los datos de la respuesta
            data = response.json()
            if "routes" in data:
                for coord in data["routes"][0]["geometry"]["coordinates"]:
                    rutas_ordenadas.append({"lat": coord[1], "lon": coord[0], "direccion": puntos[i]["direccion"]})
            else:
                st.error(f"No se encontraron rutas en la respuesta para {puntos[i]['direccion']} -> {puntos[i + 1]['direccion']}")
                return None
        else:
            # Manejo de errores específicos
            st.error(f"Error al obtener ruta entre {puntos[i]['direccion']} y {puntos[i+1]['direccion']}. Código: {response.status_code}")
            print(response.json())  # Mostrar el error completo en la consola para depuración
            return None

    return rutas_ordenadas
    
def seguimiento_vehiculo():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("Seguimiento al Vehículo")
    # Implementar funcionalidad (opcional)

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

    st.sidebar.title("Menú")
    if st.sidebar.button("🔓 Cerrar sesión"):
        logout()

    menu = st.session_state['menu']
    choice = st.sidebar.selectbox("Selecciona una opción", menu)

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
