import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import os
from dotenv import load_dotenv
import re
from datetime import datetime

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
    articulos = [doc.to_dict()['nombre'] for doc in docs]
    return articulos

# Leer datos de sucursales desde Firestore
def obtener_sucursales():
    sucursales_ref = db.collection('sucursales')
    docs = sucursales_ref.stream()
    sucursales = [doc.to_dict()['nombre'] for doc in docs]
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
                st.session_state['menu'] = ["📝 Ingresar Boleta", "🏢 Ingresar Sucursal", "🚚 Solicitar Recogida", "📝 Datos de Recojo", "📄 Datos de Boletas", "🛣️ Ver Ruta Optimizada", "🚗 Seguimiento al Vehículo"]
            elif usuario == "conductor":
                st.session_state['menu'] = ["🛣️ Ver Ruta Optimizada", "📝 Datos de Recojo"]
            elif usuario == "sucursal":
                st.session_state['menu'] = ["🚚 Solicitar Recogida", "🚗 Seguimiento al Vehículo"]
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
    articulos = obtener_articulos()
    sucursales = obtener_sucursales()
    
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
        tipo_servicio = st.selectbox("Tipo de Servicio", ["Sucursal", "Delivery"])
        
        if "Sucursal" in tipo_servicio:
            sucursal = st.selectbox("Sucursal", sucursales)
        else:
            sucursal = None
        
        # Seleccionar artículos
        articulo_seleccionado = st.multiselect("Artículos Lavados", articulos, help="Escriba las iniciales para filtrar")
        cantidades = {articulo: st.number_input(f"Cantidad de {articulo}", min_value=1, value=1) for articulo in articulo_seleccionado}
        
        fecha_registro = st.date_input("Fecha de Registro", datetime.now())
        
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
            
            # Verificar unicidad del número de boleta
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
                "articulos": cantidades,
                "fecha_registro": fecha_registro.strftime("%Y-%m-%d")
            }
            
            db.collection('boletas').add(boleta)
            st.success("Boleta ingresada correctamente.")

def ingresar_sucursal():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🏢 Ingresar Sucursal")
    # Implementar funcionalidad

def solicitar_recogida():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚚 Solicitar Recogida")
    # Implementar funcionalidad

def datos_recojo():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Datos de Recojo")
    # Implementar funcionalidad

def datos_boletas():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📄 Datos de Boletas")
    # Implementar funcionalidad

def ver_ruta_optimizada():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🛣️ Ver Ruta Optimizada")
    # Implementar funcionalidad

def seguimiento_vehiculo():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("🚗 Seguimiento al Vehículo")
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
            st.session_state['menu'] = ["📝 Ingresar Boleta", "🏢 Ingresar Sucursal", "🚚 Solicitar Recogida", "📝 Datos de Recojo", "📄 Datos de Boletas", "🛣️ Ver Ruta Optimizada", "🚗 Seguimiento al Vehículo"]
        elif usuario == "conductor":
            st.session_state['menu'] = ["🛣️ Ver Ruta Optimizada", "📝 Datos de Recojo"]
        elif usuario == "sucursal":
            st.session_state['menu'] = ["🚚 Solicitar Recogida", "🚗 Seguimiento al Vehículo"]

    st.sidebar.title("Menú")
    if st.sidebar.button("🔓 Cerrar sesión"):
        logout()

    menu = st.session_state['menu']
    choice = st.sidebar.selectbox("Selecciona una opción", menu)

    if choice == "📝 Ingresar Boleta":
        ingresar_boleta()
    elif choice == "🏢 Ingresar Sucursal":
        ingresar_sucursal()
    elif choice == "🚚 Solicitar Recogida":
        solicitar_recogida()
    elif choice == "📝 Datos de Recojo":
        datos_recojo()
    elif choice == "📄 Datos de Boletas":
        datos_boletas()
    elif choice == "🛣️ Ver Ruta Optimizada":
        ver_ruta_optimizada()
    elif choice == "🚗 Seguimiento al Vehículo":
        seguimiento_vehiculo()
