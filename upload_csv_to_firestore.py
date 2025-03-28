import firebase_admin
from firebase_admin import credentials, firestore
import os
import csv

# Inicializar Firebase
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

# Verificar la conexión a Firebase
print("Conectado a Firebase")

# Leer el archivo CSV
def leer_articulos_csv():
    articulos = []
    with open('articulos.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',')
        for row in reader:
            articulos.append(row)
    print(f"Artículos leídos del CSV: {articulos}")  # Imprimir los artículos leídos
    return articulos

# Subir los datos a Firestore
def subir_articulos_a_firestore(articulos):
    for articulo in articulos:
        db.collection('articulos').add(articulo)
        print(f"Artículo subido a Firestore: {articulo}")  # Imprimir el artículo subido

# Verificar los datos en Firestore
def verificar_articulos_en_firestore():
    articulos_ref = db.collection('articulos')
    docs = articulos_ref.stream()
    for doc in docs:
        print(f'{doc.id} => {doc.to_dict()}')

# Ejecutar el proceso
if __name__ == "__main__":
    articulos = leer_articulos_csv()
    subir_articulos_a_firestore(articulos)
    verificar_articulos_en_firestore()
