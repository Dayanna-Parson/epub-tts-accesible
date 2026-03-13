import os
import json
import logging
from datetime import datetime
import wx
from app.config_rutas import ruta_config

logger = logging.getLogger(__name__)


class ControlCuota:
    def __init__(self):
        self.ruta_uso = ruta_config("uso_cuota.json")
        # Límites mensuales por defecto (basados en las capas gratuitas de cada proveedor)
        self.limites_defecto = {
            "azure": 500000,      # 500 000 caracteres (Capa gratuita)
            "polly": 1000000,     # 1 000 000 (Capa gratuita estándar, primer año)
            "elevenlabs": 10000,  # 10 000 (Plan gratuito)
            "local": 999999999    # SAPI5 es gratuito e ilimitado
        }
        self.datos = self.cargar_datos()

    def cargar_datos(self):
        datos_base = {
            "mes_actual": datetime.now().month,
            "gastado": {"azure": 0, "polly": 0, "elevenlabs": 0, "local": 0},
            "limites": self.limites_defecto.copy()
        }

        if not os.path.exists(self.ruta_uso):
            return datos_base

        try:
            with open(self.ruta_uso, 'r', encoding='utf-8') as f:
                cargado = json.load(f)

            datos_base["mes_actual"] = cargado.get("mes_actual", datos_base["mes_actual"])

            # Fusionar sub-dicts: los valores del archivo sobreescriben los por defecto
            # solo para las claves que existen en el archivo, preservando claves nuevas
            gastado_guardado = cargado.get("gastado", {})
            for k in datos_base["gastado"]:
                if k in gastado_guardado:
                    datos_base["gastado"][k] = gastado_guardado[k]

            limites_guardados = cargado.get("limites", {})
            for k in datos_base["limites"]:
                if k in limites_guardados:
                    datos_base["limites"][k] = limites_guardados[k]

            return datos_base

        except Exception as e:
            logger.warning("[ControlCuota] No se pudo leer uso_cuota.json: %s", e)

        return datos_base

    def guardar_datos(self):
        try:
            os.makedirs(os.path.dirname(self.ruta_uso), exist_ok=True)
            with open(self.ruta_uso, 'w', encoding='utf-8') as f:
                json.dump(self.datos, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.warning("[ControlCuota] No se pudo guardar uso_cuota.json: %s", e)

    def reiniciar_contadores_si_mes_nuevo(self):
        mes_hoy = datetime.now().month
        if mes_hoy != self.datos.get("mes_actual"):
            logger.info("[ControlCuota] Nuevo mes detectado. Reiniciando contadores.")
            self.datos["mes_actual"] = mes_hoy
            self.datos["gastado"] = {"azure": 0, "polly": 0, "elevenlabs": 0, "local": 0}
            self.guardar_datos()

    def verificar_y_registrar(self, texto, proveedor):
        """
        Retorna True si hay saldo suficiente y registra el gasto.
        Retorna False y muestra aviso si se supera el límite configurado.
        """
        self.reiniciar_contadores_si_mes_nuevo()

        prov_key = proveedor.lower()
        if "azure" in prov_key:
            clave = "azure"
        elif "polly" in prov_key:
            clave = "polly"
        elif "eleven" in prov_key:
            clave = "elevenlabs"
        else:
            return True  # Voz local: gratuita e ilimitada

        cantidad = len(texto)
        gastado = self.datos["gastado"].get(clave, 0)
        limite = self.datos["limites"].get(clave, 0)

        if gastado + cantidad > limite:
            wx.MessageBox(
                f"¡ALTO! Se ha detenido la lectura por seguridad.\n\n"
                f"Proveedor: {clave.upper()}\n"
                f"Has gastado: {gastado} caracteres\n"
                f"Intentaste leer: {cantidad} caracteres\n"
                f"Límite configurado: {limite}\n\n"
                "Se usará la voz LOCAL para no generar costes extra.",
                "Escudo de Presupuesto Activo"
            )
            return False

        # Registrar el gasto y guardar inmediatamente
        self.datos["gastado"][clave] = gastado + cantidad
        self.guardar_datos()
        return True

    def get_info_uso(self, proveedor):
        clave = proveedor.lower()
        gastado = self.datos["gastado"].get(clave, 0)
        limite = self.datos["limites"].get(clave, 0)
        return gastado, limite

    def set_limite(self, proveedor, nuevo_limite):
        clave = proveedor.lower()
        self.datos["limites"][clave] = int(nuevo_limite)
        self.guardar_datos()

    def tiene_cuota(self, texto, proveedor):
        """
        Consulta silenciosa: retorna True si hay cuota disponible para el texto dado,
        sin mostrar diálogos ni registrar el gasto.
        """
        self.reiniciar_contadores_si_mes_nuevo()
        prov_key = proveedor.lower()
        if "azure" in prov_key:
            clave = "azure"
        elif "polly" in prov_key:
            clave = "polly"
        elif "eleven" in prov_key:
            clave = "elevenlabs"
        else:
            return True  # Voz local: siempre disponible

        gastado = self.datos["gastado"].get(clave, 0)
        limite = self.datos["limites"].get(clave, 0)
        return gastado + len(texto) <= limite

    def registrar_gasto(self, texto, proveedor):
        """
        Registra el gasto del texto para el proveedor indicado, sin mostrar diálogos.
        Se usa cuando ya se verificó que hay cuota (vía tiene_cuota).
        """
        prov_key = proveedor.lower()
        if "azure" in prov_key:
            clave = "azure"
        elif "polly" in prov_key:
            clave = "polly"
        elif "eleven" in prov_key:
            clave = "elevenlabs"
        else:
            return  # Voz local: no se registra
        self.datos["gastado"][clave] = self.datos["gastado"].get(clave, 0) + len(texto)
        self.guardar_datos()
