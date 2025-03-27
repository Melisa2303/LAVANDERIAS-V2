import firebase_admin
from firebase_admin import credentials, firestore
import csv
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configurar Firebase
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

# Leer datos desde un archivo CSV y subirlos a Firestore
def subir_datos_articulos(csv_file_path):
    with open(csv_file_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            db.collection('articulos').add(row)

# Llamar a la función con la ruta a tu archivo CSV
subir_datos_articulos('articulos.csv')
