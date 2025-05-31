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
from datetime import datetime, timedelta, time
import time as tiempo
from algorithms.algoritmo1 import optimizar_ruta_algoritmo1, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix
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

# ============ PÁGINA “Ver Ruta Optimizada” ============

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1,c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        tipo  = st.radio("Tipo Servicio", ["Todos","Sucursal","Delivery"], horizontal=True)

    # Variables de estado (persisten entre clicks)
    if "res" not in st.session_state:
        st.session_state["res"] = None
    if "df_ruta" not in st.session_state:
        st.session_state["df_ruta"] = None
    if "df_completo" not in st.session_state:
        st.session_state["df_completo"] = None
    if "ruta_guardada" not in st.session_state:
        st.session_state["ruta_guardada"] = False
    if "leg_0" not in st.session_state:
        st.session_state["leg_0"] = 0

    # Solo calcula si aún no hay resultado
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, tipo)
        if not pedidos:
            st.info("No hay pedidos para esa fecha/tipo.")
            return

        #Lo que es equivalente a lo de puntos fijos que se planetearon, aquí sólo se considera la planta Aka. Depósito
        DF = pd.DataFrame(pedidos)
        DEP = {
            "id":"DEP",
            "operacion":"Depósito",
            "nombre_cliente":"Depósito",
            "lat":-16.40904,
            "lon":-71.53745,
            "time_start":"08:00",
            "time_end":"18:00",
            "demand":0
        }
        df = pd.concat([pd.DataFrame([DEP]), DF], ignore_index=True)
        st.session_state["df_completo"] = df

        data = _crear_data_model(df, vehiculos=1, capacidad_veh=None)
        t0 = tiempo.time()
        res = optimizar_ruta_algoritmo1(data, tiempo_max_seg=120)
        solve_t = tiempo.time()-t0
        if not res:
            st.error("😕 Sin solución factible.")
            return

        st.session_state["res"] = res
        st.metric("⏱️ Tiempo de cómputo", f"{solve_t:.2f} s")
        st.metric("📏 Distancia total (km)", f"{res['distance_total_m']/1000:.2f}")

        route = res["routes"][0]["route"]
        arr   = res["routes"][0]["arrival_sec"]

        df_r = df.loc[route,["nombre_cliente","time_start","time_end"]].copy()
        df_r["ETA"]   = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(route))
        st.session_state["df_ruta"] = df_r

        if not st.session_state["ruta_guardada"]:
            doc = {
                "fecha": fecha.strftime("%Y-%m-%d"),
                "tipo_servicio": tipo,
                "creado_en": firestore.SERVER_TIMESTAMP,
                "vehiculos": 1,
                "distancia_total_m": res["distance_total_m"],
                "paradas":[]
            }
            for idx,n in enumerate(route):
                doc["paradas"].append({
                    "orden": idx,
                    "pedidoId": df.loc[n,"id"],
                    "nombre": df.loc[n,"nombre_cliente"],
                    "lat": df.loc[n,"lat"],
                    "lon": df.loc[n,"lon"],
                    "ETA": datetime.utcfromtimestamp(arr[idx]).strftime("%H:%M")
                })
            db.collection("rutas").add(doc)
            st.session_state["ruta_guardada"] = True

    # Mostrar tabla
    df_r = st.session_state["df_ruta"]
    df   = st.session_state["df_completo"]
    res  = st.session_state["res"]
    route = res["routes"][0]["route"]

    st.dataframe(df_r[["orden","ETA","nombre_cliente","time_start","time_end"]], use_container_width=True)

    # Botón reinicio
    if st.button("🔄 Reiniciar Tramos"): #Bueno, una vez que se terminaron de pasar los "Ya llegué a..., se reinicia el tramo"
        st.session_state["leg_0"] = 0

    leg = st.session_state["leg_0"]
    if leg >= len(route)-1:
        st.success("✅ Todas las paradas completadas") 
        return

    o,d = route[leg], route[leg+1]
    name = df.loc[d,"nombre_cliente"]
    ETA  = df_r.loc[df_r["orden"]==leg+1,"ETA"].values[0]
    st.markdown(f"### Próximo → **{name}** (ETA {ETA})")
    if st.button(f"Ya llegué a {name}"):
        st.session_state["leg_0"] += 1
        st.rerun()

    # Mapa tramo actual
    coords = [(df.loc[i,"lat"],df.loc[i,"lon"]) for i in route]
    orig = f"{coords[leg][0]},{coords[leg][1]}"
    dest = f"{coords[leg+1][0]},{coords[leg+1][1]}"
    try:
        dirs = gmaps.directions(
            orig, dest,
            mode="driving",
            departure_time=datetime.now(),
            traffic_model="best_guess"
        )
        leg0 = dirs[0]["legs"][0]
        tt   = leg0.get("duration_in_traffic",leg0["duration"])["text"]
        ov   = dirs[0]["overview_polyline"]["points"]
        seg  = [(p["lat"],p["lng"]) for p in decode_polyline(ov)]
    except:
        tt  = None
        seg = [coords[leg],coords[leg+1]]

    t1,t2 = st.tabs(["🗺 Tramo","ℹ️ Info"])
    with t1:
        m = folium.Map(location=seg[0],zoom_start=14)
        folium.PolyLine(seg,color="blue",weight=5,opacity=0.8,
                        tooltip=f"⏱ {tt}" if tt else None).add_to(m)
        folium.Marker(seg[0],popup="Origen",
                      icon=folium.Icon(color="green",icon="play",prefix="fa")).add_to(m)
        folium.Marker(seg[-1],popup=name,
                      icon=folium.Icon(color="blue",icon="map-marker",prefix="fa")).add_to(m)
        st_folium(m,width=700,height=400)
    with t2:
        st.write(f"**Tiempo estimado (tráfico):** {tt or '--'}")
        
