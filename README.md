# LAVANDERIAS-V2

Aplicación para gestión de rutas y boletas en lavanderías americanas.

---

## Requisitos

- Python 3.7+
- Cuenta de Firebase
- Google Maps API Key

---

## Estructura del proyecto

- **app.py**: Script principal de la aplicación (Streamlit).
- **requirements.txt**: Lista de dependencias.
- **scripts/**: Scripts auxiliares, por ejemplo para cargar datos masivos a Firestore.
  - `upload_csv_to_firestore.py`
- **data/**: Archivos de datos de ejemplo o para carga masiva.
  - `articulos.csv`
  - `sucursales.csv`
  - `LOGO.PNG`
- **.github/workflows/**: Automatizaciones (CI/CD) de GitHub Actions.

---

## Instalación

1. **Clona el repositorio:**
   ```bash
   git clone https://github.com/Melisa2303/LAVANDERIAS-V2.git
   cd LAVANDERIAS-V2
   ```

2. **Crea un entorno virtual y actívalo:**
   ```bash
   python -m venv myenv
   source myenv/bin/activate  # En Windows: myenv\Scripts\activate
   ```

3. **Instala las dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configura Firebase:**
   - Crea un proyecto en [Firebase](https://console.firebase.google.com/).
   - Configura Firebase Authentication y Firestore.
   - Descarga el archivo de configuración `serviceAccountKey.json` y colócalo en el directorio del proyecto.
   - Crea un archivo `.env` con tus credenciales y variables necesarias.

5. **Ejecuta la aplicación:**
   ```bash
   streamlit run app.py
   ```

---

## Scripts auxiliares

Si necesitas cargar artículos o sucursales desde archivos CSV a Firestore, utiliza los scripts dentro de la carpeta `scripts/`.  
Por ejemplo:
```bash
python scripts/upload_csv_to_firestore.py
```
*Asegúrate de que los archivos CSV estén en la carpeta `data/` y que las rutas estén correctamente configuradas en el script.*

---

## Despliegue

Para desplegar la aplicación en Streamlit Cloud, sigue las instrucciones en [Streamlit Cloud](https://streamlit.io/cloud).

---

## Licencia

Este proyecto es privado y para uso interno.

