# ruff: noqa
# Copyright 2026 Google LLC
"""ChambaBot: Asistente técnico de plomería, electricidad y gas con backend en Firestore."""

import re
from typing import Any, Dict, List, Optional
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager

from .a2ui_utils import a2ui_callback

MODEL = "gemini-2.5-flash"

# IMPORTANTE: IDs en duro como strings para evitar fallos de resolución en Agent Platform
GCP_PROJECT = "qwiklabs-gcp-04-f5bd3592d475"
FIRESTORE_PROJECT = GCP_PROJECT
STORAGE_BUCKET_NAME = "bwg3-qwiklabs-gcp-04-f5bd3592d475"

# Instancia global del cliente Firestore
_firestore_db: Optional[firestore.Client] = None


def get_db() -> firestore.Client:
    """Retorna una instancia reutilizable del cliente de Firestore con el project ID fijado."""
    global _firestore_db
    if _firestore_db is None:
        _firestore_db = firestore.Client(project=FIRESTORE_PROJECT)
    return _firestore_db


def consultar_catalogo_firestore(
    termino_busqueda: str, categoria: str = ""
) -> List[Dict[str, Any]]:
    """Consulta refacciones, herramientas y materiales directamente en la base de datos Firestore.
    Mapea términos coloquiales (ej. 'sapito', 'pastilla', 'cochinito', 'teflón') con el catálogo oficial
    y devuelve precio en pesos mexicanos, stock disponible y advertencias de seguridad.

    Args:
        termino_busqueda: Pieza que busca el usuario (ej: 'regulador de gas', 'pastilla termica', 'sapito').
        categoria: Opcional: 'gas', 'electricidad', 'plomeria'.

    Returns:
        Lista de documentos encontrados en Firestore con sus especificaciones y advertencias.
    """
    db = get_db()
    termino = termino_busqueda.lower().strip()
    categoria_filtro = categoria.lower().strip()
    collection_ref = db.collection("materiales_tlapaleria")

    query = collection_ref
    if categoria_filtro in ["gas", "electricidad", "plomeria"]:
        query = query.where("categoria", "==", categoria_filtro)

    docs = query.stream()
    resultados = []

    for doc in docs:
        data = doc.to_dict()
        nombre = data.get("nombre", "").lower()
        alias_list = [a.lower() for a in data.get("alias", [])]

        if termino in nombre or any(termino in a for a in alias_list) or any(a in termino for a in alias_list):
            resultados.append(data)

    # Si no hubo coincidencia exacta, búsqueda flexible por palabras clave
    if not resultados:
        docs = collection_ref.stream()
        palabras = [p for p in re.split(r"\s+", termino) if len(p) > 2]
        for doc in docs:
            data = doc.to_dict()
            if categoria_filtro and data.get("categoria") != categoria_filtro:
                continue
            nombre = data.get("nombre", "").lower()
            alias_list = [a.lower() for a in data.get("alias", [])]
            for p in palabras:
                if p in nombre or any(p in a for a in alias_list):
                    if data not in resultados:
                        resultados.append(data)

    return resultados


def registrar_material_en_firestore(
    nombre: str,
    categoria: str,
    precio_mxn: float,
    stock: int,
    peligro: str,
    advertencia: str,
    alias: str = "",
) -> Dict[str, Any]:
    """Registra o da de alta un nuevo material o refacción en la base de datos de Firestore.

    Args:
        nombre: Nombre técnico o comercial del producto (ej: 'Válvula de esfera para gas 1/2 pulgada').
        categoria: 'gas', 'electricidad', o 'plomeria'.
        precio_mxn: Precio estimado en pesos mexicanos.
        stock: Cantidad de piezas disponibles.
        peligro: Nivel de peligro de mala instalación: 'bajo', 'medio', 'alto', 'critico'.
        advertencia: Regla de seguridad esencial para su instalación.
        alias: Lista de apodos o nombres coloquiales separados por coma (ej: 'llave de gas, perico, valvula').

    Returns:
        Confirmación con el ID del documento creado en Firestore.
    """
    db = get_db()
    categoria_clean = categoria.lower().strip()
    prefix = "MAT"
    if "gas" in categoria_clean:
        prefix = "GAS"
    elif "elec" in categoria_clean:
        prefix = "ELEC"
    elif "plom" in categoria_clean:
        prefix = "PLOM"

    import random
    doc_id = f"{prefix}-{random.randint(100, 999)}"
    alias_list = [a.strip().lower() for a in alias.split(",") if a.strip()]

    nuevo_item = {
        "id": doc_id,
        "nombre": nombre,
        "categoria": categoria_clean,
        "precio_mxn": float(precio_mxn),
        "stock": int(stock),
        "peligro": peligro.lower(),
        "advertencia": advertencia,
        "alias": alias_list,
    }

    db.collection("materiales_tlapaleria").document(doc_id).set(nuevo_item)
    return {
        "status": "GUARDADO_EXITOSO",
        "id": doc_id,
        "item": nuevo_item,
        "mensaje": f"Se dio de alta '{nombre}' en Firestore bajo la colección 'materiales_tlapaleria'.",
    }


def actualizar_stock_compra(
    termino_o_id: str, cantidad: int, operacion: str = "compra"
) -> Dict[str, Any]:
    """Actualiza el stock de un material en Firestore al registrar una compra/consumo o reposición.

    Args:
        termino_o_id: Nombre de la refacción (ej. 'regulador', 'sapito') o su ID (ej. 'GAS-001').
        cantidad: Número de unidades a descontar o agregar.
        operacion: 'compra' (descuenta del stock) o 'reposicion' (suma al stock).

    Returns:
        Diccionario con el resultado de la operación, stock anterior y nuevo stock.
    """
    db = get_db()
    col = db.collection("materiales_tlapaleria")
    target_id = termino_o_id.strip()

    # Si no es ID directo, buscar primero en el catálogo
    doc_ref = col.document(target_id)
    doc_snap = doc_ref.get()

    if not doc_snap.exists:
        items = consultar_catalogo_firestore(target_id)
        if not items:
            return {"error": f"No se encontró ninguna refacción que coincida con '{termino_o_id}'."}
        target_id = items[0]["id"]
        doc_ref = col.document(target_id)
        doc_snap = doc_ref.get()

    data = doc_snap.to_dict()
    stock_actual = data.get("stock", 0)
    qty = abs(cantidad)

    if operacion.lower() in ["compra", "venta", "consumo", "descontar"]:
        if stock_actual < qty:
            return {
                "error": f"Stock insuficiente para '{data.get('nombre')}'. Stock actual: {stock_actual}, solicitado: {qty}."
            }
        nuevo_stock = stock_actual - qty
    else:
        nuevo_stock = stock_actual + qty

    doc_ref.update({"stock": nuevo_stock})
    return {
        "status": "ACTUALIZADO",
        "id": target_id,
        "nombre": data.get("nombre"),
        "stock_anterior": stock_actual,
        "nuevo_stock": nuevo_stock,
        "unidades_movidas": qty,
        "operacion": operacion,
    }


def consultar_clima_instalacion(ciudad_o_zona: str = "Ciudad de México") -> Dict[str, Any]:
    """Consulta el clima en tiempo real (temperatura, humedad y viento) mediante una API pública
    gratuita (Open-Meteo) para alertar sobre riesgos en instalaciones:
    - Heladas (congelamiento y ruptura de tuberías de agua expuestas).
    - Viento fuerte (apagado de pilotos en boilers o calentadores exteriores de gas).
    - Humedad extrema (riesgo de corto circuito o condensación en centros de carga).

    Args:
        ciudad_o_zona: Nombre de la ciudad, municipio o colonia (ej: 'Iztapalapa', 'Monterrey', 'Toluca').

    Returns:
        Diccionario con datos meteorológicos en tiempo real y alertas técnicas de plomería y gas.
    """
    import json
    import urllib.parse
    import urllib.request

    try:
        # 1. Geocodificar la zona para obtener coordenadas
        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode({"name": ciudad_o_zona, "count": 1})
        )
        req = urllib.request.Request(geo_url, headers={"User-Agent": "ChambaBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            geo_data = json.loads(resp.read().decode())

        if not geo_data.get("results"):
            lat, lon, nombre_resuelto = 19.4326, -99.1332, f"{ciudad_o_zona} (CDMX default)"
        else:
            loc = geo_data["results"][0]
            lat, lon = loc["latitude"], loc["longitude"]
            nombre_resuelto = f"{loc.get('name')}, {loc.get('admin1', '')} ({loc.get('country', '')})"

        # 2. Consultar clima actual
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
        )
        req_w = urllib.request.Request(weather_url, headers={"User-Agent": "ChambaBot/1.0"})
        with urllib.request.urlopen(req_w, timeout=5) as resp_w:
            w_data = json.loads(resp_w.read().decode())

        current = w_data.get("current", {})
        temp = current.get("temperature_2m", 20.0)
        hum = current.get("relative_humidity_2m", 50)
        viento = current.get("wind_speed_10m", 0.0)

        # 3. Diagnóstico de riesgos técnicos
        alertas = []
        if temp <= 3.0:
            alertas.append("PELIGRO DE HELADA: Aislar tuberías de cobre expuestas en azotea/patios para evitar que revienten.")
        if viento >= 25.0:
            alertas.append("VIENTO FUERTE: Riesgo de apagado del piloto del boiler de gas. No intentes encenderlo con ráfagas.")
        if hum >= 85:
            alertas.append("ALTA HUMEDAD: Verificar que centros de carga y pastillas exteriores tengan gabinete hermético NEMA.")

        if not alertas:
            alertas.append("Condiciones estables: sin riesgo climático severo para tuberías o pilotos de gas.")

        return {
            "ubicacion": nombre_resuelto,
            "temperatura_c": temp,
            "humedad_porcentaje": hum,
            "viento_kmh": viento,
            "alertas_tecnicas": alertas,
        }
    except Exception as exc:
        return {"error": f"No se pudo consultar el servicio meteorológico: {str(exc)}"}


async def generar_diagrama_instalacion(
    descripcion_diagrama: str, tool_context: ToolContext
) -> Dict[str, Any]:
    """Genera un diagrama visual o imagen explicativa para instalaciones de plomería, electricidad
    o gas usando el modelo 'gemini-3.1-flash-lite-image' en la región global de Vertex AI.
    Guarda la imagen como un artefacto en la sesión para el Playground y la sube al bucket público
    de Cloud Storage retornando su URL pública.

    Args:
        descripcion_diagrama: Lo que debe ilustrar el diagrama (ej: 'conexión de apagador de escalera',
                              'instalación de tanque de gas con regulador y estufa', 'trampa de fregadero').

    Returns:
        Diccionario con la URL pública en Cloud Storage y confirmación del artefacto guardado.
    """
    import uuid

    # 1. Conectar con Vertex AI en la región global para gemini-3.1-flash-lite-image
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location="global")

    prompt = (
        f"Clear, technical, educational diagram or illustration of: {descripcion_diagrama}. "
        "Show components clearly labeled (plumbing pipes, gas lines, or electrical wires with correct colors). "
        "Clean, professional DIY repair manual style."
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
    )

    # 2. Extraer los bytes de la imagen generada
    image_bytes = None
    mime_type = "image/jpeg"
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                image_bytes = part.inline_data.data
                if part.inline_data.mime_type:
                    mime_type = part.inline_data.mime_type
                break

    if not image_bytes:
        return {"error": "El modelo no generó bytes de imagen válidos."}

    # 3. Guardar artefacto en la sesión para el panel de Artifacts del Playground
    filename = f"diagrama_{uuid.uuid4().hex[:8]}.jpg"
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    artifact_version = await tool_context.save_artifact(
        filename=filename,
        artifact=artifact_part,
    )

    # 4. Subir los mismos bytes al bucket público de Cloud Storage
    storage_client = storage.Client(project=GCP_PROJECT)
    bucket = storage_client.bucket(STORAGE_BUCKET_NAME)
    blob = bucket.blob(f"diagramas/{filename}")
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET_NAME}/diagramas/{filename}"

    return {
        "status": "DIAGRAMA_GENERADO",
        "descripcion": descripcion_diagrama,
        "artifact_filename": filename,
        "artifact_version": artifact_version,
        "public_url": public_url,
        "mensaje": f"Diagrama generado con éxito. Visible en el panel de Artifacts como '{filename}' y disponible públicamente en Cloud Storage.",
    }


async def generar_video_demostrativo(
    descripcion_procedimiento: str, tool_context: ToolContext
) -> Dict[str, Any]:
    """Genera un video corto demostrativo para un procedimiento técnico en el dominio de ChambaBot
    (plomería, electricidad, gas, reparaciones del hogar) usando el modelo Google Omni ('gemini-omni-flash-preview')
    en la región 'global'.
    Guarda el video como un artefacto en la sesión con tool_context.save_artifact para que aparezca en el panel
    de Artifacts del Playground, y sube los mismos bytes del video al bucket público de Cloud Storage retornando su
    URL pública https (https://storage.googleapis.com/<bucket>/<object>).

    Args:
        descripcion_procedimiento: Explicación de la acción o procedimiento técnico a mostrar en el video corto
                                   (ej: 'técnica correcta para colocar cinta teflón en sentido horario sobre rosca de tubería',
                                   'cómo purgar aire de un calentador o boiler', 'comprobar con espuma de jabón fuga en manguera de gas').

    Returns:
        Diccionario con la URL pública en Cloud Storage (https://storage.googleapis.com/bwg3-qwiklabs-gcp-04-f5bd3592d475/videos/...),
        el nombre del artefacto guardado y detalles del video.
    """
    import base64
    import uuid

    # 1. Conectar con Vertex AI en la región global usando gemini-omni-flash-preview
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location="global")

    prompt = (
        f"Short instructional clip demonstrating: {descripcion_procedimiento}. "
        "Professional technical handyman tutorial style, clear close-up camera angles, "
        "accurate physical movements, showing step-by-step repair or installation practice."
    )

    try:
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )
    except Exception as exc:
        return {"error": f"Fallo al invocar el modelo gemini-omni-flash-preview: {str(exc)}"}

    # 2. Extraer los bytes del video MP4 generado de los steps de la interacción
    video_bytes = None
    mime_type = "video/mp4"

    steps = getattr(interaction, "steps", []) or []
    for step in steps:
        output_items = getattr(step, "output", []) or []
        for out in output_items:
            # Buscar inline_data con data base64 o bytes
            inline_data = getattr(out, "inline_data", None)
            if inline_data:
                data = getattr(inline_data, "data", None)
                if data:
                    if isinstance(data, str):
                        try:
                            video_bytes = base64.b64decode(data)
                        except Exception:
                            video_bytes = data.encode("utf-8")
                    else:
                        video_bytes = data
                    if getattr(inline_data, "mime_type", None):
                        mime_type = inline_data.mime_type
                    break
            # Revisar si el out mismo tiene data o bytes
            if hasattr(out, "data") and getattr(out, "data", None):
                raw_data = out.data
                if isinstance(raw_data, str):
                    try:
                        video_bytes = base64.b64decode(raw_data)
                    except Exception:
                        video_bytes = raw_data.encode("utf-8")
                else:
                    video_bytes = raw_data
                if hasattr(out, "mime_type") and out.mime_type:
                    mime_type = out.mime_type
                break
        if video_bytes:
            break

    if not video_bytes:
        return {"error": "El modelo gemini-omni-flash-preview no devolvió bytes de video válidos."}

    # 3. Guardar el artefacto en la sesión para el panel de Artifacts del Playground
    filename = f"video_{uuid.uuid4().hex[:8]}.mp4"
    artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
    artifact_version = await tool_context.save_artifact(
        filename=filename,
        artifact=artifact_part,
    )

    # 4. Subir los mismos bytes al bucket público de Cloud Storage (hardcodeado como string)
    storage_client = storage.Client(project=GCP_PROJECT)
    bucket = storage_client.bucket(STORAGE_BUCKET_NAME)
    blob = bucket.blob(f"videos/{filename}")
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET_NAME}/videos/{filename}"

    return {
        "status": "VIDEO_GENERADO",
        "descripcion": descripcion_procedimiento,
        "artifact_filename": filename,
        "artifact_version": artifact_version,
        "public_url": public_url,
        "mensaje": f"Video demostrativo generado con éxito. Visible en el panel de Artifacts como '{filename}' y disponible públicamente en Cloud Storage.",
    }


def triage_seguridad_urgente(servicio: str, sintoma_o_descripcion: str) -> Dict[str, Any]:
    """Evalúa de inmediato una situación reportada por el usuario en lenguaje coloquial para determinar
    si existe peligro inminente (fuga de gas, corto circuito, chispas, olor a quemado, inundación)
    y devuelve las órdenes de seguridad inmediatas que el usuario DEBE acatar antes de cualquier otra cosa.

    Args:
        servicio: Tipo de servicio afectado: 'gas', 'electricidad', 'plomeria' o 'desconocido'.
        sintoma_o_descripcion: Lo que el usuario dice que pasa (ej: 'huele a gas feo', 'saca chispas', 'chiflido').

    Returns:
        Un diccionario con el nivel_riesgo ('CRITICO', 'ALTO', 'MODERADO', 'BAJO'),
        orden_inmediata (lo que debe hacer en friega), y que NO debe hacer bajo ninguna circunstancia.
    """
    texto = (sintoma_o_descripcion + " " + servicio).lower()

    if any(k in texto for k in ["gas", "huele a gas", "chiflido", "estufa", "cilindro", "tanque", "boiler", "mercaptano"]):
        if any(k in texto for k in ["huele", "olor", "fuerte", "chiflido", "fuga", "siseo", "mareo"]):
            return {
                "servicio": "gas",
                "nivel_riesgo": "CRITICO - PELIGRO DE EXPLOSIÓN",
                "orden_inmediata": "1. CIERRA DE INMEDIATO LA LLAVE DE PASO DEL TANQUE O LA RED. 2. ABRE TODAS LAS PUERTAS Y VENTANAS PARA VENTILAR.",
                "prohibido_hacer": "NO prendas cerillos, NO toques apagadores ni conectes/desconectes nada (la chispa detona el gas). NO uses el celular adentro de la zona con olor.",
                "paso_siguiente": "Una vez ventilado y cerrada la llave, revisa conexiones con agua y jabón (burbujas). Si el olor no cede, sal de la casa y llama a bomberos/emergencias.",
            }

    if any(k in texto for k in ["chispa", "luz", "toque", "toques", "humo", "quemado", "corto", "caliente", "enchufe", "contacto", "breaker", "pastilla"]):
        if any(k in texto for k in ["chispa", "humo", "toque", "fuego", "ardiendo", "tronó", "flamazo"]):
            return {
                "servicio": "electricidad",
                "nivel_riesgo": "CRITICO - RIESGO DE ELECTROCUCIÓN O INCENDIO",
                "orden_inmediata": "BAJA LA PASTILLA O INTERRUPTOR GENERAL EN EL CENTRO DE CARGA INMEDIATAMENTE.",
                "prohibido_hacer": "NO toques el cable pelón ni el aparato con las manos descubiertas. NUNCA toques nada eléctrico si estás descalzo o mojado. NO eches agua.",
                "paso_siguiente": "Con la pastilla abajo, desconecta el aparato dañado o espera a inspeccionar el cableado con multímetro o probador de fase.",
            }

    if any(k in texto for k in ["agua", "tubo", "fuga de agua", "inundando", "chorro", "gotera", "tinaco", "fregadero", "taza"]):
        if any(k in texto for k in ["inunda", "chorro", "reventó", "tiradero"]):
            return {
                "servicio": "plomeria",
                "nivel_riesgo": "ALTO - INUNDACIÓN ACTIVA",
                "orden_inmediata": "CIERRA LA LLAVE DE PASO GENERAL DE AGUA O LA LLAVE DE ESCUADRA LOCAL.",
                "prohibido_hacer": "NO permitas que el agua llegue a contactos eléctricos en el suelo o extensiones (si hay riesgo de agua tocando luz, baja la pastilla eléctrica primero).",
                "paso_siguiente": "Coloca cubetas/trapos, drena la presión residual abriendo una llave baja y localiza la rotura o empaque vencido.",
            }

    return {
        "servicio": servicio,
        "nivel_riesgo": "MODERADO / BAJO",
        "orden_inmediata": "Identifica con precisión de dónde proviene el ruido, goteo o anomalía sin manipular conexiones presurizadas o energizadas.",
        "prohibido_hacer": "No fuerces tuercas con herramientas inadecuadas ni retires piezas sin cerrar llaves o bajar corriente.",
        "paso_siguiente": "Describe el síntoma exacto o busca la refacción necesaria en el catálogo.",
    }


def calcular_dimensionamiento(tipo_calculo: str, valor_1: float, valor_2: float, unidad_extra: str = "") -> Dict[str, Any]:
    """Realiza cálculos de ingeniería práctica para evitar accidentes e incendios:
    1. 'calibre_cable': Calcula el calibre de cable (AWG) necesario según los Watts de carga (valor_1) y el Voltaje (valor_2: 110V o 220V).
    2. 'tipo_gas_esprea': Compara presiones y requerimientos de esprea entre Gas LP y Gas Natural.

    Args:
        tipo_calculo: 'calibre_cable' o 'gas_compatibilidad'.
        valor_1: Primer valor numérico (ej. Watts de carga).
        valor_2: Segundo valor numérico (ej. Voltaje 110 o 220).
        unidad_extra: Información complementaria (ej. 'lp', 'natural', 'butano').

    Returns:
        Diccionario con el resultado del cálculo técnico y recomendaciones de norma.
    """
    tipo = tipo_calculo.lower()

    if "cable" in tipo or "amperaje" in tipo:
        watts = valor_1
        voltaje = valor_2 if valor_2 > 0 else 110.0
        amperes = watts / voltaje

        if amperes <= 10:
            calibre = "14 AWG (Soporta hasta 15A - alumbrado)"
            pastilla = "Pastilla de 15A"
        elif amperes <= 16:
            calibre = "12 AWG (Soporta hasta 20A - contactos generales)"
            pastilla = "Pastilla de 20A"
        elif amperes <= 24:
            calibre = "10 AWG (Soporta hasta 30A - aires acondicionados, bombas)"
            pastilla = "Pastilla de 30A"
        elif amperes <= 36:
            calibre = "8 AWG (Soporta hasta 40A-50A - regadera eléctrica/centro de carga)"
            pastilla = "Pastilla de 40A o 50A"
        else:
            calibre = "6 AWG o superior (Carga pesada)"
            pastilla = "Pastilla de 60A+"

        return {
            "calculo": "Selección de Calibre Eléctrico",
            "potencia_watts": watts,
            "voltaje_v": voltaje,
            "corriente_calculada_amperes": round(amperes, 2),
            "calibre_conductor_recomendado": calibre,
            "proteccion_termomagnetica": pastilla,
            "regla_de_oro": "La pastilla protege al cable, no al aparato. Nunca pongas una pastilla más grande que la capacidad del cable o se quema la instalación.",
        }

    if "gas" in tipo:
        gas_origen = unidad_extra.lower() if unidad_extra else "lp"
        return {
            "calculo": "Normativa y Compatibilidad de Gas",
            "gas_especificado": gas_origen,
            "diferencia_critica": "El Gas LP tiene mayor poder calorífico y se entrega a mayor presión (~28-30 mbar) que el Gas Natural (~18-20 mbar).",
            "regla_espreas": "Las espreas para Gas Natural tienen orificios MÁS GRANDES. Las de Gas LP tienen orificios MÁS CHICOS. Si conectas Gas LP en equipo para Gas Natural sin calibrar espreas, el flamazo es inmenso y peligroso.",
            "sellado": "Usar siempre teflón amarillo de alta densidad o pasta selladora para gas. El teflón blanco de agua se disuelve con el gas y fuga.",
        }

    return {"error": f"Tipo de cálculo no reconocido: {tipo_calculo}"}


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "Eres ChambaBot, el asistente maestro de plomería, electricidad y gas (LP, Natural, Butano). "
        "Tu misión es dar soluciones técnicas certeras, claras y sin rodeos, protegiendo SIEMPRE la vida del usuario. "
        "REGLAS DE ORO: "
        "1. SEGURIDAD INMEDIATA: Si hay olor a gas, chispas o cortos, usa triage_seguridad_urgente de inmediato. "
        "2. CATÁLOGO FIRESTORE: Consulta o registra materiales tlapaleros con consultar_catalogo_firestore o registrar_material_en_firestore. "
        "3. CÁLCULOS: Usa calcular_dimensionamiento o el sandbox de Python cuando requieras fórmulas complejas. "
        "4. RESISTENCIA: Mantén tu temple técnico de maestro chambeador directo y confiable."
    ),
    workflow_description="Analyze the request, call relevant tools, and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

AGENT_ENGINE_RESOURCE = "projects/660544112157/locations/us-central1/reasoningEngines/8330172221158850560"
SANDBOX_RESOURCE = "projects/660544112157/locations/us-central1/reasoningEngines/8330172221158850560/sandboxEnvironments/952102852619141120"

code_executor = AgentEngineSandboxCodeExecutor(
    sandbox_resource_name=SANDBOX_RESOURCE,
    agent_engine_resource_name=AGENT_ENGINE_RESOURCE,
)

# WRITE: after each turn, send the session to Memory Bank for extraction.
async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


root_agent = Agent(
    name="simple_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
    tools=[
        PreloadMemoryTool(),
        triage_seguridad_urgente,
        consultar_catalogo_firestore,
        registrar_material_en_firestore,
        actualizar_stock_compra,
        consultar_clima_instalacion,
        generar_diagrama_instalacion,
        generar_video_demostrativo,
        calcular_dimensionamiento,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
