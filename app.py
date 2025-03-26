import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import os
from dotenv import load_dotenv

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

# Páginas de la aplicación
def login():
    st.title("Login")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = auth.get_user_by_email(email)
        # Autenticación simplificada para el ejemplo
        if password == "admin12" or password == "conductor12" or password == "sucursal12":
            st.session_state['user'] = user.email
            st.success("Logged in successfully!")
        else:
            st.error("Incorrect password")

def home():
    st.title("Home")
    st.write("Welcome, ", st.session_state['user'])

def ingresar_boleta():
    st.title("Ingresar Boleta")
    # Implementar funcionalidad

def ingresar_sucursal():
    st.title("Ingresar Sucursal")
    # Implementar funcionalidad

def solicitar_recogida():
    st.title("Solicitar Recogida")
    # Implementar funcionalidad

def datos_recojo():
    st.title("Datos de Recojo")
    # Implementar funcionalidad

def datos_boletas():
    st.title("Datos de Boletas")
    # Implementar funcionalidad

def ver_ruta_optimizada():
    st.title("Ver Ruta Optimizada")
    # Implementar funcionalidad

def seguimiento_vehiculo():
    st.title("Seguimiento al Vehículo")
    # Implementar funcionalidad (opcional)

# Navegación de la aplicación
if 'user' not in st.session_state:
    login()
else:
    menu = ["Home", "Ingresar Boleta", "Ingresar Sucursal", "Solicitar Recogida", "Datos de Recojo", "Datos de Boletas", "Ver Ruta Optimizada", "Seguimiento al Vehículo"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Home":
        home()
    elif choice == "Ingresar Boleta":
        ingresar_boleta()
    elif choice == "Ingresar Sucursal":
        ingresar_sucursal()
    elif choice == "Solicitar Recogida":
        solicitar_recogida()
    elif choice == "Datos de Recojo":
        datos_recojo()
    elif choice == "Datos de Boletas":
        datos_boletas()
 
