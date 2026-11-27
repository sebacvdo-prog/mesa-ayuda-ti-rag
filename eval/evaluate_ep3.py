"""Evaluación OFFLINE: referencias estructuradas y benchmark pareado; sin LLM juez."""
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import argparse
import csv
import hashlib
import json
import random
import sqlite3
import sys
from importlib import metadata
from eval.aislamiento_ep3 import Aislamiento,configurar_offline
from eval.check_ep3_regression import RAIZ,artefactos

def ejecutar(salida: Path, pares=30):
    if not 2<=pares<=100: raise ValueError('Usa entre 2 y 100 pares.')
    configurar_offline();salida=salida.resolve();salida.mkdir(parents=True,exist_ok=False)
    antes=artefactos()
    fuentes={str(p.relative_to(RAIZ)):hashlib.sha256(p.read_bytes()).hexdigest()
             for carpeta in ('src','eval') for p in (RAIZ/carpeta).rglob('*.py')}
    with Aislamiento(RAIZ) as guardia:
        from eval.escenarios_ep3 import ejecutar_caso,recuperador,CASOS
        from src.ep3.observabilidad import Observabilidad
        from src.ep3.contratos_v2 import Evaluacion
        from src.ep3.almacenamiento import AlmacenObservabilidad
        from src.ep3.analisis import percentil
        rag=recuperador();filas=[];resultados=[];banco=[]
        with TemporaryDirectory(prefix='ep3-eval-') as temporal, Observabilidad(salida,tipo_ejecucion='simulada',clave_sesion=b'clave_sintetica_solo_evaluacion_32') as obs:
            base=Path(temporal)
            for caso in CASOS:
                for variante in range(1,6 if caso=='seguridad' else 4):
                    r=ejecutar_caso(base/f'{caso}_{variante}',caso,variante,obs,rag)
                    resultados.append(r)
            obs.flush(10)
            with closing(sqlite3.connect((salida/'observabilidad.db').as_uri()+'?mode=ro',uri=True)) as c:
                trazas=c.execute("SELECT ejecucion_id,categoria FROM trazas WHERE categoria!='benchmark' ORDER BY rowid").fetchall()
            # Cada evaluación se enlaza con la consulta concreta de su variante.
            for r in resultados:
                trace=r['ejecucion_id']
                from uuid import UUID
                for metrica,metodo,valor in r['referencias']:
                    filas.append(Evaluacion(evaluacion_id=uuid4(),ejecucion_id=UUID(trace) if trace else None,
                        tipo_ejecucion='simulada',caso=r['caso'],variante=r['variante'],metrica=metrica,
                        metodo=metodo,valor=valor,muestras=1))
            for caso in ('ticket_sla','rag_kb','impacto','nota','posponer','sin_procedimiento'):
                firmas=[r['firma'] for r in resultados if r['caso']==caso]
                acuerdo=max(firmas.count(f) for f in firmas)/len(firmas)
                filas.append(Evaluacion(evaluacion_id=uuid4(),tipo_ejecucion='simulada',caso=caso,variante=1,
                    metrica='consistencia',metodo='acuerdo_entre_variantes',valor=acuerdo,muestras=len(firmas)))
            # Calentamiento separado de las muestras. El temporizador solo abarca responder().
            ejecutar_caso(base/'warm_off','ticket_sla',1,None,rag)
            ejecutar_caso(base/'warm_on','ticket_sla',1,obs,rag)
            azar=random.Random(20261126)
            ordenes=[bool(i%2) for i in range(pares)];azar.shuffle(ordenes)
            for i in range(pares):
                orden=[True,False] if ordenes[i] else [False,True];medidas={};firmas={}
                for activa in orden:
                    from src.ep3.instrumentacion import categoria
                    with categoria('benchmark'):
                        r=ejecutar_caso(base/f'bench_{i}_{activa}','ticket_sla',1,obs if activa else None,rag,categoria_override='benchmark')
                    medidas[activa]=sum(r['latencias_ms']);firmas[activa]=r['firma']
                banco.append({'par':i+1,'orden':'on_off' if orden[0] else 'off_on',
                              'off_ms':medidas[False],'on_ms':medidas[True],
                              'delta_ms':medidas[True]-medidas[False],
                              'sobrecarga_pct':100*(medidas[True]-medidas[False])/medidas[False],
                              'equivalente':firmas[False]==firmas[True]})
            vaciada=obs.flush(15);salud=obs.estadisticas()
        almacen=AlmacenObservabilidad(salida)
        try: almacen.guardar_evaluaciones(filas)
        finally: almacen.cerrar()
        medidas={}
        for campo in ('off_ms','on_ms','delta_ms','sobrecarga_pct'):
            valores=[p[campo] for p in banco]
            medidas[campo]={'n':len(valores),'promedio':sum(valores)/len(valores),'p50':percentil(valores,.5),'p95':percentil(valores,.95)}
        metricas={}
        for nombre in sorted({f.metrica for f in filas}):
            grupo=[f for f in filas if f.metrica==nombre]
            metricas[nombre]={'registros':len(grupo),'muestras':sum(f.muestras for f in grupo),
                              'promedio_ponderado':sum(f.valor*f.muestras for f in grupo)/sum(f.muestras for f in grupo)}
        corpus={str(p.relative_to(RAIZ)):hashlib.sha256(p.read_bytes()).hexdigest()
                for carpeta in ('data/internos','data/externos') for p in (RAIZ/carpeta).glob('*.md')}
    reporte={'version':2,'fecha_utc':datetime.now(timezone.utc).isoformat(),'tipo_ejecucion':'simulada',
             'python':sys.version,'fuentes_sha256':fuentes,
             'dependencias':{p:metadata.version(p) for p in ('langchain','langchain-core','langchain-openai','faiss-cpu','streamlit','pydantic')},
             'casos':len(resultados),'resultados':[{k:v for k,v in r.items() if k not in ('referencias','firma')} for r in resultados],
             'metricas':metricas,'benchmark':medidas,'pares':banco,'semilla':20261126,
             'corpus_sha256':corpus,'salud':salud,'controles':guardia.controles,
             'artefactos_originales_intactos':antes==artefactos(),
             'limites':['LLM y vectores simulados; no mide calidad de Groq ni precisión semántica del embedding.',
                       'Consistencia solo entre paráfrasis equivalentes, no entre fallas inyectadas distintas.',
                       'Benchmark local en caliente, sin latencia de red; no extrapolar sobrecarga porcentual a producción.']}
    reporte['aprobado']=(vaciada and all(r['restricciones'] for r in resultados)
        and all(f.valor==1 for f in filas) and all(p['equivalente'] for p in banco)
        and guardia.aprobado() and reporte['artefactos_originales_intactos']
        and salud['descartados']==salud['fallos_instrumentacion']==salud['fallos_almacenamiento']==0)
    (salida/'evaluacion.json').write_text(json.dumps(reporte,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (salida/'evaluaciones.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(filas[0].model_dump()));w.writeheader();w.writerows(x.model_dump(mode='json') for x in filas)
    with (salida/'benchmark.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(banco[0]));w.writeheader();w.writerows(banco)
    return reporte

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--salida',type=Path,required=True);p.add_argument('--pares',type=int,default=30)
    args=p.parse_args();r=ejecutar(args.salida,args.pares)
    print(json.dumps({k:r[k] for k in ('aprobado','casos','metricas','benchmark','controles','artefactos_originales_intactos')},ensure_ascii=False))
    return 0 if r['aprobado'] else 1

if __name__=='__main__': raise SystemExit(main())
