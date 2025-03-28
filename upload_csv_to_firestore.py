import firebase_admin
from firebase_admin import credentials, firestore
import os
import csv
import hashlib
import streamlit as st

# Inicializar Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate({
        "type": os.getenv("FIREBASE_TYPE"),
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": st.secrets["FIREBASE_CLIENT_EMAIL"],
        "client_id": st.secrets["FIREBASE_CLIENT_ID"],
        "auth_uri": st.secrets["FIREBASE_AUTH_URI"],
        "token_uri": st.secrets["FIREBASE_TOKEN_URI"],
        "auth_provider_x509_cert_url": st.secrets["FIREBASE_AUTH_PROVIDER_X509_CERT_URL"],
        "client_x509_cert_url": st.secrets["FIREBASE_CLIENT_X509_CERT_URL"]
    })
    firebase_admin.initialize_app(cred)

db = firestore.client()

HASH_COLLECTION = 'csv_hashes'

# Leer el archivo CSV y calcular su hash
def leer_articulos_csv():
    articulos = []
    hasher = hashlib.sha256()
    with open('articulos.csv', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, delimiter=',')
        for row in reader:
            articulos.append(row)
            hasher.update(str(row).encode('utf-8'))
    csv_hash = hasher.hexdigest()
    return articulos, csv_hash

# Subir los datos a Firestore
def subir_articulos_a_firestore(articulos):
    for articulo in articulos:
        # Verificar si el artículo ya existe en Firestore
        docs = db.collection('articulos').where('Codigo', '==', articulo['Codigo']).stream()
        existing_docs = list(docs)
        if not existing_docs:
            db.collection('articulos').add(articulo)
            print(f"Artículo subido a Firestore: {articulo}")  # Imprimir el artículo subido
        else:
            # Actualizar documento existente si los datos han cambiado
            doc_id = existing_docs[0].id
            db.collection('articulos').document(doc_id).set(articulo)
            print(f"Artículo actualizado en Firestore: {articulo}")

# Verificar los datos en Firestore
def verificar_articulos_en_firestore():
    articulos_ref = db.collection('articulos')
    docs = articulos_ref.stream()
    for doc in docs:
        print(f'{doc.id} => {doc.to_dict()}')

# Verificar si el hash del CSV ha cambiado
def verificar_csv_hash(csv_hash):
    hash_doc = db.collection(HASH_COLLECTION).document('articulos_csv').get()
    if hash_doc.exists:
        stored_hash = hash_doc.to_dict().get('hash')
        if stored_hash == csv_hash:
            return False
    # Guardar el nuevo hash
    db.collection(HASH_COLLECTION).document('articulos_csv').set({'hash': csv_hash})
    return True

# Ejecutar el proceso
if __name__ == "__main__":
    articulos, csv_hash = leer_articulos_csv()
    if verificar_csv_hash(csv_hash):
        subir_articulos_a_firestore(articulos)
    else:
        print("El archivo CSV no ha cambiado. No se subirán datos.")
    verificar_articulos_en_firestore()
