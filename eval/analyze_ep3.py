"""Análisis de observaciones sanitizadas y matriz de hipótesis; sin inferencias de calidad real."""
from collections import Counter,defaultdict
from pathlib import Path
import argparse
import json
from src.ep3.lectura import cargar
from src.ep3.analisis import resumen,percentil,reintentos

def analizar(ruta: Path, salida: Path, evaluacion: Path | None=None):
    datos=cargar(ruta);salida.mkdir(parents=True,exist_ok=False)
    por_origen={}
    for origen in ('real','simulada','historica'):
        eventos=[e for e in datos.eventos if e['tipo_ejecucion']==origen]
        if not eventos: continue
        etapas=defaultdict(list)
        for e in eventos:
            if e.get('duracion_ms') is not None: etapas[e['evento']].append(e['duracion_ms'])
        por_origen[origen]={'kpi':resumen(eventos),'etapas':{k:{'n':len(v),'promedio_ms':sum(v)/len(v),'p95_ms':percentil(v,.95)} for k,v in etapas.items()},
            'reintentos':reintentos(eventos),'codigos_error':dict(Counter(e['codigo'] for e in eventos if e['estado']=='error')),
            'ejemplos_errores':[{'ejecucion_id':e['ejecucion_id'],'evento_id':e['evento_id'],'codigo':e['codigo']} for e in eventos if e['evento']=='modelo_error'][:8]}
    informe={'version':2,'origenes_separados':por_origen,'registros_invalidos':datos.invalidos,
             'limites':['Duraciones de etapas inclusivas: no sumar herramientas y RAG como tiempos independientes.',
                       'Un modelo simulado no permite identificar cuellos de botella de Groq o calidad generativa real.']}
    if evaluacion: informe['evaluacion']=json.loads(evaluacion.read_text(encoding='utf-8'))['benchmark']
    (salida/'analisis.json').write_text(json.dumps(informe,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lineas=['# Análisis EP3 de registros observados','',f'Fuente: `{ruta.name}`. Los resultados se separan por origen.','',
            '| Hallazgo observado | Evidencia concreta | Impacto | Hipótesis (no demostrada) | Propuesta | Riesgo / costo | Verificación |',
            '|---|---|---|---|---|---|---|']
    for origen,d in por_origen.items():
        k=d['kpi'];errores=d['ejemplos_errores']
        lineas.append(f"| {origen}: {k['consultas']} consultas, {k['muestras_latencia']} tiempos, P95 {k['p95_ms']} ms | analisis.json/origenes_separados/{origen}/kpi | Describe solo esta muestra | El volumen y el modelo condicionan los tiempos | Repetir con condiciones documentadas | Bajo; nuevas corridas | Comparar mismos escenarios y tamaños de muestra |")
        if errores:
            e=errores[0]
            lineas.append(f"| {origen}: errores de modelo observados | trace `{e['ejecucion_id']}`, evento `{e['evento_id']}`, `{e['codigo']}` | Puede interrumpir o recuperar una consulta | Inyección controlada si el origen es simulado | Conservar clasificación, correlacionar con llamada_fin | Bajo; sin cambiar reintentos | Revisar resultado definitivo de cada llamada_id |")
    model=[e for e in datos.eventos if e['evento']=='modelo_fin']
    conocidos=sum(e['detalles'].get('tokens_entrada') is not None for e in model)
    lineas.append(f'| Tokens de entrada disponibles en {conocidos}/{len(model)} respuestas | Eventos modelo_fin y detalles.origen_tokens | No se puede afirmar consumo faltante ni costo | El doble de modelo puede no informar uso | Mantener NULL y ejecutar prueba real autorizada | Consumo externo; pendiente | Inspeccionar usage del proveedor sin guardar mensajes |')
    lineas.extend(['','## Alcance del benchmark','',
        'Los pares comparan responder() en caliente con bases temporales equivalentes, orden balanceado y semilla fija. El vaciado de la cola está fuera de la ventana medida.',
        'El benchmark local sin espera de red puede amplificar el porcentaje de sobrecarga. Los deltas pueden ser negativos por variación del proceso; no se recortan ni se ocultan.',
        'No se aplicaron optimizaciones especulativas a prompts, herramientas o planificación. Se mantiene la cola acotada y escritura por lotes. Una optimización adicional requiere medir antes y después.',
        '','## Límites para la interpretación','',
        '- No se midió Groq, exactitud generativa real, carga multiusuario ni precisión semántica de embeddings reales.',
        '- Las comprobaciones de calidad comparan hechos, documentos e invariantes contra referencias controladas; no usan similitud FAISS como exactitud.',
        '- Esta matriz proporciona evidencia e hipótesis técnicas; los estudiantes deben elaborar sus propias conclusiones y justificar sus decisiones.'])
    (salida/'hallazgos.md').write_text('\n'.join(lineas)+'\n',encoding='utf-8')
    return informe

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--salida',type=Path,required=True);p.add_argument('--evaluacion',type=Path)
    a=p.parse_args();r=analizar(a.base,a.salida,a.evaluacion);print(json.dumps({k:v['kpi'] for k,v in r['origenes_separados'].items()}));return 0

if __name__=='__main__': raise SystemExit(main())
