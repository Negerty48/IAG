import os
import operator
import subprocess
import threading
from typing import Annotated, Optional
from typing_extensions import Literal, TypedDict
import pyautogui
import screen_brightness_control as sbc
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import comtypes
import difflib

import pyttsx3
import speech_recognition as sr

# Variables de entorno, motor de voz y reconocimiento de voz
load_dotenv()

def _ejecutar_voz(texto: str):
    """Función de bajo nivel que se ejecuta en una burbuja aislada (Hilo)."""
    
    comtypes.CoInitialize()
    
    try:
        motor_aislado = pyttsx3.init()
        motor_aislado.setProperty('rate', 175)
        motor_aislado.say(texto)
        motor_aislado.runAndWait()
    finally:        
        comtypes.CoUninitialize()

recognizer = sr.Recognizer()

# ==========================================
# FUNUCIONES AUXILIARES DE VOZ
# ==========================================

def hablar(texto: str):
    """Lanzador principal a prueba de bloqueos asíncronos."""
    print(f"\n🗣️ Onyx: {texto}")
    
    # Creamos un hilo de usar y tirar solo para hablar
    hilo_voz = threading.Thread(target=_ejecutar_voz, args=(texto,))
    hilo_voz.start()
    hilo_voz.join() # El programa espera aquí pacientemente hasta que Onyx termine la frase

def escuchar() -> str:
    """Abre el micrófono y traduce la voz del usuario a texto"""    

    with sr.Microphone() as source:
        print("\n🎤 [Onyx te está escuchando...]")
        # Ajusta el ruido de fondo rápido para mayor precisión
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            texto = recognizer.recognize_google(audio, language="es-ES")
            print(f"👤 Analista: {texto}")
            return texto
        except sr.WaitTimeoutError:
            return ""
        except sr.UnknownValueError:
            print("⚠️ (No he entendido lo que has dicho)")
            return ""
        except sr.RequestError:
            print("❌ Error con el servicio de reconocimiento de voz.")
            return ""

# ==========================================
# ESTADO GLOBAL DE ONYX
# ==========================================
class OnyxState(TypedDict):
    messages: list
    intencion: Optional[str]
    nivel_volumen: Optional[int]
    nivel_brillo: Optional[int]
    termino_busqueda: Optional[str]
    indice_ejecutar: Optional[int]
    modo_apertura: Optional[str]
    juegos_encontrados: list[str]
    contexto_paralelo: Annotated[list, operator.add]

# ==========================================
# MODELO DE EXTRACCIÓN UNIFICADO (Pydantic)
# ==========================================
class ClasificadorOnyx(BaseModel):
    intencion: Literal["ajustes", "buscar", "ejecutar", "charla"] = Field(
        description="Clasifica la orden. Usa 'ajustes' EXCLUSIVAMENTE para modificar hardware (cambiar brillo, atenuar pantalla, subir/bajar volumen). Usa 'buscar' para encontrar cosas. Usa 'ejecutar' para abrir números/archivos. Usa 'charla' para conversar."
    )
    brillo: Optional[int] = Field(description="Nivel de brillo si se menciona (0-100).", default=None)
    volumen: Optional[int] = Field(description="Nivel de volumen si se menciona (0-100).", default=None)
    termino_busqueda: Optional[str] = Field(
        description="Aísla ÚNICAMENTE el nombre central del programa, juego o archivo. NUNCA incluyas verbos ni frases. Si detectas un error tipográfico en un nombre comercial conocido, corrígelo automáticamente.", 
        default=None
    )
    indice_ejecutar: Optional[int] = Field(description="El número elegido (ej. 1, 2) si la intención es 'ejecutar'.", default=None)
    abrir_con_vscode: bool = Field(description="True si el usuario pide explícitamente abrir con VS Code o Visual Studio Code.", default=False)

# ==========================================
# LLM CONFIGURACIÓN
# ==========================================
llm = AzureChatOpenAI(
    azure_deployment="gpt-4o-mini",
    api_version="2024-02-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0.0
)

# ==========================================
# NODOS DEL GRAFO
# ==========================================

def nodo_clasificador(state: OnyxState):
    ultimo_mensaje = state["messages"][-1].content
    extractor = llm.with_structured_output(ClasificadorOnyx)

    res = extractor.invoke(ultimo_mensaje) 
    
    return {
        "intencion": res.intencion,
        "nivel_brillo": res.brillo,
        "nivel_volumen": res.volumen,
        "termino_busqueda": res.termino_busqueda,
        "indice_ejecutar": res.indice_ejecutar,
        "modo_apertura": "vscode" if res.abrir_con_vscode else "normal"
    }

from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

# --- Subgrafo Fatiga ---
def nodo_bajar_volumen(state: OnyxState):
    objetivo = state.get("nivel_volumen")
    
    if objetivo is None:
        return {"contexto_paralelo": ["volumen sin cambios"]}
        
    objetivo = max(0, min(100, int(objetivo)))
    
    comtypes.CoInitialize()
    
    try:
        # Obtenemos el enumerador nativo de dispositivos de pycaw
        enumerator = AudioUtilities.GetDeviceEnumerator()
        
        # Pedimos el endpoint por defecto
        dispositivo_nativo_windows = enumerator.GetDefaultAudioEndpoint(0, 1)
                
        interfaz = dispositivo_nativo_windows.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        control_volumen = cast(interfaz, POINTER(IAudioEndpointVolume))
        
        nivel_float = objetivo / 100.0
        control_volumen.SetMasterVolumeLevelScalar(nivel_float, None)
        return {"contexto_paralelo": [f"✅ Audio fijado al {objetivo}%"]}
        
    except Exception as e:
        return {"contexto_paralelo": [f"❌ Error directo en la API de Windows: {e}"]}
    finally:        
        comtypes.CoUninitialize()


def nodo_bajar_brillo(state: OnyxState):
    objetivo = state.get("nivel_brillo")
    
    # CASO 1: El usuario NO ha pedido modificar el brillo en este turno
    if objetivo is None:
        return {"contexto_paralelo": ["brillo sin cambios"]}
        
    # CASO 2: Sí hay un valor, ajustamos físicamente la pantalla
    objetivo = max(0, min(100, int(objetivo)))
    try:
        sbc.set_brightness(objetivo)
        return {"contexto_paralelo": [f"✅ Brillo ajustado al {objetivo}%"]}
    except Exception as e:
        return {"contexto_paralelo": [f"❌ Error en hardware de brillo: {e}"]}


def nodo_sintesis_ajustes(state: OnyxState):
    bloques = state.get("contexto_paralelo", [])
    cambios_reales = [b for b in bloques if "sin cambios" not in b]
    
    info = ", ".join(cambios_reales) if cambios_reales else "Ningún ajuste"
    ultimo_mensaje = state["messages"][-1]
    
    instruccion = SystemMessage(content=(
        f"Eres Onyx, el asistente del sistema. Acabas de ejecutar estas acciones: {info}. "
        "Confírmale al usuario de forma hablada, extremadamente natural, empática y breve (1 frase) que ya lo has hecho. "
        "No parezcas un robot."
    ))
    
    respuesta = llm.invoke([instruccion, ultimo_mensaje])
    return {"messages": [respuesta], "contexto_paralelo": []}

# --- Subgrafo Map-Reduce (Búsqueda) ---
def nodo_buscar_archivos(state: dict):
    directorio_base = state["directorio_base"]
    termino = state["termino_busqueda"].lower()
    resultados_locales = []
    
    # Extensiones de máxima prioridad para Onyx
    ext_ejecutables = ['.exe', '.lnk', '.bat', '.iso', '.pkg']
    
    if os.path.exists(directorio_base):
        for raiz, carpetas, archivos in os.walk(directorio_base):
            for nombre in carpetas + archivos:
                nombre_limpio = nombre.lower()
                
                # Separamos el nombre de la extensión para que la similitud no se contamine
                nombre_sin_ext, ext = os.path.splitext(nombre_limpio)
                
                # 1. Búsqueda exacta parcial (el método clásico)
                coincidencia_exacta = termino in nombre_sin_ext
                
                # 2. Búsqueda Difusa (Fuzzy Matching): Evalúa si se parecen más de un 70%
                similitud = difflib.SequenceMatcher(None, termino, nombre_sin_ext).ratio()
                coincidencia_difusa = similitud > 0.70
                
                if coincidencia_exacta or coincidencia_difusa:
                    ruta_completa = os.path.join(raiz, nombre)
                    
                    # Ordenación inteligente: Si es un ejecutable, lo colamos al principio de la lista
                    if os.path.isfile(ruta_completa) and ext in ext_ejecutables:
                        resultados_locales.insert(0, ruta_completa)
                    else:
                        resultados_locales.append(ruta_completa)
                        
            # Límite de seguridad
            if len(resultados_locales) >= 5: 
                break
                
    if resultados_locales:
        # Aseguramos devolver solo los 5 primeros para no saturar el contexto
        bloque = f"📁 Resultados en {directorio_base}:\n" + "\n".join([f"PATH:{r}" for r in resultados_locales[:5]])
        return {"contexto_paralelo": [bloque]}
    
    return {"contexto_paralelo": []}

def nodo_sintesis_busqueda(state: OnyxState):
    bloques_contexto = state.get("contexto_paralelo", [])
    rutas_limpias = []
    
    for bloque in bloques_contexto:
        for linea in bloque.split("\n"):
            if linea.startswith("PATH:"):
                rutas_limpias.append(linea.replace("PATH:", ""))
                
    ultimo_mensaje = state["messages"][-1]
                
    if not rutas_limpias:
        instruccion = SystemMessage(content=f"Eres Onyx. Dile al usuario de forma natural y hablada que no has encontrado '{state.get('termino_busqueda')}'. Sé breve.")
        respuesta = llm.invoke([instruccion, ultimo_mensaje])
        return {"messages": [respuesta], "contexto_paralelo": []}
        
    # 1. SALIDA VISUAL: Imprimimos la lista en la terminal al instante
    print("\n" + "="*60)
    print("📁 LISTA DE ARCHIVOS ENCONTRADOS EN EL SISTEMA:")
    for idx, ruta in enumerate(rutas_limpias, 1):
        print(f"[{idx}] {os.path.basename(ruta)}")
        print(f"    └─ {ruta}")
    print("="*60 + "\n")
    
    # 2. SALIDA DE VOZ (NLG): Le decimos al LLM que sea conversacional
    instruccion = SystemMessage(content=(
        "Eres Onyx. Acabas de imprimir una lista visual de archivos en la pantalla del usuario. "
        "NO LEAS LA LISTA. Dile de forma natural y hablada algo como: 'Ya los tienes en pantalla, ¿cuál quieres ver?' o 'He encontrado esto, ¿cuál abro?'."
    ))
    respuesta = llm.invoke([instruccion, ultimo_mensaje])
    
    return {
        "messages": [respuesta],
        "juegos_encontrados": rutas_limpias,
        "contexto_paralelo": []
    }

# --- Nodo de Acción Física (Ejecución y Apertura) ---
def nodo_ejecutar_archivo(state: OnyxState):
    idx = state.get("indice_ejecutar")
    lista_juegos = state.get("juegos_encontrados", [])
    modo = state.get("modo_apertura", "normal")
    ultimo_mensaje = state["messages"][-1]
    
    if not lista_juegos or idx is None or idx < 1 or idx > len(lista_juegos):
        instruccion = SystemMessage(content="Eres Onyx. Dile al usuario de forma natural que el número que ha elegido no está en la lista o que necesitas que busque algo primero.")
        return {"messages": [llm.invoke([instruccion, ultimo_mensaje])]}
        
    ruta_real = lista_juegos[idx - 1]
    
    try:
        if modo == "vscode":
            import subprocess
            subprocess.Popen(['code', ruta_real], shell=True)
            accion = "Abierto en Visual Studio Code"
        else:
            if os.path.exists(ruta_real):
                os.startfile(ruta_real)
                accion = "Ejecutado de forma nativa"
            else:
                accion = "Error: La ruta ya no existe"
    except Exception as e:
        accion = f"Error del sistema operativo: {e}"
        
    # Invocación final a NLG
    instruccion = SystemMessage(content=(
        f"Eres Onyx. Acabas de hacer esto en el PC: '{accion}' con el archivo '{os.path.basename(ruta_real)}'. "
        "Informa al usuario de forma natural y hablada (1 frase breve). NO leas la ruta completa del disco duro."
    ))
    respuesta = llm.invoke([instruccion, ultimo_mensaje])
    
    return {"messages": [respuesta]}

def nodo_charla(state: OnyxState):
    res = llm.invoke(state["messages"])
    return {"messages": [res]}

def nodo_preguntar_parametros(state: OnyxState):
    # Cogemos el último mensaje del usuario para que el LLM tenga el contexto
    ultimo_mensaje = state["messages"][-1]
    
    # Le damos la instrucción por sistema
    instruccion = SystemMessage(content=(
        "Eres Onyx, el asistente del sistema operativo. "
        "El usuario te ha pedido cambiar ajustes del entorno (brillo o volumen), "
        "pero se le ha olvidado decirte a qué nivel o porcentaje (0-100). "
        "Pregúntale de forma natural, muy breve y conversacional qué niveles desea."
    ))
    
    # Invocamos al LLM pasándole la instrucción y lo que dijo el usuario
    respuesta_dinamica = llm.invoke([instruccion, ultimo_mensaje])
    
    return {"messages": [respuesta_dinamica]}

def nodo_preguntar_termino(state: OnyxState):
    ultimo_mensaje = state["messages"][-1]
    
    instruccion = SystemMessage(content=(
        "Eres Onyx, el asistente del sistema. "
        "El usuario quiere que busques un archivo, juego o programa en el equipo, "
        "pero no te ha dicho el nombre. "
        "Pregúntale de forma natural y muy directa qué es exactamente lo que quiere buscar."
    ))
    
    respuesta_dinamica = llm.invoke([instruccion, ultimo_mensaje])
    
    return {"messages": [respuesta_dinamica]}

# ==========================================
# 5. ENRUTADORES CONDICIONALES
# ==========================================
def enrutador_maestro(state: OnyxState):
    intencion_cruda = state.get("intencion")
    intencion = intencion_cruda.lower().strip()
    
    if intencion == "ajustes": 
        return "evaluar_ajustes"
    elif intencion == "buscar": 
        return "evaluar_busqueda"
    elif intencion == "ejecutar": 
        return "ejecutor"
        
    return "charla"

def enrutador_ajustes(state: OnyxState):
    if state.get("nivel_brillo") is None and state.get("nivel_volumen") is None:
        return "nodo_preguntar_parametros"
    return ["ajustes_volumen", "ajustes_brillo"]

def enrutador_busqueda(state: OnyxState):
    if not state.get("termino_busqueda"):
        return "nodo_preguntar_termino"
        
    # Tus directorios del setup para escanear en paralelo (Map)
    directorios = [r"C:\Users\anyel\OneDrive\Escritorio", r"C:\Users\anyel", r"C:\Users\anyel\Documents", r"C:\Users\Program Files"]
    return [Send("buscar_worker", {"directorio_base": d, "termino_busqueda": state["termino_busqueda"]}) for d in directorios]

# ==========================================
# CONSTRUCCIÓN Y COMPILACIÓN DEL GRAFO
# ==========================================
builder = StateGraph(OnyxState)

# Declarar los nodos principales y auxiliares
builder.add_node("clasificador", nodo_clasificador)
builder.add_node("charla", nodo_charla)
builder.add_node("ejecutor", nodo_ejecutar_archivo)
builder.add_node("nodo_preguntar_parametros", nodo_preguntar_parametros)
builder.add_node("nodo_preguntar_termino", nodo_preguntar_termino)

# Nodos subflujo Ajustes
builder.add_node("ajustes_volumen", nodo_bajar_volumen)
builder.add_node("ajustes_brillo", nodo_bajar_brillo)
builder.add_node("ajustes_sintesis", nodo_sintesis_ajustes)

# Nodos subflujo Map-Reduce
builder.add_node("buscar_worker", nodo_buscar_archivos)
builder.add_node("buscar_sintesis", nodo_sintesis_busqueda)

# Flujo de Bordes y Enrutamientos
builder.add_edge(START, "clasificador")
builder.add_conditional_edges("clasificador", enrutador_maestro, {
    "evaluar_ajustes": "evaluar_ajustes_sub",
    "evaluar_busqueda": "evaluar_busqueda_sub",
    "ejecutor": "ejecutor",
    "charla": "charla"
})

# Orquestación virtual para ramificar Ajustes
builder.add_node("evaluar_ajustes_sub", lambda s: s)
builder.add_conditional_edges("evaluar_ajustes_sub", enrutador_ajustes, ["nodo_preguntar_parametros", "ajustes_volumen", "ajustes_brillo"])
builder.add_edge(["ajustes_volumen", "ajustes_brillo"], "ajustes_sintesis")
builder.add_edge("ajustes_sintesis", END)
builder.add_edge("nodo_preguntar_parametros", END)

# Orquestación virtual para Map-Reduce
builder.add_node("evaluar_busqueda_sub", lambda s: s)
builder.add_conditional_edges("evaluar_busqueda_sub", enrutador_busqueda, ["nodo_preguntar_termino", "buscar_worker"])
builder.add_edge("buscar_worker", "buscar_sintesis")
builder.add_edge("buscar_sintesis", END)
builder.add_edge("nodo_preguntar_termino", END)

builder.add_edge("ejecutor", END)
builder.add_edge("charla", END)

# COMPILACIÓN DEL AGENTE INTEGRADO
agente_onyx = builder.compile()

# ==========================================
# BUCLE INTERACTIVO (STT + TTS)
# ==========================================
if __name__ == "__main__":
    print("\n" + "*"*50)
    print("🖥️  Onyx OS Engine activo con Voice Interface")
    print("*"*50)
    
    estado_sesion = {
        "messages": [],
        "juegos_encontrados": [],
        "contexto_paralelo": []
    }
    
    hablar("Sistemas en línea. A tu disposición.")

    while True:
        # 1. Escuchamos por el micrófono
        usuario_input = escuchar()
        
        # Si no detectó voz o hubo un error, repetimos el bucle
        if not usuario_input:
            continue
            
        # Comando manual de emergencia para salir
        if "apagar sistema" in usuario_input.lower() or "salir" in usuario_input.lower():
            hablar("Desconectando módulos. Que tengas un buen día.")
            break
            
        estado_sesion["messages"].append(HumanMessage(content=usuario_input))
        
        # 2. Ejecución del Grafo
        resultado_grafo = agente_onyx.invoke(estado_sesion)
        
        estado_sesion["messages"] = resultado_grafo["messages"]
        if "juegos_encontrados" in resultado_grafo:
            estado_sesion["juegos_encontrados"] = resultado_grafo["juegos_encontrados"]
            
        # 3. El LLM Habla (La respuesta final generada por NLG)
        respuesta_final = resultado_grafo['messages'][-1].content
        hablar(respuesta_final)