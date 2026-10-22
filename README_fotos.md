# Fotos oficiais de candidatos no DER

O comando `baixar_fotos.py` acrescenta a tabela `Foto_Candidato` ao DER existente.
O banco socioeconômico e a Q10 não precisam ser reconstruídos.

## Execução

```powershell
uv run python baixar_fotos.py --banco dados_bdr/saida/pipeline_bdr_der_completo_v2_demografia.duckdb --ano-minimo 2020
```

As UFs vêm da tabela `Municipio`: no banco atual, CE, MA, MS, RJ, RN e RS. É
possível limitar com `--ufs RN MA`. A carga consulta os anos presentes nas
candidaturas, do mais recente até 2020 por padrão, e só procura anos anteriores para
candidatos que continuam sem foto. `--anos 2024 2022` limita os anos explicitamente.
Se a pessoa só tem candidaturas anteriores a 2020, sua foto não é buscada.
Para ampliar o histórico explicitamente, use `--ano-minimo 2006`.

Pode repetir o mesmo comando após uma interrupção. Cada UF/ano é gravada em uma
transação. Fotos já gravadas são ignoradas; os ZIPs existentes são reutilizados.
`--somente-cache` processa exclusivamente arquivos já baixados, sem rede.
Feche conexões que escrevem no mesmo banco antes de executar a carga.

## Fonte e vínculo

O [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/dataset/candidatos-2024)
publica ZIPs de fotos por UF, por exemplo:

```text
https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2024/fotos/foto_cand2024_RN_div.zip
```

O nome confirmado no ZIP é `FRN200002189759_div.jpeg`. A leitura também aceita
nomes como `MA233112.jpg`. O vínculo usa **ano do ZIP + UF + SQ_CANDIDATO**, que
corresponde à coluna `Candidatura.sequencial`, e só então encontra o `id_candidato`.
Não usa nome, número de urna, CPF ou um sequencial de outro ano.

Se uma chave corresponde a mais de um `id_candidato`, a foto não é associada
automaticamente. O manifesto registra essas ambiguidades. Uma candidatura em
dois turnos para o mesmo ID não é ambígua. Uma foto da pessoa pode aparecer em
sua trajetória de outros anos, sempre exibindo o ano original da foto.

O TSE fornece arquivos por UF/ano: para localizar uma imagem é necessário baixar
o ZIP correspondente. Isso pode transferir imagens de outras pessoas, mas só as
fotos identificadas no DER são lidas e persistidas. Não é possível evitar essa
transferência em lote usando apenas os ZIPs do portal.

## Armazenamento e validação

`Foto_Candidato` tem chave primária e FK `id_candidato`, garantindo uma foto por
pessoa. Contém ano, UF, sequencial, nome original, URL oficial, tipo MIME, SHA-256,
dimensões, tamanho, data de coleta e **imagem BLOB**. As imagens JPEG/PNG são
validadas antes da gravação. Não há caminhos locais usados como referência das
imagens no banco. Casos sem foto ficam sem linha; não se inventa uma imagem.

O cache fica em `dados_bdr/fotos/zips/`. O relatório de cada execução está em
`dados_bdr/fotos/manifesto_fotos.json`, com arquivos processados/indisponíveis,
chaves ambíguas, imagens inválidas e total de candidatos ainda sem foto.

A relação com municípios passa por `Candidatura`, pois uma pessoa pode concorrer
em municípios diferentes ao longo da vida. Não se fixa um único município na foto:

```sql
SELECT DISTINCT m.id_municipio, m.nome AS municipio, m.uf,
       c.id_candidato, p.nome_civil, f.ano_foto, f.mime_type, f.imagem
FROM Candidatura c
JOIN Municipio m USING (id_municipio)
JOIN Candidato p USING (id_candidato)
JOIN Foto_Candidato f USING (id_candidato)
WHERE m.uf = 'MA';
```

Disputas estaduais e nacionais não ganham um município artificialmente. A foto é
ligada à pessoa mesmo quando `Candidatura.id_municipio` não está preenchido.

## Painel

Execute `uv run streamlit run bdr/app_apuracao.py`, selecione o banco local e abra
**Q10 → Trajetória individual**. A foto aparece após selecionar a pessoa.

## Enviar depois ao MotherDuck

```powershell
uv run python publicar_fotos.py --banco-local dados_bdr/saida/pipeline_bdr_der_completo_v2_demografia.duckdb --motherduck-db pipeline_bdr_der_completo_v2
```

Use a mesma autenticação já empregada pelo projeto (`MOTHERDUCK_TOKEN` no ambiente
ou autenticação oferecida pela extensão). O comando é uma etapa explícita e não
roda durante o download. Ele acrescenta somente `Foto_Candidato`, conferindo antes
que as candidaturas de origem existem no destino, depois compara SHA-256 e bytes.
Fotos já existentes são ignoradas. Se um ID já tiver outra foto, a publicação
interrompe sem substituir a imagem. As outras tabelas não são recriadas.

O esquema `TABELAS_DER` também inclui `Foto_Candidato` para publicações completas
de bancos novos. Em bancos locais antigos, execute a etapa de fotos antes de
publicar com esse esquema atualizado.
