# Fotos oficiais dos candidatos

A CLI independente consulta os recursos reais do [Portal de Dados Abertos do TSE](https://dadosabertos.tse.jus.br/), constrói vínculos auditáveis e mantém **uma foto principal por `id_candidato`**. A foto é da candidatura mais recente identificada com imagem válida no recorte CE, MA, MS, RJ, RN e RS. A análise pode estar em 2012 e mostrar uma foto de 2024, com o ano informado na interface. Partido, cargo, território, resultados e despesas continuam pertencendo à eleição analisada.

O banco eleitoral é aberto com `read_only=True`. Nenhuma carga de candidaturas, votos ou despesas é executada, nem há escrita automática no MotherDuck. A API não importa o downloader e não consulta o TSE para servir imagens.

## Configuração (PowerShell, na raiz do projeto)

```powershell
uv sync --locked
$env:BDR_BANCO = 'dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb'
$env:BDR_FOTOS_DIR = "$PWD/dados_bdr/fotos/imagens"
$env:BDR_FOTOS_CATALOGO = "$PWD/dados_bdr/fotos/catalogo.sqlite3"
$env:BDR_FOTOS_CACHE = "$PWD/dados_bdr/fotos/zips"
```

Para o banco online, utilize o nome configurado no seu ambiente e forneça `MOTHERDUCK_TOKEN` apenas ao processo servidor/CLI. Neste ambiente não havia `BDR_BANCO` nem token; a configuração padrão resolve para `md:pipeline_bdr_der_completo_v3`, que não pôde ser consultado. O piloto e a aquisição ampla usam explicitamente o DER local v2 existente. Não há troca automática do banco da aplicação.

As variáveis são opcionais: os três caminhos de fotos acima são os padrões, resolvidos a partir da raiz do repositório. `--imagens`, `--catalogo`, `--cache` e `--banco` permitem substituí-los na CLI. Configure os mesmos caminhos na API. A pasta de imagens pode ficar em outro disco/volume; não precisa ficar junto ao código. Dados e ZIPs não entram no Git.

## Piloto real e outros recortes

```powershell
# ENOQUE REIS SILVA (exemplo MA/2012) e uma pessoa do recorte Q9/2024.
uv run python -m bdr.fotos adquirir --banco $env:BDR_BANCO --pessoa 70d7ce77dc24bbd7f954660bae3ee758 --pessoa ea74dcd94638af13ede521863773cfa5 --uf MA --ano 2012 2024 2026 --workers 1

# Uma pessoa: procura também anos posteriores aos presentes no DER, inclusive 2026.
uv run python -m bdr.fotos adquirir --pessoa ea74dcd94638af13ede521863773cfa5

# Todas as pessoas vinculadas a CE e MA; busca limitada a essas UFs.
uv run python -m bdr.fotos adquirir --todos --uf CE MA --workers 2

# Todas as pessoas das seis UFs; execução ampla explicitamente autorizada por --todos.
uv run python -m bdr.fotos adquirir --todos --workers 2

# Retomar a aquisi??o completa, sem --atualizar.
uv run python -m bdr.fotos adquirir --todos --workers 2

# Continuar apenas fotos ap?s concluir a confer?ncia de identidade no cat?logo.
# N?o abre o DER, n?o redescobre fontes e n?o busca candidaturas novas.
uv run python -m bdr.fotos adquirir --todos --retomar-fotos --workers 4

# Atualização explícita: redescobre conjuntos e substitui caches a partir de 2024.
uv run python -m bdr.fotos adquirir --todos --atualizar --desde 2024 --workers 2

# Somente cadastros/vínculos, sem baixar pacotes de fotos.
uv run python -m bdr.fotos adquirir --todos --somente-cadastros

# Estatísticas persistidas e pendências, sem abrir o DER nem acessar a rede.
uv run python -m bdr.fotos relatorio
```

O executável `uv run bdr-fotos` também está disponível. `--pessoa` aceita o **id da pessoa** e pode ser repetido; não aceita o hash da candidatura como substituto. `--ano` limita fontes para pilotos e sempre produz cobertura incompleta. Ao reutilizar o catálogo, as pessoas e fontes anteriormente processadas são mantidas; um filtro acrescenta/atualiza esse escopo, sem apagar as demais pessoas.

Uma execução interrompida mantém os lotes concluídos e os pacotes em cache. Apenas um processo de aquisição deve escrever nesse catálogo por vez. Em encerramento forçado do processo/SO, confirme que o processo terminou e remova **somente** `dados_bdr/fotos/catalogo.lock` antes de retomar. Transações incompletas do SQLite são revertidas. Arquivos `.part` abandonados podem ser removidos com o processo parado; nunca são tratados como cache válido.

## Identidade e escolha da imagem

1. O DER é descoberto em `der_bdr` ou `main`, seguindo a estratégia existente. Pessoas e candidaturas são consultadas em lotes de 1.000 linhas. Sequenciais permanecem texto; nulos, negativos e marcadores não se tornam chaves.
2. Os conjuntos são descobertos pela API CKAN `package_search`, com paginação. As URLs de cadastro e fotos são lidas dos recursos publicados, sem fabricar URLs de download. O catálogo guarda o JSON de metadados, a URL e a data da descoberta.
3. Os cadastros são lidos do mais recente para o mais antigo. A âncora principal usa ano + UF + sequencial da candidatura interna, com conferência da biografia e do título quando disponível. Título é apenas chave candidata, acompanhado de nome normalizado exato e nascimento exato. CPF válido utiliza a função de validação da pipeline. Um hash interno só é reconhecido como hash CPF quando o CPF válido da fonte reproduz exatamente `md5('CPF|' + cpf)` e a biografia confere. Não se presume que todos os IDs sejam hashes CPF.
4. Identificadores comprovados nas âncoras permitem encontrar outras candidaturas da pessoa nos cadastros, inclusive candidaturas de 2026 inexistentes no DER. Cada registro-fonte tem chave técnica própria no catálogo, **sem inventar `id_candidatura` eleitoral**. Título/CPF nunca são expostos na API; o catálogo usa hashes locais desses valores e da biografia. Os ZIPs brutos continuam contendo os dados oficiais e devem ficar restritos ao processamento.
5. Associações contraditórias ou múltiplas pessoas para uma mesma evidência são auditadas e não recebem vínculo automático. Não há vínculo por nome isolado, aproximação, partido ou número de urna. A recuperação de sequencial ausente ocorre somente no catálogo pelo método auditável de título+biografia; nunca altera a candidatura do DER.
6. A ordenação usa data da eleição, ou ano quando a data está ausente. Candidaturas suplementares presentes nos cadastros são consideradas por sua data. Turnos com a mesma chave de foto compartilham o arquivo. Duas chaves diferentes empatadas na última data geram `associacao_ambigua`.
7. A foto mais recente válida é escolhida por pessoa. Se a última candidatura não tem imagem válida, uma anterior pode ser usada, com `foto_anterior=true`, mantendo separados os metadados da última candidatura e da origem da foto. Falha temporária não vira ausência definitiva.

O catálogo não afirma que a fonte publicada contém todas as inscrições possíveis. Cobertura significa fontes efetivamente lidas no escopo e data registrados. Não é uma busca nacional. Ausência de conjuntos suplementares separados nos metadados não comprova ausência de todas as eleições suplementares; candidaturas suplementares só podem ser consideradas quando publicadas nos cadastros descobertos.

## Aquisição, segurança e retomada

Dois pacotes simultâneos por padrão (`--workers 1..4`), timeout de 60 segundos por operação de rede e três tentativas limitadas. Cada pacote tem cache único por nome oficial. Downloads e imagens usam arquivo temporário no mesmo volume e substituição atômica. Os cadastros são descompactados em fluxo, sem `extractall()` e sem carregar os ZIPs/imagens completos em memória. A lista central de membros do ZIP fica em memória; os dados das imagens, uma por vez.

Limites: pacote de 4 GiB, membro CSV de 3 GiB, imagem de 12 MiB e 24 milhões de pixels. Caminhos absolutos, `..`, barras invertidas, volumes Windows e links simbólicos são recusados. Somente JPEG/PNG reais com extensão compatível são publicados, após verificação e decodificação completa pelo Pillow. SHA-256, tamanho, dimensões, origem e data da validação são persistidos.

Foram inspecionados os nomes `MA100000006157_div.jpg` no pacote de 2012 e `FMA100002141968_div.jpg` no de 2024. Existem dois reconhecedores explícitos para esses formatos (com UF variável e extensões JPEG/PNG permitidas). Cada pacote é inspecionado; outros nomes geram `formato_desconhecido`, sem adivinhar sequenciais. PDFs informativos são ignorados. Fotos excedentes nunca criam candidaturas ou pessoas. Reexecuções verificam as imagens existentes e não reextraem arquivos válidos. Uma foto disponível mais recente dispensa baixar fotos históricas daquela pessoa.

Estados relevantes: `nao_processada`, `disponivel`, `nao_encontrada`, `erro_temporario`, `pacote_indisponivel`, `pacote_invalido`, `formato_desconhecido`, `imagem_invalida`, `associacao_pendente` e `associacao_ambigua`. As falhas ficam isoladas por fonte/pacote/imagem. `nao_processada` não significa ausência na fonte. Consulte `cobertura`, `aquisicao_imagens` e `auditoria` no relatório para pendências.

## API e implantação

```powershell
uv run uvicorn frontend.main:app --host 127.0.0.1 --port 8000
```

Em outro terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

`GET /api/candidatos/{id_candidato}/foto` serve o arquivo local com MIME validado, ETag, cache de uma hora e `nosniff`; arquivo ausente retorna 404 sem cache. O cliente fornece somente o id da pessoa. O caminho é resolvido pelo catálogo e confinado à raiz configurada. A rota não consulta o DER, nem acessa o TSE.

`/api/q9/candidatos`, o candidato selecionado de `/api/q9/despesas` e a entidade pessoa de `/api/q9/evolucao` preservam seus campos e acrescentam `foto_url`, `foto_ano`, `foto_status`, `foto_anterior`, `foto_cobertura_completa`, `foto_ultima_status` e `foto_ultima_candidatura`. A consulta ao SQLite é indexada e feita em lote, sem reler todo o catálogo e sem consulta eleitoral por foto. O enriquecimento fica fora do cache dos resultados analíticos: aquisições novas aparecem sem invalidar as despesas. Sem catálogo ou com armazenamento indisponível, os painéis continuam funcionando com avatar.

O componente Preact `FotoCandidato` mostra o ano da imagem, mantém dimensões, utiliza lazy loading e trata erros com iniciais. O estado do retrato é reiniciado quando muda a pessoa ou a imagem. O cartão histórico de evolução continua sem retratos por eleição; o retrato principal aparece na busca/cartão da pessoa com a data identificada. Nenhuma paleta partidária foi alterada.

Na implantação, monte/preserve o diretório de imagens e o catálogo auxiliar em volume persistente. A API precisa apenas de leitura; a CLI precisa de escrita no catálogo, nas imagens e no cache. Não exponha o cache de ZIPs nem o SQLite como diretório estático. Para copiar um SQLite com processo de aquisição ativo, use a API de backup do SQLite; para uma cópia de arquivos, finalize a aquisição antes e preserve a consistência dos arquivos WAL/SHM. Em múltiplas máquinas, execute a aquisição em uma e publique uma cópia consistente do catálogo e das imagens para cada servidor. O proxy `/api` existente do Vite já atende a rota.

## Validação

```powershell
uv run python -m unittest discover -s tests -v
Set-Location frontend
npm run test:q9
npm run test:cores
npm run build
```

O relatório real desta execução, os números de cobertura e a verificação dos totais eleitorais são registrados em [RESULTADO_fotos.md](RESULTADO_fotos.md). Os relatórios detalhados e logs ficam em `dados_bdr/fotos/`, fora do Git.
