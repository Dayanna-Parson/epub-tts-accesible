import os
import json
from datetime import datetime
import wx

class ControlCuota:
    def __init__(self):
        self.ruta_uso = os.path.join("configuraciones", "uso_cuota.json")
        # Límites por defecto (basados en la info que me diste)
        self.limites_defecto = {
            "azure": 500000,      # 500k caracteres (Capa gratuita)
            "polly": 1000000,     # 1 Millón (Capa gratuita estándar)
            "elevenlabs": 10000,  # 10k (Plan gratis)
            "local": 999999999    # SAPI5 es gratis infinito
        }
        self.datos = self.cargar_datos()

    def cargar_datos(self):
        datos_base = {
            "mes_actual": datetime.now().month,
            "gastado": {"azure": 0, "polly": 0, "elevenlabs": 0, "local": 0},
            "limites": self.limites_defecto.copy()
        }
        
        if os.path.exists(self.ruta_uso):
            try:
                with open(self.ruta_uso, 'r') as f:
                    cargado = json.load(f)
                    # Fusionar por si faltan claves nuevas
                    datos_base.update(cargado)
                    # Asegurar que existen sub-diccionarios
                    if "gastado" not in datos_base: datos_base["gastado"] = {"azure": 0, "polly": 0, "elevenlabs": 0, "local": 0}
                    if "limites" not in datos_base: datos_base["limites"] = self.limites_defecto.copy()
                    return datos_base
            except: pass
        return datos_base

    def guardar_datos(self):
        try:
            os.makedirs("configuraciones", exist_ok=True)
            with open(self.ruta_uso, 'w') as f: json.dump(self.datos, f, indent=4)
        except: pass

    def reiniciar_contadores_si_mes_nuevo(self):
        mes_hoy = datetime.now().month
        if mes_hoy != self.datos.get("mes_actual"):
            print("📅 ¡Nuevo mes! Reiniciando contadores de cuota.")
            self.datos["mes_actual"] = mes_hoy
            self.datos["gastado"] = {"azure": 0, "polly": 0, "elevenlabs": 0, "local": 0}
            self.guardar_datos()

    def verificar_y_registrar(self, texto, proveedor):
        """
        Retorna TRUE si hay saldo. Retorna FALSE si se pasó el límite.
        """
        self.reiniciar_contadores_si_mes_nuevo()
        
        prov_key = proveedor.lower()
        if "azure" in prov_key: clave = "azure"
        elif "polly" in prov_key: clave = "polly"
        elif "eleven" in prov_key: clave = "elevenlabs"
        else: return True # Local siempre es gratis

        cantidad = len(texto)
        gastado = self.datos["gastado"].get(clave, 0)
        limite = self.datos["limites"].get(clave, 0)
        
        # Comprobar límite
        if gastado + cantidad > limite:
            wx.MessageBox(
                f"🚫 ¡ALTO! Se ha detenido la lectura por seguridad.\n\n"
                f"Proveedor: {clave.upper()}\n"
                f"Has gastado: {gastado} chars\n"
                f"Intentaste leer: {cantidad} chars\n"
                f"Límite configurado: {limite}\n\n"
                "Se usará la voz LOCAL para no generar costes extra.",
                "Escudo de Presupuesto Activo"
            )
            return False
        
        # Registrar gasto
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