import os
import operator
import subprocess
from typing import Annotated, Optional
from typing_extensions import TypedDict
import pyautogui
import screen_brightness_control as sbc
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import comtypes
import difflib

# Cargar variables de entorno (.env)
load_dotenv()

# ==========================================
# 1. ESTADO GLOBAL DE ONYX
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
# 2. MODELO DE EXTRACCIÓN UNIFICADO (Pydantic)
# ==========================================
class ClasificadorOnyx(BaseModel):
    intencion: str = Field(
        description="Clasifica la intención del usuario. Opciones: 'relax' (fatiga/descanso), 'buscar' (encontrar archivos/juegos), 'ejecutar' (abrir/lanzar una opción numérica), 'charla' (conversación normal)."
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
# 3. LLM CONFIGURACIÓN
# ==========================================
llm = AzureChatOpenAI(
    azure_deployment="gpt-4o-mini",
    api_version="2024-02-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0.0
)

# ==========================================
# 4. NODOS DEL GRAFO
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


def nodo_sintesis_relax(state: OnyxState):
    # Filtramos los mensajes para omitir los "sin cambios" y dejar un reporte limpísimo
    bloques = state.get("contexto_paralelo", [])
    cambios_reales = [b for b in bloques if "sin cambios" not in b]
    
    if cambios_reales:
        detalles = ", ".join(cambios_reales)
        msg = f"Onyx: Entorno relax configurado con éxito. ({detalles})"
    else:
        msg = "Onyx: No se han realizado modificaciones en el entorno."
        
    return {"messages": [AIMessage(content=msg)], "contexto_paralelo": []}

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
    
    # Parseamos las rutas reales ocultas en tus bloques de texto
    for bloque in bloques_contexto:
        for linea in bloque.split("\n"):
            if linea.startswith("PATH:"):
                rutas_limpias.append(linea.replace("PATH:", ""))
                
    if not rutas_limpias:
        msg = f"Onyx: No he encontrado nada relacionado con '{state.get('termino_busqueda')}' en tus directorios."
        return {"messages": [AIMessage(content=msg)], "contexto_paralelo": []}
        
    texto_out = "Onyx: He peinado tus carpetas en paralelo. Aquí tienes las opciones sobre la mesa:\n"
    for idx, ruta in enumerate(rutas_limpias, 1):
        texto_out += f"\n[{idx}] 📁 {os.path.basename(ruta)}\n   └─ Ruta: {ruta}"
    texto_out += "\n\nDime el número que quieres que ejecute (ej: 'ejecuta el 1' o 'abre el 2 en vscode')"
    
    return {
        "messages": [AIMessage(content=texto_out)],
        "juegos_encontrados": rutas_limpias, # Persiste la lista indexada en el estado
        "contexto_paralelo": []
    }

# --- Nodo de Acción Física (Ejecución y Apertura) ---
def nodo_ejecutar_archivo(state: OnyxState):
    idx = state.get("indice_ejecutar")
    lista_juegos = state.get("juegos_encontrados", [])
    modo = state.get("modo_apertura", "normal")
    
    if not lista_juegos:
        return {"messages": [AIMessage(content="Onyx: No tengo ninguna lista de archivos en caché. Primero pídeme buscar algo.")]}
        
    if idx is None or idx < 1 or idx > len(lista_juegos):
        return {"messages": [AIMessage(content=f"Onyx: El índice {idx} no corresponde a ninguna opción válida (1-{len(lista_juegos)}).")]}
        
    ruta_real = lista_juegos[idx - 1]
    
    try:
        if modo == "vscode":
            # Ejecuta 'code <ruta>' de forma asíncrona mediante la terminal de Windows
            subprocess.Popen(['code', ruta_real], shell=True)
            msg = f"💻 Abriendo ruta en Visual Studio Code:\n`{ruta_real}`"
        else:
            if os.path.exists(ruta_real):
                os.startfile(ruta_real) # os.startfile abre carpetas en explorador y arranca ejecutables
                if os.path.isdir(ruta_real):
                    msg = f"📁 Explorador de archivos abierto en:\n`{ruta_real}`"
                else:
                    msg = f"🚀 Ejecutando aplicación:\n`{ruta_real}`"
            else:
                msg = f"❌ Vaya, parece que la ruta ya no existe en el disco: `{ruta_real}`"
    except Exception as e:
        msg = f"❌ Error de Windows al procesar la acción: {e}"
        
    return {"messages": [AIMessage(content=msg)]}

def nodo_charla(state: OnyxState):
    res = llm.invoke(state["messages"])
    return {"messages": [res]}

def nodo_preguntar_parametros(state: OnyxState):
    return {"messages": [AIMessage(content="Onyx: De acuerdo, vamos a atenuar el entorno. ¿A qué nivel configuro el brillo y el volumen?")]}

def nodo_preguntar_termino(state: OnyxState):
    return {"messages": [AIMessage(content="Onyx: Por supuesto. ¿Qué juego, carpeta o archivo quieres que busque en el equipo?")]}

# ==========================================
# 5. ENRUTADORES CONDICIONALES
# ==========================================
def enrutador_maestro(state: OnyxState):
    intencion = state.get("intencion")
    if intencion == "relax": return "evaluar_relax"
    elif intencion == "buscar": return "evaluar_busqueda"
    elif intencion == "ejecutar": return "ejecutor"
    return "charla"

def enrutador_relax(state: OnyxState):
    if state.get("nivel_brillo") is None and state.get("nivel_volumen") is None:
        return "nodo_preguntar_parametros"
    return ["relax_volumen", "relax_brillo"] # Ejecución en Paralelo Estático

def enrutador_busqueda(state: OnyxState):
    if not state.get("termino_busqueda"):
        return "nodo_preguntar_termino"
        
    # Tus directorios del setup para escanear en paralelo (Map)
    directorios = [r"C:\Users\anyel\OneDrive\Escritorio", r"C:\Users\anyel", r"C:\Users\anyel\Documents", r"C:\Users\Program Files"]
    return [Send("buscar_worker", {"directorio_base": d, "termino_busqueda": state["termino_busqueda"]}) for d in directorios]

# ==========================================
# 6. CONSTRUCCIÓN Y COMPILACIÓN DEL GRAFO
# ==========================================
builder = StateGraph(OnyxState)

# Declarar los nodos principales y auxiliares
builder.add_node("clasificador", nodo_clasificador)
builder.add_node("charla", nodo_charla)
builder.add_node("ejecutor", nodo_ejecutar_archivo)
builder.add_node("nodo_preguntar_parametros", nodo_preguntar_parametros)
builder.add_node("nodo_preguntar_termino", nodo_preguntar_termino)

# Nodos subflujo Relax
builder.add_node("relax_volumen", nodo_bajar_volumen)
builder.add_node("relax_brillo", nodo_bajar_brillo)
builder.add_node("relax_sintesis", nodo_sintesis_relax)

# Nodos subflujo Map-Reduce
builder.add_node("buscar_worker", nodo_buscar_archivos)
builder.add_node("buscar_sintesis", nodo_sintesis_busqueda)

# Flujo de Bordes y Enrutamientos
builder.add_edge(START, "clasificador")
builder.add_conditional_edges("clasificador", enrutador_maestro, {
    "evaluar_relax": "evaluar_relax_sub",
    "evaluar_busqueda": "evaluar_busqueda_sub",
    "ejecutor": "ejecutor",
    "charla": "charla"
})

# Orquestación virtual para ramificar Relax
builder.add_node("evaluar_relax_sub", lambda s: s)
builder.add_conditional_edges("evaluar_relax_sub", enrutador_relax, ["nodo_preguntar_parametros", "relax_volumen", "relax_brillo"])
builder.add_edge(["relax_volumen", "relax_brillo"], "relax_sintesis")
builder.add_edge("relax_sintesis", END)
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
# 7. BUCLE INTERACTIVO DE CONSOLA
# ==========================================
if __name__ == "__main__":
    print("🖥️  Onyx OS Engine activo. Escribe 'salir' para finalizar.")
    
    # Mantenemos las variables persistentes (como la caché de juegos) vivas en la sesión de consola
    estado_sesion = {
        "messages": [],
        "juegos_encontrados": [],
        "contexto_paralelo": []
    }
    
    # Exportar el grafo a imagen para tu documentación/TFM si posees pygraphviz
    try:
        with open("grafo_arquitectura_onyx.png", "wb") as f:
            f.write(agente_onyx.get_graph().draw_mermaid_png())
        print("📊 Grafo de arquitectura exportado como 'grafo_arquitectura_onyx.png'")
    except:
        pass

    while True:
        usuario_input = input("\nAnalista: ")
        if usuario_input.lower() == 'salir':
            print("Apagando módulos de Onyx...")
            break
            
        estado_sesion["messages"].append(HumanMessage(content=usuario_input))
        
        # Ejecución a través del grafo integrado de LangGraph
        resultado_grafo = agente_onyx.invoke(estado_sesion)
        
        # Sincronizamos el estado de la sesión para mantener la memoria multi-turno
        estado_sesion["messages"] = resultado_grafo["messages"]
        if "juegos_encontrados" in resultado_grafo:
            estado_sesion["juegos_encontrados"] = resultado_grafo["juegos_encontrados"]
            
        print(f"\n{resultado_grafo['messages'][-1].content}")