#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_polly_debug.py — Diagnóstico completo de Amazon Polly
===========================================================
Ejecutar desde la raíz del proyecto:
    python test_polly_debug.py

No abre la interfaz gráfica. Solo necesita Python y la consola.
Imprime el error exacto de cada paso para que sepas exactamente qué falla.
"""

import os
import sys
import json

# ── Añadir raíz del proyecto al path para importar los módulos de la app ──
RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

SEP = "=" * 60


def ok(msg):  print(f"    ✓ {msg}")
def fallo(msg): print(f"    ✗ {msg}")
def info(msg): print(f"    → {msg}")


print(SEP)
print("DIAGNÓSTICO DE AMAZON POLLY — Epub TTS Accesible")
print(SEP)

# ──────────────────────────────────────────────────────────
# PASO 1: ¿boto3 está instalado?
# ──────────────────────────────────────────────────────────
print("\n[PASO 1] Comprobando boto3...")
try:
    import boto3
    ok(f"boto3 instalado: versión {boto3.__version__}")
except ImportError as e:
    fallo("boto3 NO está instalado.")
    info(f"Error exacto: {e}")
    info("Solución:  pip install boto3")
    info("Si usas un entorno virtual, actívalo primero.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# PASO 2: ¿sounddevice y soundfile están instalados?
# ──────────────────────────────────────────────────────────
print("\n[PASO 2] Comprobando librerías de audio...")
try:
    import sounddevice as sd
    import soundfile as sf
    import io
    ok("sounddevice y soundfile disponibles.")
except ImportError as e:
    fallo(f"Librería de audio faltante: {e}")
    info("Solución: pip install sounddevice soundfile")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# PASO 3: ¿Existe config_general.json?
# ──────────────────────────────────────────────────────────
print("\n[PASO 3] Leyendo config_general.json...")
ruta_cfg = os.path.join(RAIZ, "configuraciones", "config_general.json")
print(f"    Ruta: {ruta_cfg}")

if not os.path.exists(ruta_cfg):
    fallo("El archivo NO existe.")
    info("Ve a Ajustes > Claves y Proveedores, introduce las claves y guarda.")
    sys.exit(1)

try:
    with open(ruta_cfg, 'r', encoding='utf-8') as f:
        config = json.load(f)
    ok(f"JSON cargado. Secciones presentes: {list(config.keys())}")
except Exception as e:
    fallo(f"Error leyendo JSON: {e}")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# PASO 4: ¿Las credenciales de Polly están en el JSON?
# ──────────────────────────────────────────────────────────
print("\n[PASO 4] Leyendo credenciales de Amazon Polly...")
po_conf = config.get("polly", {})
print(f"    Sección 'polly' en el JSON: {po_conf}")

access_key = po_conf.get("access_key", "").strip()
secret_key = po_conf.get("secret_key", "").strip()
region_raw = po_conf.get("region", "").strip()
region = region_raw if region_raw else "us-east-1"

if access_key:
    ok(f"Access Key presente ({len(access_key)} caracteres).")
else:
    fallo("Access Key VACÍA.")
    info("Ve a Ajustes > Claves y Proveedores > Amazon Polly.")

if secret_key:
    ok(f"Secret Key presente ({len(secret_key)} caracteres).")
else:
    fallo("Secret Key VACÍA.")
    info("Ve a Ajustes > Claves y Proveedores > Amazon Polly.")

print(f"    Región raw='{region_raw}' → se usará='{region}'")

if not access_key or not secret_key:
    info("No se puede continuar sin credenciales.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# PASO 5: ¿Se puede conectar a Polly y listar voces?
# ──────────────────────────────────────────────────────────
print("\n[PASO 5] Conectando a Amazon Polly (describe_voices)...")
try:
    cliente = boto3.client(
        "polly",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    respuesta = cliente.describe_voices(LanguageCode="es-ES")
    voces_es = respuesta.get("Voices", [])
    ok(f"Conexión exitosa. Voces en español: {len(voces_es)}")
    for v in voces_es[:5]:
        info(f"  {v['Id']} — {v['Name']} ({v['Gender']}) "
             f"[{', '.join(v.get('SupportedEngines', []))}]")
except Exception as e:
    fallo(f"Error de conexión a Polly: {e}")
    info("Causas comunes:")
    info("  · Credenciales incorrectas o expiradas")
    info("  · Región inválida (prueba 'us-east-1')")
    info("  · Sin acceso a internet")
    info("  · La cuenta AWS no tiene permisos para Polly")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# PASO 6: ¿Se puede sintetizar audio?
# ──────────────────────────────────────────────────────────
print("\n[PASO 6] Sintetizando texto de prueba (voz: Lucia, neural)...")
TEXTO_PRUEBA = "Hola, Amazon Polly funciona correctamente."
try:
    try:
        res = cliente.synthesize_speech(
            Engine="neural",
            Text=TEXTO_PRUEBA,
            TextType="text",
            OutputFormat="ogg_vorbis",
            VoiceId="Lucia",
        )
        ok("Motor 'neural' disponible.")
    except Exception as e_neural:
        info(f"Motor 'neural' no disponible ({e_neural}). Probando 'standard'…")
        res = cliente.synthesize_speech(
            Engine="standard",
            Text=TEXTO_PRUEBA,
            TextType="text",
            OutputFormat="ogg_vorbis",
            VoiceId="Lucia",
        )
        ok("Motor 'standard' disponible.")

    audio_bytes = res["AudioStream"].read()
    data, fs = sf.read(io.BytesIO(audio_bytes))
    ok(f"Audio sintetizado: {len(data)} muestras a {fs} Hz.")

    print("\n[PASO 7] Reproduciendo audio de prueba...")
    sd.play(data, fs)
    sd.wait()
    ok("Reproducción completada sin errores.")

except Exception as e:
    fallo(f"Error en síntesis: {e}")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
# FIN
# ──────────────────────────────────────────────────────────
print("\n" + SEP)
print("✓ TODOS LOS PASOS SUPERADOS — Amazon Polly está configurado correctamente.")
print("  Si la app sigue sin mostrar voces de Polly, ve a:")
print("  Ajustes > Claves y Proveedores > 'Comprobar y descargar'")
print(SEP)
