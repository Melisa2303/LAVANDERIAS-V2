# LavanderiaApp

Aplicación para gestión de rutas y boletas en lavanderías americanas.

## Requisitos

- Python 3.7+
- Firebase Account
- Google Maps API Key

## Instalación

1. Clonar el repositorio:
   ```bash
   git clone https://github.com/Melisa2303/LavanderiaApp.git
   cd LavanderiaApp
   ```

2. Crear un entorno virtual y activar:
   ```bash
   python -m venv myenv
   source myenv/bin/activate  # En Windows: myenv\Scripts\activate
   ```

3. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```

4. Configurar Firebase:
   - Crear un proyecto en Firebase.
   - Configurar Firebase Authentication y Firestore.
   - Descargar el archivo de configuración `serviceAccountKey.json` y colocarlo en el directorio del proyecto.

5. Ejecutar la aplicación:
   ```bash
   streamlit run app.py
   ```

## Despliegue

Para desplegar la aplicación en Streamlit Cloud, sigue las instrucciones en [Streamlit Cloud](https://streamlit.io/cloud).
