import os
import requests
from typing import Annotated
from dotenv import load_dotenv

from azure.identity import AzureCliCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage

# Importaciones específicas de la arquitectura de LangGraph
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

# Cargar variables de entorno
load_dotenv()

# ==========================================
# 1. HERRAMIENTAS (TOOLS)
# ==========================================
@tool
def buscar_calendario_o_plantillas(
    endpoint_id: Annotated[str, "El endpoint exacto a consultar. Formato: 'matches/43/106.json' o 'lineups/NUMERO.json'."]
) -> dict:
    """Busca el calendario de partidos o las plantillas/alineaciones completas."""
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/{endpoint_id}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if "matches" in endpoint_id:
            return {"partidos": [{
                "match_id": p.get("match_id"),
                "fecha": p.get("match_date"),
                "fase": p.get("competition_stage", {}).get("name"),
                "equipo_local": p.get("home_team", {}).get("home_team_name"),
                "equipo_visitante": p.get("away_team", {}).get("away_team_name"),
                "goles_local": p.get("home_score"),
                "goles_visitante": p.get("away_score")
            } for p in data]}
        return data
    return {"error": f"Error {response.status_code} al consultar StatsBomb."}

@tool
def obtener_estadisticas_partido(
    match_id: Annotated[str, "El ID numérico del partido. Ejemplo: '3869685'."]
) -> dict:
    """Devuelve un resumen estadístico básico por equipo (tiros, pases, faltas)."""
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{match_id}.json"
    response = requests.get(url)
    if response.status_code != 200:
        return {"error": "No se encontraron eventos para este partido."}
        
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
                
    return {"resumen_estadisticas": stats}

@tool
def obtener_estadisticas_jugador(
    match_id: Annotated[str, "El ID numérico del partido. Ejemplo: '3869685'."],
    nombre_jugador: Annotated[str, "El nombre o apellido del jugador a buscar. Ejemplo: 'Morata' o 'Pedri'."]
) -> dict:
    """Procesa los eventos de un partido y devuelve el resumen estadístico de un jugador concreto."""
    url = f"https://raw.githubusercontent.com/statsbomb/open-data/master/data/events/{match_id}.json"
    response = requests.get(url)
    
    if response.status_code != 200:
        return {"error": "No se encontraron eventos para este partido."}
        
    stats = {"tiros": 0, "goles": 0, "pases": 0, "faltas_cometidas": 0}
    eventos_encontrados = False
    
    for ev in response.json():
        # Saltamos los eventos que no estén asociados a un jugador concreto (ej. fin de la primera parte)
        if 'player' not in ev:
            continue
            
        nombre_evento = ev['player']['name']
        
        # Búsqueda parcial: comprobamos si el nombre que pide el agente está dentro del nombre oficial
        if nombre_jugador.lower() in nombre_evento.lower():
            eventos_encontrados = True
            ev_type = ev.get('type', {}).get('name')
            
            if ev_type == "Pass": stats["pases"] += 1
            elif ev_type == "Foul Committed": stats["faltas_cometidas"] += 1
            elif ev_type == "Shot":
                stats["tiros"] += 1
                if ev.get('shot', {}).get('outcome', {}).get('name') == "Goal":
                    stats["goles"] += 1
                    
    if not eventos_encontrados:
        return {"error": f"No se ha encontrado a '{nombre_jugador}' en este partido. Es posible que no jugara o que necesites comprobar su nombre oficial en las alineaciones."}
        
    return {f"estadisticas_de_{nombre_jugador}": stats}

tools = [buscar_calendario_o_plantillas, obtener_estadisticas_partido, obtener_estadisticas_jugador]

# ==========================================
# 2. CONFIGURACIÓN DEL LLM
# ==========================================
token_provider = get_bearer_token_provider(AzureCliCredential(), "https://cognitiveservices.azure.com/.default")

llm = AzureChatOpenAI(
    azure_deployment="gpt-4o-mini",
    api_version="2024-02-15-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_ad_token_provider=token_provider,
    temperature=0.2
)

# Enlazamos las herramientas al modelo
llm_with_tools = llm.bind_tools(tools)

SYSTEM_PROMPT = """
Eres un experto ojeador y director deportivo del Mundial de Qatar 2022. 
Tienes acceso a StatsBomb Open Data. Utiliza tus herramientas estratégicamente:

1. Partidos y Resultados: matches/43/106.json
2. Alineaciones y Plantillas: lineups/{match_id}.json
3. Estadísticas de EQUIPO: Usa EXCLUSIVAMENTE 'obtener_estadisticas_partido'.
4. Estadísticas de JUGADOR: Usa EXCLUSIVAMENTE 'obtener_estadisticas_jugador'. Si no sabes el nombre oficial del jugador, búscalo primero en las alineaciones.

REGLAS:
- Lee hasta el final para incluir todas las fases.
- Presenta TODOS los datos (Tiros, Goles, Pases, Faltas).
- Interpreta el partido (dominio, efectividad).
- PROHIBIDO usar tablas de Markdown (|). Usa viñetas y negritas (**Texto**).
"""

# ==========================================
# 3. DEFINICIÓN DE LOS NODOS
# ==========================================

# Este es el nodo principal: la mente del agente
def assistant(state: MessagesState):
    # 1. Inyectamos las instrucciones del sistema al principio de la memoria
    sys_msg = SystemMessage(content=SYSTEM_PROMPT)
    messages = [sys_msg] + state["messages"]
    
    # 2. Invocamos al LLM con el historial completo
    response = llm_with_tools.invoke(messages)
    
    # 3. Devolvemos el nuevo mensaje para que se añada al estado global
    return {"messages": [response]}

# ==========================================
# 4. CONSTRUCCIÓN DEL GRAFO (El Enrutador)
# ==========================================
builder = StateGraph(MessagesState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "assistant")

graph = builder.compile()