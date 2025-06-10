# Lógica para ingreso y visualización de boletas

import streamlit as st
import re
from datetime import datetime
from core.firebase import obtener_articulos, obtener_sucursales, verificar_unicidad_boleta, db
import pandas as pd
from io import BytesIO

def ingresar_boleta():
    # Inicialización de claves en session_state
    if "numero_boleta" not in st.session_state:
        st.session_state.numero_boleta = ""
    if "nombre_cliente" not in st.session_state:
        st.session_state.nombre_cliente = ""
    if "dni" not in st.session_state:
        st.session_state.dni = ""
    if "telefono" not in st.session_state:
        st.session_state.telefono = ""
    if "monto" not in st.session_state:
        st.session_state.monto = 0.0
    if "fecha_registro" not in st.session_state:
        st.session_state.fecha_registro = datetime.now()
    if "sucursal" not in st.session_state:
        st.session_state.sucursal = None
    if "articulo_seleccionado" not in st.session_state:
        st.session_state.articulo_seleccionado = ""
    if "tipo_servicio" not in st.session_state:
        st.session_state.tipo_servicio = "🏢 Sucursal"
    if "cantidades" not in st.session_state:
        st.session_state['cantidades'] = {}

    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Boleta")
  
    # Obtener datos necesarios
    articulos = obtener_articulos()
    sucursales = obtener_sucursales()

    # Campos de entrada principales
    numero_boleta = st.text_input("Número de Boleta", max_chars=5, key="numero_boleta")
    nombre_cliente = st.text_input("Nombre del Cliente", key="nombre_cliente")
    
    col1, col2 = st.columns(2)
    with col1:
        dni = st.text_input("Número de DNI (Opcional)", max_chars=8, key="dni")
    with col2:
        telefono = st.text_input("Teléfono (Opcional)", max_chars=9, key="telefono")

    monto = st.number_input("Monto a Pagar", min_value=0.0, format="%.2f", step=0.01, key="monto")

    nombres_sucursales = [sucursal['nombre'] for sucursal in sucursales]

    tipo_servicio = st.radio("Tipo de Servicio", ["🏢 Sucursal", "🚚 Delivery"], horizontal=True, key="tipo_servicio")
    if "Sucursal" in tipo_servicio:
        sucursal = st.selectbox("Sucursal", nombres_sucursales, key="sucursal")
    else:
        sucursal = None

    # Sección de artículos
    st.markdown("<h3 style='margin-bottom: 10px;'>Seleccionar Artículos Lavados</h3>", unsafe_allow_html=True)
    articulo_seleccionado = st.selectbox("Agregar Artículo", [""] + articulos, index=0, key="articulo_seleccionado")

    if articulo_seleccionado and articulo_seleccionado not in st.session_state['cantidades']:
        st.session_state['cantidades'][articulo_seleccionado] = 1

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
                    st.session_state['update'] = True

        if articulos_a_eliminar:
            for articulo in articulos_a_eliminar:
                del st.session_state['cantidades'][articulo]
            st.rerun()

    if 'update' in st.session_state and st.session_state['update']:
        st.session_state['update'] = False

    fecha_registro = st.date_input("Fecha de Registro (AAAA/MM/DD)", value=datetime.now(), key="fecha_registro")

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
            if monto <= 0:
                st.error("El monto a pagar debe ser mayor a 0.")
                return
            if not st.session_state['cantidades']:
                st.error("Debe seleccionar al menos un artículo antes de ingresar la boleta.")
                return
            if not verificar_unicidad_boleta(numero_boleta, tipo_servicio, sucursal):
                st.error("Ya existe una boleta con este número en la misma sucursal o tipo de servicio.")
                return

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

            # Limpiar todos los campos
            st.session_state['cantidades'] = {}
            st.session_state.numero_boleta = ""
            st.session_state.nombre_cliente = ""
            st.session_state.dni = ""
            st.session_state.telefono = ""
            st.session_state.monto = 0.0
            st.session_state.fecha_registro = datetime.now()
            st.session_state.articulo_seleccionado = ""
            st.session_state.sucursal = None
            st.session_state.tipo_servicio = "🏢 Sucursal"

            st.rerun()



def datos_boletas():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Datos de Boletas")

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

    # Filtro de fechas
    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha de Inicio")
    with col2:
        fecha_fin = st.date_input("Fecha de Fin")

    # Consulta optimizada a Firebase
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

    # Procesar datos
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

    # Mostrar resultados
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

  
