import streamlit as st
import numpy as np
import cv2
from tensorflow.keras.models import load_model
from PIL import Image, ImageOps

st.set_page_config(page_title="Ruteo Postal", page_icon="📬", layout="centered")
st.title("Detector de Códigos Postales")

@st.cache_resource
def cargar_modelo():
    return load_model('modelo_reconocimiento_postales.keras')

modelo = cargar_modelo()

archivo_subido = st.file_uploader("Sube la imagen del código postal completo", type=["jpg", "png", "jpeg"])

if archivo_subido is not None:
    imagen = Image.open(archivo_subido).convert('L')
    st.image(imagen, caption='Imagen original', width=300)
    
    # Preprocesamiento para segmentación (OpenCV)
    img_cv = np.array(imagen)
    # Invertir si es necesario y aplicar umbralizado
    ret, thresh = cv2.threshold(img_cv, 127, 255, cv2.THRESH_BINARY_INV)
    
    # Encontrar contornos de los números
    contornos, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Ordenar contornos de izquierda a derecha
    boundingBoxes = [cv2.boundingRect(c) for c in contornos]
    (contornos, boundingBoxes) = zip(*sorted(zip(contornos, boundingBoxes), key=lambda b: b[1][0]))

    codigo_postal = ""
    confianzas = []
    
    columnas = st.columns(len(contornos))
    
    for i, (x, y, w, h) in enumerate(boundingBoxes):
        # Extraer el dígito, añadir margen y redimensionar a 28x28
        roi = thresh[y:y+h, x:x+w]
        roi = cv2.copyMakeBorder(roi, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=0)
        roi = cv2.resize(roi, (28, 28))
        
        # Preparar para el modelo
        img_final = roi.astype('float32') / 255.0
        img_final = img_final.reshape(1, 28, 28, 1)
        
        # Predicción
        pred = modelo.predict(img_final)
        num = np.argmax(pred)
        conf = np.max(pred)
        
        codigo_postal += str(num)
        confianzas.append(conf)
        
        # Mostrar cada recorte en la web
        with columnas[i]:
            st.image(roi, caption=f"Dígito {i+1}")

    st.divider()
    confianza_media = np.mean(confianzas) * 100
    st.success(f"## Código Detectado: **{codigo_postal}**")
    st.metric("Confianza Media del Sistema", f"{confianza_media:.2f}%")
    
    if confianza_media < 85:
        st.warning("⚠️ Confianza baja: Verifique la calidad de la imagen o la caligrafía.")