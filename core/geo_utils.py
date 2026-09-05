# Aquí irán funciones de geolocalización, sugerencias y mapas

import os
import time
import threading
import streamlit as st
import requests
import folium
from geopy.geocoders import Nominatim

# Inicializar Geolocalizador
geolocator = Nominatim(user_agent="StreamlitApp/1.0")

# Email de contacto para Nominatim (opcional pero recomendado)
NOMINATIM_EMAIL = st.secrets.get("nominatim", {}).get("email") or os.getenv("NOMINATIM_EMAIL")

# Simple rate limiter mínimo para respetar la política de Nominatim (≈1s entre peticiones)
_last_nominatim_call = 0.0
_nominatim_lock = threading.Lock()
_MIN_INTERVAL = 1.05

def _ensure_rate_limit():
    global _last_nominatim_call
    with _nominatim_lock:
        elapsed = time.time() - _last_nominatim_call
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _last_nominatim_call = time.time()

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
            _ensure_rate_limit()
            resp = requests.get(url, params=params, headers=headers, timeout=8)
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
            # Rate limited: esperar y reintentar (backoff simple)
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
    if not direccion:
        return None, None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "format": "json",
        "q": direccion,
        "addressdetails": 1,
        "limit": 1
    }
    if NOMINATIM_EMAIL:
        params["email"] = NOMINATIM_EMAIL

    headers = {"User-Agent": f"LavanderiasApp/1.0 ({NOMINATIM_EMAIL or 'no-email-provided'})"}

    try:
        _ensure_rate_limit()
        response = requests.get(url, params=params, headers=headers, timeout=8)
        if response.status_code == 200 and response.json():
            data = response.json()[0]
            return float(data["lat"]), float(data["lon"])
        else:
            st.warning("No se encontraron coordenadas para la dirección ingresada.")
    except Exception as e:
        st.error(f"Error al conectarse a la API: {e}")
    return None, None

@st.cache_data(ttl=3600, show_spinner=False)
def obtener_direccion_desde_coordenadas(lat, lon):
    """
    Versión rápida y silenciosa — timeout corto y sin mensajes de error que afecten la UI.
    Devuelve 'Dirección no encontrada' si falla para no interrumpir la experiencia.
    """
    if lat is None or lon is None:
        return "Dirección no encontrada"
    try:
        # Respetar rate limit antes de pedir reverse
        _ensure_rate_limit()
        # timeout aumentado a 5s para evitar ReadTimeoutError frecuente
        location = geolocator.reverse((lat, lon), language="es", timeout=5)
        return location.address if location else "Dirección no encontrada"
    except Exception:
        # No llamamos a st.error ni st.warning aquí para evitar recargas o modales.
        return "Dirección no encontrada"
