import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app, auth
import os
from dotenv import load_dotenv
import re
from datetime import datetime, timedelta
import requests  # Importar requests
import pydeck as pdk
from streamlit_folium import st_folium
import folium
from geopy.geocoders import Nominatim  # Usaremos esto para obtener la dirección desde coordenadas
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import pandas as pd
from io import BytesIO
import time

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
    st.rerun()

# Leer datos de artículos desde Firestore
def obtener_articulos():
    if 'articulos' not in st.session_state:
        # Solo leer si no hay caché
        articulos_ref = db.collection('articulos')
        docs = articulos_ref.stream()
        st.session_state.articulos = [doc.to_dict().get('Nombre', 'Nombre no disponible') for doc in docs]
    return st.session_state.articulos

# Leer datos de sucursales desde Firestore
def obtener_sucursales():
    if 'sucursales' not in st.session_state:
        # Solo leer si no hay caché
        sucursales_ref = db.collection('sucursales')
        docs = sucursales_ref.stream()
        st.session_state.sucursales = [
            {
                "nombre": doc.to_dict().get('nombre', 'Nombre no disponible'),
                "direccion": doc.to_dict().get('direccion', 'Dirección no disponible'),
                "coordenadas": doc.to_dict().get('coordenadas', {})
            }
            for doc in docs
        ]
    return st.session_state.sucursales
    
# Verificar unicidad del número de boleta
def verificar_unicidad_boleta(numero_boleta, tipo_servicio, sucursal):
    # Caché local para verificaciones recientes
    cache_key = f"{numero_boleta}-{tipo_servicio}-{sucursal}"
    if 'boletas_verificadas' in st.session_state and cache_key in st.session_state.boletas_verificadas:
        return st.session_state.boletas_verificadas[cache_key]
    
    boletas_ref = db.collection('boletas')
    
    # Construimos una consulta con LIMIT 1 para optimizar
    if tipo_servicio == "🏢 Sucursal":
        query = boletas_ref.where('numero_boleta', '==', numero_boleta)\
                          .where('tipo_servicio', '==', tipo_servicio)\
                          .where('sucursal', '==', sucursal)\
                          .limit(1)  # Solo necesitamos saber si existe al menos una
    else:
        query = boletas_ref.where('numero_boleta', '==', numero_boleta)\
                          .where('tipo_servicio', '==', tipo_servicio)\
                          .limit(1)
    
    # Verificamos si hay al menos un documento
    existe = bool(next(query.stream(), None))
    
    # Actualizamos caché
    if 'boletas_verificadas' not in st.session_state:
        st.session_state.boletas_verificadas = {}
    st.session_state.boletas_verificadas[cache_key] = not existe
    
    return not existe

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
            st.rerun()
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

    nombres_sucursales = [sucursal['nombre'] for sucursal in sucursales]

    tipo_servicio = st.radio("Tipo de Servicio", ["🏢 Sucursal", "🚚 Delivery"], horizontal=True)
    if "Sucursal" in tipo_servicio:
        sucursal = st.selectbox("Sucursal", nombres_sucursales)
    else:
        sucursal = None  # Asegurar que 'sucursal' esté inicializada para el caso "Delivery"

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
        if articulos_a_eliminar:
            for articulo in articulos_a_eliminar:
                del st.session_state['cantidades'][articulo]
            st.rerun()

    # Si la bandera de actualización está activa, reiniciar después de la acción
    if 'update' in st.session_state and st.session_state['update']:
        st.session_state['update'] = False  # Reinicia la bandera después de actualizar

    # Selector de fecha
    fecha_registro = st.date_input("Fecha de Registro (AAAA/MM/DD)", value=datetime.now())

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

            if monto <= 0:  # Validación para el monto
                st.error("El monto a pagar debe ser mayor a 0.")
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
            # Reset form fields
            st.session_state['cantidades'] = {}  # Already present
            st.session_state.numero_boleta = ""  # Add keys for other inputs
            st.session_state.nombre_cliente = ""
            st.session_state.dni = ""
            st.session_state.telefono = ""
            st.session_state.monto = 0.0
            st.session_state.fecha_registro = datetime.now()
            st.rerun()
            
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
    
def ingresar_sucursal():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Sucursal")

    # Inicialización
    if "ingresar_sucursal_lat" not in st.session_state:
        st.session_state.update({
            "ingresar_sucursal_lat": -16.409047,
            "ingresar_sucursal_lon": -71.537451,
            "ingresar_sucursal_direccion": "Arequipa, Perú",
            "nombre_sucursal": "",
            "encargado": "",
            "telefono": ""
        })

    # Campos del formulario
    nombre_sucursal = st.text_input(
        "Nombre de la Sucursal", 
        value=st.session_state.nombre_sucursal
    )
    
    direccion_input = st.text_input(
        "Dirección",
        value=st.session_state.ingresar_sucursal_direccion,
        key="ingresar_sucursal_direccion_input"
    )

    # Buscar sugerencias
    sugerencias = []
    if direccion_input and direccion_input != st.session_state.ingresar_sucursal_direccion:
        sugerencias = obtener_sugerencias_direccion(direccion_input)
    
    direccion_seleccionada = st.selectbox(
        "Sugerencias de Direcciones:",
        ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias] if sugerencias else ["No hay sugerencias"],
        key="ingresar_sucursal_sugerencias"
    )

    # Actualizar al seleccionar sugerencia
    if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
        for sug in sugerencias:
            if direccion_seleccionada == sug["display_name"]:
                st.session_state.ingresar_sucursal_lat = float(sug["lat"])
                st.session_state.ingresar_sucursal_lon = float(sug["lon"])
                st.session_state.ingresar_sucursal_direccion = direccion_seleccionada
                
                # Actualizar mapa
                st.session_state.ingresar_sucursal_mapa = folium.Map(
                    location=[st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
                    zoom_start=15
                )
                folium.Marker(
                    [st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
                    tooltip="Punto seleccionado"
                ).add_to(st.session_state.ingresar_sucursal_mapa)
                break

    # Mapa
    if "ingresar_sucursal_mapa" not in st.session_state:
        st.session_state.ingresar_sucursal_mapa = folium.Map(
            location=[st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
            zoom_start=15
        )
        folium.Marker(
            [st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
            tooltip="Punto seleccionado"
        ).add_to(st.session_state.ingresar_sucursal_mapa)

    mapa = st_folium(
        st.session_state.ingresar_sucursal_mapa,
        width=700,
        height=500,
        key="ingresar_sucursal_mapa_folium"
    )

    # Actualizar al hacer clic
    if mapa.get("last_clicked"):
        st.session_state.ingresar_sucursal_lat = mapa["last_clicked"]["lat"]
        st.session_state.ingresar_sucursal_lon = mapa["last_clicked"]["lng"]
        st.session_state.ingresar_sucursal_direccion = obtener_direccion_desde_coordenadas(
            st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon
        )
        
        # Actualizar mapa
        st.session_state.ingresar_sucursal_mapa = folium.Map(
            location=[st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
            zoom_start=15
        )
        folium.Marker(
            [st.session_state.ingresar_sucursal_lat, st.session_state.ingresar_sucursal_lon],
            tooltip="Punto seleccionado"
        ).add_to(st.session_state.ingresar_sucursal_mapa)
        st.rerun()

    # Mostrar dirección final
    st.markdown(f"""
        <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
            <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
            <p style='color: #555; font-size: 16px;'>{st.session_state.ingresar_sucursal_direccion}</p>
        </div>
    """, unsafe_allow_html=True)

    # Otros campos
    col1, col2 = st.columns(2)
    with col1:
        encargado = st.text_input("Encargado (Opcional)", value=st.session_state.encargado)
    with col2:
        telefono = st.text_input("Teléfono (Opcional)", value=st.session_state.telefono, max_chars=9)
        
    if st.button("💾 Ingresar Sucursal"):
        # Validaciones
        if not nombre_sucursal:
            st.error("El nombre de la sucursal es obligatorio.")
            return
        if telefono and not re.match(r"^\d{9}$", telefono):
            st.error("El teléfono debe tener 9 dígitos.")
            return

        try:
            # Guardar en Firestore
            db.collection("sucursales").add({
                "nombre": nombre_sucursal,
                "direccion": st.session_state.ingresar_sucursal_direccion,
                "coordenadas": {
                    "lat": st.session_state.ingresar_sucursal_lat,
                    "lon": st.session_state.ingresar_sucursal_lon
                },
                "encargado": encargado if encargado else None,
                "telefono": telefono if telefono else None,
            })
            
            # Mensaje de éxito
            st.success("✅ Sucursal registrada correctamente")
            
            # Limpiar caché
            if 'sucursales' in st.session_state:
                del st.session_state.sucursales
            if 'sucursales_mapa' in st.session_state:
                del st.session_state.sucursales_mapa
            
            # Resetear campos
            st.session_state.update({
                "nombre_sucursal": "",
                "encargado": "",
                "telefono": "",
                "ingresar_sucursal_direccion": "Arequipa, Perú",
                "ingresar_sucursal_lat": -16.409047,
                "ingresar_sucursal_lon": -71.537451
            })
            
            success_msg.empty()
            st.rerun()
            
        except Exception as e:
            st.error(f"Error al guardar: {e}")
              
def solicitar_recogida():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🛒 Solicitar Recogida")

    # Función para calcular fecha de entrega
    def calcular_fecha_entrega(fecha_recojo):
        dia_semana = fecha_recojo.weekday()
        if dia_semana == 5:  # Sábado
            return fecha_recojo + timedelta(days=4)  # Miércoles
        elif dia_semana == 3:  # Jueves
            return fecha_recojo + timedelta(days=4)  # Lunes
        return fecha_recojo + timedelta(days=3)  # Normal (3 días)

    tipo_solicitud = st.radio("Tipo de Solicitud", ["Sucursal", "Cliente Delivery"], horizontal=True)

    if tipo_solicitud == "Sucursal":
        sucursales = obtener_sucursales()
        nombres_sucursales = [s["nombre"] for s in sucursales]
        nombre_sucursal = st.selectbox("Seleccionar Sucursal", nombres_sucursales)
        
        sucursal_seleccionada = next((s for s in sucursales if s["nombre"] == nombre_sucursal), None)
        if sucursal_seleccionada:
            lat, lon = sucursal_seleccionada["coordenadas"]["lat"], sucursal_seleccionada["coordenadas"]["lon"]
            direccion = sucursal_seleccionada["direccion"]
            st.markdown(f"**Dirección:** {direccion}")
        else:
            st.error("Datos de sucursal incompletos.")
            return
        
        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())

        if st.button("💾 Solicitar Recogida"):
            fecha_entrega = calcular_fecha_entrega(fecha_recojo)
            
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "sucursal": nombre_sucursal,
                # Campos para recogida
                "direccion_recojo": direccion,
                "coordenadas_recojo": {"lat": lat, "lon": lon},
                # Campos para entrega (iguales por defecto)
                "direccion_entrega": direccion,
                "coordenadas_entrega": {"lat": lat, "lon": lon},
                # Fechas
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d"),
                # Hora dejada en blanco intencionalmente
            }
            
            try:
                db.collection('recogidas').add(solicitud)
                st.success(f"Recogida agendada. Entrega el {fecha_entrega.strftime('%d/%m/%Y')}")
            except Exception as e:
                st.error(f"Error al guardar: {e}")

    elif tipo_solicitud == "Cliente Delivery":
        # Configuración inicial del mapa
        # Inicialización independiente
        if "delivery_lat" not in st.session_state:
            st.session_state.delivery_lat = -16.409047
            st.session_state.delivery_lon = -71.537451
            st.session_state.delivery_direccion = "Arequipa, Perú"
            st.session_state.delivery_mapa = folium.Map(
                location=[st.session_state.delivery_lat, st.session_state.delivery_lon],
                zoom_start=15
            )
            st.session_state.delivery_marker = folium.Marker(
                [st.session_state.delivery_lat, st.session_state.delivery_lon],
                tooltip="Punto seleccionado"
            ).add_to(st.session_state.delivery_mapa)

        # Widgets de entrada
        col1, col2 = st.columns(2)
        with col1:
            nombre_cliente = st.text_input("Nombre del Cliente")
        with col2:
            telefono = st.text_input("Teléfono", max_chars=9)
        
        # Búsqueda de dirección
        direccion_input = st.text_input(
            "Dirección",
            value=st.session_state.delivery_direccion,
            key="delivery_direccion_input"
        )

        # Buscar sugerencias
        sugerencias = []
        if direccion_input and direccion_input != st.session_state.delivery_direccion:
            sugerencias = obtener_sugerencias_direccion(direccion_input)
        
        direccion_seleccionada = st.selectbox(
            "Sugerencias de Direcciones:",
            ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias] if sugerencias else ["No hay sugerencias"],
            key="delivery_sugerencias"
        )

        # Actualizar al seleccionar sugerencia
        if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
            for sug in sugerencias:
                if direccion_seleccionada == sug["display_name"]:
                    st.session_state.delivery_lat = float(sug["lat"])
                    st.session_state.delivery_lon = float(sug["lon"])
                    st.session_state.delivery_direccion = direccion_seleccionada
                    
                    # Actualizar mapa y marcador
                    st.session_state.delivery_mapa = folium.Map(
                        location=[st.session_state.delivery_lat, st.session_state.delivery_lon],
                        zoom_start=15
                    )
                    st.session_state.delivery_marker = folium.Marker(
                        [st.session_state.delivery_lat, st.session_state.delivery_lon],
                        tooltip="Punto seleccionado"
                    ).add_to(st.session_state.delivery_mapa)
                    break

        # Renderizar mapa
        mapa = st_folium(
            st.session_state.delivery_mapa,
            width=700,
            height=500,
            key="delivery_mapa_folium"
        )

        # Actualizar al hacer clic
        if mapa.get("last_clicked"):
            st.session_state.delivery_lat = mapa["last_clicked"]["lat"]
            st.session_state.delivery_lon = mapa["last_clicked"]["lng"]
            st.session_state.delivery_direccion = obtener_direccion_desde_coordenadas(
                st.session_state.delivery_lat, st.session_state.delivery_lon
            )
            
            # Actualizar mapa y marcador
            st.session_state.delivery_mapa = folium.Map(
                location=[st.session_state.delivery_lat, st.session_state.delivery_lon],
                zoom_start=15
            )
            st.session_state.delivery_marker = folium.Marker(
                [st.session_state.delivery_lat, st.session_state.delivery_lon],
                tooltip="Punto seleccionado"
            ).add_to(st.session_state.delivery_mapa)
            st.rerun()

        # Mostrar dirección final
        st.markdown(f"""
            <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
                <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
                <p style='color: #555; font-size: 16px;'>{st.session_state.delivery_direccion}</p>
            </div>
        """, unsafe_allow_html=True)

        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())

        if st.button("💾 Solicitar Recogida"):
            if not nombre_cliente:
                st.error("El nombre del cliente es obligatorio.")
                return
            if not re.match(r"^\d{9}$", telefono):
                st.error("El teléfono debe tener 9 dígitos.")
                return

            fecha_entrega = calcular_fecha_entrega(fecha_recojo)
            
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "nombre_cliente": nombre_cliente,
                "telefono": telefono,
                # Campos para recogida
                "direccion_recojo": st.session_state.delivery_data["direccion"],
                "coordenadas_recojo": {
                    "lat": st.session_state.delivery_data["lat"],
                    "lon": st.session_state.delivery_data["lon"]
                },
                # Campos para entrega (iguales por defecto)
                "direccion_entrega": st.session_state.delivery_data["direccion"],
                "coordenadas_entrega": {
                    "lat": st.session_state.delivery_data["lat"],
                    "lon": st.session_state.delivery_data["lon"]
                },
                # Fechas
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d"),
                # Hora dejada en blanco intencionalmente
            }

            try:
                db.collection('recogidas').add(solicitud)
                st.success(f"Recogida agendada. Entrega el {fecha_entrega.strftime('%d/%m/%Y')}")
            except Exception as e:
                st.error(f"Error al guardar: {e}")

def datos_ruta():
    # --- Configuración inicial ---
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    
    st.title("📋 Ruta del Día")

    # --- Filtros ---
    col1, col2 = st.columns(2)
    with col1:
        fecha_seleccionada = st.date_input("Seleccionar Fecha", value=datetime.now().date())
    with col2:
        tipo_servicio = st.radio("Tipo de Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)

    # --- Obtener datos ---
    @st.cache_data(ttl=300)
    def cargar_ruta(fecha, tipo):
        try:
            query = db.collection('recogidas')
            docs = list(query.where("fecha_recojo", "==", fecha.strftime("%Y-%m-%d")).stream()) + \
                   list(query.where("fecha_entrega", "==", fecha.strftime("%Y-%m-%d")).stream())

            if tipo != "Todos":
                tipo_filtro = "Sucursal" if tipo == "Sucursal" else "Cliente Delivery"
                docs = [doc for doc in docs if doc.to_dict().get("tipo_solicitud") == tipo_filtro]

            datos = []
            for doc in docs:
                data = doc.to_dict()
                doc_id = doc.id
                
                if data.get("fecha_recojo") == fecha.strftime("%Y-%m-%d"):
                    datos.append({
                        "id": doc_id,
                        "operacion": "Recojo",
                        "nombre_cliente": data.get("nombre_cliente"),
                        "sucursal": data.get("sucursal"),
                        "direccion": data.get("direccion_recojo", "N/A"),
                        "telefono": data.get("telefono", "N/A"),
                        "hora": data.get("hora_recojo", ""),
                        "tipo_solicitud": data.get("tipo_solicitud"),
                        "coordenadas": data.get("coordenadas_recojo", {"lat": -16.409047, "lon": -71.537451}),
                        "fecha": data.get("fecha_recojo"),
                    })
                
                if data.get("fecha_entrega") == fecha.strftime("%Y-%m-%d"):
                    datos.append({
                        "id": doc_id,
                        "operacion": "Entrega",
                        "nombre_cliente": data.get("nombre_cliente"),
                        "sucursal": data.get("sucursal"),
                        "direccion": data.get("direccion_entrega", "N/A"),
                        "telefono": data.get("telefono", "N/A"),
                        "hora": data.get("hora_entrega", ""),
                        "tipo_solicitud": data.get("tipo_solicitud"),
                        "coordenadas": data.get("coordenadas_entrega", {"lat": -16.409047, "lon": -71.537451}),
                        "fecha": data.get("fecha_entrega"),
                    })
            
            return datos
        except Exception as e:
            st.error(f"Error al cargar datos: {e}")
            return []

    datos = cargar_ruta(fecha_seleccionada, tipo_servicio)

    # --- Mostrar Tabla ---
    if datos:
        tabla_data = []
        for item in datos:
            nombre_mostrar = item["nombre_cliente"] if item["tipo_solicitud"] == "Cliente Delivery" else item["sucursal"]
            
            tabla_data.append({
                "Operación": item["operacion"],
                "Cliente/Sucursal": nombre_mostrar if nombre_mostrar else "N/A",
                "Dirección": item["direccion"],
                "Teléfono": item["telefono"],
                "Hora": item["hora"] if item["hora"] else "Sin hora",
            })

        df_tabla = pd.DataFrame(tabla_data)
        st.dataframe(df_tabla, height=600, use_container_width=True, hide_index=True)

        # --- Mapa de Ruta ---
        puntos_validos = [item["coordenadas"] for item in datos if item.get("coordenadas")]
        if puntos_validos:
            centro = {
                "lat": sum(p["lat"] for p in puntos_validos) / len(puntos_validos),
                "lon": sum(p["lon"] for p in puntos_validos) / len(puntos_validos)
            }
            
            m = folium.Map(location=[centro["lat"], centro["lon"]], zoom_start=13)
            for item in datos:
                if item.get("coordenadas"):
                    nombre = item["nombre_cliente"] if item["tipo_solicitud"] == "Cliente Delivery" else item["sucursal"]
                    folium.Marker(
                        [item["coordenadas"]["lat"], item["coordenadas"]["lon"]],
                        popup=f"{nombre} - {item['operacion']}",
                        icon=folium.Icon(color="green" if item["operacion"] == "Recojo" else "blue")
                    ).add_to(m)
            
            st_folium(m, width=700, height=500)

        # --- Gestión de Deliveries ---
        deliveries = [item for item in datos if item["tipo_solicitud"] == "Cliente Delivery"]
        
        if deliveries:
            st.markdown("---")
            st.subheader("🔄 Gestión de Deliveries")
            
            opciones = {f"{item['operacion']} - {item['nombre_cliente']}": item for item in deliveries}
            selected = st.selectbox("Seleccionar operación:", options=opciones.keys())
            delivery_data = opciones[selected]

            # --- Selector de Hora Unificado ---
            st.markdown(f"### Hora de {delivery_data['operacion']}")
            
            # Crear una fila con el combobox y botón
            hora_col1, hora_col2 = st.columns([4, 1])
            
            with hora_col1:
                # Generar opciones de hora (7:00 a 18:00 cada 30 min)
                horas_sugeridas = [f"{h:02d}:{m:02d}" for h in range(7, 19) for m in (0, 30)]
                hora_actual = delivery_data.get("hora", "12:00:00")[:5]  # Formato HH:MM
                
                # Si la hora actual no está en las sugeridas, la agregamos
                if hora_actual not in horas_sugeridas:
                    horas_sugeridas.append(hora_actual)
                    horas_sugeridas.sort()
                
                # Combobox unificado
                nueva_hora = st.selectbox(
                    "Seleccionar o escribir hora (HH:MM):",
                    options=horas_sugeridas,
                    index=horas_sugeridas.index(hora_actual) if hora_actual in horas_sugeridas else 0,
                    key=f"hora_combobox_{delivery_data['id']}"
                )
            
            with hora_col2:
                st.write("")  # Espaciado
                st.write("")  # Espaciado
                if st.button("💾 Guardar", key=f"guardar_btn_{delivery_data['id']}"):
                    try:
                        # Validar formato HH:MM
                        if len(nueva_hora.split(":")) != 2:
                            raise ValueError
                        hora, minutos = map(int, nueva_hora.split(":"))
                        if not (0 <= hora < 24 and 0 <= minutos < 60):
                            raise ValueError
                        
                        campo_hora = "hora_recojo" if delivery_data["operacion"] == "Recojo" else "hora_entrega"
                        db.collection('recogidas').document(delivery_data["id"]).update({
                            campo_hora: f"{hora:02d}:{minutos:02d}:00"
                        })
                        st.success("Hora actualizada")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                    except ValueError:
                        st.error("Formato inválido. Use HH:MM")
                    except Exception as e:
                        st.error(f"Error: {e}")

            # --- Sección de Dirección y Mapa (Versión idéntica a Solicitar Recogida) ---
            st.markdown(f"### 📅 Reprogramación de {delivery_data['operacion']}")
            with st.expander("Cambiar fecha y ubicación", expanded=True):
                # Inicialización independiente (usando prefijo "reprogramar_" en lugar de "delivery_")
                if "reprogramar_lat" not in st.session_state:
                    st.session_state.reprogramar_lat = delivery_data["coordenadas"]["lat"]
                    st.session_state.reprogramar_lon = delivery_data["coordenadas"]["lon"]
                    st.session_state.reprogramar_direccion = delivery_data["direccion"]
                    st.session_state.reprogramar_mapa = folium.Map(
                        location=[st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        zoom_start=15
                    )
                    st.session_state.reprogramar_marker = folium.Marker(
                        [st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        tooltip="Punto seleccionado"        
                    ).add_to(st.session_state.reprogramar_mapa)

                # Campo de dirección
                direccion_input = st.text_input(
                    "Dirección",
                    value=st.session_state.reprogramar_direccion,
                    key=f"reprogramar_direccion_input_{delivery_data['id']}"
                )

                # Buscar sugerencias
                sugerencias = []
                if direccion_input and direccion_input != st.session_state.reprogramar_direccion:
                    sugerencias = obtener_sugerencias_direccion(direccion_input)
    
                direccion_seleccionada = st.selectbox(
                    "Sugerencias de Direcciones:",
                    ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias] if sugerencias else ["No hay sugerencias"],
                    key=f"reprogramar_sugerencias_{delivery_data['id']}"
                )

                # Actualizar al seleccionar sugerencia
                if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
                    for sug in sugerencias:
                        if direccion_seleccionada == sug["display_name"]:
                            st.session_state.reprogramar_lat = float(sug["lat"])
                            st.session_state.reprogramar_lon = float(sug["lon"])
                            st.session_state.reprogramar_direccion = direccion_seleccionada
                
                            # Actualizar mapa y marcador
                            st.session_state.reprogramar_mapa = folium.Map(
                                location=[st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                                zoom_start=15
                            )
                            st.session_state.reprogramar_marker = folium.Marker(
                                [st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                                tooltip="Punto seleccionado"
                            ).add_to(st.session_state.reprogramar_mapa)
                            break

                # Renderizar mapa
                mapa = st_folium(
                    st.session_state.reprogramar_mapa,
                    width=700,
                    height=500,
                    key=f"reprogramar_mapa_{delivery_data['id']}"
                )

                # Actualizar al hacer clic
                if mapa.get("last_clicked"):
                    st.session_state.reprogramar_lat = mapa["last_clicked"]["lat"]
                    st.session_state.reprogramar_lon = mapa["last_clicked"]["lng"]
                    st.session_state.reprogramar_direccion = obtener_direccion_desde_coordenadas(
                        st.session_state.reprogramar_lat, st.session_state.reprogramar_lon
                    )
        
                    # Actualizar mapa y marcador
                    st.session_state.reprogramar_mapa = folium.Map(
                        location=[st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        zoom_start=15
                    )
                    st.session_state.reprogramar_marker = folium.Marker(
                        [st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        tooltip="Punto seleccionado"
                    ).add_to(st.session_state.reprogramar_mapa)
                    st.rerun()

                # Mostrar dirección final
                st.markdown(f"""
                    <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
                        <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
                        <p style='color: #555; font-size: 16px;'>{st.session_state.reprogramar_direccion}</p>
                    </div>
                """, unsafe_allow_html=True)

                # Selector de fecha (manteniendo tu lógica original)
                min_date = datetime.now().date() if delivery_data["operacion"] == "Recojo" else datetime.strptime(delivery_data["fecha"], "%Y-%m-%d").date()
                nueva_fecha = st.date_input(
                    "Nueva fecha:",
                    value=min_date + timedelta(days=1),
                    min_value=min_date
                )

                # Botón para guardar cambios
                if st.button(f"💾 Guardar Cambios de {delivery_data['operacion']}"):
                    try:
                        updates = {
                            "fecha_recojo" if delivery_data["operacion"] == "Recojo" else "fecha_entrega": nueva_fecha.strftime("%Y-%m-%d"),
                            "direccion_recojo" if delivery_data["operacion"] == "Recojo" else "direccion_entrega": st.session_state.reprogramar_direccion,
                            "coordenadas_recojo" if delivery_data["operacion"] == "Recojo" else "coordenadas_entrega": {
                                "lat": st.session_state.reprogramar_lat,
                                "lon": st.session_state.reprogramar_lon
                            }
                        }
            
                        db.collection('recogidas').document(delivery_data["id"]).update(updates)
                        st.success("¡Reprogramación exitosa!")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")

        # --- Botón de Descarga ---
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df_tabla.to_excel(writer, index=False)
        
        st.download_button(
            label="Descargar Excel",
            data=excel_buffer.getvalue(),
            file_name=f"ruta_{fecha_seleccionada.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No hay datos para la fecha seleccionada con los filtros actuales.")
                
def datos_boletas():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Datos de Boletas")

    # --- Filtros (Mismo diseño original) ---
    tipo_servicio = st.radio(
        label="Filtrar por Tipo de Servicio",
        options=["Todos", "Sucursal", "Delivery"],
        horizontal=True
    )

    # Filtro de sucursal (solo si se elige "Sucursal")
    sucursal_seleccionada = None
    if tipo_servicio == "Sucursal":
        sucursales = obtener_sucursales()  # Usa la caché de session_state
        nombres_sucursales = ["Todas"] + [s["nombre"] for s in sucursales]
        sucursal_seleccionada = st.selectbox(
            "Seleccionar Sucursal", 
            nombres_sucursales
        )

    # Filtro de fechas (igual que antes)
    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha de Inicio")
    with col2:
        fecha_fin = st.date_input("Fecha de Fin")

    # --- Consulta optimizada a Firebase ---
    query = db.collection('boletas')

    # Aplicar filtros directamente en Firestore
    if tipo_servicio == "Sucursal":
        query = query.where("tipo_servicio", "==", "🏢 Sucursal")
        if sucursal_seleccionada and sucursal_seleccionada != "Todas":
            query = query.where("sucursal", "==", sucursal_seleccionada)
    elif tipo_servicio == "Delivery":
        query = query.where("tipo_servicio", "==", "🚚 Delivery")

    if fecha_inicio and fecha_fin:
        query = query.where("fecha_registro", ">=", fecha_inicio.strftime("%Y-%m-%d")) \
                     .where("fecha_registro", "<=", fecha_fin.strftime("%Y-%m-%d"))

    # Ejecutar consulta (con límite para evitar sobrecarga)
    try:
        boletas = list(query.limit(1000).stream())
    except Exception as e:
        st.error(f"Error al cargar boletas: {e}")
        return

    # --- Procesar datos (Mismo formato visual original) ---
    datos = []
    for doc in boletas:
        boleta = doc.to_dict()
        articulos = boleta.get("articulos", {})
        articulos_lavados = "\n".join([f"{k}: {v}" for k, v in articulos.items()])

        # Formatear tipo de servicio (igual que antes)
        tipo_servicio_formateado = boleta.get("tipo_servicio", "N/A")
        if tipo_servicio_formateado == "🏢 Sucursal":
            nombre_sucursal_boleta = boleta.get("sucursal", "Sin Nombre")
            tipo_servicio_formateado = f"🏢 Sucursal: {nombre_sucursal_boleta}"

        datos.append({
            "Número de Boleta": boleta.get("numero_boleta", "N/A"),
            "Cliente": boleta.get("nombre_cliente", "N/A"),
            "Teléfono": boleta.get("telefono", "N/A"),
            "Tipo de Servicio": tipo_servicio_formateado,
            "Fecha de Registro": boleta.get("fecha_registro", "N/A"),
            "Monto": f"S/. {boleta.get('monto', 0):.2f}",
            "Artículos Lavados": articulos_lavados
        })

    # --- Mostrar resultados (Mismo estilo original) ---
    if datos:
        st.write("📋 Resultados Filtrados:")
        st.dataframe(
            datos, 
            width=1000, 
            height=600,
            column_config={
                "Artículos Lavados": st.column_config.TextColumn(width="large")
            }
        )

        # Botón de descarga en Excel (opcional)
        df = pd.DataFrame(datos)
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="DatosBoletas")
        st.download_button(
            label="📥 Descargar en Excel",
            data=excel_buffer.getvalue(),
            file_name="datos_boletas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("No hay boletas que coincidan con los filtros seleccionados.")
        
def ver_ruta_optimizada():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚐 Ver Ruta Optimizada")

    # Filtro por fecha (se mantiene igual)
    fecha_seleccionada = st.date_input("Seleccionar Fecha")

    # --- OPTIMIZACIÓN: Consulta filtrada desde Firestore ---
    query = db.collection('recogidas').where("fecha_recojo", "==", fecha_seleccionada.strftime("%Y-%m-%d"))
    docs = query.stream()
    
    puntos_dia = []
    for doc in docs:
        solicitud = doc.to_dict()
        # Mantenemos el mismo procesamiento de siempre
        if 'coordenadas' in solicitud and 'direccion' in solicitud:
            puntos_dia.append({
                "lat": solicitud["coordenadas"]["lat"],
                "lon": solicitud["coordenadas"]["lon"],
                "direccion": solicitud["direccion"]
            })

    # Puntos fijos (se mantienen igual)
    puntos_fijos = [
        {"lat": -16.4141434959913, "lon": -71.51839574233342, "direccion": "Cochera"},
        {"lat": -16.398605226701633, "lon": -71.4376266111019, "direccion": "Planta"},
        {"lat": -16.43564123078658, "lon": -71.52216190495753, "direccion": "Sucursal Av Dolores"}
    ]

    # Construcción de ruta (igual que antes)
    ruta_completa = puntos_fijos[:3] + puntos_dia + puntos_fijos[::-1][:3]

    # --- Mapa (código idéntico al original) ---
    if ruta_completa:
        m = folium.Map(location=[-16.409047, -71.537451], zoom_start=13)
        
        # Marcadores (igual)
        for i, punto in enumerate(ruta_completa):
            folium.Marker(
                location=[punto["lat"], punto["lon"]],
                tooltip=f"{i+1}. {punto['direccion']}",
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)

        # Línea de ruta (igual)
        coords = [(p["lat"], p["lon"]) for p in ruta_completa]
        folium.PolyLine(coords, color="blue", weight=5).add_to(m)
        
        # Flechas de dirección (igual)
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

# Configuración del servidor Traccar
TRACCAR_URL = "http://traccar-docker-production.up.railway.app"
TRACCAR_USERNAME = "melisa.mezadelg@gmail.com"
TRACCAR_PASSWORD = "lavanderias"

# Obtener posiciones desde la API
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

def seguimiento_vehiculo():
    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📍 Seguimiento de Vehículo en Tiempo Real")
    
    posiciones = obtener_posiciones()
    if posiciones:
        # Configurar mapa
        m = folium.Map(location=[-16.409047, -71.537451], zoom_start=13)

        # Añadir marcadores al mapa
        for posicion in posiciones:
            lat = posicion["latitude"]
            lon = posicion["longitude"]
            device_id = posicion["deviceId"]
            folium.Marker(
                location=[lat, lon],
                popup=f"Vehículo ID: {device_id}",
                icon=folium.Icon(color="blue")
            ).add_to(m)
        
        # Mostrar mapa interactivo
        st_folium(m, width=800, height=500)
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
