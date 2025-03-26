import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import googlemaps

# Configurar Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Configurar Google Maps API
gmaps = googlemaps.Client(key='YOUR_GOOGLE_MAPS_API_KEY')

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
    elif choice == "Ver Ruta Optimizada":
        ver_ruta_optimizada()
    elif choice == "Seguimiento al Vehículo":
        seguimiento_vehiculo()
