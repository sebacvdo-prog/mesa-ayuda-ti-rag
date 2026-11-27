from eval.evaluate_ep3 import ejecutar

def test_evaluacion_etiquetada_y_benchmark_pareado(tmp_path):
    r=ejecutar(tmp_path/'evaluacion',pares=2)
    assert r['aprobado'],r['resultados']
    assert r['casos']==26
    assert r['benchmark']['on_ms']['n']==2
    assert all(p['equivalente'] for p in r['pares'])
    assert r['metricas']['consistencia']['muestras']==18
