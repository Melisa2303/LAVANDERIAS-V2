# /datosrutas/rutas2.py

import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta
import time

import firebase_admin
from firebase_admin import credentials, firestore
from core.firebase import db, obtener_sucursales
from core.constants import GOOGLE_MAPS_API_KEY, PUNTOS_FIJOS_COMPLETOS

from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
import googlemaps
from core.geo_utils import (
    obtener_sugerencias_direccion,
    obtener_direccion_desde_coordenadas,
)

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# -------------------------------------------------------------------
# Estado para invalidar cachés SOLO cuando hay cambios
# -------------------------------------------------------------------
if "version_datos" not in st.session_state:
    st.session_state.version_datos = 0


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def normalizar_hora(h):
    """
    Acepta: '10:00', '10:00:00', '' o None.
    Devuelve: 'HH:MM:SS' o None si inválida/vacía.
    """
    if h is None:
        return None
    h = str(h).strip()
    if not h:
        return None

    partes = h.split(":")
    if len(partes) == 2:
        hh, mm = partes
        ss = "00"
    elif len(partes) == 3:
        hh, mm, ss = partes
    else:
        return None  # formato no reconocido

    try:
        hh = int(hh)
        mm = int(mm)
        ss = int(ss)
    except ValueError:
        return None

    if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
        return None

    return f"{hh:02d}:{mm:02d}:{ss:02d}"


# -------------------------------------------------------------------
# Carga de ruta del día desde Firestore (CONSULTA FILTRADA)
# -------------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_ruta(fecha, version):
    """
    Lee SOLO los documentos cuya fecha_recojo o fecha_entrega == fecha.
    Prioriza mostrar la ENTREGA cuando ambas coinciden el mismo día (por id).
    'version' permite invalidar caché cuando hay escrituras.
    """
    try:
        fecha_str = fecha.strftime("%Y-%m-%d")
        col = db.collection("recogidas")

        # Dos queries específicas (evita barrer toda la colección)
        rec_q = col.where("fecha_recojo", "==", fecha_str).stream()
        ent_q = col.where("fecha_entrega", "==", fecha_str).stream()

        por_id = {}

        # Recojos del día
        for doc in rec_q:
            d = doc.to_dict()
            por_id[doc.id] = {
                "id": doc.id,
                "operacion": "Recojo",
                "nombre_cliente": d.get("nombre_cliente"),
                "sucursal": d.get("sucursal"),
                "direccion": d.get("direccion_recojo", "N/A"),
                "telefono": d.get("telefono", "N/A"),
                "hora": d.get("hora_recojo", ""),
                "tipo_solicitud": d.get("tipo_solicitud"),
                "coordenadas": d.get("coordenadas_recojo", {"lat": -16.409047, "lon": -71.537451}),
                "fecha": d.get("fecha_recojo"),
            }

        # Entregas del día (si ya había el mismo id como recojo, SOBRESCRIBE con entrega)
        for doc in ent_q:
            d = doc.to_dict()
            por_id[doc.id] = {
                "id": doc.id,
                "operacion": "Entrega",  # prioridad
                "nombre_cliente": d.get("nombre_cliente"),
                "sucursal": d.get("sucursal"),
                "direccion": d.get("direccion_entrega", "N/A"),
                "telefono": d.get("telefono", "N/A"),
                "hora": d.get("hora_entrega", ""),  # aquí verás la hora del CSV
                "tipo_solicitud": d.get("tipo_solicitud"),
                "coordenadas": d.get("coordenadas_entrega", {"lat": -16.409047, "lon": -71.537451}),
                "fecha": d.get("fecha_entrega"),
            }

        return list(por_id.values())
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        return []


# -------------------------------------------------------------------
# UI principal
# -------------------------------------------------------------------
def datos_ruta():
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image(
            "https://github.com/Melisa2303/LAVANDERIAS-V2/raw/main/data/LOGO.PNG",
            width=100,
        )
    with col2:
        st.markdown(
            "<h1 style='text-align: left; color: black;'>Lavanderías Americanas</h1>",
            unsafe_allow_html=True,
        )
    st.title("📋 Ruta del Día")

    # Form para reducir reruns por cada widget
    with st.form("form_filtro_fecha"):
        fecha_seleccionada = st.date_input(
            "Seleccionar Fecha", value=datetime.now().date()
        )
        submitted = st.form_submit_button("Actualizar")

    datos = cargar_ruta(fecha_seleccionada, st.session_state.version_datos)

    if datos:
        tabla_data = []
        for item in datos:
            nombre_mostrar = (
                item["nombre_cliente"]
                if item["tipo_solicitud"] == "Cliente Delivery"
                else item["sucursal"]
            )
            tabla_data.append(
                {
                    "Operación": item["operacion"],
                    "Cliente/Sucursal": nombre_mostrar if nombre_mostrar else "N/A",
                    "Dirección": item["direccion"],
                    "Teléfono": item["telefono"],
                    "Hora": item["hora"] if item["hora"] else "Sin hora",
                }
            )

        df_tabla = pd.DataFrame(tabla_data)
        st.dataframe(df_tabla, height=600, use_container_width=True, hide_index=True)

        # ---------------- Gestión de Deliveries (edición de hora) ----------------
        deliveries = [
            item for item in datos if item["tipo_solicitud"] == "Cliente Delivery"
        ]
        if deliveries:
            st.markdown("---")
            st.subheader("🔄 Gestión de Deliveries")

            opciones = {
                f"{item['operacion']} - {item['nombre_cliente']}": item for item in deliveries
            }
            selected = st.selectbox("Seleccionar operación:", options=opciones.keys())
            delivery_data = opciones[selected]

            st.markdown(f"### Hora de {delivery_data['operacion']}")
            hora_col1, hora_col2 = st.columns([4, 1])
            with hora_col1:
                horas_sugeridas = [
                    f"{h:02d}:{m:02d}" for h in range(7, 19) for m in (0, 30)
                ]
                hora_actual = delivery_data.get("hora")

                if hora_actual and hora_actual[:5] not in horas_sugeridas:
                    horas_sugeridas.append(hora_actual[:5])
                    horas_sugeridas.sort()

                opciones_hora = ["-- Sin asignar --"] + horas_sugeridas
                if hora_actual and hora_actual[:5] in horas_sugeridas:
                    index_hora = opciones_hora.index(hora_actual[:5])
                else:
                    index_hora = 0

                nueva_hora = st.selectbox(
                    "Seleccionar o escribir hora (HH:MM):",
                    options=opciones_hora,
                    index=index_hora,
                    key=f"hora_combobox_{delivery_data['id']}",
                )

            with hora_col2:
                st.write("")
                st.write("")
                if st.button("💾 Guardar", key=f"guardar_btn_{delivery_data['id']}"):
                    try:
                        campo_hora = (
                            "hora_recojo"
                            if delivery_data["operacion"] == "Recojo"
                            else "hora_entrega"
                        )
                        if nueva_hora == "-- Sin asignar --":
                            db.collection("recogidas").document(
                                delivery_data["id"]
                            ).update({campo_hora: None})
                            st.success("Hora eliminada")
                        else:
                            if len(nueva_hora.split(":")) != 2:
                                raise ValueError
                            hora_i, minutos_i = map(int, nueva_hora.split(":"))
                            if not (0 <= hora_i < 24 and 0 <= minutos_i < 60):
                                raise ValueError

                            db.collection("recogidas").document(
                                delivery_data["id"]
                            ).update({campo_hora: f"{hora_i:02d}:{minutos_i:02d}:00"})
                            st.success("Hora actualizada")

                        # Invalida SOLO este caché
                        st.session_state.version_datos += 1
                        time.sleep(0.5)
                        st.rerun()

                    except ValueError:
                        st.error("Formato inválido. Use HH:MM")
                    except Exception as e:
                        st.error(f"Error: {e}")

        # ---------------- Exportar Excel ----------------
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df_tabla.to_excel(writer, index=False)

        st.download_button(
            label="Descargar Excel",
            data=excel_buffer.getvalue(),
            file_name=f"ruta_{fecha_seleccionada.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    else:
        st.info("No hay datos para la fecha seleccionada con los filtros actuales.")

    # -------------------------------------------------------------------
    # 📤 CARGA DE CSV A FIRESTORE (solo ENTREGA; guarda hora_entrega)
    # -------------------------------------------------------------------
    st.markdown("---")
    st.subheader("📤 Cargar datos desde archivo CSV")

    with st.form("form_subida_csv"):
        uploaded_file = st.file_uploader(
            "Selecciona el archivo CSV", type=["csv"], key="cargar_csv"
        )
        subir = st.form_submit_button("🚀 Subir a Firestore")

    if uploaded_file and subir:
        # dtype=str para evitar NaN y respetar formatos (teléfonos, horas)
        df_csv = pd.read_csv(
            uploaded_file, dtype=str, encoding="utf-8-sig", keep_default_na=False
        )
        st.dataframe(df_csv)

        total = len(df_csv)
        errores = 0

        for i, row in df_csv.iterrows():
            try:
                tipo_solicitud = (row.get("tipo_solicitud") or "").strip()
                nombre_cliente = row.get("nombre_cliente", "")
                sucursal = row.get("sucursal", "")
                telefono = (row.get("telefono") or "").strip()
                fecha_str = (row.get("fecha") or "").strip()
                direccion = (row.get("direccion") or "").strip()

                # Coordenadas (columnas: coordenadas.lat, coordenadas.lon)
                lat = float(row.get("coordenadas.lat"))
                lon = float(row.get("coordenadas.lon"))

                # HORA CSV -> hora_entrega
                hora_unificada = normalizar_hora(row.get("hora"))

                # Validación básica de fecha (YYYY-MM-DD)
                fecha = datetime.strptime(fecha_str, "%Y-%m-%d").strftime("%Y-%m-%d")

                # ✅ SOLO ENTREGAS: recojo = None, entrega desde CSV
                doc_data = {
                    "tipo_solicitud": tipo_solicitud,
                    "telefono": telefono,
                    "nombre_cliente": nombre_cliente
                    if tipo_solicitud == "Cliente Delivery"
                    else None,
                    "sucursal": sucursal if tipo_solicitud == "Sucursal" else None,
                    # Recojo vacío (para que no compita ni se muestre)
                    "coordenadas_recojo": None,
                    "direccion_recojo": None,
                    "fecha_recojo": None,
                    "hora_recojo": None,
                    # Entrega completa
                    "coordenadas_entrega": {"lat": lat, "lon": lon},
                    "direccion_entrega": direccion,
                    "fecha_entrega": fecha,
                    "hora_entrega": hora_unificada,
                }

                db.collection("recogidas").add(doc_data)

            except Exception as e:
                errores += 1
                st.warning(f"⚠️ Error en fila {i + 2}: {e}")

        st.success(
            f"✅ Se subieron {total - errores} registros correctamente. {errores} errores."
        )
        # Invalida SOLO el caché de cargar_ruta
        st.session_state.version_datos += 1

    # -------------------------------------------------------------------
    # ❌ ELIMINAR RUTAS DE LA FECHA SELECCIONADA
    # -------------------------------------------------------------------
    st.markdown("---")
    st.subheader("❌ Eliminar rutas del día")

    with st.expander(
        "⚠️ Esta acción eliminará todos los pedidos (recogidas y entregas) de la fecha seleccionada."
    ):
        confirmar = st.checkbox("Sí, quiero eliminar todos los registros de esta fecha")

        if confirmar:
            if st.button("🗑️ Eliminar todas las rutas de esta fecha"):
                try:
                    fecha_str = fecha_seleccionada.strftime("%Y-%m-%d")
                    recojo_docs = list(
                        db.collection("recogidas")
                        .where("fecha_recojo", "==", fecha_str)
                        .stream()
                    )
                    entrega_docs = list(
                        db.collection("recogidas")
                        .where("fecha_entrega", "==", fecha_str)
                        .stream()
                    )

                    todos_ids = set([doc.id for doc in recojo_docs + entrega_docs])

                    for doc_id in todos_ids:
                        db.collection("recogidas").document(doc_id).delete()

                    st.success(
                        f"✅ Se eliminaron {len(todos_ids)} documentos correspondientes a {fecha_str}."
                    )
                    # Invalida SOLO el caché de cargar_ruta
                    st.session_state.version_datos += 1
                    time.sleep(0.5)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error al eliminar rutas: {e}")
