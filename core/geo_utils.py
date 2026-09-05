# Aquí irán funciones de geolocalización, sugerencias y mapas

import os
import time
import streamlit as st
import requests
import folium
from geopy.geocoders import Nominatim

# Inicializar Geolocalizador
geolocator = Nominatim(user_agent="StreamlitApp/1.0")

# Email de contacto para Nominatim (opcional pero recomendado)
NOMINATIM_EMAIL = st.secrets.get("nominatim", {}).get("email") or os.getenv("NOMINATIM_EMAIL")

@st.cache_data(ttl=300, show_spinner=False)
def obtener_sugerencias_direccion(direccion, limit=5):
    """
    Consulta Nominatim con caché (5 min) y reintentos simples para minimizar 429.
    Mantiene la misma firma: recibir una cadena 'direccion' y devolver lista JSON.
    """
    direccion = (direccion or "").strip()
    if not direccion:
        return []

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "format": "json",
        "q": direccion,
        "addressdetails": 1,
        "limit": limit
    }
    if NOMINATIM_EMAIL:
        params["email"] = NOMINATIM_EMAIL

    headers = {"User-Agent": f"LavanderiasApp/1.0 ({NOMINATIM_EMAIL or 'no-email-provided'})"}

    max_retries = 2
    for intento in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=6)
        except requests.RequestException:
            # Error de red: esperar un poco y reintentar
            time.sleep(0.5 * (intento + 1))
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                st.warning("Respuesta no válida desde el servicio de geocodificación.")
                return []
        elif resp.status_code == 429:
            # Rate limited: esperar y reintentar
            time.sleep(1.0 * (intento + 1))
            continue
        else:
            st.warning(f"Error al consultar API de direcciones: {resp.status_code}")
            return []

    # Si agotamos reintentos, devolvemos lista vacía (no rompe otros flujos)
    st.warning("Límite de peticiones al servicio de direcciones. Intente nuevamente más tarde.")
    return []

def obtener_coordenadas(direccion):
    # Extrae las coordenadas de una dirección usando la API de Nominatim.
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={direccion}&addressdetails=1"
    headers = {"User-Agent": "StreamlitApp/1.0"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200 and response.json():
            data = response.json()[0]
            return float(data["lat"]), float(data["lon"])
        else:
            st.warning("No se encontraron coordenadas para la dirección ingresada.")
    except Exception as e:
        st.error(f"Error al conectarse a la API: {e}")
    return None, None

def obtener_direccion_desde_coordenadas(lat, lon):
    # Usa Geopy para obtener una dirección a partir de coordenadas (latitud y longitud).
    try:
        location = geolocator.reverse((lat, lon), language="es")
        return location.address if location else "Dirección no encontrada"
    except Exception as e:
        st.error(f"Error al obtener dirección desde coordenadas: {e}")
        return "Dirección no encontrada"
