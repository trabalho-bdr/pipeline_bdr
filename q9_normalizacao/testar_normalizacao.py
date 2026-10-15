"""Teste integrado opcional: requer duckdb e a exportação original.
Uso: uv run --with duckdb python testar_normalizacao.py /caminho/export.json
Testa em memória; nunca se conecta ao MotherDuck.
"""
import argparse
from decimal import Decimal
from pathlib import Path
import time
import duckdb
import gerar_normalizacao as g


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('exportacao',type=Path)
 a=p.parse_args();start=time.monotonic();rows=g.load(a.exportacao)
 c=duckdb.connect(':memory:')
 c.execute('CREATE TABLE Despesa_Candidatura(id_despesa VARCHAR PRIMARY KEY,id_candidatura VARCHAR,categoria VARCHAR,valor DOUBLE)')
 c.execute("INSERT INTO Despesa_Candidatura SELECT cast(row_number() OVER () - 1 AS VARCHAR), 'ca' || cast((row_number() OVER () - 1) % 500 AS VARCHAR), categoria, try_cast(valor_contratado AS DOUBLE) FROM read_json_auto(?)", [str(a.exportacao)])
 edge=[('edge1','ca1','serviços contábeis',0),('edge2','ca2','SERVICOS CONTABEIS',None),('edge3','ca3','SANTINHO',-20),('edge4','ca4','SANTINHO',30),('edge5','ca5',None,10),('edge6','ca6','COORDENAÇÃO, IMPULSIONAMENTO E EQUIPE DE BANDEIRAS',40),('edge7','ca7','CATEGORIA FUTURA SEM REGRA',float('inf'))]
 c.executemany('INSERT INTO Despesa_Candidatura VALUES (?,?,?,?)',edge)
 before=c.execute('SELECT count(*),sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END) FROM Despesa_Candidatura').fetchone()
 sql=g.make_sql();ddl=sql.split('COMMIT;',1)[0]+'COMMIT;'
 c.execute(ddl)
 # Conferência de todas as descrições, não apenas de exemplos escolhidos.
 campos=list(g.classify('SANTINHO'))
 query='SELECT categoria_original,'+','.join(campos)+' FROM vw_q9_categorias'
 actual=c.execute(query).fetchall()
 for row in actual:
  expected=tuple(g.classify(row[0])[field] for field in campos)
  assert tuple(row[1:])==expected,(row[0],row[1:],expected)
 assert len(actual)==len({r['categoria'] for r in rows}|{e[2] for e in edge})
 after=c.execute('SELECT count(*),sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END) FROM vw_q9_despesas_normalizadas').fetchone()
 assert before==after,(before,after)
 assert c.execute('SELECT count(*)=count(DISTINCT id_despesa) FROM vw_q9_despesas_normalizadas').fetchone()[0]
 snapshot=c.execute('SELECT * FROM Despesa_Candidatura ORDER BY id_despesa').fetchall()
 c.execute(ddl)
 assert snapshot==c.execute('SELECT * FROM Despesa_Candidatura ORDER BY id_despesa').fetchall()
 for stmt in c.extract_statements(sql.split('COMMIT;',1)[1]):
  c.execute(stmt)
 print('APROVADO: classificação SQL = Python em',len(actual),'descrições distintas; sem perda, duplicação ou alteração dos valores e linhas da fonte.')
 print('Inclui regras futuras, ambiguidades, ausentes, acentos, singular/plural, zero, negativos, infinito, alias, consultas de resumo e reexecução.')
 print('Tempo de teste:',round(time.monotonic()-start,2),'s. Teste local sobre exportação agregada; não valida a carga do banco remoto.')

if __name__=='__main__':main()
