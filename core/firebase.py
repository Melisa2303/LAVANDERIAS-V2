# Aquí irá la configuración de firebase y helpers de Firestore

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import pytz

# Cargar variables de entorno
load_dotenv()

# Inicializa Firebase solo si no está inicializado
if not firebase_admin._apps:
    cred = credentials.Certificate({
        "type": os.getenv("FIREBASE_TYPE"),
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    })
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Leer datos de artículos desde Firestore
def obtener_articulos():
    if 'articulos' not in st.session_state:
        # Solo leer si no hay caché
        articulos_ref = db.collection('articulos')
        docs = articulos_ref.stream()
        st.session_state.articulos = [doc.to_dict().get('Nombre', 'Nombre no disponible') for doc in docs]
    return st.session_state.articulos

# Leer datos de sucursales desde Firestore
def obtener_sucursales():
    if 'sucursales' not in st.session_state:
        # Solo leer si no hay caché
        sucursales_ref = db.collection('sucursales')
        docs = sucursales_ref.stream()
        st.session_state.sucursales = [
            {
                "nombre": doc.to_dict().get('nombre', 'Nombre no disponible'),
                "direccion": doc.to_dict().get('direccion', 'Dirección no disponible'),
                "coordenadas": doc.to_dict().get('coordenadas', {})
            }
            for doc in docs
        ]
    return st.session_state.sucursales

# Verificar unicidad del número de boleta
def verificar_unicidad_boleta(numero_boleta, tipo_servicio, sucursal):
    # Caché local para verificaciones recientes
    cache_key = f"{numero_boleta}-{tipo_servicio}-{sucursal}"
    if 'boletas_verificadas' in st.session_state and cache_key in st.session_state.boletas_verificadas:
        return st.session_state.boletas_verificadas[cache_key]
    
    boletas_ref = db.collection('boletas')
    
    # Construimos una consulta con LIMIT 1 para optimizar
    if tipo_servicio == "🏢 Sucursal":
        query = boletas_ref.where('numero_boleta', '==', numero_boleta)\
                          .where('tipo_servicio', '==', tipo_servicio)\
                          .where('sucursal', '==', sucursal)\
                          .limit(1)  # Solo necesitamos saber si existe al menos una
    else:
        query = boletas_ref.where('numero_boleta', '==', numero_boleta)\
                          .where('tipo_servicio', '==', tipo_servicio)\
                          .limit(1)
    
    # Verificamos si hay al menos un documento
    existe = bool(next(query.stream(), None))
    
    # Actualizamos caché
    if 'boletas_verificadas' not in st.session_state:
        st.session_state.boletas_verificadas = {}
    st.session_state.boletas_verificadas[cache_key] = not existe
    
    return not existe

# ------------------- GUARDAR RESULTADO DE UNA CORRIDA ----------------------

def guardar_resultado_corrida(
    db,
    fecha_ruta: str,
    algoritmo: str,
    distancia_km: float,
    tiempo_min: float,
    tiempo_computo_s: float,
    num_puntos: int
):
    """
    Guarda en Firestore el resultado FINAL de una corrida de algoritmo,
    con las 4 métricas correctas (NO las "driving"/Google, sino las del optimizador).
    """
    # Timestamp de la corrida (momento en que se guarda)
    # Hora local de Lima/Perú
    lima = pytz.timezone("America/Lima")
    fecha_corrida = datetime.now(lima).strftime("%Y-%m-%d %H:%M:%S")
    doc = {
        "fecha_corrida": fecha_corrida,
        "fecha_ruta": fecha_ruta,
        "algoritmo": algoritmo,
        "distancia_km": distancia_km,
        "tiempo_min": tiempo_min,
        "tiempo_computo_s": tiempo_computo_s,
        "num_puntos": num_puntos
    }
    # Colección centralizada (ajusta el nombre si deseas)
    db.collection("resultados_algoritmos").add(doc)

# ------------------- DESCARGAR HISTORIAL DE CORRIDAS -----------------------

def obtener_historial_corridas(db):
    """
    Lee TODOS los resultados guardados en Firestore y los retorna como DataFrame.
    """
    docs = db.collection("resultados_algoritmos").stream()
    data = []
    for doc in docs:
        data.append(doc.to_dict())
    # Si quieres, aquí puedes ordenar por fecha_corrida
    df = pd.DataFrame(data)
    if not df.empty and "fecha_corrida" in df.columns:
        df = df.sort_values("fecha_corrida", ascending=True)
    return df
