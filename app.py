import streamlit as st
from core.auth import login, logout
              
# Inicializar 'logged_in.', 'usuario_actual' y 'menu' en session_state
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

    if choice == "Ingresar Boleta":
        from features.boletas import ingresar_boleta
        ingresar_boleta()
    elif choice == "Ingresar Sucursal":
        from features.sucursales import ingresar_sucursal
        ingresar_sucursal()
    elif choice == "Solicitar Recogida":
        from features.recogidas import solicitar_recogida
        solicitar_recogida()
    elif choice == "Datos de Ruta":
        from features.datosRuta import datos_ruta
        datos_ruta()
    elif choice == "Datos de Boletas":
        from features.boletas import datos_boletas
        datos_boletas()
    elif choice == "Ver Ruta Optimizada":
        from features.rutas3 import ver_ruta_optimizada
        ver_ruta_optimizada()
    elif choice == "Seguimiento al Vehículo":
        from features.tracking import seguimiento_vehiculo
        seguimiento_vehiculo()
