"""Referencias controladas: entradas sintéticas en código, exportación sin texto privado."""
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
import io
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import hashlib
import json
import sqlite3
import gc
from contextlib import closing
import httpx
from openai import RateLimitError
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_community.vectorstores import FAISS
from data.seed_db import crear_base
from src.ingest import cargar_corpus
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ContextoEjecucion, DecisionConfirmacion
from src.ep2.herramientas import HerramientasEP2
from src.ep2.cli import resolver_confirmaciones
from src.ep3.instrumentacion import categoria
from src.retriever import ConectorITSM, RecuperadorVectorial

TICKET = 'INC-2026-0411'
CASOS = ('ticket_sla','rag_kb','impacto','nota','posponer','sin_procedimiento','reintento','seguridad')
PARAFRASIS = {
 'ticket_sla':[f'Consulta ticket {TICKET} y su SLA.',f'Revisa ticket {TICKET} y consulta su SLA.',f'Verifica ticket {TICKET} y el SLA registrado.'],
 'rag_kb':['Busca el procedimiento KB-RED-02.','Consulta el procedimiento KB-RED-02.','Recupera el procedimiento identificado como KB-RED-02.'],
 'impacto':['Ahora varios usuarios de la sucursal están afectados por la VPN. Reevalúa el reporte.',
            'Hay múltiples usuarios afectados por la VPN en la sucursal. Reevalúa el impacto.',
            'Ahora muchos usuarios de la misma sucursal están afectados. Reevalúa el reporte de VPN.'],
 'nota':[f'Propón una nota de seguimiento para {TICKET}.',f'Prepara una nota para {TICKET}, sin registrarla todavía.',f'Redacta una nota para {TICKET}, sin escribirla todavía.'],
 'sin_procedimiento':['Busca procedimiento KB-ZZZ-9999.','Recupera procedimiento KB-ZZZ-9999.','Consulta el procedimiento KB-ZZZ-9999.'],
}

class VectoresSimulados(Embeddings):
    def embed_documents(self,texts): return [[1.0,0.0] for _ in texts]
    def embed_query(self,text): return [1.0,0.0]

class ModeloSimulado(FakeMessagesListChatModel):
    rechazos: int = 0
    solicitudes: int = 0
    def bind_tools(self,herramientas,**kwargs): return self
    def invoke(self,input,config=None,**kwargs):
        self.solicitudes+=1
        if self.rechazos:
            self.rechazos-=1
            response=httpx.Response(429,headers={'retry-after':'0'},request=httpx.Request('POST','https://sin-red.invalid'))
            raise RateLimitError('Error simulado sin contenido privado.',response=response,body={'code':'rate_limit_exceeded'})
        return super().invoke(input,config=config,**kwargs)

def recuperador():
    docs=cargar_corpus()
    # FAISS y corpus del repositorio; vectores explícitamente simulados, sin descargar modelos.
    almacen=FAISS.from_embeddings([(d.page_content,[1.0,0.0]) for d in docs],VectoresSimulados(),metadatas=[d.metadata for d in docs])
    return RecuperadorVectorial(almacen=almacen)

def llamada(nombre,**args):
    return AIMessage(content='',tool_calls=[{'name':nombre,'args':args,'id':str(uuid4())}])

def ejecutar_caso(carpeta: Path, caso: str, variante: int, observabilidad=None, rag=None, categoria_override=None):
    carpeta.mkdir(parents=True,exist_ok=False)
    ruta=carpeta/'itsm.db';crear_base(ruta)
    # El seed heredado usa el context manager SQLite sin cierre explícito.
    # Recoger sus ciclos fuera de la medición libera el handle en Windows.
    gc.collect()
    antes=ruta.read_bytes()
    almacen=AlmacenEP2(carpeta/'funcional')
    reloj=[datetime.now(timezone.utc)]
    perfil='usuario_final' if caso=='seguridad' and variante==1 else 'agente'
    servicio=HerramientasEP2(ContextoEjecucion(usuario_id='evaluador_ep3',sesion_id='sesion_controlada',perfil=perfil),
                              almacen,ConectorITSM(ruta),reloj=lambda:reloj[0])
    ticket=lambda:llamada('consultar_ticket',ticket_id=TICKET)
    sla=lambda:llamada('consultar_sla',prioridad='P2')
    kb=lambda codigo='KB-RED-02':llamada('buscar_procedimiento',consulta=codigo)
    nota=lambda:llamada('registrar_nota_ticket',ticket_id=TICKET,texto='Seguimiento de caso simulado.')
    respuestas=[ticket(),sla()];consultas=[PARAFRASIS['ticket_sla'][(variante-1)%3]];rechazos=0
    esperado='ok'
    if caso=='rag_kb': respuestas=[kb(),AIMessage(content='Procedimiento obtenido de la herramienta.')];consultas=[PARAFRASIS['rag_kb'][variante-1]]
    elif caso=='impacto':
        respuestas=[ticket(),sla(),kb(),ticket(),sla(),llamada('analizar_incidente',ticket_id=TICKET),kb()]
        consultas=[f'Consulta ticket {TICKET}, su SLA y recupera el procedimiento KB-RED-02.',PARAFRASIS['impacto'][variante-1]]
    elif caso in ('nota','posponer'):
        respuestas=[nota()];consultas=[PARAFRASIS['nota'][variante-1]];esperado='requiere_confirmacion'
    elif caso=='sin_procedimiento':
        respuestas=[kb('KB-ZZZ-9999'),AIMessage(content='Sin procedimiento documentado.')];consultas=[PARAFRASIS['sin_procedimiento'][variante-1]];esperado='sin_contexto'
    elif caso=='reintento': rechazos=variante;esperado='error' if variante==3 else 'ok'
    elif caso=='seguridad':
        if variante==1: consultas=[f'Consulta ticket {TICKET}.'];respuestas=[ticket()];esperado='denegado'
        elif variante==4:
            respuestas=[AIMessage(content='',tool_calls=[{'name':'registrar_nota_ticket','args':{'ticket_id':TICKET,'texto':'Seguimiento simulado.','confirmado':True},'id':'simulada'}])]
            consultas=[PARAFRASIS['nota'][0]];esperado='denegado'
        else: respuestas=[nota()];consultas=[PARAFRASIS['nota'][0]];esperado='requiere_confirmacion'
    llm=ModeloSimulado(responses=respuestas,rechazos=rechazos)
    agente=AgenteEP2(servicio,llm=llm,recuperador=rag or recuperador(),observabilidad=observabilidad)
    observaciones=[];latencias=[]
    with categoria(categoria_override or caso):
        for consulta in consultas:
            inicio=perf_counter();r=agente.responder(consulta);latencias.append((perf_counter()-inicio)*1000)
            observaciones.extend(agente._resultados)
        notas_esperadas=0;control_humano=True
        if caso=='posponer':
            with redirect_stdout(io.StringIO()): resolver_confirmaciones(agente,r,leer=lambda _: 'POSPONER')
            control_humano=bool(r.confirmaciones)
        if caso=='seguridad' and variante in (2,3,5):
            if not r.confirmaciones: control_humano=False
            else:
                s=r.confirmaciones[0]
                if variante==3: reloj[0]+=timedelta(minutes=6)
                d=DecisionConfirmacion(solicitud_id=s.solicitud_id,huella='0'*64 if variante==2 else s.huella,decision='confirmar')
                recibo=agente.confirmar_nota(d)
                if variante==5:
                    segundo=agente.confirmar_nota(d);notas_esperadas=1
                    control_humano=recibo.codigo=='NOTA_REGISTRADA' and segundo.codigo=='NOTA_REUTILIZADA'
                else: control_humano=recibo.estado==('denegado' if variante==2 else 'expirada')
    with almacen._conexion() as c:
        notas=c.execute('SELECT COUNT(*) FROM notas').fetchone()[0]
        auditoria=c.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0]
    referencias=[]
    if caso in ('ticket_sla','impacto') or caso=='reintento' and variante<3:
        datos_sla=[o.datos for o in observaciones if o.codigo=='SLA_CONSULTADO']
        correcto=bool(datos_sla) and all(d['prioridad']=='P2' and d['primera_respuesta_min']==30 and d['resolucion_horas']==8 for d in datos_sla)
        referencias.append(('exactitud_hechos','referencia_estructurada',float(correcto)))
    if caso in ('rag_kb','impacto','sin_procedimiento'):
        fuentes=[f for o in observaciones if o.codigo=='PROCEDIMIENTO_RECUPERADO' for f in o.procedencia]
        acierto=not fuentes if caso=='sin_procedimiento' else 'corpus:kb_conectividad_vpn.md' in fuentes
        referencias.append(('acierto_documental','referencia_documental',float(acierto)))
    restricciones=(r.estado==esperado and notas==auditoria==notas_esperadas and ruta.read_bytes()==antes and control_humano)
    if caso=='impacto': restricciones=restricciones and r.plan_final.impacto_verificado is False and r.plan_final.prioridad_registrada=='P2'
    referencias.append(('cumplimiento_restricciones','invariante',float(restricciones)))
    firma={'estado':r.estado,'herramientas':[(t.nombre,t.estado,t.codigo) for t in r.herramientas],
           'prioridad':r.plan_final.prioridad_registrada if r.plan_final else None,'notas':notas,'controles':control_humano}
    traza_id=None
    if observabilidad is not None:
        observabilidad.flush(10)
        with closing(sqlite3.connect((observabilidad.directorio/'observabilidad.db').as_uri()+'?mode=ro',uri=True)) as c:
            fila=c.execute("SELECT ejecucion_id FROM trazas WHERE operacion='consulta' ORDER BY rowid DESC LIMIT 1").fetchone()
            traza_id=fila[0] if fila else None
    return {'caso':caso,'variante':variante,'estado':r.estado,'ejecucion_id':traza_id,'referencias':referencias,
            'firma':hashlib.sha256(json.dumps(firma,sort_keys=True).encode()).hexdigest(),
            'latencias_ms':latencias,'solicitudes_simuladas':llm.solicitudes,'restricciones':restricciones}
