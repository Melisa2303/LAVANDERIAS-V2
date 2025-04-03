import firebase_admin
from firebase_admin import credentials, firestore
import os
import csv

# Inicializar Firebase
cred = credentials.Certificate({
    "type": os.getenv("FIREBASE_TYPE"),
    "project_id": os.getenv("FIREBASE_PROJECT_ID"),
    "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"],
    "client_id": os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri": os.getenv("FIREBASE_AUTH_URI"),
    "token_uri": os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
})
firebase_admin.initialize_app(cred)

db = firestore.client()

# Leer el archivo CSV de artículos
def leer_articulos_csv():
    articulos = []
    with open('articulos.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',')
        for row in reader:
            articulos.append(row)
    print(f"Artículos leídos del CSV: {articulos}")
    return articulos

# Subir los datos de artículos a Firestore
def subir_articulos_a_firestore(articulos):
    for articulo in articulos:
        docs = db.collection('articulos').where('Codigo', '==', articulo['Codigo']).stream()
        if not any(docs):
            db.collection('articulos').add(articulo)
            print(f"Artículo subido a Firestore: {articulo}")
        else:
            print(f"Artículo duplicado no subido: {articulo}")

# Leer el archivo CSV de sucursales
def leer_sucursales_csv():
    sucursales = []
    with open('sucursales.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',')
        for row in reader:
            sucursales.append(row)
    print(f"Sucursales leídas del CSV: {sucursales}")
    return sucursales

# Subir los datos de sucursales a Firestore
def subir_sucursales_a_firestore(sucursales):
    for sucursal in sucursales:
        docs = db.collection('sucursales').where('nombre', '==', sucursal['nombre']).stream()
        if not any(docs):
            sucursal_document = {
                "nombre": sucursal['nombre'],
                "direccion": sucursal['direccion'],
                "encargado": sucursal['encargado'],
                "telefono": sucursal['telefono'],
                "coordenadas": {
                    "lat": float(sucursal['coordenadas.lat']),
                    "lon": float(sucursal['coordenadas.lon'])
                }
            }
            db.collection('sucursales').add(sucursal_document)
            print(f"Sucursal subida a Firestore: {sucursal_document}")
        else:
            print(f"Sucursal duplicada no subida: {sucursal}")

# Verificar los datos de artículos en Firestore
def verificar_articulos_en_firestore():
    articulos_ref = db.collection('articulos')
    docs = articulos_ref.stream()
    for doc in docs:
        print(f'{doc.id} => {doc.to_dict()}')

# Verificar los datos de sucursales en Firestore
def verificar_sucursales_en_firestore():
    sucursales_ref = db.collection('sucursales')
    docs = sucursales_ref.stream()
    for doc in docs:
        print(f'{doc.id} => {doc.to_dict()}')

# Ejecutar el proceso
if __name__ == "__main__":
    # Procesar artículos
    articulos = leer_articulos_csv()
    subir_articulos_a_firestore(articulos)
    verificar_articulos_en_firestore()
    
    # Procesar sucursales
    sucursales = leer_sucursales_csv()
    subir_sucursales_a_firestore(sucursales)
    verificar_sucursales_en_firestore()
