# Aquí irán las funciones de login, logout y gestión de sesión

import streamlit as st

# Páginas de la aplicación
def login():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
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

# Función de cierre de sesión
def logout():
    st.session_state['logged_in'] = False
    st.session_state['usuario_actual'] = None
    st.session_state['menu'] = []
    st.rerun()
