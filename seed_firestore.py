# Copyright 2026 Google LLC
"""Script de poblado (seed) para la base de datos Firestore de ChambaBot."""

from google.cloud import firestore

# IMPORTANTE: ID del proyecto en duro como string para evitar 404s en Agent Platform
FIRESTORE_PROJECT = "qwiklabs-gcp-04-f5bd3592d475"

ITEMS_FERRETERIA = [
    {
        "id": "GAS-001",
        "nombre": "Regulador de Gas LP de Baja Presión (1 vía)",
        "categoria": "gas",
        "tipo_gas": ["lp", "butano"],
        "precio_mxn": 220.0,
        "stock": 15,
        "peligro": "alto",
        "descripcion": "Regulador estándar para cilindro de 20 o 30 kg o tanque estacionario doméstico.",
        "advertencia": "Usar únicamente cinta teflón amarilla para gas o sellador de roscas para gas. Jamás usar teflón blanco común.",
        "alias": ["regulador", "regulador lp", "cochinito", "tuerca de gas"],
    },
    {
        "id": "GAS-002",
        "nombre": "Manguera Flexible Coflex para Gas (3/8 x 3/8)",
        "categoria": "gas",
        "tipo_gas": ["lp", "natural", "butano"],
        "precio_mxn": 160.0,
        "stock": 25,
        "peligro": "alto",
        "descripcion": "Manguera trenzada de aluminio para conexión de estufas, secadoras y calentadores.",
        "advertencia": "Revisar fecha de caducidad. No apretar en exceso para evitar degollar el cono de bronce.",
        "alias": ["manguera de gas", "manguera estufa", "manguera coflex", "tubo flexible gas"],
    },
    {
        "id": "GAS-003",
        "nombre": "Cinta Teflón Amarillo para Gas (Alta Densidad)",
        "categoria": "gas",
        "tipo_gas": ["lp", "natural", "butano"],
        "precio_mxn": 35.0,
        "stock": 50,
        "peligro": "medio",
        "descripcion": "Cinta selladora de PTFE de alta densidad certificada para líneas de hidrocarburos.",
        "advertencia": "Aplicar en sentido horario de 3 a 5 vueltas. El teflón blanco de agua se disuelve con el gas.",
        "alias": ["teflon amarillo", "teflon gas", "cinta amarilla"],
    },
    {
        "id": "ELEC-001",
        "nombre": "Interruptor Termomagnético 20A (Pastilla / Breaker)",
        "categoria": "electricidad",
        "precio_mxn": 140.0,
        "stock": 30,
        "peligro": "critico",
        "descripcion": "Pastilla térmica de 1 polo 20 Amperes para riel o centro de carga QO.",
        "advertencia": "Bajar la palanca principal del medidor antes de manipular el centro de carga.",
        "alias": ["pastilla", "breaker", "termomagnetico", "pastilla termica", "pastilla de 20"],
    },
    {
        "id": "ELEC-002",
        "nombre": "Cable Eléctrico THW Calibre 12 AWG (Cobre)",
        "categoria": "electricidad",
        "precio_mxn": 18.0,
        "unidad": "metro",
        "stock": 500,
        "peligro": "alto",
        "descripcion": "Conductor de cobre suave de 19 hilos con aislamiento termoplástico resistente a 75°C.",
        "advertencia": "Soporta hasta 20A. Usar negro/rojo para Fase, blanco para Neutro, verde para Tierra.",
        "alias": ["cable", "alambre", "cable del 12", "cable para enchufes"],
    },
    {
        "id": "ELEC-003",
        "nombre": "Contacto Doble Polarizado con Tierra",
        "categoria": "electricidad",
        "precio_mxn": 65.0,
        "stock": 40,
        "peligro": "alto",
        "descripcion": "Tomacorriente dúplex 15A 125V con placa blanca incluida.",
        "advertencia": "Ranura chica = Fase. Ranura grande = Neutro. Entrada redonda = Tierra física.",
        "alias": ["enchufe", "contacto", "clavija de pared", "tomacorriente"],
    },
    {
        "id": "PLOM-001",
        "nombre": "Válvula de Descarga y Sapo para WC (3 pulgadas)",
        "categoria": "plomeria",
        "precio_mxn": 95.0,
        "stock": 20,
        "peligro": "bajo",
        "descripcion": "Kit de obturador y sapito de silicón con cadena de acero inoxidable resistente al cloro.",
        "advertencia": "Cerrar la llave de escuadra debajo de la taza antes de desmontar.",
        "alias": ["sapito", "sapo", "sapo de bano", "empaque de taza", "flotador"],
    },
    {
        "id": "PLOM-002",
        "nombre": "Cespol Flexible para Fregadero / Lavabo",
        "categoria": "plomeria",
        "precio_mxn": 75.0,
        "stock": 35,
        "peligro": "bajo",
        "descripcion": "Tubo extensible acordeón para desagüe con adaptadores universales para 1-1/4 y 1-1/2.",
        "advertencia": "Conservar la curvatura en 'U' o 'P' para trampa de agua, si no suben los olores del caño.",
        "alias": ["trampa", "cespol", "tubo acordeon", "desague", "cuello de ganso"],
    },
    {
        "id": "PLOM-003",
        "nombre": "Cinta Teflón Blanco para Plomería (Agua)",
        "categoria": "plomeria",
        "precio_mxn": 15.0,
        "stock": 60,
        "peligro": "bajo",
        "descripcion": "Cinta de teflón económica para tuberías roscadas de agua fría y caliente.",
        "advertencia": "Exclusivo para agua. NUNCA usar en líneas de gas.",
        "alias": ["teflon", "teflon blanco", "cinta teflon"],
    },
]


def seed_database():
    print(f"Conectando a Firestore en el proyecto: {FIRESTORE_PROJECT}...")
    db = firestore.Client(project=FIRESTORE_PROJECT)
    collection_ref = db.collection("materiales_tlapaleria")

    count = 0
    for item in ITEMS_FERRETERIA:
        doc_id = item["id"]
        collection_ref.document(doc_id).set(item)
        print(f" ✓ Guardado: {doc_id} - {item['nombre']}")
        count += 1

    print(f"\n¡Éxito! Se poblaron {count} refacciones en la colección 'materiales_tlapaleria'.")


if __name__ == "__main__":
    seed_database()
