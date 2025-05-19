import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
import requests  # Importar requests
from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
from algorithms.algoritmo1 import optimizar_ruta_algoritmo1
from algorithms.algoritmo2 import optimizar_ruta_algoritmo2
from algorithms.algoritmo3 import optimizar_ruta_algoritmo3
from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

@st.cache_data(ttl=300)
def cargar_ruta(fecha, tipo):
    # Carga las rutas de recogida y entrega desde la base de datos para una fecha y tipo de servicio específicos.
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

def datos_ruta():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image("https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG", width=100)
    with col2:
        st.markdown("<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>", unsafe_allow_html=True)
    st.title("📋 Ruta del Día")

    # Filtros
    col1, col2 = st.columns(2)
    with col1:
        fecha_seleccionada = st.date_input("Seleccionar Fecha", value=datetime.now().date())
    with col2:
        tipo_servicio = st.radio("Tipo de Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)
        
    # Obtener datos
    datos = cargar_ruta(fecha_seleccionada, tipo_servicio)

    # Mostrar Tabla
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

        # Gestión de Deliveries
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

            # Sección de Dirección y Mapa (Versión idéntica a Solicitar Recogida)
          
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

        # Botón de Descarga
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

# Función para mostrar ruta en mapa (completa con puntos fijos)
def mostrar_ruta_en_mapa(ruta_completa):
    """
    Muestra la ruta optimizada en un mapa interactivo considerando calles y puntos fijos.
    """
    try:
        # Validar que haya suficientes puntos en la ruta
        if len(ruta_completa) < 2:
            st.warning("Se necesitan al menos 2 puntos para mostrar la ruta")
            return None

        # Preparar los puntos para la solicitud a Google Maps Directions API
        waypoints = "|".join([f"{p['lat']},{p['lon']}" for p in ruta_completa[1:-1]])
        origin = f"{ruta_completa[0]['lat']},{ruta_completa[0]['lon']}"
        destination = f"{ruta_completa[-1]['lat']},{ruta_completa[-1]['lon']}"

        # Hacer la solicitud a la API de Google Maps Directions
        url = (
            f"https://maps.googleapis.com/maps/api/directions/json?"
            f"origin={origin}&destination={destination}"
            f"&waypoints={waypoints}&key={GOOGLE_MAPS_API_KEY}&mode=driving"
        )
        response = requests.get(url)
        data = response.json()

        if data.get("status") != "OK":
            st.error(f"Error al obtener la ruta: {data.get('error_message', 'Desconocido')}")
            return None

        # Decodificar la polilínea de la ruta
        polyline_points = decode_polyline(data["routes"][0]["overview_polyline"]["points"])
        route_coords = [(p["lat"], p["lng"]) for p in polyline_points]

        # Crear el mapa centrado en el primer punto
        m = folium.Map(location=[ruta_completa[0]['lat'], ruta_completa[0]['lon']], zoom_start=13)

        # Dibujar la ruta en el mapa
        folium.PolyLine(
            route_coords,
            color="#0066cc",
            weight=6,
            opacity=0.8,
            tooltip="Ruta optimizada completa"
        ).add_to(m)

        # Añadir marcadores para todos los puntos
        for i, punto in enumerate(ruta_completa):
            if i == 0:
                icon = folium.Icon(color='red', icon='flag', prefix='fa')  # Inicio
            elif i == len(ruta_completa) - 1:
                icon = folium.Icon(color='black', icon='flag-checkered', prefix='fa')  # Fin
            elif punto.get('tipo') == 'fijo':
                icon = folium.Icon(color='green', icon='building', prefix='fa')  # Puntos fijos
            else:
                icon = folium.Icon(color='blue', icon='map-pin', prefix='fa')  # Intermedios

            # Agregar marcador al mapa
            folium.Marker(
                location=[punto['lat'], punto['lon']],
                popup=folium.Popup(
                    f"{punto.get('direccion', 'Sin dirección')}<br>Hora: {punto.get('hora', 'N/A')}",
                    max_width=300
                ),
                icon=icon
            ).add_to(m)

        # Mostrar el mapa en Streamlit
        st_folium(m, width=700, height=500)

    except Exception as e:
        st.error(f"Error al generar el mapa: {e}")

def mostrar_metricas(ruta, time_matrix):
    """Métricas mejoradas con validación de restricciones"""
    if len(ruta) <= 1:
        st.warning("No hay suficientes puntos para calcular métricas")
        return
    
    # Calcular métricas basadas en la matriz de tiempos real
    tiempo_total = 0
    tiempo_con_restricciones = 0
    puntos_con_restriccion = 0
    
    for i in range(len(ruta)-1):
        tiempo_segmento = time_matrix[i][i+1]
        tiempo_total += tiempo_segmento
        
        if ruta[i].get('hora'):
            puntos_con_restriccion += 1
            tiempo_con_restricciones += tiempo_segmento
    
    # Convertir a horas/minutos
    horas_total = int(tiempo_total // 3600)
    minutos_total = int((tiempo_total % 3600) // 60)
    
    # Eficiencia
    eficiencia = (tiempo_con_restricciones / tiempo_total) * 100 if tiempo_total > 0 else 0
    
    # Mostrar en columnas con formato mejorado
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("📌 Total de paradas", len(ruta))
    col2.metric("⏱️ Tiempo total", f"{horas_total}h {minutos_total}m")
    col3.metric("⏳ Puntos con restricción", f"{puntos_con_restriccion}/{len(ruta)}")
    col4.metric("📊 Eficiencia", f"{eficiencia:.1f}%")
    
    # Gráfico de tiempo por segmento
    segmentos = [f"{i+1}-{i+2}" for i in range(len(ruta)-1)]
    tiempos = [time_matrix[i][i+1]/60 for i in range(len(ruta)-1)]  # En minutos
    
    df_tiempos = pd.DataFrame({
        'Segmento': segmentos,
        'Tiempo (min)': tiempos
    })
    
    st.bar_chart(df_tiempos.set_index('Segmento'))
    
    # Detalle de restricciones
    with st.expander("🔍 Ver detalles de restricciones"):
        for i, punto in enumerate(ruta):
            if punto.get('hora'):
                st.write(f"📍 **Punto {i+1}**: {punto.get('nombre', '')}")
                st.write(f"   - Hora requerida: {punto['hora']}")
                st.write(f"   - Dirección: {punto.get('direccion', '')}")
      
def ver_ruta_optimizada():
    st.title("🚚 Ruta Optimizada")
    col1, col2, col3 = st.columns(3)
    with col1:
        fecha_seleccionada = st.date_input("Seleccionar Fecha", value=datetime.now().date())
    with col2:
        tipo_servicio = st.radio("Tipo de Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)
    with col3:
        algoritmo = st.selectbox("Algoritmo", ["Algoritmo 1", "Algoritmo 2", "Algoritmo 3", "Algoritmo 4"])

    datos = cargar_ruta(fecha_seleccionada, tipo_servicio)

    if datos:
        # Validar puntos con coordenadas
        puntos_validos = []
        for item in datos:
            coords = item.get("coordenadas")
            try:
                if isinstance(coords, dict) and "lat" in coords and "lon" in coords:
                    lat = float(coords["lat"])
                    lon = float(coords["lon"])
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        puntos_validos.append(item)
                    else:
                        st.warning(f"Punto descartado (coordenadas fuera de rango): {item.get('direccion', 'N/A')}")
                else:
                    st.warning(f"Punto descartado (coordenadas inválidas): {item.get('direccion', 'N/A')}")
            except (ValueError, TypeError) as e:
                st.warning(f"Punto descartado (error en coordenadas): {item.get('direccion', 'N/A')} - Error: {e}")

        puntos_con_hora = [item for item in puntos_validos if item.get("hora")]

        if not puntos_validos:
            st.error("No hay puntos válidos con coordenadas correctas para optimizar.")
            return

        # Ejecutar Algoritmo Seleccionado
        try:
            if algoritmo == "Algoritmo 1":
                puntos_optimizados = optimizar_ruta_algoritmo1(
                    puntos_validos,
                    puntos_con_hora,
                    considerar_trafico=True
                )
            elif algoritmo == "Algoritmo 2":
                puntos_optimizados = optimizar_ruta_algoritmo2(
                    puntos_validos,
                    puntos_con_hora,
                    considerar_trafico=True
                )
            elif algoritmo == "Algoritmo 3":
                puntos_optimizados = optimizar_ruta_algoritmo3(
                    puntos_validos,
                    puntos_con_hora,
                    considerar_trafico=True
                )
            else:
                puntos_optimizados = optimizar_ruta_algoritmo4(
                    puntos_validos,
                    puntos_con_hora,
                    considerar_trafico=True
                )
                
        except Exception as e:
            st.error(f"Error al optimizar la ruta con {algoritmo}: {e}")
            puntos_optimizados = puntos_validos  # Usar orden original como respaldo

        # Mostrar Tabla de Puntos Optimizada
        tabla_data = []
        for idx, item in enumerate(puntos_optimizados):
            # Validar la presencia de 'tipo_solicitud' y usar un valor predeterminado si falta
            tipo_solicitud = item.get("tipo_solicitud", "N/A")
            nombre_mostrar = (
                item["nombre_cliente"]
                if tipo_solicitud == "Cliente Delivery"
                else item.get("sucursal", "Sin Nombre")
            )
            tabla_data.append({
                "Orden": idx + 1,
                "Operación": item.get("operacion", "N/A"),
                "Cliente/Sucursal": nombre_mostrar,
                "Dirección": item.get("direccion", "N/A"),
                "Teléfono": item.get("telefono", "N/A"),
                "Hora": item.get("hora", "Sin hora"),
            })

        df_tabla = pd.DataFrame(tabla_data)
        st.dataframe(df_tabla, height=600, use_container_width=True, hide_index=True)

        # Botón de Descarga
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df_tabla.to_excel(writer, index=False)

        # Mostrar botón justo después de la tabla
        st.download_button(
            label="Descargar Excel",
            data=excel_buffer.getvalue(),
            file_name=f"ruta_optimizada_{fecha_seleccionada.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Mapa de Ruta Optimizada
        mostrar_ruta_en_mapa(puntos_optimizados)

    else:
        st.info("No hay datos para la fecha seleccionada con los filtros actuales.")
