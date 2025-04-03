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
    sucursales = [{"nombre": doc.to_dict().get('nombre', 'Nombre no disponible'), "direccion": doc.to_dict().get('direccion', 'Dirección no disponible')} for doc in docs]
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
                st.session_state['menu'] = ["Ingresar Boleta", "Ingresar Sucursal", "Solicitar Recogida", "Datos de Recojo", "Datos de Boletas", "Ver Ruta Optimizada", "Seguimiento al Vehículo"]
            elif usuario == "conductor":
                st.session_state['menu'] = ["Ver Ruta Optimizada", "Datos de Recojo"]
            elif usuario == "sucursal":
                st.session_state['menu'] = ["Solicitar Recogida", "Seguimiento al Vehículo"]
        else:
            st.error("Usuario o contraseña incorrectos")

# Función para ingresar boleta
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

    # Formulario de ingreso de boleta
    with st.form(key='form_boleta'):
        col1, col2 = st.columns(2)
        with col1:
            numero_boleta = st.text_input("Número de Boleta", max_chars=5)
        with col2:
            nombre_cliente = st.text_input("Nombre del Cliente")

        col1, col2 = st.columns(2)
        with col1:
            dni = st.text_input("Número de DNI (Opcional)", max_chars=8)
        with col2:
            telefono = st.text_input("Teléfono (Opcional)", max_chars=9)

        monto = st.number_input("Monto a Pagar", min_value=0.0, format="%.2f", step=0.01)

        tipo_servicio = st.radio("Tipo de Servicio", ["🏢 Sucursal", "🚚 Delivery"], horizontal=True)

        if "Sucursal" in tipo_servicio:
            sucursal = st.selectbox("Sucursal", sucursales)
        else:
            sucursal = None

        # Agregar artículos de forma dinámica
        st.markdown("<h3 style='margin-bottom: 10px;'>Seleccionar Artículos Lavados</h3>", unsafe_allow_html=True)
        articulo_seleccionado = st.selectbox("Agregar Artículo", [""] + articulos, index=0)

        # Manejar selección y actualización de cantidades automáticamente
        if articulo_seleccionado and articulo_seleccionado not in st.session_state['cantidades']:
            st.session_state['cantidades'][articulo_seleccionado] = 1

        # Mostrar los artículos seleccionados dinámicamente
        if st.session_state['cantidades']:
            for articulo, cantidad in st.session_state['cantidades'].items():
                col1, col2 = st.columns([2, 1])
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

        # Selector de fecha
        fecha_registro = st.date_input("Fecha de Registro", value=datetime.now())

        # Botón para guardar
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

            db.collection('boletas').add(boleta)  # Comenta o descomenta según pruebas
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
    # Extrae las coordenadas de una dirección usando la API de Nominatim.
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
    # Usa Geopy para obtener una dirección a partir de coordenadas (latitud y longitud).
    try:
        location = geolocator.reverse((lat, lon), language="es")
        return location.address if location else "Dirección no encontrada"
    except Exception as e:
        st.error(f"Error al obtener dirección desde coordenadas: {e}")
        return "Dirección no encontrada"

# Función para mostrar el mapa y actualizar dinámicamente el marcador
def actualizar_mapa(lat, lon):
    # Genera un mapa interactivo que siempre se actualiza en el mismo lugar.
    m = folium.Map(location=[lat, lon], zoom_start=15)

    # Agregar marcador dinámico basado en las coordenadas actuales
    folium.Marker([lat, lon], tooltip="Punto seleccionado").add_to(m)

    # Retorna el mapa interactivo que será actualizado
    return st_folium(m, width=700, height=500)

# Función principal para ingresar sucursal
def ingresar_sucursal():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Sucursal")

    # Campos de entrada
    nombre_sucursal = st.text_input("Nombre de la Sucursal")
    direccion = st.text_input("Dirección", key="direccion")

    # Buscar sugerencias de direcciones mientras se escribe
    sugerencias = []
    if direccion:
        sugerencias = obtener_sugerencias_direccion(direccion)
        opciones_desplegable = ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias]

    # Desplegable para seleccionar dirección
    direccion_seleccionada = st.selectbox(
        "Sugerencias de Direcciones:", opciones_desplegable if sugerencias else ["No hay sugerencias"]
    )

    # Coordenadas dinámicas basadas en la dirección seleccionada o clics en el mapa
    lat, lon = -12.046374, -77.042793  # Coordenadas por defecto (Lima, Perú)

    if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
        for sug in sugerencias:
            if direccion_seleccionada == sug["display_name"]:
                lat = float(sug["lat"])
                lon = float(sug["lon"])
                direccion = direccion_seleccionada  # Actualizar campo de dirección con la sugerencia elegida
                break

    # Mostrar mapa dinámico basado en coordenadas actuales
    mapa = actualizar_mapa(lat, lon)
    seleccion_usuario = mapa.get("last_clicked")  # Coordenadas del último clic en el mapa
    if seleccion_usuario:
        lat = seleccion_usuario["lat"]
        lon = seleccion_usuario["lng"]
        direccion = obtener_direccion_desde_coordenadas(lat, lon)  # Actualizar dirección final
        # Actualizar el mapa nuevamente en el mismo lugar
        mapa = actualizar_mapa(lat, lon)

    # Mostrar la dirección final estilizada
    st.markdown(f"""
        <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
            <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
            <p style='color: #555; font-size: 16px;'>{direccion}</p>
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

        if not direccion or not lat or not lon:
            st.error("La dirección no es válida. Por favor, ingrese una dirección existente y válida.")
            return

        # Crear el diccionario de datos para la sucursal
        sucursal = {
            "nombre": nombre_sucursal,
            "direccion": direccion,  # Usará la dirección actualizada
            "coordenadas": {
                "lat": lat,
                "lon": lon
            },
            "encargado": encargado if encargado else "",
            "telefono": telefono if telefono else "",
        }

        # Guardar en Firestore
        db.collection("sucursales").add(sucursal)
        st.success("Sucursal ingresada correctamente.")

def solicitar_recogida():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🛒 Solicitar Recogida")
    
    tipo_solicitud = st.radio("Tipo de Solicitud", ["Sucursal", "Cliente Delivery"], horizontal=True)
    
    if tipo_solicitud == "Sucursal":
        sucursales = obtener_sucursales()
        nombres_sucursales = [sucursal["nombre"] for sucursal in sucursales]
        nombre_sucursal = st.selectbox("Seleccionar Sucursal", nombres_sucursales)
        
        sucursal_seleccionada = next((sucursal for sucursal in sucursales if sucursal["nombre"] == nombre_sucursal), None)
        if sucursal_seleccionada:
            direccion = sucursal_seleccionada["direccion"]
            st.write(f"Dirección: {direccion}")
        
        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())
        
        if st.button("💾 Solicitar Recogida"):
            fecha_entrega = fecha_recojo + timedelta(days=3)
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "sucursal": nombre_sucursal,
                "direccion": direccion,
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d")
            }
            db.collection('recogidas').add(solicitud)
            st.success("Recogida solicitada correctamente.")

    elif tipo_solicitud == "Cliente Delivery":
        nombre_cliente = st.text_input("Nombre del Cliente")
        telefono = st.text_input("Teléfono")
        direccion = st.text_input("Dirección")
        fecha_recojo = st.date_input("Fecha de Recojo", min_value=datetime.now().date())
        
        if st.button("💾 Solicitar Recogida"):
            # Validaciones
            if not re.match(r'^\d{9}$', telefono):
                st.error("El número de teléfono debe tener exactamente 9 dígitos.")
                return
            
            if not verificar_direccion(direccion):
                st.error("La dirección no es válida. Por favor, ingrese una dirección existente.")
                return
            
            fecha_entrega = fecha_recojo + timedelta(days=3)
            solicitud = {
                "tipo_solicitud": tipo_solicitud,
                "nombre_cliente": nombre_cliente,
                "telefono": telefono,
                "direccion": direccion,
                "fecha_recojo": fecha_recojo.strftime("%Y-%m-%d"),
                "fecha_entrega": fecha_entrega.strftime("%Y-%m-%d")
            }
            db.collection('recogidas').add(solicitud)
            st.success("Recogida solicitada correctamente.")

def datos_recojo():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("Datos de Recojo")
    # Implementar funcionalidad

def datos_boletas():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("Datos de Boletas")
    # Implementar funcionalidad

def ver_ruta_optimizada():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("Ver Ruta Optimizada")
    # Implementar funcionalidad

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
            st.session_state['menu'] = ["Ingresar Boleta", "Ingresar Sucursal", "Solicitar Recogida", "Datos de Recojo", "Datos de Boletas", "Ver Ruta Optimizada", "Seguimiento al Vehículo"]
        elif usuario == "conductor":
            st.session_state['menu'] = ["Ver Ruta Optimizada", "Datos de Recojo"]
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
    elif choice == "Datos de Recojo":
        datos_recojo()
    elif choice == "Datos de Boletas":
        datos_boletas()
    elif choice == "Ver Ruta Optimizada":
        ver_ruta_optimizada()
    elif choice == "Seguimiento al Vehículo":
        seguimiento_vehiculo()
