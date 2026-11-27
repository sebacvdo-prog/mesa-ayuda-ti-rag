"""Agregaciones explícitas sobre observaciones, nunca rellena métricas ausentes."""
import math
import pandas as pd

def tabla(eventos):
    filas = []
    for e in eventos:
        d = {**e}
        # Metadatos de presentación explícitamente desconocidos en v1, sin
        # inventar categoría o correlación ni reescribir el evento persistido.
        d.setdefault('categoria','no_disponible_v1')
        d.setdefault('correlacion','legado_no_estable')
        d.setdefault('clave_id',None)
        d.setdefault('operacion','no_disponible_v1')
        detalle = d.pop('detalles', {})
        d.update(detalle)
        filas.append(d)
    return pd.DataFrame(filas)

def percentil(valores, q):
    v = sorted(float(x) for x in valores if x is not None and math.isfinite(float(x)))
    if not v: return None
    indice = (len(v)-1)*q
    a = int(indice)
    return v[a]+(v[min(a+1,len(v)-1)]-v[a])*(indice-a)

def resumen(eventos):
    finales = [e for e in eventos if e['evento']=='consulta_fin']
    duraciones = [e['duracion_ms'] for e in finales if e.get('duracion_ms') is not None]
    return {'consultas':len(finales),'ok':sum(e['estado']=='ok' for e in finales),
            'fallas_tecnicas':sum(e['estado'] in ('error','limite') for e in finales),
            'pendientes':sum(e['estado']=='requiere_confirmacion' for e in finales),
            'muestras_latencia':len(duraciones),'promedio_ms':sum(duraciones)/len(duraciones) if duraciones else None,
            'p50_ms':percentil(duraciones,.5),'p95_ms':percentil(duraciones,.95),
            'solicitudes_llm':sum(e['evento']=='modelo_inicio' and e.get('detalles',{}).get('frontera')=='llm' for e in eventos),
            'decisiones':sum(e['evento']=='decision' for e in eventos)}

def reintentos(eventos):
    grupos = {}
    for e in eventos:
        d = e.get('detalles',{})
        identificador = d.get('llamada_id')
        if not identificador: continue
        if e['evento']=='modelo_reintento':
            grupos.setdefault(identificador, {'llamada_id':identificador,'reintentos':0,'resultado':'no_disponible'})['reintentos']+=1
    for e in eventos:
        identificador = e.get('detalles',{}).get('llamada_id')
        if e['evento']=='llamada_fin' and identificador in grupos:
            grupos[identificador]['resultado']=e['estado']
    return list(grupos.values())
