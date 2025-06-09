import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from core.firebase import db
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS
import requests  # Importar requests
from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
from datetime import datetime, timedelta, time
import time as tiempo
import googlemaps
from core.firebase import db, obtener_sucursales
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas
from algorithms.algoritmo1 import optimizar_ruta_algoritmo1, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix
from algorithms.algoritmo2 import optimizar_ruta_algoritmo2, cargar_pedidos, _crear_data_model, _distancia_duracion_matrix, agrupar_puntos_aglomerativo
from algorithms.algoritmo3 import optimizar_ruta_algoritmo3
from algorithms.algoritmo4 import optimizar_ruta_algoritmo4

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

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

# ===================== PÁGINA “Ver Ruta Optimizada” =====================

def ver_ruta_optimizada():
    st.title("🚚 Ver Ruta Optimizada")
    c1, c2 = st.columns(2)
    with c1:
        fecha = st.date_input("Fecha", value=datetime.now().date())
    with c2:
        tipo  = st.radio("Tipo Servicio", ["Todos", "Sucursal", "Delivery"], horizontal=True)

    # Estado persistente
    if "res" not in st.session_state:
        st.session_state["res"] = None
    if "df_clusters" not in st.session_state:
        st.session_state["df_clusters"] = None
    if "df_etiquetado" not in st.session_state:
        st.session_state["df_etiquetado"] = None
    if "df_final" not in st.session_state:
        st.session_state["df_final"] = None
    if "ruta_guardada" not in st.session_state:
        st.session_state["ruta_guardada"] = False
    if "leg_0" not in st.session_state:
        st.session_state["leg_0"] = 0

    # Si aún no se resolvió para esta fecha/tipo, calculo todo
    if st.session_state["res"] is None:
        pedidos = cargar_pedidos(fecha, tipo)
        if not pedidos:
            st.info("No hay pedidos para esa fecha/tipo.")
            return

        # 1) DataFrame original con todos los pedidos (incluye 'direccion')
        df_original = pd.DataFrame(pedidos)

        # 2) Agrupo con AgglomerativeClustering (umbral 300 m)
        df_clusters, df_etiquetado = agrupar_puntos_aglomerativo(df_original, eps_metros=300)
        st.session_state["df_clusters"]  = df_clusters.copy()
        st.session_state["df_etiquetado"] = df_etiquetado.copy()

        # 3) Construyo DataFrame final que voy a pasar al solver (DEPÓSITO + centroides)
        DEP = {
            "id":             "DEP",
            "operacion":      "Depósito",
            "nombre_cliente": "Depósito",
            "direccion":      "Planta Lavandería",
            "lat":            -16.40904,
            "lon":            -71.53745,
            "time_start":     "08:00",
            "time_end":       "18:00",
            "demand":         0
        }
        df_final = pd.concat([pd.DataFrame([DEP]), df_clusters], ignore_index=True)
        st.session_state["df_final"] = df_final.copy()

        # 4) Crear modelo de datos para VRPTW
        data = _crear_data_model(df_final, vehiculos=1, capacidad_veh=None)

        # 5) Resolver VRPTW
        t0 = tiempo.time()
        res = optimizar_ruta_algoritmo2(data, tiempo_max_seg=120)
        solve_t = tiempo.time() - t0
        if not res:
            st.error("😕 Sin solución factible. Usando aproximación euclidiana.")
            return

        st.session_state["res"] = res
        st.metric("⏱️ Tiempo de cómputo", f"{solve_t:.2f} s")
        st.metric("📏 Distancia total (km)", f"{res['distance_total_m'] / 1000:.2f}")

        # 6) Construir tabla de ruta optimizada incluyendo “direccion”
        ruta = res["routes"][0]["route"]
        arr   = res["routes"][0]["arrival_sec"]

        df_r = df_final.loc[ruta, ["nombre_cliente", "direccion", "time_start", "time_end"]].copy()
        df_r["ETA"]   = [datetime.utcfromtimestamp(t).strftime("%H:%M") for t in arr]
        df_r["orden"] = range(len(ruta))
        st.session_state["df_ruta"] = df_r.copy()

        # 7) Guardar ruta en Firestore (solo una vez)
        if not st.session_state["ruta_guardada"]:
            doc = {
                "fecha": fecha.strftime("%Y-%m-%d"),
                "tipo_servicio": tipo,
                "creado_en": firestore.SERVER_TIMESTAMP,
                "vehiculos": 1,
                "distancia_total_m": res["distance_total_m"],
                "paradas": []
            }
            for idx, n in enumerate(ruta):
                doc["paradas"].append({
                    "orden":    idx,
                    "pedidoId": df_final.loc[n, "id"],
                    "nombre":   df_final.loc[n, "nombre_cliente"],
                    "direccion": df_final.loc[n, "direccion"],
                    "lat":      df_final.loc[n, "lat"],
                    "lon":      df_final.loc[n, "lon"],
                    "ETA":      datetime.utcfromtimestamp(arr[idx]).strftime("%H:%M")
                })
            db.collection("rutas").add(doc)
            st.session_state["ruta_guardada"] = True

    # -------------------- MOSTRAR RESULTADOS --------------------

    df_r   = st.session_state["df_ruta"]
    df_f   = st.session_state["df_final"]      # depósito + centroides
    df_cl  = st.session_state["df_clusters"]   # sólo centroides
    df_et  = st.session_state["df_etiquetado"] # pedidos individuales (con columna 'cluster')
    res    = st.session_state["res"]
    ruta   = res["routes"][0]["route"]

    # 1) Mostrar la tabla con orden de visitas, incluyendo “direccion”
    st.subheader("📋 Orden de visita optimizada")
    st.dataframe(
        df_r[["orden", "ETA", "nombre_cliente", "direccion", "time_start", "time_end"]],
        use_container_width=True
    )

    # 2) Botón para reiniciar tramos
    if st.button("🔄 Reiniciar Tramos"):
        st.session_state["leg_0"] = 0

    leg = st.session_state["leg_0"]
    if leg >= len(ruta) - 1:
        st.success("✅ Todas las paradas completadas")
        return

    # Nodo de origen y destino del tramo actual
    n_origen = ruta[leg]
    n_dest   = ruta[leg + 1]
    nombre_dest   = df_f.loc[n_dest, "nombre_cliente"]
    direccion_dest = df_f.loc[n_dest, "direccion"]
    ETA_dest      = df_r.loc[df_r["orden"] == leg + 1, "ETA"].values[0]

    # Mostrar nombre y ETA, y agregar el botón con “Ya llegué a [nombre_dest]”
    st.markdown(f"### Próximo → **{nombre_dest}**<br>📍 {direccion_dest} (ETA {ETA_dest})",
                unsafe_allow_html=True)
    if st.button(f"Ya llegué a {nombre_dest}"):
        st.session_state["leg_0"] += 1
        st.rerun()

    # Construir lista de coordenadas en orden de ruta
    coords_final = [(df_f.loc[i, "lat"], df_f.loc[i, "lon"]) for i in ruta]

    # Intentar obtener segmento con Directions API (con tráfico)
    orig = f"{coords_final[leg][0]},{coords_final[leg][1]}"
    dest = f"{coords_final[leg+1][0]},{coords_final[leg+1][1]}"
    try:
        directions = gmaps.directions(
            orig, dest,
            mode="driving",
            departure_time=datetime.now(),
            traffic_model="best_guess"
        )
        leg0 = directions[0]["legs"][0]
        tiempo_traffic = leg0.get("duration_in_traffic", leg0["duration"])["text"]
        overview = directions[0]["overview_polyline"]["points"]
        segmento = [(p["lat"], p["lng"]) for p in decode_polyline(overview)]
    except:
        tiempo_traffic = None
        segmento = [coords_final[leg], coords_final[leg+1]]

    # -------------------- MOSTRAR MAPA --------------------
    t1, t2 = st.tabs(["🗺 Tramo", "ℹ️ Info"])
    with t1:
        # 1) Crear mapa centrado en el punto de inicio del tramo
        m = folium.Map(location=segmento[0], zoom_start=14)

        # 2) Pintar todos los centroides de clusters (ÍNDICES >=1 en df_f) con icono naranja
        for idx_cluster, fila in df_f.iloc[1:].iterrows():
            folium.Marker(
                (fila["lat"], fila["lon"]),
                popup=(
                    f"<b>{fila['nombre_cliente']}</b><br>"
                    f"Dirección: {fila['direccion']}<br>"
                    f"Ventana: {fila['time_start']} - {fila['time_end']}<br>"
                    f"Demanda (nº pedidos): {fila['demand']}"
                ),
                icon=folium.Icon(color="orange", icon="users", prefix="fa")
            ).add_to(m)

        # 3) Pintar cada pedido individual (df_et) con CircleMarker gris,
        #    de modo que se vean sus ubicaciones exactas (incluso si forman parte de un cluster).
        for _, fila_p in df_et.iterrows():
            folium.CircleMarker(
                location=(fila_p["lat"], fila_p["lon"]),
                radius=5,
                color="gray",
                fill=True,
                fill_color="gray",
                fill_opacity=0.6,
                popup=(
                    f"<b>{fila_p['nombre_cliente']}</b><br>"
                    f"Dirección: {fila_p['direccion']}<br>"
                    f"Cluster: {fila_p['cluster']}<br>"
                    f"Ventana: {fila_p['time_start']} - {fila_p['time_end']}"
                )
            ).add_to(m)

        # 4) Dibujar la línea del tramo actual (azul)
        folium.PolyLine(
            segmento,
            color="blue",
            weight=5,
            opacity=0.8,
            tooltip=f"⏱ {tiempo_traffic}" if tiempo_traffic else None
        ).add_to(m)

        # 5) Marcar origen (ícono verde) y destino (ícono azul) del tramo
        folium.Marker(
            coords_final[leg],
            popup="Origen tramo",
            icon=folium.Icon(color="green", icon="play", prefix="fa")
        ).add_to(m)
        folium.Marker(
            coords_final[leg+1],
            popup=f"{nombre_dest}<br>{direccion_dest}",
            icon=folium.Icon(color="blue", icon="map-marker", prefix="fa")
        ).add_to(m)

        # 6) Mostrar mapa
        st_folium(m, width=700, height=400)

    with t2:
        st.write(f"**Tiempo estimado (tráfico):** {tiempo_traffic or '--'}")
