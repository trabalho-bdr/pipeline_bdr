"""Consultas somente leitura da Q9; reutiliza a normalização existente."""
import unicodedata
from decimal import Decimal
from functools import lru_cache

from fastapi import HTTPException

ANOS = (2018, 2020, 2022, 2024)
UFS = ('CE', 'MA', 'MS', 'RJ', 'RN', 'RS')


def _ident(value):
    return '"' + value.replace('"', '""') + '"'


def _codigo(value):
    text = unicodedata.normalize('NFD', value.strip())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn').upper()


def _fontes(consultar):
    rows = consultar('''SELECT table_catalog,table_schema,table_name
        FROM information_schema.tables WHERE table_catalog=current_database()
        AND table_schema IN ('main','der_bdr')
        AND lower(table_name) IN ('candidatura','candidato','municipio','partido','eleicao','despesa_candidatura','vw_q9_categorias')''')
    for schema in ('main', 'der_bdr'):
        found = {r['table_name'].lower(): '.'.join(map(_ident, (r['table_catalog'], schema, r['table_name'])))
                 for r in rows if r['table_schema'] == schema}
        if all(name in found for name in ('candidatura', 'eleicao', 'despesa_candidatura')):
            return found
    raise HTTPException(503, 'O banco selecionado não contém as tabelas de despesas e candidaturas da Q9.')


def _recorte(refs, ano, cargo, uf, id_candidatura=None):
    source = (f"{refs['despesa_candidatura']} d JOIN {refs['candidatura']} c USING(id_candidatura) "
              f"JOIN {refs['eleicao']} e USING(id_eleicao)")
    where = "e.ano=? AND upper(strip_accents(trim(e.cargo)))=? AND c.uf IN ('CE','MA','MS','RJ','RN','RS')"
    params = [ano, _codigo(cargo)]
    if uf:
        where += ' AND c.uf=?'
        params.append(uf)
    if id_candidatura:
        where += ' AND c.id_candidatura=?'
        params.append(id_candidatura)
    return source, where, params


def _buscar_candidatos(consultar, refs, ano, cargo, uf, busca='', id_candidatura=None):
    if not all(t in refs for t in ('candidato', 'municipio', 'partido')):
        raise HTTPException(503, 'O banco não contém o cadastro necessário para pesquisar candidatos.')
    source, where, params = _recorte(refs, ano, cargo, uf, id_candidatura)
    if busca:
        where += ''' AND (contains(upper(strip_accents(coalesce(c.nome_urna,''))),?)
            OR contains(upper(strip_accents(coalesce(a.nome_civil,''))),?))'''
        params += [_codigo(busca), _codigo(busca)]
    return consultar(f'''SELECT DISTINCT c.id_candidatura,c.id_candidato,c.nome_urna,a.nome_civil,
        coalesce(nullif(trim(c.nome_urna),''),a.nome_civil,'Candidato sem nome') nome,
        c.numero_urna,c.uf,m.nome municipio,p.sigla partido,e.ano,
        upper(strip_accents(trim(e.cargo))) cargo
        FROM {source} JOIN {refs['candidato']} a USING(id_candidato)
        LEFT JOIN {refs['municipio']} m ON m.id_municipio=c.id_municipio
        LEFT JOIN {refs['partido']} p ON p.id_partido=c.id_partido
        WHERE {where} ORDER BY nome,c.uf,municipio,c.id_candidatura LIMIT 21''', params)


def candidatos(consultar, ano, cargo, busca, uf=None):
    if ano not in ANOS or not cargo or not cargo.strip():
        raise HTTPException(422, 'Selecione um ano e cargo válidos para a Q9.')
    uf = uf.upper() if uf else None
    if uf and uf not in UFS:
        raise HTTPException(422, 'UF fora do recorte disponível.')
    busca = busca.strip()
    if len(busca) < 2:
        return {'candidatos': [], 'tem_mais': False}
    if len(busca) > 120:
        raise HTTPException(422, 'A busca aceita até 120 caracteres.')
    rows = _buscar_candidatos(consultar, _fontes(consultar), ano, cargo, uf, busca)
    return {'candidatos': rows[:20], 'tem_mais': len(rows) > 20}


def opcoes(consultar):
    refs = _fontes(consultar)
    rows = consultar(f'''SELECT DISTINCT e.ano, upper(strip_accents(trim(e.cargo))) cargo
        FROM {refs['despesa_candidatura']} d JOIN {refs['candidatura']} c USING(id_candidatura)
        JOIN {refs['eleicao']} e USING(id_eleicao)
        WHERE e.ano IN (2018,2020,2022,2024) AND c.uf IN ('CE','MA','MS','RJ','RN','RS')
        AND nullif(trim(e.cargo),'') IS NOT NULL ORDER BY e.ano DESC,cargo''')
    return {'opcoes': [dict(ano=r['ano'], cargo=r['cargo'], rotulo=r['cargo'].capitalize()) for r in rows],
            'anos': list(ANOS), 'ufs': list(UFS)}


@lru_cache(maxsize=50000)
def _classificar(categoria):
    # Não modifica o gerador ou as regras que o usuário decidiu manter.
    from q9_normalizacao.gerar_normalizacao import classify
    result = classify(categoria)
    return (result['categoria_padronizada'], result['grupo_despesa'],
            result['eh_publicidade_sugerida'], result['status_classificacao'], result['requer_revisao'])


def resumo(consultar, ano, cargo, uf=None, criterio='sugeridas', id_candidatura=None):
    if ano not in ANOS:
        raise HTTPException(422, 'A Q9 aceita os anos 2018, 2020, 2022 e 2024.')
    if not cargo or not cargo.strip():
        raise HTTPException(422, 'Selecione o cargo disputado.')
    uf = uf.upper() if uf else None
    if uf and uf not in UFS:
        raise HTTPException(422, 'UF fora do recorte disponível.')
    if criterio not in ('sugeridas', 'explicitas'):
        raise HTTPException(422, 'Critério de classificação inválido.')
    refs = _fontes(consultar)
    candidato = None
    if id_candidatura:
        encontrados = _buscar_candidatos(consultar, refs, ano, cargo, uf, id_candidatura=id_candidatura)
        if not encontrados:
            raise HTTPException(404, 'Candidatura sem despesas no ano, cargo e estado selecionados.')
        candidato = encontrados[0]
    source, where, params = _recorte(refs, ano, cargo, uf, id_candidatura)
    categorias = [r['categoria'] for r in consultar(f'SELECT DISTINCT d.categoria FROM {source} WHERE {where}', params)]
    origem = 'views_q9' if 'vw_q9_categorias' in refs else 'regras_locais_q9'
    dimension = {}
    if categorias and origem == 'views_q9':
        rows = consultar(f'''SELECT DISTINCT n.categoria_original,n.categoria_padronizada,n.grupo_despesa,
            n.eh_publicidade_sugerida,n.status_classificacao,n.requer_revisao
            FROM {refs['vw_q9_categorias']} n JOIN unnest(?::VARCHAR[]) f(categoria)
            ON n.categoria_original IS NOT DISTINCT FROM f.categoria''', [categorias])
        for row in rows:
            raw = row['categoria_original']
            if raw in dimension:
                raise HTTPException(503, 'Há classificações conflitantes para uma mesma descrição na Q9.')
            dimension[raw] = tuple(row[k] for k in ('categoria_padronizada', 'grupo_despesa',
                'eh_publicidade_sugerida', 'status_classificacao', 'requer_revisao'))
        if set(dimension) != set(categorias):
            raise HTTPException(503, 'A normalização da Q9 está incompleta para o recorte selecionado.')
    else:
        dimension = {raw: _classificar(raw) for raw in categorias}

    arrays = [categorias] + [[dimension[raw][i] for raw in categorias] for i in range(5)]
    # A dimensão é um parâmetro da consulta, nunca uma tabela criada no banco.
    # GROUPING SETS recalcula distintos no total: não soma candidaturas de categorias.
    rows = consultar(f'''
        WITH classificacao AS (
            SELECT unnest(?::VARCHAR[]) categoria,unnest(?::VARCHAR[]) categoria_padronizada,
                   unnest(?::VARCHAR[]) grupo_despesa,unnest(?::BOOLEAN[]) publicidade,
                   unnest(?::VARCHAR[]) status_classificacao,unnest(?::BOOLEAN[]) revisar
        ), base AS (
            SELECT d.id_despesa,c.id_candidatura,n.* EXCLUDE(categoria),
                   CASE WHEN isfinite(d.valor) THEN try_cast(d.valor AS DECIMAL(24,2)) END valor_centavos,
                   (n.publicidade IS TRUE AND (?='sugeridas' OR
                    (n.status_classificacao='ALIAS_EXPLICITO' AND NOT n.revisar))) elegivel
            FROM {source} LEFT JOIN classificacao n ON n.categoria IS NOT DISTINCT FROM d.categoria
            WHERE {where}
        )
        SELECT grouping(grupo_despesa) geral,grouping(categoria_padronizada) agregado_categoria,
               grupo_despesa,categoria_padronizada,
               count(*) FILTER (WHERE elegivel) registros,
               count(DISTINCT id_candidatura) FILTER (WHERE elegivel) candidaturas,
               coalesce(sum(valor_centavos) FILTER (WHERE elegivel),0) valor,
               coalesce(sum(valor_centavos),0) total_campanha,
               coalesce(sum(valor_centavos) FILTER (WHERE publicidade IS NULL),0) indefinido,
               coalesce(sum(valor_centavos) FILTER (WHERE publicidade IS FALSE),0) fora_publicidade,
               coalesce(sum(valor_centavos) FILTER (WHERE publicidade IS TRUE AND NOT elegivel),0) excluido_criterio,
               coalesce(sum(valor_centavos) FILTER (WHERE elegivel AND revisar),0) em_revisao,
               count(*) FILTER (WHERE valor_centavos IS NULL) sem_valor,
               count(*) FILTER (WHERE elegivel AND valor_centavos<0) ajustes_negativos
        FROM base GROUP BY GROUPING SETS ((),(grupo_despesa),(grupo_despesa,categoria_padronizada))
    ''', arrays + [criterio] + params)
    total = next(r for r in rows if r['geral'])
    denominator = Decimal(total['valor'])

    def item(row):
        value = Decimal(row['valor'])
        return {'grupo': row['grupo_despesa'], 'categoria': row['categoria_padronizada'],
                'valor': float(value), 'participacao': float(100 * value / denominator) if denominator > 0 else None,
                'candidaturas': row['candidaturas'], 'registros': row['registros'],
                'em_revisao': float(row['em_revisao'])}

    grupos = sorted([item(r) for r in rows if not r['geral'] and r['agregado_categoria'] and r['registros']],
                    key=lambda r: (-r['valor'], r['grupo'] or ''))
    palavras = sorted([item(r) for r in rows if not r['agregado_categoria'] and r['registros']],
                      key=lambda r: (-r['valor'], r['categoria'] or ''))
    return {'ano': ano, 'cargo': _codigo(cargo), 'uf': uf, 'ufs_cobertas': list(UFS), 'criterio': criterio,
            'origem_normalizacao': origem, 'grupos': grupos, 'categorias': palavras, 'candidato': candidato,
            'resumo': {'publicidade': float(total['valor']), 'total_campanha': float(total['total_campanha']),
                       'indefinido': float(total['indefinido']), 'fora_publicidade': float(total['fora_publicidade']),
                       'excluido_criterio': float(total['excluido_criterio']), 'em_revisao': float(total['em_revisao']),
                       'registros': total['registros'], 'candidaturas': total['candidaturas'],
                       'sem_valor': total['sem_valor'], 'ajustes_negativos': total['ajustes_negativos'],
                       'tipos': len(grupos), 'categorias': len(palavras)}}
