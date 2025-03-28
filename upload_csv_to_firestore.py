import firebase_admin
from firebase_admin import credentials, firestore
import os
import csv

# Initialize Firebase
try:
    cred = credentials.Certificate({
        "type": os.getenv("FIREBASE_TYPE", "service_account"),
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
        "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    })
    firebase_admin.initialize_app(cred)
    print("Conectado a Firebase")
except Exception as e:
    print(f"Error al conectar a Firebase: {e}")

db = firestore.client()

# Read the CSV file
def leer_articulos_csv():
    articulos = []
    try:
        with open('articulos.csv', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',')
            for row in reader:
                articulos.append(row)
        print(f"Artículos leídos del CSV: {articulos}")
    except Exception as e:
        print(f"Error al leer el archivo CSV: {e}")
    return articulos

# Upload data to Firestore
def subir_articulos_a_firestore(articulos):
    try:
        for articulo in articulos:
            db.collection('articulos').add(articulo)
            print(f"Artículo subido a Firestore: {articulo}")
    except Exception as e:
        print(f"Error al subir artículos a Firestore: {e}")

# Verify data in Firestore
def verificar_articulos_en_firestore():
    try:
        articulos_ref = db.collection('articulos')
        docs = articulos_ref.stream()
        for doc in docs:
            print(f'{doc.id} => {doc.to_dict()}')
    except Exception as e:
        print(f"Error al verificar artículos en Firestore: {e}")

# Execute the process
if __name__ == "__main__":
    articulos = leer_articulos_csv()
    subir_articulos_a_firestore(articulos)
    verificar_articulos_en_firestore()
