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

import requests  # Importar requests A
from googlemaps.convert import decode_polyline
from streamlit_folium import st_folium
import folium
import googlemaps
from core.geo_utils import obtener_sugerencias_direccion, obtener_direccion_desde_coordenadas

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


# -----------------------------------------------
# Helpers
# -----------------------------------------------
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


# -----------------------------------------------
# Carga de ruta del día desde Firestore
# -----------------------------------------------
@st.cache_data(ttl=300)
def cargar_ruta(fecha):
    """
    Carga las rutas de recogida y entrega desde la base de datos para una fecha específica.
    Retorna una lista de dict con los campos necesarios.
    """
    try:
        fecha_str = fecha.strftime("%Y-%m-%d")
        query = db.collection('recogidas')
        docs = list(query.stream())  # Traemos todos para controlar duplicación

        datos = []
        for doc in docs:
            data = doc.to_dict()
            doc_id = doc.id

            if data.get("fecha_recojo") == fecha_str:
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

            if data.get("fecha_entrega") == fecha_str and data.get("fecha_entrega") != data.get("fecha_recojo"):
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


# -----------------------------------------------
# UI principal
# -----------------------------------------------
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
                "Cliente/Sucursal": nombre_mostrar if nombre_mostrar else "N/A",
                "Dirección": item["direccion"],
                "Teléfono": item["telefono"],
                "Hora": item["hora"] if item["hora"] else "Sin hora",
            })

        df_tabla = pd.DataFrame(tabla_data)
        st.dataframe(df_tabla, height=600, use_container_width=True, hide_index=True)

        # … resto del bloque de gestión y mapa SIN CAMBIOS …

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

    # -----------------------------------------------
    # 📤 CARGA DE CSV A FIRESTORE (guarda en hora_entrega)
    # -----------------------------------------------
    st.markdown("---")
    st.subheader("📤 Cargar datos desde archivo CSV")

    uploaded_file = st.file_uploader("Selecciona el archivo CSV", type=["csv"], key="cargar_csv")

    if uploaded_file:
        df_csv = pd.read_csv(uploaded_file, dtype=str, encoding="utf-8-sig", keep_default_na=False)
        st.dataframe(df_csv)

        if st.button("🚀 Subir a Firestore", key="boton_subir_csv"):
            total = len(df_csv)
            errores = 0

            for i, row in df_csv.iterrows():
                try:
                    tipo_solicitud = (row.get("tipo_solicitud") or "").strip()
                    nombre_cliente = row.get("nombre_cliente", "")
                    sucursal       = row.get("sucursal", "")
                    telefono       = (row.get("telefono") or "").strip()
                    fecha_str      = (row.get("fecha") or "").strip()
                    direccion      = (row.get("direccion") or "").strip()

                    lat = float(row.get("coordenadas.lat"))
                    lon = float(row.get("coordenadas.lon"))

                    # 🔹 HORA CSV -> hora_entrega
                    hora_unificada = normalizar_hora(row.get("hora"))
                    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").strftime("%Y-%m-%d")

                    doc_data = {
                        "tipo_solicitud": tipo_solicitud,
                        "telefono": telefono,
                        "nombre_cliente": nombre_cliente if tipo_solicitud == "Cliente Delivery" else None,
                        "sucursal": sucursal if tipo_solicitud == "Sucursal" else None,

                        "coordenadas_recojo": {"lat": lat, "lon": lon},
                        "coordenadas_entrega": {"lat": lat, "lon": lon},

                        "direccion_recojo": direccion,
                        "direccion_entrega": direccion,

                        "fecha_recojo": fecha,
                        "fecha_entrega": fecha,

                        "hora_recojo": None,
                        "hora_entrega": hora_unificada  # ✅ se guarda aquí
                    }

                    db.collection("recogidas").add(doc_data)

                except Exception as e:
                    errores += 1
                    st.warning(f"⚠️ Error en fila {i + 2}: {e}")

            st.success(f"✅ Se subieron {total - errores} registros correctamente. {errores} errores.")
            st.cache_data.clear()

    # -----------------------------------------------
    # ❌ ELIMINAR RUTAS DE LA FECHA SELECCIONADA
    # -----------------------------------------------
    st.markdown("---")
    st.subheader("❌ Eliminar rutas del día")

    with st.expander("⚠️ Esta acción eliminará todos los pedidos (recogidas y entregas) de la fecha seleccionada."):
        confirmar = st.checkbox("Sí, quiero eliminar todos los registros de esta fecha")

        if confirmar:
            if st.button("🗑️ Eliminar todas las rutas de esta fecha"):
                try:
                    fecha_str = fecha_seleccionada.strftime("%Y-%m-%d")
                    recojo_docs = list(db.collection("recogidas").where("fecha_recojo", "==", fecha_str).stream())
                    entrega_docs = list(db.collection("recogidas").where("fecha_entrega", "==", fecha_str).stream())

                    todos_ids = set([doc.id for doc in recojo_docs + entrega_docs])

                    for doc_id in todos_ids:
                        db.collection("recogidas").document(doc_id).delete()

                    st.success(f"✅ Se eliminaron {len(todos_ids)} documentos correspondientes a {fecha_str}.")
                    st.cache_data.clear()
                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error al eliminar rutas: {e}")
