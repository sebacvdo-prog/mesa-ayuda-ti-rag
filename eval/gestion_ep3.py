"""Preparación local explícita de HMAC, exportación sanitizada y esquemas."""
from pathlib import Path
import argparse
import csv
import json
import os
from eval.aislamiento_ep3 import Aislamiento,configurar_offline
from eval.check_ep3_regression import RAIZ

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('accion',choices=['clave','verificar-hmac','exportar','esquemas'])
    p.add_argument('--ruta',type=Path,required=True);p.add_argument('--salida',type=Path)
    a=p.parse_args();configurar_offline()
    # La creación explícita de clave no usa datos, agentes ni proveedores.
    if a.accion=='clave':
        from src.ep3.identidad import crear_clave
        crear_clave(a.ruta);print('Clave local creada; su contenido no se muestra.');return 0
    with Aislamiento(RAIZ):
        if a.accion=='verificar-hmac':
            from src.ep3.identidad import leer_clave
            from src.ep3.observabilidad import Observabilidad
            with Observabilidad(a.ruta.parent/'verificacion',clave_sesion=leer_clave(a.ruta),tipo_ejecucion='simulada') as obs:
                traza=obs.iniciar('ep2',('verificacion_sintetica','sesion_sintetica','agente')).traza
            dato={'pid':os.getpid(),'sesion_ref':traza.sesion_ref,'clave_id':traza.clave_id,'tipo_ejecucion':'simulada'}
            if a.salida:
                with a.salida.open('x',encoding='utf-8') as f: json.dump(dato,f,indent=2)
            print(json.dumps(dato));return 0
        if a.accion=='esquemas':
            from src.ep3.contratos_v2 import EventoV2,TrazaV2,Evaluacion
            a.ruta.mkdir(parents=True,exist_ok=True)
            for nombre,modelo in [('evento',EventoV2),('traza',TrazaV2),('evaluacion',Evaluacion)]:
                destino=a.ruta/f'ep3_{nombre}_v2.schema.json'
                with destino.open('x',encoding='utf-8') as f: json.dump(modelo.model_json_schema(),f,ensure_ascii=False,indent=2)
            return 0
        from src.ep3.lectura import cargar
        datos=cargar(a.ruta)
        if a.salida is None: p.error('exportar requiere --salida')
        a.salida.mkdir(parents=True,exist_ok=False)
        (a.salida/'eventos.json').write_text(json.dumps(datos.eventos,ensure_ascii=False,indent=2),encoding='utf-8')
        campos=['version_esquema','ejecucion_id','evento_id','fecha_utc','tipo_ejecucion','evento','componente','estado','codigo','duracion_ms']
        with (a.salida/'eventos.csv').open('x',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=campos,extrasaction='ignore');w.writeheader();w.writerows(datos.eventos)
    return 0

if __name__=='__main__': raise SystemExit(main())
