"""Servicio de extracción de métricas tácticas (Simulador de Visión Artificial)."""
import json

def get_tactical_metrics(team: str) -> dict:
    """
    Simula la extracción de métricas tácticas basadas en visión artificial.
    Devuelve los datos procesados o un diccionario genérico.
    """
    team_lower = team.lower()

    # Patrón táctico específico simulado
    if "atleti" in team_lower or "atlético" in team_lower:
        return {
            "equipo": "Atlético de Madrid",
            "formacion_detectada": "4-4-2",
            "distancia_entre_lineas_m": 12.5,
            "altura_bloque_defensivo_m": 35.2,
            "ppda": 9.4, # Passes allowed per defensive action
            "anotaciones_cv": "Bloque medio-bajo muy compacto. Las líneas de defensa y mediocampo mantienen sincronía perfecta en la basculación lateral."
        }
    elif "madrid" in team_lower:
        return {
            "equipo": "Real Madrid",
            "formacion_detectada": "4-3-3",
            "distancia_entre_lineas_m": 18.2,
            "altura_bloque_defensivo_m": 48.5,
            "ppda": 11.2,
            "anotaciones_cv": "Distancia amplia entre líneas centrales. Tendencia a romper la línea defensiva en transiciones rápidas."
        }
    else:
        # Respuesta genérica de respaldo
        return {
            "equipo": team.title(),
            "formacion_detectada": "Desconocida",
            "distancia_entre_lineas_m": 15.0,
            "altura_bloque_defensivo_m": 40.0,
            "ppda": 10.5,
            "anotaciones_cv": "Líneas equilibradas. No se detectan anomalías estructurales significativas en la extracción de frames."
        }

if __name__ == "__main__":
    # Prueba directa del servicio
    print(get_tactical_metrics("Atlético de Madrid"))