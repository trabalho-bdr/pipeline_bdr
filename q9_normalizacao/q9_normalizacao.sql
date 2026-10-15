/* Q9 — normalização e agrupamento analítico de descrições de despesas.
Selecionar antes o banco/schema com Despesa_Candidatura(id_despesa,
id_candidatura,categoria,valor). Executar a instalação uma vez.
Não altera tabelas nem valores. Cria/substitui apenas macro e views q9.
Grupos sugeridos a partir de texto; não são categorias oficiais do TSE.
A exportação usada contém exatamente 50.000 descrições e pode ser parcial.
As regras são aplicadas a TODAS as descrições existentes no banco selecionado.

ALIAS_EXPLICITO: equivalência definida no dicionário fornecido; não significa
validação oficial. REGRA_TEXTUAL_REVISAR: sugestão por expressão regular.
MULTIPLAS_CATEGORIAS: mais de um grupo detectado, sem rateio do valor.
SEM_REGRA/AUSENTE: preservados sem classificação forçada.
FALSE no indicador de publicidade significa "fora do conceito estreito de
publicidade adotado nesta proposta", não uma classificação legal ou oficial.
NULL significa indefinido. Toda REGRA_TEXTUAL_REVISAR requer conferência.
Panfletagem e militância ficam em mobilização com publicidade indefinida:
a inclusão no conceito de propaganda deve ser uma decisão metodológica.
As categorias são processadas uma vez por descrição distinta, antes da junção.
*/
BEGIN TRANSACTION;
CREATE OR REPLACE MACRO q9_normalizar_categoria(texto) AS
    trim(regexp_replace(upper(strip_accents(coalesce(cast(texto AS VARCHAR), ''))),
                        '[^A-Z0-9]+', ' ', 'g'));

CREATE OR REPLACE VIEW vw_q9_regras_categorias AS
SELECT * FROM (VALUES
    ('DIGITAL_PAGO', 'Publicidade digital paga', 'Impulsionamento e mídia paga', TRUE, '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|ANUNCIOS? PATROCINADOS?)\b', NULL),
    ('IMPRESSOS', 'Materiais impressos', 'Impressos de campanha', TRUE, '\b(SANTINHOS?|SANTOES|SANTAO|COLINHAS?|FOLDERS?|FOLHETOS?|PANFLETOS?|CARTAZES?|CARTAZ|INFORMATIVOS?|MATERIA(IS|L) (GRAFICO(S)?|IMPRESSO(S)?))\b|^IMPRESSOS?$', NULL),
    ('ADESIVOS', 'Adesivos e botons', 'Adesivos e botons', TRUE, '\b(ADESIVOS?|PRAGUINHAS?|BOTONS?|BOTTONS?|BOTON|BOTTON|PERFURADOS?|MICROPERFURADOS?|PERFURITE)\b', NULL),
    ('VISUAIS', 'Bandeiras, faixas e banners', 'Bandeiras, faixas e banners', TRUE, '\b(BANDEIRAS?|FAIXAS?|BANNERS?|WINDBANNERS?|WIND BANNERS?)\b', NULL),
    ('AUDIOVISUAL', 'Produção audiovisual', 'Produção de áudio, vídeo e fotografia', TRUE, '\b(AUDIOVISUA(L|IS)|VIDEOS?|JINGLES?|FILMAGEM|CINEGRAFISTAS?|FOTOGRAF(IA|IAS|ICO|ICOS|O|OS|A|AS))\b|\bPRODUCAO\b.*\b(RADIO|TV|TELEVISAO|PROGRAMAS?)\b', NULL),
    ('CARRO_SOM', 'Carro de som e sonorização de propaganda', 'Carro de som', TRUE, '\b(CARROS? DE SOM|VEICULOS? DE SOM|BICICLETAS? DE SOM|PROPAGANDA VOLANTE)\b', NULL),
    ('VEICULACAO', 'Veiculação em rádio, TV e imprensa', 'Veiculação em meios de comunicação', TRUE, '\b(VEICULACAO|ANUNCIOS?|INSERCOES)\b.*\b(RADIO|TV|TELEVISAO|JORNAL|JORNAIS|REVISTAS?|IMPRENSA)\b', NULL),
    ('PUBLICIDADE_GERAL', 'Publicidade e marketing sem modalidade definida', 'Publicidade sem modalidade definida', TRUE, '\b(PUBLICIDADE|PROPAGANDA|MARKETING)\b', '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|SANTINHOS?|SANTAO|SANTOES|COLINHAS?|FOLDERS?|FOLHETOS?|PANFLETOS?|CARTAZES?|ADESIVOS?|PRAGUINHAS?|BOTONS?|BOTTONS?|BANDEIRAS?|BANNERS?|WINDBANNERS?|VIDEOS?|JINGLES?|AUDIOVISUA(L|IS)|CARROS? DE SOM|VEICULACAO)\b'),
    ('REDES_DIGITAIS', 'Redes sociais e conteúdo digital', NULL, NULL, '\b(REDES? SOCIA(IS|L)|MIDIAS? SOCIA(IS|L)|SOCIAL MEDIA|FACEBOOK|INSTAGRAM|GOOGLE|SITES?|INTERNET)\b', '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|ANUNCIOS? PATROCINADOS?)\b'),
    ('MOBILIZACAO', 'Mobilização, militância e panfletagem', NULL, NULL, '\b(MILITAN(CIA|CIAS|TES?|TE)|MOBILIZA(CAO|COES)|CABOS? ELEITORA(IS|L)|ATIVISTAS?|PANFLETAGEM|PANFLETEIR(O|OS|A|AS)|PANFLETISTAS?|BANDEIRISTAS?)\b', NULL),
    ('JURIDICO', 'Serviços jurídicos', NULL, FALSE, '\b(ADVOC[A-Z]*|ADVOG[A-Z]*|JURIDIC[A-Z]*)\b', NULL),
    ('CONTABIL', 'Serviços contábeis', NULL, FALSE, '\b(CONTAB[A-Z]*|CONTADOR(ES|AS|A)?)\b', NULL),
    ('COMBUSTIVEL', 'Combustíveis', NULL, FALSE, '\b(GASOLINA|DIESEL|ETANOL|COMBUSTIVE(L|IS))\b', NULL),
    ('VEICULOS', 'Locação de veículos e transporte', NULL, FALSE, '\b(LOCACAO|ALUGUEL|CESSAO|FRETAMENTO)\b.*\b(VEICULOS?|CARROS?|VANS?|ONIBUS|MICROONIBUS|AERONAVES?|HELICOPTEROS?|AVIAO|CAMINHAO|MOTOCICLETAS?)\b|\b(PASSAGENS|TRANSPORTE DE PESSOAL|SERVICOS DE TRANSPORTE)\b', '\b(CARROS? DE SOM|VEICULOS? DE SOM)\b'),
    ('MOTORISTAS', 'Serviços de motorista', NULL, FALSE, '\bMOTORISTAS?\b', NULL),
    ('PESSOAL', 'Pessoal administrativo e coordenação', NULL, FALSE, '\b(COORDEN[A-Z]*|ASSISTENTES?|ADMINISTRADOR(ES|AS|A)?|GERENTES?|SECRETARI(O|OS|A|AS)|DESPESAS? COM PESSOAL|LIDER(ES)? DE EQUIPE|ATENDENTES?)\b', NULL),
    ('IMOVEIS', 'Locação de imóveis e espaços', NULL, FALSE, '\b(LOCACAO|ALUGUEL|CESSAO)\b.*\b(IMOVEL|IMOVEIS|ESPACOS?|SALAS?|SEDE|COMITE)\b', NULL),
    ('ALIMENTACAO', 'Alimentação e bebidas', NULL, FALSE, '\b(ALIMENTACAO|REFEICOES|REFEICAO|MARMIT(EX|AS|A)|LANCHES?|REFRIGERANTES?|BEBIDAS?|AGUA MINERAL)\b', NULL),
    ('PESQUISAS', 'Pesquisas eleitorais e de opinião', NULL, FALSE, '\b(PESQUISAS?|SONDAGEM|SONDAGENS)\b', NULL),
    ('EVENTOS', 'Eventos e estrutura', NULL, NULL, '\b(COMICIOS?|CARREATAS?|EVENTOS?|PALCOS?|TENDAS?|ILUMINACAO|SONORIZACAO|ESTRUTURA DE SOM)\b', '\b(CARROS? DE SOM|VEICULOS? DE SOM)\b'),
    ('POSTAIS', 'Correspondência e serviços postais', NULL, NULL, '\b(CORREIOS|POSTAIS|MALA DIRETA)\b', NULL),
    ('TELEFONIA', 'Telefonia e conectividade', NULL, FALSE, '\b(TELEFONIA|TELEFONES?|LINHAS? TELEFONICAS?|DADOS MOVEIS|BANDA LARGA)\b', NULL),
    ('TRIBUTOS', 'Tributos e tarifas', NULL, FALSE, '\b(TARIFAS?|TAXAS?|IMPOSTOS?|IRRF|INSS|ISSQN|ENCARGOS SOCIAIS)\b', NULL),
    ('EQUIPAMENTOS', 'Equipamentos e materiais de apoio', NULL, FALSE, '\b(COMPUTADORES?|NOTEBOOKS?|IMPRESSORAS?|AR CONDICIONADO|MATERIAL DE ESCRITORIO|MATERIAIS DE ESCRITORIO)\b', NULL),
    ('VESTUARIO', 'Vestuário e acessórios', NULL, NULL, '\b(CAMISETAS?|CAMISAS?|BONES?|COLETES?)\b', NULL),
    ('COMUNICACAO', 'Comunicação sem especificação', NULL, NULL, '\bCOMUNICACAO\b', '\b(MARKETING|PUBLICIDADE|PROPAGANDA|IMPULSIONAMENTOS?|VIDEOS?|AUDIOVISUA(L|IS)|RADIO|TV|TELEVISAO)\b'),
    ('GENERICO', 'Serviços ou documentos sem especificação', NULL, NULL, '^(CONTRATO|ADITIVO CONTRATUAL|CONTRATO DE PRESTACAO DE SERVICOS?|PRESTACAO DE SERVICOS?|SERVICOS? PRESTADOS?|HONORARIOS|SERVICOS? DE CAMPANHA|SERVICOS? ELEITORAIS|DIVULGACAO|APOIO NA CAMPANHA ELEITORAL|ATIVIDADES POLITICAS EM GERAL)$', NULL)
) AS r(codigo_regra, grupo_despesa, modalidade_publicidade_sugerida,
       eh_publicidade_sugerida, padrao, exclusao);

CREATE OR REPLACE VIEW vw_q9_aliases_categorias AS
SELECT * FROM (VALUES
    ('ADESIVO', 'Adesivos', 'ADESIVOS'),
    ('ADESIVO MICROPERFURADO', 'Adesivos perfurados', 'ADESIVOS'),
    ('ADESIVO PERFURADO', 'Adesivos perfurados', 'ADESIVOS'),
    ('ADESIVO VINIL', 'Adesivos', 'ADESIVOS'),
    ('ADESIVOS', 'Adesivos', 'ADESIVOS'),
    ('ADESIVOS PERFURADOS', 'Adesivos perfurados', 'ADESIVOS'),
    ('ALUGUEL DO CARRO', 'Locação de veículos', 'VEICULOS'),
    ('ASSESSORIA CONTABIL', 'Serviços contábeis', 'CONTABIL'),
    ('ASSESSORIA DE COMUNICACAO', 'Comunicação sem especificação', 'COMUNICACAO'),
    ('ASSESSORIA JURIDICA', 'Assessoria e consultoria jurídica', 'JURIDICO'),
    ('ASSISTENTE', 'Assistência de campanha', 'PESSOAL'),
    ('ASSISTENTE DE CAMPANHA', 'Assistência de campanha', 'PESSOAL'),
    ('ASSISTENTE DE CAMPANHA ELEITORAL', 'Assistência de campanha', 'PESSOAL'),
    ('ATIVIDADE DE MILITANCIA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('ATIVIDADE DE MILITANCIA E MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('ATIVIDADE DE MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('ATIVIDADES DE MILITANCIA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('ATIVIDADES DE MILITANCIA E MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('ATIVISTA', 'Ativista de campanha', 'MOBILIZACAO'),
    ('BANDEIRA', 'Bandeiras', 'VISUAIS'),
    ('BANDEIRA FIXA', 'Bandeiras', 'VISUAIS'),
    ('BANDEIRAS', 'Bandeiras', 'VISUAIS'),
    ('BANNER', 'Banners', 'VISUAIS'),
    ('BANNERS', 'Banners', 'VISUAIS'),
    ('BOTON', 'Botons', 'ADESIVOS'),
    ('BOTONS', 'Botons', 'ADESIVOS'),
    ('BOTTON', 'Botons', 'ADESIVOS'),
    ('BOTTONS', 'Botons', 'ADESIVOS'),
    ('CABO ELEITORAL', 'Cabo eleitoral', 'MOBILIZACAO'),
    ('CARRO DE SOM', 'Carro de som', 'CARRO_SOM'),
    ('CARTAZ', 'Cartazes', 'IMPRESSOS'),
    ('CARTAZES', 'Cartazes', 'IMPRESSOS'),
    ('COLINHA', 'Colinhas', 'IMPRESSOS'),
    ('COLINHAS', 'Colinhas', 'IMPRESSOS'),
    ('COMBUSTIVEIS', 'Combustíveis sem especificação', 'COMBUSTIVEL'),
    ('COMBUSTIVEL', 'Combustíveis sem especificação', 'COMBUSTIVEL'),
    ('CONSULTORIA DE MARKETING', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('CONSULTORIA JURIDICA', 'Assessoria e consultoria jurídica', 'JURIDICO'),
    ('COORDENACAO', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENACAO DE CAMPANHA', 'Coordenação de campanha', 'PESSOAL'),
    ('COORDENADOR', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENADOR DE CAMPANHA', 'Coordenação de campanha', 'PESSOAL'),
    ('COORDENADOR DE EQUIPE', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENADOR ELEITORAL', 'Coordenação de campanha', 'PESSOAL'),
    ('COORDENADOR GERAL', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENADOR GERAL DE CAMPANHA', 'Coordenação de campanha', 'PESSOAL'),
    ('COORDENADOR REGIONAL', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENADORA', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('COORDENADORA DE CAMPANHA', 'Coordenação de campanha', 'PESSOAL'),
    ('CORREIOS', 'Serviços postais', 'POSTAIS'),
    ('CREDITO DE IMPULSIONAMENTO', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('CRIACAO E PRODUCAO AUDIOVISUAL', 'Produção audiovisual', 'AUDIOVISUAL'),
    ('DESPESA COM IMPULSIONAMENTO', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('DESPESA COM PESSOAL', 'Despesas com pessoal', 'PESSOAL'),
    ('DESPESA COM PESSOAL DE CAMPANHA', 'Despesas com pessoal', 'PESSOAL'),
    ('DESPESAS COM PESSOAL', 'Despesas com pessoal', 'PESSOAL'),
    ('DIESEL', 'Óleo diesel', 'COMBUSTIVEL'),
    ('DIESEL S10', 'Diesel S10', 'COMBUSTIVEL'),
    ('DISTRIBUICAO DE PANFLETOS', 'Panfletagem', 'MOBILIZACAO'),
    ('DIVULGACAO POR PANFLETAGEM', 'Panfletagem', 'MOBILIZACAO'),
    ('FACEBOOK', 'Plataforma digital sem especificação do serviço', 'REDES_DIGITAIS'),
    ('FOLDER', 'Folders', 'IMPRESSOS'),
    ('FOLDERS', 'Folders', 'IMPRESSOS'),
    ('FOLHETO', 'Folhetos e panfletos', 'IMPRESSOS'),
    ('FOLHETOS', 'Folhetos e panfletos', 'IMPRESSOS'),
    ('FUNCAO DE COORDENADOR DE EQUIPE', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('GASOLINA', 'Gasolina', 'COMBUSTIVEL'),
    ('GASOLINA ADITIVADA', 'Gasolina aditivada', 'COMBUSTIVEL'),
    ('GASOLINA C COMUM', 'Gasolina comum', 'COMBUSTIVEL'),
    ('GASOLINA COMUM', 'Gasolina comum', 'COMBUSTIVEL'),
    ('GASOLINA COMUN', 'Gasolina comum', 'COMBUSTIVEL'),
    ('GOOGLE', 'Plataforma digital sem especificação do serviço', 'REDES_DIGITAIS'),
    ('HONORARIOS ADVOCATICIOS', 'Serviços advocatícios', 'JURIDICO'),
    ('HONORARIOS CONTABEIS', 'Serviços contábeis', 'CONTABIL'),
    ('IMPRESSOS', 'Material gráfico impresso', 'IMPRESSOS'),
    ('IMPULSIONAMENTO', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO DE CONTEUDO', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO DE CONTEUDOS', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO DE FACEBOOK', 'Impulsionamento no Facebook', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO DE REDE FACEBOOK', 'Impulsionamento no Facebook', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO FACEBOOK', 'Impulsionamento no Facebook', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO GOOGLE', 'Impulsionamento no Google', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO NO FACEBOOK', 'Impulsionamento no Facebook', 'DIGITAL_PAGO'),
    ('IMPULSIONAMENTO REDES SOCIAIS', 'Impulsionamento em redes sociais', 'DIGITAL_PAGO'),
    ('INFORMATIVO', 'Informativos', 'IMPRESSOS'),
    ('INFORMATIVOS', 'Informativos', 'IMPRESSOS'),
    ('INSTAGRAM', 'Plataforma digital sem especificação do serviço', 'REDES_DIGITAIS'),
    ('JINGLE', 'Jingles', 'AUDIOVISUAL'),
    ('LIDER DE EQUIPE', 'Coordenação sem função detalhada', 'PESSOAL'),
    ('LOCACAO DE IMOVEL', 'Locação de imóveis', 'IMOVEIS'),
    ('LOCACAO DE IMOVEL PARA O COMITE DE CAMPANHA', 'Locação de imóveis', 'IMOVEIS'),
    ('LOCACAO DE VEICULO', 'Locação de veículos', 'VEICULOS'),
    ('LOCACAO DE VEICULOS', 'Locação de veículos', 'VEICULOS'),
    ('LOCACAO VEICULO', 'Locação de veículos', 'VEICULOS'),
    ('MALA DIRETA POSTAL', 'Serviços postais', 'POSTAIS'),
    ('MARKETING', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('MARKETING DIGITAL', 'Marketing digital sem especificação de mídia paga', 'PUBLICIDADE_GERAL'),
    ('MATERIAIS IMPRESSOS', 'Material gráfico impresso', 'IMPRESSOS'),
    ('MATERIAL GRAFICO', 'Material gráfico impresso', 'IMPRESSOS'),
    ('MATERIAL IMPRESSO', 'Material gráfico impresso', 'IMPRESSOS'),
    ('MATL IMPRESSO', 'Material gráfico impresso', 'IMPRESSOS'),
    ('MILITANCIA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('MILITANCIA DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('MILITANCIA E MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('MILITANTE', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('MOTORISTA', 'Serviços de motorista', 'MOTORISTAS'),
    ('OLEO DIESEL', 'Óleo diesel', 'COMBUSTIVEL'),
    ('OLEO DIESEL B S10', 'Diesel S10', 'COMBUSTIVEL'),
    ('OLEO DIESEL S10', 'Diesel S10', 'COMBUSTIVEL'),
    ('PANFLETAGEM', 'Panfletagem', 'MOBILIZACAO'),
    ('PANFLETEIRO', 'Panfletagem', 'MOBILIZACAO'),
    ('PANFLETISTA', 'Panfletagem', 'MOBILIZACAO'),
    ('PANFLETO', 'Folhetos e panfletos', 'IMPRESSOS'),
    ('PANFLETOS', 'Folhetos e panfletos', 'IMPRESSOS'),
    ('PERFURADO', 'Adesivos perfurados', 'ADESIVOS'),
    ('PERFURADOS', 'Adesivos perfurados', 'ADESIVOS'),
    ('PESQUISA', 'Pesquisas eleitorais e de opinião', 'PESQUISAS'),
    ('PESQUISA ELEITORAL', 'Pesquisas eleitorais e de opinião', 'PESQUISAS'),
    ('PESQUISA QUALITATIVA', 'Pesquisas eleitorais e de opinião', 'PESQUISAS'),
    ('PRAGUINHA', 'Adesivos', 'ADESIVOS'),
    ('PRAGUINHAS', 'Adesivos', 'ADESIVOS'),
    ('PRESTACAO DE SERVICOS ADVOCATICIOS', 'Serviços advocatícios', 'JURIDICO'),
    ('PRESTACAO DE SERVICOS CONTABEIS', 'Serviços contábeis', 'CONTABIL'),
    ('PRODUCAO DE JINGLE', 'Jingles', 'AUDIOVISUAL'),
    ('PRODUCAO DE PROGRAMA DE TV', 'Produção audiovisual', 'AUDIOVISUAL'),
    ('PRODUCAO DE VIDEOS', 'Produção de vídeos', 'AUDIOVISUAL'),
    ('PRODUCAO PARA RADIO E TELEVISAO', 'Produção audiovisual', 'AUDIOVISUAL'),
    ('PROGRAMA DE RADIO E TV', 'Produção audiovisual', 'AUDIOVISUAL'),
    ('PROPAGANDA E PUBLICIDADE', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('PUBLICIDADE POR CARRO DE SOM', 'Carro de som', 'CARRO_SOM'),
    ('SANTAO', 'Santões', 'IMPRESSOS'),
    ('SANTINHO', 'Santinhos', 'IMPRESSOS'),
    ('SANTINHOS', 'Santinhos', 'IMPRESSOS'),
    ('SANTOES', 'Santões', 'IMPRESSOS'),
    ('SERVICO DE ATIVISTA', 'Ativista de campanha', 'MOBILIZACAO'),
    ('SERVICO DE CABO ELEITORAL', 'Cabo eleitoral', 'MOBILIZACAO'),
    ('SERVICO DE IMPULSIONAMENTO', 'Impulsionamento de conteúdo', 'DIGITAL_PAGO'),
    ('SERVICO DE MARKETING', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('SERVICO DE MILITANCIA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('SERVICO DE MOTORISTA', 'Serviços de motorista', 'MOTORISTAS'),
    ('SERVICO DE PANFLETAGEM', 'Panfletagem', 'MOBILIZACAO'),
    ('SERVICOS ADVOCATICIOS', 'Serviços advocatícios', 'JURIDICO'),
    ('SERVICOS CONTABEIS', 'Serviços contábeis', 'CONTABIL'),
    ('SERVICOS DE ADVOCACIA', 'Serviços advocatícios', 'JURIDICO'),
    ('SERVICOS DE ATIVISTA', 'Ativista de campanha', 'MOBILIZACAO'),
    ('SERVICOS DE CABO ELEITORAL', 'Cabo eleitoral', 'MOBILIZACAO'),
    ('SERVICOS DE COMUNICACAO', 'Comunicação sem especificação', 'COMUNICACAO'),
    ('SERVICOS DE CONTABILIDADE', 'Serviços contábeis', 'CONTABIL'),
    ('SERVICOS DE IMPULSIONAMENTO EM REDE SOCIAL', 'Impulsionamento em redes sociais', 'DIGITAL_PAGO'),
    ('SERVICOS DE MARKETING', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('SERVICOS DE MILITANCIA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('SERVICOS DE MOBILIZACAO DE RUA', 'Militância e mobilização de rua', 'MOBILIZACAO'),
    ('SERVICOS DE MOTORISTA', 'Serviços de motorista', 'MOTORISTAS'),
    ('SERVICOS DE PANFLETAGEM', 'Panfletagem', 'MOBILIZACAO'),
    ('SERVICOS DE PUBLICIDADE', 'Publicidade e marketing sem modalidade definida', 'PUBLICIDADE_GERAL'),
    ('SERVICOS JURIDICOS', 'Assessoria e consultoria jurídica', 'JURIDICO'),
    ('SERVICOS POSTAIS', 'Serviços postais', 'POSTAIS'),
    ('WIND BANNER', 'Banners', 'VISUAIS'),
    ('WINDBANNER', 'Banners', 'VISUAIS')
) AS a(categoria_chave, categoria_padronizada, codigo_regra);

CREATE OR REPLACE VIEW vw_q9_categorias AS
WITH distintas AS (
 SELECT DISTINCT categoria AS categoria_original,
        q9_normalizar_categoria(categoria) AS chave
 FROM "Despesa_Candidatura"
), chaves AS (
 SELECT DISTINCT chave FROM distintas
), correspondencias AS (
 SELECT chave, 'DIGITAL_PAGO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|ANUNCIOS? PATROCINADOS?)\b')
 UNION ALL
 SELECT chave, 'IMPRESSOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(SANTINHOS?|SANTOES|SANTAO|COLINHAS?|FOLDERS?|FOLHETOS?|PANFLETOS?|CARTAZES?|CARTAZ|INFORMATIVOS?|MATERIA(IS|L) (GRAFICO(S)?|IMPRESSO(S)?))\b|^IMPRESSOS?$')
 UNION ALL
 SELECT chave, 'ADESIVOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(ADESIVOS?|PRAGUINHAS?|BOTONS?|BOTTONS?|BOTON|BOTTON|PERFURADOS?|MICROPERFURADOS?|PERFURITE)\b')
 UNION ALL
 SELECT chave, 'VISUAIS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(BANDEIRAS?|FAIXAS?|BANNERS?|WINDBANNERS?|WIND BANNERS?)\b')
 UNION ALL
 SELECT chave, 'AUDIOVISUAL' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(AUDIOVISUA(L|IS)|VIDEOS?|JINGLES?|FILMAGEM|CINEGRAFISTAS?|FOTOGRAF(IA|IAS|ICO|ICOS|O|OS|A|AS))\b|\bPRODUCAO\b.*\b(RADIO|TV|TELEVISAO|PROGRAMAS?)\b')
 UNION ALL
 SELECT chave, 'CARRO_SOM' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(CARROS? DE SOM|VEICULOS? DE SOM|BICICLETAS? DE SOM|PROPAGANDA VOLANTE)\b')
 UNION ALL
 SELECT chave, 'VEICULACAO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(VEICULACAO|ANUNCIOS?|INSERCOES)\b.*\b(RADIO|TV|TELEVISAO|JORNAL|JORNAIS|REVISTAS?|IMPRENSA)\b')
 UNION ALL
 SELECT chave, 'PUBLICIDADE_GERAL' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(PUBLICIDADE|PROPAGANDA|MARKETING)\b') AND NOT regexp_matches(chave, '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|SANTINHOS?|SANTAO|SANTOES|COLINHAS?|FOLDERS?|FOLHETOS?|PANFLETOS?|CARTAZES?|ADESIVOS?|PRAGUINHAS?|BOTONS?|BOTTONS?|BANDEIRAS?|BANNERS?|WINDBANNERS?|VIDEOS?|JINGLES?|AUDIOVISUA(L|IS)|CARROS? DE SOM|VEICULACAO)\b')
 UNION ALL
 SELECT chave, 'REDES_DIGITAIS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(REDES? SOCIA(IS|L)|MIDIAS? SOCIA(IS|L)|SOCIAL MEDIA|FACEBOOK|INSTAGRAM|GOOGLE|SITES?|INTERNET)\b') AND NOT regexp_matches(chave, '\b(IMPULSIONAMENTOS?|TRAFEGO PAGO|ANUNCIOS? PATROCINADOS?)\b')
 UNION ALL
 SELECT chave, 'MOBILIZACAO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(MILITAN(CIA|CIAS|TES?|TE)|MOBILIZA(CAO|COES)|CABOS? ELEITORA(IS|L)|ATIVISTAS?|PANFLETAGEM|PANFLETEIR(O|OS|A|AS)|PANFLETISTAS?|BANDEIRISTAS?)\b')
 UNION ALL
 SELECT chave, 'JURIDICO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(ADVOC[A-Z]*|ADVOG[A-Z]*|JURIDIC[A-Z]*)\b')
 UNION ALL
 SELECT chave, 'CONTABIL' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(CONTAB[A-Z]*|CONTADOR(ES|AS|A)?)\b')
 UNION ALL
 SELECT chave, 'COMBUSTIVEL' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(GASOLINA|DIESEL|ETANOL|COMBUSTIVE(L|IS))\b')
 UNION ALL
 SELECT chave, 'VEICULOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(LOCACAO|ALUGUEL|CESSAO|FRETAMENTO)\b.*\b(VEICULOS?|CARROS?|VANS?|ONIBUS|MICROONIBUS|AERONAVES?|HELICOPTEROS?|AVIAO|CAMINHAO|MOTOCICLETAS?)\b|\b(PASSAGENS|TRANSPORTE DE PESSOAL|SERVICOS DE TRANSPORTE)\b') AND NOT regexp_matches(chave, '\b(CARROS? DE SOM|VEICULOS? DE SOM)\b')
 UNION ALL
 SELECT chave, 'MOTORISTAS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\bMOTORISTAS?\b')
 UNION ALL
 SELECT chave, 'PESSOAL' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(COORDEN[A-Z]*|ASSISTENTES?|ADMINISTRADOR(ES|AS|A)?|GERENTES?|SECRETARI(O|OS|A|AS)|DESPESAS? COM PESSOAL|LIDER(ES)? DE EQUIPE|ATENDENTES?)\b')
 UNION ALL
 SELECT chave, 'IMOVEIS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(LOCACAO|ALUGUEL|CESSAO)\b.*\b(IMOVEL|IMOVEIS|ESPACOS?|SALAS?|SEDE|COMITE)\b')
 UNION ALL
 SELECT chave, 'ALIMENTACAO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(ALIMENTACAO|REFEICOES|REFEICAO|MARMIT(EX|AS|A)|LANCHES?|REFRIGERANTES?|BEBIDAS?|AGUA MINERAL)\b')
 UNION ALL
 SELECT chave, 'PESQUISAS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(PESQUISAS?|SONDAGEM|SONDAGENS)\b')
 UNION ALL
 SELECT chave, 'EVENTOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(COMICIOS?|CARREATAS?|EVENTOS?|PALCOS?|TENDAS?|ILUMINACAO|SONORIZACAO|ESTRUTURA DE SOM)\b') AND NOT regexp_matches(chave, '\b(CARROS? DE SOM|VEICULOS? DE SOM)\b')
 UNION ALL
 SELECT chave, 'POSTAIS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(CORREIOS|POSTAIS|MALA DIRETA)\b')
 UNION ALL
 SELECT chave, 'TELEFONIA' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(TELEFONIA|TELEFONES?|LINHAS? TELEFONICAS?|DADOS MOVEIS|BANDA LARGA)\b')
 UNION ALL
 SELECT chave, 'TRIBUTOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(TARIFAS?|TAXAS?|IMPOSTOS?|IRRF|INSS|ISSQN|ENCARGOS SOCIAIS)\b')
 UNION ALL
 SELECT chave, 'EQUIPAMENTOS' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(COMPUTADORES?|NOTEBOOKS?|IMPRESSORAS?|AR CONDICIONADO|MATERIAL DE ESCRITORIO|MATERIAIS DE ESCRITORIO)\b')
 UNION ALL
 SELECT chave, 'VESTUARIO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\b(CAMISETAS?|CAMISAS?|BONES?|COLETES?)\b')
 UNION ALL
 SELECT chave, 'COMUNICACAO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '\bCOMUNICACAO\b') AND NOT regexp_matches(chave, '\b(MARKETING|PUBLICIDADE|PROPAGANDA|IMPULSIONAMENTOS?|VIDEOS?|AUDIOVISUA(L|IS)|RADIO|TV|TELEVISAO)\b')
 UNION ALL
 SELECT chave, 'GENERICO' AS codigo_regra FROM chaves WHERE regexp_matches(chave, '^(CONTRATO|ADITIVO CONTRATUAL|CONTRATO DE PRESTACAO DE SERVICOS?|PRESTACAO DE SERVICOS?|SERVICOS? PRESTADOS?|HONORARIOS|SERVICOS? DE CAMPANHA|SERVICOS? ELEITORAIS|DIVULGACAO|APOIO NA CAMPANHA ELEITORAL|ATIVIDADES POLITICAS EM GERAL)$')
), detectadas AS (
 SELECT c.chave, count(r.codigo_regra) AS quantidade_regras,
        min(r.codigo_regra) AS regra_unica,
        string_agg(r.codigo_regra, ' | ' ORDER BY r.codigo_regra) AS regras,
        string_agg(r.grupo_despesa, ' | ' ORDER BY r.grupo_despesa) AS grupos
 FROM chaves c LEFT JOIN correspondencias hit ON hit.chave=c.chave
 LEFT JOIN vw_q9_regras_categorias r ON r.codigo_regra=hit.codigo_regra
 GROUP BY c.chave
)
SELECT
 d.categoria_original,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN NULL ELSE d.chave END AS categoria_chave,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN 'Não informada'
      WHEN a.categoria_chave IS NOT NULL THEN a.categoria_padronizada
      WHEN x.quantidade_regras=1 THEN u.grupo_despesa
      ELSE d.chave END AS categoria_padronizada,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN 'Não informada'
      WHEN a.categoria_chave IS NOT NULL THEN ar.grupo_despesa
      WHEN x.quantidade_regras=1 THEN u.grupo_despesa
      WHEN x.quantidade_regras>1 THEN 'Mistos — revisar'
      ELSE 'Não classificada — revisar' END AS grupo_despesa,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN NULL
      WHEN a.categoria_chave IS NOT NULL THEN ar.modalidade_publicidade_sugerida
      WHEN x.quantidade_regras=1 THEN u.modalidade_publicidade_sugerida
 END AS modalidade_publicidade_sugerida,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN NULL::BOOLEAN
      WHEN a.categoria_chave IS NOT NULL THEN ar.eh_publicidade_sugerida
      WHEN x.quantidade_regras=1 THEN u.eh_publicidade_sugerida
 END AS eh_publicidade_sugerida,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN 'AUSENTE'
      WHEN a.categoria_chave IS NOT NULL THEN 'ALIAS_EXPLICITO'
      WHEN x.quantidade_regras=1 THEN 'REGRA_TEXTUAL_REVISAR'
      WHEN x.quantidade_regras>1 THEN 'MULTIPLAS_CATEGORIAS'
      ELSE 'SEM_REGRA' END AS status_classificacao,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN TRUE
      WHEN a.categoria_chave IS NOT NULL AND a.codigo_regra NOT IN ('COMUNICACAO', 'GENERICO', 'REDES_DIGITAIS') THEN FALSE
      ELSE TRUE END AS requer_revisao,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN NULL
      WHEN a.categoria_chave IS NOT NULL THEN 'ALIAS:' || a.codigo_regra
      ELSE x.regras END AS regras_aplicadas,
 CASE WHEN d.chave IN ('', 'N A', 'NA', 'NAO ESPECIFICADA', 'NAO ESPECIFICADO', 'NAO INFORMADA', 'NAO INFORMADO', 'NAO SE APLICA', 'NULL', 'NULO', 'SEM DESCRICAO', 'SEM INFORMACAO') THEN NULL
      WHEN a.categoria_chave IS NOT NULL THEN ar.grupo_despesa
      ELSE x.grupos END AS grupos_detectados
FROM distintas d
JOIN detectadas x ON x.chave=d.chave
LEFT JOIN vw_q9_aliases_categorias a ON a.categoria_chave=d.chave
LEFT JOIN vw_q9_regras_categorias ar ON ar.codigo_regra=a.codigo_regra
LEFT JOIN vw_q9_regras_categorias u ON u.codigo_regra=x.regra_unica;

CREATE OR REPLACE VIEW vw_q9_despesas_normalizadas AS
SELECT d.id_despesa, d.id_candidatura,
       d.categoria AS categoria_original, c.categoria_chave,
       c.categoria_padronizada, c.grupo_despesa,
       c.modalidade_publicidade_sugerida, c.eh_publicidade_sugerida,
       c.status_classificacao, c.requer_revisao, c.regras_aplicadas,
       c.grupos_detectados, d.valor
FROM "Despesa_Candidatura" d
LEFT JOIN vw_q9_categorias c
 ON c.categoria_original IS NOT DISTINCT FROM d.categoria;

CREATE OR REPLACE VIEW vw_q9_resumo_categorias AS
SELECT grupo_despesa, status_classificacao, requer_revisao,
       eh_publicidade_sugerida,
       count(*) AS registros_agregados,
       count(DISTINCT id_candidatura) AS candidaturas,
       count(DISTINCT categoria_original) AS descricoes_originais,
       count(valor) FILTER (WHERE isfinite(valor)) AS registros_com_valor_finito,
       sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
           AS valor_contratado
FROM vw_q9_despesas_normalizadas
GROUP BY grupo_despesa, status_classificacao, requer_revisao,
         eh_publicidade_sugerida;
COMMIT;

-- CONSULTAS (executar individualmente após instalar).
-- 1. Lista de categorias normalizadas e a justificativa por regra.
SELECT * FROM vw_q9_categorias
ORDER BY grupo_despesa, categoria_padronizada, categoria_original;

-- 2. Ranking por grupo (inclui sugestões ainda não revisadas).
SELECT grupo_despesa, count(*) AS registros_agregados,
       count(DISTINCT id_candidatura) AS candidaturas,
       sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
           AS valor_contratado
FROM vw_q9_despesas_normalizadas
GROUP BY grupo_despesa
ORDER BY valor_contratado DESC NULLS LAST;

-- 3. Fila de revisão priorizada por valor.
SELECT categoria_original, categoria_padronizada, grupo_despesa,
       status_classificacao, grupos_detectados,
       sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
           AS valor_contratado
FROM vw_q9_despesas_normalizadas
WHERE requer_revisao
GROUP BY categoria_original, categoria_padronizada, grupo_despesa,
         status_classificacao, grupos_detectados
ORDER BY valor_contratado DESC NULLS LAST;

-- 4. Conferência: uma linha por ID de despesa e mesmos valores da fonte.
SELECT
 (SELECT count(*) FROM "Despesa_Candidatura") AS linhas_fonte,
 count(*) AS linhas_view, count(DISTINCT id_despesa) AS ids_despesa_view,
 sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
     AS total_view,
 (SELECT sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
  FROM "Despesa_Candidatura") AS total_fonte
FROM vw_q9_despesas_normalizadas;

-- 5. Subconjunto estrito por equivalências explícitas de publicidade.
-- Não representa toda a publicidade da base: omite inferências e indefinidos.
SELECT grupo_despesa,
       sum(CASE WHEN isfinite(valor) THEN try_cast(valor AS DECIMAL(24,2)) END)
           AS valor_contratado
FROM vw_q9_despesas_normalizadas
WHERE eh_publicidade_sugerida IS TRUE
  AND status_classificacao='ALIAS_EXPLICITO'
  AND NOT requer_revisao
GROUP BY grupo_despesa
ORDER BY valor_contratado DESC NULLS LAST;
