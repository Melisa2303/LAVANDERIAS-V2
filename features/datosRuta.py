import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import time
import folium
from streamlit_folium import st_folium
import googlemaps

from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

@st.cache_data(ttl=300)
def cargar_ruta(fecha):
    docs = []
    col = db.collection('recogidas')
    fecha_str = fecha.strftime("%Y-%m-%d")
    docs += col.where("fecha_recojo", "==", fecha_str).stream()
    docs += col.where("fecha_entrega", "==", fecha_str).stream()
    datos = []
    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        datos.append(d)
    return datos

def datos_ruta():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Ruta del Día")

    fecha_seleccionada = st.date_input("Seleccionar Fecha", value=datetime.now().date())
    datos = cargar_ruta(fecha_seleccionada)

    if datos:
        tabla_data = []
        for item in datos:
            nombre_mostrar = item["nombre_cliente"] if item["tipo_solicitud"] == "Cliente Delivery" else item["sucursal"]
            tabla_data.append({
                "Operación": item["operacion"],
                "Cliente/Sucursal": nombre_mostrar or "N/A",
                "Dirección": item["direccion"],
                "Teléfono": item["telefono"],
                "Hora": item["hora"] if item["hora"] else "Sin hora",
            })

        df_tabla = pd.DataFrame(tabla_data)
        st.dataframe(df_tabla, height=600, use_container_width=True, hide_index=True)

        deliveries = [item for item in datos if item["tipo_solicitud"] == "Cliente Delivery"]

        if deliveries:
            st.markdown("---")
            st.subheader("🔄 Gestión de Deliveries")

            opciones = {f"{item['operacion']} - {item['nombre_cliente']}": item for item in deliveries}
            selected = st.selectbox("Seleccionar operación:", options=opciones.keys())
            delivery_data = opciones[selected]

            st.markdown(f"### Rango de Horario para {delivery_data['operacion']}")
            horas_sugeridas = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 30)]
            rango_actual = delivery_data.get("hora", "12:00 - 13:00")
            hora_inicio_default, hora_fin_default = "9:00", "16:00"
            if " - " in rango_actual:
                partes = rango_actual.split(" - ")
                if len(partes) == 2:
                    hora_inicio_default, hora_fin_default = partes

            col_ini, col_fin, col_btn = st.columns([2, 2, 1])
            with col_ini:
                hora_inicio = st.selectbox("Hora de inicio:", horas_sugeridas,
                                           index=horas_sugeridas.index(hora_inicio_default)
                                           if hora_inicio_default in horas_sugeridas else 0,
                                           key=f"hora_inicio_{delivery_data['id']}")
            with col_fin:
                hora_fin = st.selectbox("Hora de fin:", horas_sugeridas,
                                        index=horas_sugeridas.index(hora_fin_default)
                                        if hora_fin_default in horas_sugeridas else 0,
                                        key=f"hora_fin_{delivery_data['id']}")
            with col_btn:
                st.write("")
                st.write("")
                if st.button("💾 Guardar", key=f"guardar_btn_{delivery_data['id']}"):
                    try:
                        h_ini = list(map(int, hora_inicio.split(":")))
                        h_fin = list(map(int, hora_fin.split(":")))
                        if h_ini >= h_fin:
                            st.error("❌ La hora de fin debe ser mayor que la de inicio.")
                        else:
                            rango_hora = f"{hora_inicio} - {hora_fin}"
                            campo_hora = "hora_recojo" if delivery_data["operacion"] == "Recojo" else "hora_entrega"
                            db.collection('recogidas').document(delivery_data["id"]).update({campo_hora: rango_hora})
                            with st.toast("✅ Rango actualizado correctamente", icon="🕒"):
                                st.cache_data.clear()
                    except Exception as e:
                        st.error(f"⚠️ Error al guardar: {e}")

            st.markdown(f"### 📅 Reprogramación de {delivery_data['operacion']}")
            with st.expander("Cambiar fecha y ubicación", expanded=True):
                if "reprogramar_lat" not in st.session_state:
                    st.session_state.reprogramar_lat = delivery_data["coordenadas"]["lat"]
                    st.session_state.reprogramar_lon = delivery_data["coordenadas"]["lon"]
                    st.session_state.reprogramar_direccion = delivery_data["direccion"]
                    st.session_state.reprogramar_mapa = folium.Map(
                        location=[st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        zoom_start=15
                    )
                    folium.Marker(
                        [st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                        tooltip="Punto seleccionado"
                    ).add_to(st.session_state.reprogramar_mapa)

                direccion_input = st.text_input("Dirección", value=st.session_state.reprogramar_direccion,
                                                key=f"reprogramar_direccion_input_{delivery_data['id']}")
                sugerencias = obtener_sugerencias_direccion(direccion_input) if direccion_input and direccion_input != st.session_state.reprogramar_direccion else []
                direccion_seleccionada = st.selectbox("Sugerencias de Direcciones:",
                                                      ["Seleccione una dirección"] + [sug["display_name"] for sug in sugerencias]
                                                      if sugerencias else ["No hay sugerencias"],
                                                      key=f"reprogramar_sugerencias_{delivery_data['id']}")

                if direccion_seleccionada and direccion_seleccionada != "Seleccione una dirección":
                    for sug in sugerencias:
                        if direccion_seleccionada == sug["display_name"]:
                            st.session_state.reprogramar_lat = float(sug["lat"])
                            st.session_state.reprogramar_lon = float(sug["lon"])
                            st.session_state.reprogramar_direccion = direccion_seleccionada
                            st.session_state.reprogramar_mapa = folium.Map(
                                location=[st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                                zoom_start=15
                            )
                            folium.Marker([st.session_state.reprogramar_lat, st.session_state.reprogramar_lon],
                                          tooltip="Punto seleccionado").add_to(st.session_state.reprogramar_mapa)
                            break

                mapa = st_folium(st.session_state.reprogramar_mapa, width=700, height=500,
                                 key=f"reprogramar_mapa_{delivery_data['id']}")
                if mapa.get("last_clicked"):
                    st.session_state.reprogramar_lat = mapa["last_clicked"]["lat"]
                    st.session_state.reprogramar_lon = mapa["last_clicked"]["lng"]
                    st.session_state.reprogramar_direccion = obtener_direccion_desde_coordenadas(
                        st.session_state.reprogramar_lat, st.session_state.reprogramar_lon)
                    st.rerun()

                st.markdown(f"""
                    <div style='background-color: #f0f8ff; padding: 10px; border-radius: 5px; margin-top: 10px;'>
                        <h4 style='color: #333; margin: 0;'>Dirección Final:</h4>
                        <p style='color: #555; font-size: 16px;'>{st.session_state.reprogramar_direccion}</p>
                    </div>
                """, unsafe_allow_html=True)

                min_date = datetime.now().date() if delivery_data["operacion"] == "Recojo" else datetime.strptime(delivery_data["fecha"], "%Y-%m-%d").date()
                nueva_fecha = st.date_input("Nueva fecha:", value=min_date + timedelta(days=1), min_value=min_date)

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
