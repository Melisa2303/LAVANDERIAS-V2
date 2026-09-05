import streamlit as st
import re
import folium
from streamlit_folium import st_folium
from core.firebase import db
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas

def ingresar_sucursal():
    # Inicializar claves del session_state si no existen
    st.session_state.setdefault("ingresar_sucursal_lat", -16.409047)
    st.session_state.setdefault("ingresar_sucursal_lon", -71.537451)
    st.session_state.setdefault("ingresar_sucursal_direccion", "Arequipa, Perú")
    st.session_state.setdefault("nombre_sucursal", "")
    st.session_state.setdefault("encargado", "")
    st.session_state.setdefault("telefono", "")

    # Encabezado
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📝 Ingresar Sucursal")

    # Campos del formulario
    nombre_sucursal = st.text_input("Nombre de la Sucursal", value=st.session_state.get("nombre_sucursal", ""))
    direccion_input = st.text_input("Dirección", value=st.session_state.get("ingresar_sucursal_direccion", "Arequipa, Perú"), key="ingresar_sucursal_direccion_input")

    # Buscar sugerencias si la dirección cambió
    sugerencias = []
    if direccion_input and direccion_input != st.session_state["ingresar_sucursal_direccion"]:
        sugerencias = obtener_sugerencias_direccion(direccion_input)
    
    direccion_seleccionada = st.selectbox(
        "Sugerencias de Direcciones:",
        ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias] if sugerencias else ["No hay sugerencias"],
        key="ingresar_sucursal_sugerencias"
    )

    # Actualizar coordenadas si se elige sugerencia
    if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
        for sug in sugerencias:
            if direccion_seleccionada == sug["display_name"]:
                st.session_state["ingresar_sucursal_lat"] = float(sug["lat"])
                st.session_state["ingresar_sucursal_lon"] = float(sug["lon"])
                st.session_state["ingresar_sucursal_direccion"] = direccion_seleccionada
                break

    # Crear mapa con coordenadas actuales
    mapa = folium.Map(
        location=[st.session_state["ingresar_sucursal_lat"], st.session_state["ingresar_sucursal_lon"]],
        zoom_start=15
    )
    folium.Marker(
        [st.session_state["ingresar_sucursal_lat"], st.session_state["ingresar_sucursal_lon"]],
        tooltip="Punto seleccionado"
    ).add_to(mapa)

    mapa_result = st_folium(
        mapa,
        width=700,
        height=500,
        key="mapa_principal"
    )

    # Si se hace clic en el mapa, actualizar coordenadas y dirección
    if mapa_result and mapa_result.get("last_clicked"):
        last_click = mapa_result["last_clicked"]
        if last_click and "lat" in last_click and "lng" in last_click:
            st.session_state["ingresar_sucursal_lat"] = last_click["lat"]
            st.session_state["ingresar_sucursal_lon"] = last_click["lng"]
            st.session_state["ingresar_sucursal_direccion"] = obtener_direccion_desde_coordenadas(
                st.session_state["ingresar_sucursal_lat"],
                st.session_state["ingresar_sucursal_lon"]
            )

    # Mostrar dirección final elegida
    st.markdown(f"""
        <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
            <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
            <p style='color: #555; font-size: 16px;'>{st.session_state["ingresar_sucursal_direccion"]}</p>
        </div>
    """, unsafe_allow_html=True)

    # Otros campos
    col1, col2 = st.columns(2)
    with col1:
        encargado = st.text_input("Encargado (Opcional)", value=st.session_state.get("encargado", ""))
    with col2:
        telefono = st.text_input("Teléfono (Opcional)", value=st.session_state.get("telefono", ""), max_chars=9)

    if st.button("💾 Ingresar Sucursal"):
        if not nombre_sucursal:
            st.error("El nombre de la sucursal es obligatorio.")
            return
        if telefono and not re.match(r"^\d{9}$", telefono):
            st.error("El teléfono debe tener 9 dígitos.")
            return

        try:
            db.collection("sucursales").add({
                "nombre": nombre_sucursal,
                "direccion": st.session_state["ingresar_sucursal_direccion"],
                "coordenadas": {
                    "lat": st.session_state["ingresar_sucursal_lat"],
                    "lon": st.session_state["ingresar_sucursal_lon"]
                },
                "encargado": encargado if encargado else None,
                "telefono": telefono if telefono else None,
            })

            st.success("✅ Sucursal registrada correctamente")

            # Resetear campos visibles
            st.session_state.update({
                "nombre_sucursal": "",
                "encargado": "",
                "telefono": "",
                "ingresar_sucursal_direccion": "Arequipa, Perú",
                "ingresar_sucursal_lat": -16.409047,
                "ingresar_sucursal_lon": -71.537451
            })

        except Exception as e:
            st.error(f"Error al guardar: {e}") 

