"""Converte os bancos operacionais de Q3/Q10 nas dez tabelas finais do DER."""

from pathlib import Path
import duckdb

from .esquema import criar


def _sql_path(path):
    return "'" + str(Path(path).resolve()).replace("'", "''") + "'"


def construir(q3, q10, destino, consulta_cand=()):
    """Gera um banco novo. Bancos de origem são anexados somente para leitura."""
    destino = Path(destino)
    if destino.exists():
        raise FileExistsError(f"Saída já existe: {destino}")
    if not Path(q3).is_file() or not Path(q10).is_file():
        raise FileNotFoundError("São necessários os bancos operacionais completos de Q3 e Q10")
    destino.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(destino))
    try:
        con.execute(f"ATTACH {_sql_path(q3)} AS q3 (READ_ONLY)")
        con.execute(f"ATTACH {_sql_path(q10)} AS q10 (READ_ONLY)")
        con.execute("BEGIN TRANSACTION")
        criar(con)
        con.execute("""CREATE TEMP TABLE partido_chave AS
            WITH fonte AS (
                SELECT numero, upper(sigla) sigla, nome FROM q3.main.partido
                UNION ALL SELECT numero, upper(sigla) sigla, nome FROM q10.main.partido)
            SELECT md5('PARTIDO|' || cast(numero AS varchar) || '|' || sigla) id_partido,
                   sigla, arg_max(nome, length(coalesce(nome,''))) nome, numero
            FROM fonte WHERE numero IS NOT NULL AND sigla IS NOT NULL
            GROUP BY numero, sigla""")
        con.execute("""CREATE TEMP TABLE eleicao_chave AS
            WITH fonte AS (
                SELECT c.ano, c.cd_eleicao, c.turno, c.cd_cargo, ca.nome cargo
                FROM q10.main.candidatura c LEFT JOIN q10.main.cargo ca USING(cd_cargo)
                UNION ALL SELECT ano, cd_eleicao, turno, cd_cargo, cargo
                FROM q3.main.votos_partido_municipio)
            SELECT md5('ELEICAO|' || cast(ano AS varchar) || '|' || cd_eleicao || '|'
                       || cast(turno AS varchar) || '|' || cd_cargo) id_eleicao,
                   ano, cd_eleicao, turno, cd_cargo,
                   arg_max(cargo, length(coalesce(cargo,''))) cargo
            FROM fonte WHERE ano IS NOT NULL AND cd_eleicao IS NOT NULL
                AND turno IS NOT NULL AND cd_cargo IS NOT NULL
            GROUP BY ano, cd_eleicao, turno, cd_cargo""")
        arquivos = [str(Path(p).resolve()) for p in consulta_cand if Path(p).is_file()]
        tem_staging_tipo = con.execute("""SELECT count(*) FROM information_schema.tables
            WHERE table_catalog='q10' AND table_schema='main'
              AND table_name='stg_tipo_eleicao'""").fetchone()[0] > 0
        if tem_staging_tipo:
            con.execute("""CREATE TEMP TABLE tipo_eleicao AS
                SELECT ano,cd_eleicao,turno,cd_cargo,tipo_eleicao,data_eleicao
                FROM q10.main.stg_tipo_eleicao""")
        elif arquivos:
            con.execute("""CREATE TEMP TABLE tipo_eleicao AS
                WITH fonte AS (
                    SELECT try_cast(ANO_ELEICAO AS INTEGER) ano, trim(CD_ELEICAO) cd_eleicao,
                           try_cast(NR_TURNO AS SMALLINT) turno, trim(CD_CARGO) cd_cargo,
                           nullif(trim(NM_TIPO_ELEICAO),'') tipo_eleicao,
                           try_strptime(DT_ELEICAO, '%d/%m/%Y')::DATE data_eleicao
                    FROM read_csv(?, delim=';', header=true, all_varchar=true, union_by_name=true))
                SELECT ano, cd_eleicao, turno, cd_cargo,
                       CASE WHEN count(DISTINCT tipo_eleicao)=1 THEN min(tipo_eleicao) END tipo_eleicao,
                       min(data_eleicao) data_eleicao
                FROM fonte GROUP BY ano, cd_eleicao, turno, cd_cargo""", [arquivos])
        else:
            con.execute("""CREATE TEMP TABLE tipo_eleicao AS
                SELECT NULL::INTEGER ano, NULL::VARCHAR cd_eleicao,
                       NULL::SMALLINT turno, NULL::VARCHAR cd_cargo,
                       NULL::VARCHAR tipo_eleicao, NULL::DATE data_eleicao WHERE false""")
        statements = [
            '''INSERT INTO "Municipio" SELECT id_municipio,cod_tse,nome,uf,regiao FROM q3.main.municipio WHERE id_municipio IS NOT NULL''',
            '''INSERT INTO "Partido" SELECT id_partido,sigla,nome,numero FROM partido_chave''',
            '''INSERT INTO "Eleicao" SELECT e.id_eleicao,e.ano,t.tipo_eleicao,e.turno,e.cargo,
               coalesce(t.data_eleicao,q10e.dt_eleicao,q3e.dt_eleicao)
               FROM eleicao_chave e LEFT JOIN tipo_eleicao t USING(ano,cd_eleicao,turno,cd_cargo)
               LEFT JOIN q10.main.eleicao q10e ON q10e.ano=e.ano AND q10e.cd_eleicao=e.cd_eleicao AND q10e.turno=e.turno
               LEFT JOIN q3.main.eleicao q3e ON q3e.ano=e.ano AND q3e.cd_eleicao=e.cd_eleicao AND q3e.turno=e.turno''',
            '''INSERT INTO "Candidato" SELECT id_candidato,titulo_eleitoral,nome,data_nascimento,genero,raca,ocupacao FROM q10.main.candidato''',
            '''INSERT INTO "Censo_Municipio" SELECT c.id_municipio,c.ano_referencia,c.populacao,c.idhm,c.pib,NULL,NULL
               FROM q3.main.censo_municipio c JOIN "Municipio" m USING(id_municipio)''',
            '''INSERT INTO "Participacao_Eleitoral" SELECT md5('PARTICIPACAO|'||cast(p.ano AS varchar)||'|'||p.id_municipio),
               p.id_municipio,p.ano,NULL,p.eleitorado_apto,p.comparecimento,p.abstencoes,p.taxa_abstencao
               FROM q3.main.participacao_eleitoral p JOIN "Municipio" m USING(id_municipio)
               WHERE (p.ano=2022 AND p.cd_eleicao='544' AND p.turno=1)
                  OR (p.ano=2024 AND p.cd_eleicao='619' AND p.turno=1)''',
                '''INSERT INTO "Candidatura" SELECT c.id_candidatura,e.id_eleicao,c.id_candidato,m.id_municipio,p.id_partido,
                    c.uf,cand.nome_urna,c.numero_candidato,c.idade_eleicao,c.situacao_registro,c.sequencial,c.escolaridade_candidatura,c.patrimonio,c.publicidade_propaganda
               FROM q10.main.candidatura c JOIN eleicao_chave e ON e.ano=c.ano AND e.cd_eleicao=c.cd_eleicao
                 AND e.turno=c.turno AND e.cd_cargo=c.cd_cargo
                    LEFT JOIN q10.main.candidato cand ON cand.id_candidato=c.id_candidato
               LEFT JOIN "Municipio" m ON m.cod_tse=c.cod_tse_municipio
               LEFT JOIN partido_chave p ON p.numero=c.numero_partido AND p.sigla=upper(c.sigla_partido)''',
            '''INSERT INTO "Resultado_Candidatura" SELECT md5('RESULTADO|'||r.id_candidatura),r.id_candidatura,
               c.turno,r.situacao_final,r.votos FROM q10.main.resultado_candidatura r
               JOIN q10.main.candidatura c USING(id_candidatura)''',
            '''INSERT INTO "Cargo" SELECT md5('CARGO|'||c.id_candidatura),ca.nome,c.id_candidatura
               FROM q10.main.candidatura c JOIN q10.main.cargo ca USING(cd_cargo)''',
            '''INSERT INTO "Votos_Partido_Municipio" SELECT md5('VOTOS|'||e.id_eleicao||'|'||p.id_partido||'|'||m.id_municipio),
               e.id_eleicao,p.id_partido,m.id_municipio,v.turno,v.votos_nominais,v.votos_legenda
               FROM q3.main.votos_partido_municipio v JOIN eleicao_chave e ON e.ano=v.ano
                 AND e.cd_eleicao=v.cd_eleicao AND e.turno=v.turno AND e.cd_cargo=v.cd_cargo
               JOIN partido_chave p ON p.numero=v.numero_partido AND p.sigla=upper(v.sigla_partido)
               JOIN "Municipio" m ON m.cod_tse=v.cod_tse_municipio''',
        ]
        for statement in statements:
            con.execute(statement)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return destino
