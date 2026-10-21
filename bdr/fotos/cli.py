"""python -m bdr.fotos --help. Aquisição fora da API/pipeline, com DER somente leitura."""
import argparse
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

from .aquisicao import (adquirir_pacote, importar_fonte, importar_internas, necessidades,
                        preparar_selecao, relatorio, revalidar_imagens, selecionar_principais, vincular)
from .catalogo import RAIZ, UFS, abrir, configuracao
from .fontes import agora, descobrir


def parser():
    p = argparse.ArgumentParser(description='Foto principal por pessoa, a partir dos recursos oficiais do TSE.')
    p.add_argument('comando', choices=('adquirir', 'relatorio', 'deduplicar'))
    p.add_argument('--banco', default=os.environ.get('BDR_BANCO'), help='DER local ou md:...; aberto somente para leitura')
    imagens, banco, cache = configuracao()
    p.add_argument('--imagens', type=Path, default=imagens)
    p.add_argument('--catalogo', type=Path, default=banco)
    p.add_argument('--destino', type=Path, default=RAIZ / 'dados_bdr/fotos selecionadas', help='Diretório final fotos selecionadas')
    p.add_argument('--aplicar', action='store_true', help='Efetivar deduplicação e exclusão')
    p.add_argument('--limite', type=int, default=None, help='Limite de pessoas para análise ou deduplicação')
    p.add_argument('--cache', type=Path, default=cache)
    p.add_argument('--uf', nargs='+', choices=UFS, default=list(UFS))
    p.add_argument('--pessoa', action='append', default=[], help='id_candidato existente; repetível')
    p.add_argument('--todos', action='store_true', help='Processar todas as pessoas nas UFs selecionadas')
    p.add_argument('--ano', nargs='+', type=int, help='Limitar fontes para piloto; marca cobertura incompleta')
    p.add_argument('--workers', type=int, choices=range(1, 5), default=2, help='Pacotes simultâneos (1 a 4)')
    p.add_argument('--atualizar', action='store_true', help='Reconsultar metadados e substituir caches dos anos recentes')
    p.add_argument('--desde', type=int, default=2024, help='Ano mínimo para atualizar caches com --atualizar')
    p.add_argument('--somente-cadastros', action='store_true', help='Construir vínculos sem baixar fotos')
    p.add_argument('--retomar-fotos', action='store_true', help='Usar cadastros e vínculos já catalogados, sem consultar o DER ou descobrir fontes novas')
    return p


def executar(args):
    if args.comando == 'relatorio':
        if not args.catalogo.is_file():
            raise ValueError('Catálogo ainda não criado; execute adquirir primeiro.')
        con = sqlite3.connect(args.catalogo.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            return relatorio(con)
        finally:
            con.close()
    if args.comando == 'deduplicar':
        from .deduplicacao import construir_plano, executar_deduplicacao, obter_banco_der_padrao, salvar_relatorios
        banco_der = args.banco or obter_banco_der_padrao()
        cat = abrir(args.catalogo)
        try:
            plano = construir_plano(cat, banco_der, args.imagens, args.destino, args.pessoa if args.pessoa else None, limite=args.limite)
        finally:
            cat.close()
        res = executar_deduplicacao(plano, args.catalogo, args.imagens, args.destino, aplicar=args.aplicar)
        salvar_relatorios(res)
        return res
    if args.retomar_fotos and not args.catalogo.is_file():
        raise ValueError('A retomada de fotos exige um catálogo com a fase de identidade concluída.')
    if args.retomar_fotos and (args.atualizar or args.somente_cadastros):
        raise ValueError('--retomar-fotos não pode ser combinado com --atualizar ou --somente-cadastros.')
    cat = abrir(args.catalogo)
    inicio = agora()
    try:
        if not args.todos and not args.pessoa:
            raise ValueError('Informe --pessoa ID ou --todos explicitamente')
        banco = args.banco
        if args.retomar_fotos:
            cat.execute('CREATE TEMP TABLE ativos(id_candidato TEXT PRIMARY KEY)')
            if set(args.uf) == set(UFS) and not args.pessoa:
                cat.execute('INSERT INTO ativos SELECT id_candidato FROM pessoas')
            else:
                where = 'uf IN (' + ','.join('?' for _ in args.uf) + ')'
                params = list(args.uf)
                if args.pessoa:
                    where += ' AND id_candidato IN (' + ','.join('?' for _ in args.pessoa) + ')'
                    params.extend(args.pessoa)
                cat.execute('INSERT INTO ativos SELECT DISTINCT id_candidato FROM internas WHERE ' + where, params)
            resumo_interno = {'pessoas': cat.execute('SELECT count(*) FROM ativos').fetchone()[0],
                               'origem': 'catalogo_auxiliar; DER nao consultado nesta retomada'}
            cat.commit()
            print('Retomando fotos do catálogo local: ' + json.dumps(resumo_interno), flush=True)
        elif not banco:
            from frontend.main import _obter_banco_padrao
            banco = _obter_banco_padrao()
        if not args.retomar_fotos and banco.startswith('md:'):
            token = os.environ.get('MOTHERDUCK_TOKEN') or os.environ.get('motherduck_token')
            if not token:
                raise ValueError('MOTHERDUCK_TOKEN ausente. Configure-o ou indique --banco local.')
            os.environ['motherduck_token'] = token
        # read_only é o modo de arquivo do DuckDB. No MotherDuck, segue a conexão
        # existente da API e executa apenas SELECT; as permissões pertencem ao token.
        if not args.retomar_fotos:
            der = duckdb.connect(banco, read_only=not banco.startswith('md:'))
            try:
                resumo_interno = importar_internas(der, cat, args.uf, args.pessoa)
            finally:
                der.close()
            print('DER (somente leitura): ' + json.dumps(resumo_interno), flush=True)
        if not resumo_interno['pessoas']:
            raise ValueError('Nenhuma pessoa encontrada no escopo solicitado')
        cat.execute('INSERT INTO execucoes(inicio,escopo) VALUES (?,?)',
                    (inicio, json.dumps({'ufs': args.uf, 'pessoas': args.pessoa, 'anos': args.ano,
                                         'retomar_fotos': args.retomar_fotos})))
        cat.commit()
        pacotes = ([json.loads(r[0]) for r in cat.execute('SELECT metadados FROM fontes')]
                   if args.retomar_fotos else descobrir(args.cache, args.atualizar))
        ano_min = cat.execute('SELECT min(ano) FROM internas').fetchone()[0]
        if ano_min is None:
            raise ValueError('Catálogo sem candidaturas internas; execute adquirir sem --retomar-fotos primeiro.')
        # Histórico anterior ao banco só é necessário se a pessoa já existia antes;
        # o menor ano interno delimita o início declarado desta pesquisa.
        esperados = [p for p in pacotes if p['ano'] >= ano_min]
        selecionados = sorted([p for p in esperados if not args.ano or p['ano'] in args.ano],
                              key=lambda p: (p['ano'], p['dataset']), reverse=True)
        if not selecionados:
            raise ValueError('Nenhum conjunto oficial de candidatos foi descoberto para os anos solicitados.')
        if not args.retomar_fotos:
            for pacote in selecionados:
                importar_fonte(cat, pacote, args.cache, args.uf, args.atualizar and pacote['ano'] >= args.desde)
            print('Associando identidades e verificando ambiguidades…', flush=True)
            vincular(cat)
        print('Conferindo os arquivos locais antes da retomada…', flush=True)
        revalidar_imagens(cat, args.imagens)
        preparar_selecao(cat)
        if not args.somente_cadastros:
            # Mais recentes primeiro. Todos os trabalhos de um ano terminam antes do anterior.
            for ano in sorted({p['ano'] for p in selecionados}, reverse=True):
                anuais = [p for p in selecionados if p['ano'] == ano]
                jobs = []
                for uf in args.uf:
                    sqs = necessidades(cat, ano, uf, args.atualizar and ano >= args.desde)
                    if not sqs:
                        continue
                    # Só utiliza um recurso que realmente consta nos metadados desse ano.
                    candidatos = [p for p in anuais if any(
                        r.get('name', '').upper() == f'{uf} - FOTOS DE CANDIDATOS' for r in p['resources'])]
                    pacote = candidatos[0] if candidatos else anuais[0]
                    jobs.append((pacote, uf, sqs))
                jobs.sort(key=lambda job: len(job[2]), reverse=True)
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = [pool.submit(adquirir_pacote, args.catalogo, args.imagens, args.cache, p, uf, sqs,
                                           args.atualizar and ano >= args.desde) for p, uf, sqs in jobs]
                    for (pacote, uf, _), future in zip(jobs, futures):
                        try:
                            future.result()
                        except Exception as e:
                            print(f"  Falha isolada {pacote['ano']}/{uf}: {type(e).__name__}: {e}", flush=True)
                selecionar_principais(cat, False)
                quant = cat.execute("SELECT count(*) FROM principais WHERE foto_status='disponivel'").fetchone()[0]
                print(f"  Progresso: {quant} pessoas com foto local", flush=True)
        cobertura_ok = all(cat.execute("SELECT 1 FROM cobertura WHERE dataset=? AND uf=? AND status='ok'",
                                      (p['dataset'], uf)).fetchone() for p in esperados for uf in UFS)
        # Um piloto, descoberta antiga ou recorte de UF nunca comprova cobertura completa.
        imagens_pendentes = cat.execute("""SELECT count(*) FROM imagens
            WHERE status NOT IN ('disponivel','nao_encontrada')""").fetchone()[0]
        pacotes_pendentes = cat.execute("SELECT count(*) FROM cobertura WHERE dataset LIKE '%::fotos' AND status<>'ok'").fetchone()[0]
        ultimas_nao_processadas = cat.execute('''SELECT count(*) FROM opcoes_foto o
            WHERE o.imagem_status IS NULL AND NOT EXISTS (SELECT 1 FROM opcoes_foto posterior
              WHERE posterior.id_candidato=o.id_candidato AND posterior.ordem>o.ordem)''').fetchone()[0]
        completa = (cobertura_ok and not imagens_pendentes and not pacotes_pendentes and not args.ano
                    and not ultimas_nao_processadas and set(args.uf) == set(UFS)
                    and not args.somente_cadastros and not args.retomar_fotos)
        selecionar_principais(cat, completa)
        resultado = relatorio(cat)
        resultado['banco_lido'] = banco if not args.retomar_fotos else None
        resultado['escopo_interno'] = resumo_interno
        cat.execute('UPDATE execucoes SET fim=?,relatorio=? WHERE inicio=?',
                    (agora(), json.dumps(resultado, ensure_ascii=False), inicio))
        cat.commit()
        destino = args.catalogo.with_suffix('.relatorio.json')
        tmp = destino.with_suffix('.tmp')
        tmp.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf8')
        tmp.replace(destino)
        return resultado
    finally:
        cat.close()


def main():
    args = parser().parse_args()
    if args.comando == 'relatorio':
        try:
            print(json.dumps(executar(args), ensure_ascii=False, indent=2))
        except (ValueError, sqlite3.Error) as e:
            raise SystemExit(str(e))
        return
    args.catalogo.parent.mkdir(parents=True, exist_ok=True)
    # Impede duas CLIs de substituírem simultaneamente o mesmo catálogo/cache.
    lock = args.catalogo.with_suffix('.lock')
    try:
        with lock.open('x', encoding='utf8') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit(f'Outra aquisição usa {lock}. Se o processo terminou, remova somente esse lock.')
    try:
        print(json.dumps(executar(args), ensure_ascii=False, indent=2), flush=True)
    except KeyboardInterrupt:
        raise SystemExit('Interrompido. O cache e os lotes concluídos foram preservados; reexecute para retomar.')
    except (ValueError, OSError, RuntimeError, duckdb.Error, sqlite3.Error) as e:
        raise SystemExit(str(e))
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
