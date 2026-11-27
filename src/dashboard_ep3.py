"""Dashboard local EP3. Solo lectura; no importa ni instancia el agente."""
from pathlib import Path
import os
import sys

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path: sys.path.insert(0,str(RAIZ))
import pandas as pd
import streamlit as st
from src.ep3.lectura import cargar, DatosNoDisponibles
from src.ep3.analisis import tabla, resumen, reintentos

def formato(valor, unidad=' ms'):
    return 'No disponible' if valor is None or pd.isna(valor) else f'{valor:,.2f}{unidad}'

def main():
    st.set_page_config(page_title='EP3 · Observabilidad',page_icon='📊',layout='wide')
    st.title('Observabilidad · Mesa de Ayuda TI')
    st.caption('EP3 · Lectura local de telemetría · Los orígenes se analizan por separado')
    ruta = st.sidebar.text_input('Base SQLite',value=os.getenv('EP3_DASHBOARD_DB',str(RAIZ/'storage/ep3/observabilidad.db')))
    if st.sidebar.button('Actualizar lectura'): st.rerun()
    try: datos = cargar(Path(ruta))
    except DatosNoDisponibles as e:
        st.info(str(e)); return
    st.sidebar.caption(f'Esquema BD v{datos.version} · Retención recomendada: {datos.retencion_dias} días. Sin borrado automático.')
    if datos.invalidos: st.warning(f'{datos.invalidos} registros incompatibles omitidos; no se muestra su contenido.')
    if datos.recortado: st.warning('Lectura limitada a los últimos 50.000 eventos. Los KPI corresponden a esta muestra.')
    if not datos.eventos:
        st.info('La base está vacía. No hay mediciones disponibles.'); return
    df = tabla(datos.eventos)
    origenes = sorted(df.tipo_ejecucion.unique())
    origen = st.sidebar.selectbox('Origen de ejecución',origenes)
    st.info({'simulada':'SIMULACIÓN OFFLINE · Estos tiempos y tokens no acreditan rendimiento o consumo de Groq.',
             'real':'OPERACIÓN REAL · Una consulta puede finalizar sin llamar al proveedor.',
             'historica':'EVIDENCIA HISTÓRICA · No corresponde a mediciones nuevas de EP3.'}[origen])
    df = df[df.tipo_ejecucion==origen].copy()
    df['fecha_utc']=pd.to_datetime(df.fecha_utc,utc=True)
    incluir_antiguos=st.sidebar.checkbox('Incluir fuera de ventana de retención',value=origen=='historica')
    if not incluir_antiguos:
        df=df[df.fecha_utc>=pd.Timestamp.now(tz='UTC')-pd.Timedelta(days=datos.retencion_dias)]
    if df.empty:
        st.info('No hay datos dentro de la ventana elegida; se conservan los registros antiguos.');return
    fechas = st.sidebar.date_input('Fecha UTC',value=(df.fecha_utc.min().date(),df.fecha_utc.max().date()))
    if isinstance(fechas,tuple) and len(fechas)==2:
        df=df[(df.fecha_utc.dt.date>=fechas[0])&(df.fecha_utc.dt.date<=fechas[1])]
    categorias = ['Todas',*sorted(df.get('categoria',pd.Series(['interactiva'])).dropna().unique())]
    cat=st.sidebar.selectbox('Categoría',categorias)
    if cat!='Todas': df=df[df.categoria==cat]
    finales=df[df.evento=='consulta_fin']
    estado=st.sidebar.selectbox('Estado de consulta',['Todos',*sorted(finales.estado.unique())])
    if estado!='Todos': df=df[df.ejecucion_id.isin(finales[finales.estado==estado].ejecucion_id)]
    opciones=sorted(df.get('herramienta',pd.Series(dtype=str)).dropna().unique())
    herramienta=st.sidebar.selectbox('Herramienta',['Todas',*opciones])
    if herramienta!='Todas': df=df[df.ejecucion_id.isin(df[df.herramienta==herramienta].ejecucion_id)]
    sesiones=sorted(df.sesion_ref.dropna().unique())
    sesion=st.sidebar.selectbox('Sesión seudonimizada',['Todas',*sesiones])
    if sesion!='Todas': df=df[df.sesion_ref==sesion]
    if 'correlacion' not in df or (df.get('correlacion')!='estable').any():
        st.caption('Hay trazas sin correlación estable o v1: no se infiere identidad entre procesos.')
    ids=set(df.ejecucion_id)
    eventos=[e for e in datos.eventos if e['ejecucion_id'] in ids and e['tipo_ejecucion']==origen]
    # Aplicar también rango temporal a los KPI, evitando reincorporar eventos fuera del filtro.
    eventos=[e for e in eventos if e['evento_id'] in set(df.evento_id)]
    r=resumen(eventos)
    a,b,c,d=st.columns(4)
    a.metric('Consultas finalizadas',r['consultas']);b.metric('Éxito: estado ok',r['ok'])
    c.metric('Fallas técnicas / límites',r['fallas_tecnicas']);d.metric('Pendientes de confirmación',r['pendientes'])
    a,b,c,d=st.columns(4)
    a.metric('Latencia promedio',formato(r['promedio_ms']));b.metric('P50',formato(r['p50_ms']))
    c.metric('P95',formato(r['p95_ms']));d.metric('Muestras de latencia',r['muestras_latencia'])
    st.caption('Éxito = consultas con estado ok / finalizadas. Denegación y ausencia de contexto se muestran por separado en los estados. Los tiempos incluyen memoria; excluyen espera humana.')
    st.metric('Tasa de estado ok',f"{100*r['ok']/r['consultas']:.1f}%" if r['consultas'] else 'No disponible')
    vistas=st.tabs(['Actividad y errores','Modelo y recursos','RAG y calidad','Trazas y planificación','Salud'])
    with vistas[0]:
        st.subheader('Actividad por hora UTC')
        f=df[df.evento=='consulta_fin'].copy()
        if not f.empty:
            f['hora']=f.fecha_utc.dt.floor('h')
            st.line_chart(f.groupby('hora').size().rename('consultas'))
            st.line_chart(f.groupby('hora').duracion_ms.mean().rename('latencia_media_ms'))
            st.dataframe(f.groupby('estado').size().rename('consultas').reset_index(),hide_index=True)
        err=df[df.evento.isin(['modelo_error','herramienta_fin']) & df.estado.isin(['error','denegado','no_encontrado'])]
        st.subheader('Errores y rechazos observados')
        st.dataframe(err.groupby(['evento','codigo']).size().rename('eventos').reset_index(),hide_index=True)
        st.metric('HTTP 429: solicitudes LLM',sum(e['evento']=='modelo_error' and e['codigo']=='HTTP_429'
                  and e.get('detalles',{}).get('frontera')=='llm' for e in eventos))
        st.caption('Los errores de cadena y los errores LLM son fronteras distintas; no sumarlos como solicitudes.')
        st.subheader('Resultado definitivo de reintentos')
        st.dataframe(pd.DataFrame(reintentos(eventos)),hide_index=True)
        st.subheader('Herramientas')
        h=df[df.evento=='herramienta_fin']
        if not h.empty: st.dataframe(h.groupby(['herramienta','estado']).agg(muestras=('evento_id','size'),promedio_ms=('duracion_ms','mean')),use_container_width=True)
    with vistas[1]:
        st.metric('Solicitudes LLM observadas',r['solicitudes_llm']);st.metric('Decisiones del agente',r['decisiones'])
        st.caption('Una solicitud es un intento de inferencia; los reintentos comparten llamada_id. Un cierre local puede tomar una decisión sin solicitud LLM.')
        modelos=df[df.evento=='modelo_fin']
        for campo,etiqueta in [('tokens_entrada','Tokens de entrada informados'),('tokens_salida','Tokens de salida informados')]:
            valores=modelos.get(campo,pd.Series(dtype=float)).dropna()
            st.metric(etiqueta,int(valores.sum()) if len(valores) else 'No disponible')
            st.caption(f'Cobertura: {len(valores)} respuestas con dato; subtotal observado del origen seleccionado.')
        f=df[df.evento=='consulta_fin']
        for campo,etiqueta,unidad in [('cpu_ms','CPU del proceso: promedio',' ms'),('ram_fin_bytes','RAM del proceso: promedio',' bytes')]:
            valores=f.get(campo,pd.Series(dtype=float)).dropna()
            st.metric(etiqueta,formato(valores.mean() if len(valores) else None,unidad))
        st.caption('CPU y RAM pertenecen al proceso completo, incluido el escritor. RAM es working set en Windows o RSS en Linux; no es un pico por consulta.')
    with vistas[2]:
        rag=df[df.evento=='rag_fin']
        if rag.empty: st.info('Sin mediciones RAG en la selección.')
        else:
            cols=[x for x in ['ejecucion_id','rag_metodo','rag_devueltos','puntaje_maximo','duracion_ms','estado'] if x in rag]
            st.dataframe(rag[cols],hide_index=True)
        st.caption('La similitud vectorial no mide exactitud, fidelidad ni consistencia. Las coincidencias por identificador no tienen puntaje semántico.')
        casos_presentes=set(df.get('categoria',pd.Series(dtype=str)).dropna())
        evaluaciones=[e for e in datos.evaluaciones if e['tipo_ejecucion']==origen and
                      (e['ejecucion_id'] in ids or e['ejecucion_id'] is None and e['caso'] in casos_presentes)]
        if evaluaciones: st.dataframe(pd.DataFrame(evaluaciones),hide_index=True)
        else: st.info('No hay evaluaciones etiquetadas para estas trazas. No se calculan valores de calidad a partir de similitud.')
    with vistas[3]:
        st.dataframe(df[df.evento.isin(['consulta_fin','confirmacion_fin','posponer'])][['ejecucion_id','fecha_utc','evento','estado','codigo','duracion_ms']],hide_index=True)
        if not df.empty:
            traza=st.selectbox('Trace ID',list(df.ejecucion_id.unique()))
            detalle=df[df.ejecucion_id==traza].sort_values('secuencia')
            cols=[x for x in ['secuencia','fecha_utc','evento','componente','estado','codigo','duracion_ms','revision','pasos_total','pasos_completados','pasos_bloqueados','cambio_codigo'] if x in detalle]
            st.dataframe(detalle[cols],hide_index=True,use_container_width=True)
        st.caption('Proponer o POSPONER no registra una nota. Confirmaciones y cancelaciones proceden de la API humana; no se muestran contenido ni capacidades de autorización.')
    with vistas[4]:
        st.caption('Salud global acumulada del archivo por recolector; no se atribuye a los filtros de consulta.')
        st.dataframe(pd.DataFrame(datos.salud),hide_index=True)
        st.metric('Registros incompatibles omitidos',datos.invalidos)
        st.caption('Si falla el almacenamiento, los contadores pueden existir solo en RAM; una interrupción abrupta puede dejar trazas incompletas.')

if __name__=='__main__': main()
