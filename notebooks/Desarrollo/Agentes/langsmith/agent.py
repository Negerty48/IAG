import os
import httpx
import operator
from typing import Annotated, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.types import Send
from langgraph.graph import StateGraph, START, END, MessagesState

load_dotenv()

# ==========================================
# 1. ESTADO GLOBAL DE ONYX
# ==========================================
class OnyxState(MessagesState):
    match_id: Optional[str]
    lista_jugadores: list[str]
    contexto_paralelo: Annotated[list, operator.add]
    respuesta_cruda: Optional[str]

# ==========================================
# 2. MODELO DE EXTRACCIÓN (Pydantic)
# ==========================================
class ParametrosBusqueda(BaseModel):
    equipo_1: str = Field(description="Nombre en INGLÉS del primer equipo (ej. 'France'). Vacío si no aplica.", default="")
    equipo_2: str = Field(description="Nombre en INGLÉS del segundo equipo. Vacío si no aplica.", default="")
    jugadores: list[str] = Field(
        description="Lista de jugadores a analizar. REGLA: Si el usuario NO menciona a ningún jugador, propón tú una lista con los 3 jugadores estrella/más importantes de los equipos mencionados.", 
        default_factory=list
    )

# ==========================================
# 3. CONFIGURACIÓN DEL LLM
# ==========================================
llm = AzureChatOpenAI(
    azure_deployment="gpt-4o-mini",
    api_version="2024-02-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0.2
)

# ==========================================
# 4. NODOS DEL GRAFO
# ==========================================

# --- NODO 1: CONSEGUIR MATCH_ID ---
async def nodo_conseguir_id(state: OnyxState):
    ultimo_mensaje = state["messages"][-1].content
    extractor = llm.with_structured_output(ParametrosBusqueda)
    info = await extractor.ainvoke(ultimo_mensaje)
    
    match_id = None
    if info.equipo_1:
        url_calendario = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/matches/43/106.json"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url_calendario)
            if response.status_code == 200:
                datos = response.json()
                for p in datos:
                    local = p.get("home_team", {}).get("home_team_name", "").lower()
                    visitante = p.get("away_team", {}).get("away_team_name", "").lower()
                    eq1, eq2 = info.equipo_1.lower(), info.equipo_2.lower()
                    
                    if eq1 and eq2:
                        if (eq1 in local or eq1 in visitante) and (eq2 in local or eq2 in visitante):
                            match_id = str(p["match_id"])
                            break
                    elif eq1:
                        if eq1 in local or eq1 in visitante:
                            match_id = str(p["match_id"])
                            break
        except Exception as e:
            print(f"Error en calendario: {e}")
            
    return {"match_id": match_id, "lista_jugadores": info.jugadores}


# --- NODO 2A: ESTADÍSTICAS DEL EQUIPO ---
async def nodo_stats_equipo(state: OnyxState):
    match_id = state.get("match_id")
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{match_id}.json"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        if response.status_code == 200:
            stats = {}
            for ev in response.json():
                if 'team' not in ev: continue
                team = ev['team']['name']
                if team not in stats:
                    stats[team] = {"tiros": 0, "goles": 0, "pases": 0, "faltas_cometidas": 0}
                ev_type = ev.get('type', {}).get('name')
                if ev_type == "Pass": stats[team]["pases"] += 1
                elif ev_type == "Foul Committed": stats[team]["faltas_cometidas"] += 1
                elif ev_type == "Shot":
                    stats[team]["tiros"] += 1
                    if ev.get('shot', {}).get('outcome', {}).get('name') == "Goal":
                        stats[team]["goles"] += 1
            return {"contexto_paralelo": [f"RESUMEN EQUIPOS:\n{stats}"]}
    except:
        pass
    return {"contexto_paralelo": []}

# --- NODO 2B: ESTADÍSTICAS DEL JUGADOR ---
async def nodo_stats_jugador(state: dict): 
    match_id = state.get("match_id")
    jugador = state.get("jugador_objetivo")
    
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{match_id}.json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
        if response.status_code == 200:
            stats = {"tiros": 0, "goles": 0, "pases": 0, "faltas_cometidas": 0}
            encontrado = False
            for ev in response.json():
                if 'player' not in ev: continue
            
                nombre_oficial = ev['player']['name'].lower()
                
                # Dividimos el nombre que buscamos en palabras individuales (ej. ["lionel", "messi"])
                partes_buscadas = jugador.lower().split()
                
                # Verificamos si TODAS las partes buscadas están en el nombre oficial
                if all(parte in nombre_oficial for parte in partes_buscadas):
                    encontrado = True
                    ev_type = ev.get('type', {}).get('name')
                    
                    if ev_type == "Pass": stats["pases"] += 1
                    elif ev_type == "Foul Committed": stats["faltas_cometidas"] += 1
                    elif ev_type == "Shot":
                        stats["tiros"] += 1
                        if ev.get('shot', {}).get('outcome', {}).get('name') == "Goal":
                            stats["goles"] += 1
            if encontrado:
                return {"contexto_paralelo": [f"RENDIMIENTO DE {jugador.upper()}:\n{stats}"]}
    except:
        pass
    return {"contexto_paralelo": []}

# --- NODO 3: SÍNTESIS DEL LLM ---
async def nodo_sintesis(state: OnyxState):
    contexto = "\n\n".join(state.get("contexto_paralelo", []))
    peticion_usuario = state["messages"][-1].content
    
    prompt_fuerte = (
        "Eres el Analista de Rendimiento Principal de un club de élite.\n\n"
        f"El usuario ha solicitado lo siguiente: '{peticion_usuario}'\n\n"
        "Aquí tienes los datos puros extraídos de StatsBomb para este partido:\n"
        f"{contexto}\n\n"
        "TU TAREA OBLIGATORIA AHORA MISMO ES REDACTAR EL INFORME FINAL. DEBES INCLUIR ESTRICTAMENTE:\n"
        "1. Un resumen de los datos globales de los equipos.\n"
        "2. Una comparativa analítica real de los jugadores evaluados (no te limites a listar números, crúzalos).\n"
        "3. La elección del Jugador Más Valioso (MVP) con una justificación táctica basada en estos datos.\n\n"
        "PROHIBIDO decir 'Si necesitas más detalles dímelo'. HAZ EL ANÁLISIS DETALLADO AHORA."
    )
    
    # Invocamos al LLM pasándole SOLO esta orden contundente como usuario humano
    from langchain_core.messages import HumanMessage
    respuesta = await llm.ainvoke([HumanMessage(content=prompt_fuerte)])
    
    return {"respuesta_cruda": respuesta.content}


# --- NODO 4: SALVAVIDAS TELEGRAM (Resumidor) ---
async def nodo_resumen_telegram(state: OnyxState):
    texto_final = state.get("respuesta_cruda", "")
    
    # Si el texto excede el límite de Telegram, obligamos al LLM a resumirlo
    if len(texto_final) > 4000:
        instruccion_resumen = (
            "El siguiente análisis táctico es demasiado largo para Telegram. "
            "Resúmelo estrictamente a menos de 4000 caracteres, conservando obligatoriamente "
            f"las métricas clave (goles, pases, tiros). Texto original:\n\n{texto_final}"
        )
        resumen = await llm.ainvoke(instruccion_resumen)
        texto_final = resumen.content

    # Añadimos la respuesta definitiva a 'messages' para que main.py pueda leerla e imprimirla
    return {"messages": [AIMessage(content=texto_final)]}

# ==========================================
# EL ENRUTADOR PRINCIPAL
# ==========================================
def enrutador_partido(state: OnyxState):
    match_id = state.get("match_id")
    
    # Si no hay partido, vamos directo al nodo de síntesis a charlar
    if not match_id:
        return "sintesis"
        
    # Si hay partido, mandamos el flujo a la "caja negra" (el subgrafo completo)
    return "subflujo_stats"

# ==========================================
# EL ENRUTADOR DINÁMICO (MAP)
# ==========================================

def enrutador_subflujo(state: OnyxState):
    # 1. El equipo SIEMPRE se ejecuta una vez. Lo pasamos como un string normal.
    peticiones = ["stats_equipo"] 
    
    # 2. Los jugadores se lanzan dinámicamente con Map-Reduce (Send)
    for jugador in state.get("lista_jugadores", []):
        peticiones.append(
            Send("stats_jugador", {"match_id": state["match_id"], "jugador_objetivo": jugador})
        )
        
    # LangGraph ejecutará toda esta lista a la vez de forma paralela
    return peticiones

# --- CREACIÓN DEL SUBGRAFO PARALELO HÍBRIDO ---
sub_builder = StateGraph(OnyxState)
sub_builder.add_node("stats_equipo", nodo_stats_equipo)
sub_builder.add_node("stats_jugador", nodo_stats_jugador) # Recuerda que este nodo ahora recibe el 'dict' del Send

# La puerta de entrada es dinámica: arranca desde START y lanza la lista mixta
sub_builder.add_conditional_edges(
    START, 
    enrutador_subflujo, 
    ["stats_equipo", "stats_jugador"] # Le decimos qué nodos existen dentro para que valide
)

# Todas las ramas, sean 2 o sean 10, convergen y mueren juntas en el END del subgrafo
sub_builder.add_edge("stats_equipo", END)
sub_builder.add_edge("stats_jugador", END)

subflujo_compilado = sub_builder.compile()

# --- CREACIÓN DEL GRAFO PRINCIPAL ---
builder = StateGraph(OnyxState)

builder.add_node("identificador", nodo_conseguir_id)
builder.add_node("subflujo_stats", subflujo_compilado) # Metemos la caja negra
builder.add_node("sintesis", nodo_sintesis)
builder.add_node("resumen_telegram", nodo_resumen_telegram)

# Flujo maestro lineal
builder.add_edge(START, "identificador")
builder.add_conditional_edges("identificador", enrutador_partido) # Decide si hay partido o solo charla
builder.add_edge("subflujo_stats", "sintesis") # Espera a que termine la caja negra
builder.add_edge("sintesis", "resumen_telegram")
builder.add_edge("resumen_telegram", END)