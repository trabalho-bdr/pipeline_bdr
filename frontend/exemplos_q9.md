# Casos reais para verificar a evolução da publicidade

Conferência realizada em 15/10/2026 sobre a cópia local `dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb`, com `criterio=sugeridas` e as regras originais da Q9. Não é uma consulta ao banco v3 remoto. Mudanças no banco ou no catálogo podem alterar os números.

## Darlene Torrada Pereira — Rio Grande/RS, PT

É um exemplo didático de mudança de composição com resultado eleitoral diferente e total identificado de publicidade semelhante. Mesma pessoa, cargo, município e partido em 2020 e 2024. Foi escolhida após examinar os resultados; não representa uma amostra aleatória nem permite inferir causalidade.

No frontend: **Publicidade → 2024 → Prefeito → RS → pesquisar Darlene → selecionar DARLENE TORRADA PEREIRA, RIO GRANDE → Por candidato**. Use a classificação sugerida padrão; a opção conservadora de equivalências explícitas gera outro recorte.

| Medida | 2020 | 2024 |
|---|---:|---:|
| Publicidade identificada | R$ 297.126,69 | R$ 309.600,05 |
| Produção audiovisual | R$ 215.000,00 (72,36%) | R$ 113.250,00 (36,58%) |
| Materiais impressos | R$ 15.735,69 (5,30%) | R$ 98.631,40 (31,86%) |
| Adesivos e botons | R$ 22.441,00 (7,55%) | R$ 57.666,65 (18,63%) |
| Publicidade digital paga | R$ 25.000,00 (8,41%) | R$ 15.000,00 (4,84%) |
| Bandeiras, faixas e banners | R$ 18.950,00 (6,38%) | R$ 52,00 (0,02%) |
| Publicidade e marketing sem modalidade definida | R$ 0,00 (0%) | R$ 25.000,00 (8,07%) |
| Resultado | Não eleita | Eleita |

O total identificado cresceu 4,20% em reais nominais, enquanto o índice de redistribuição atingiu 45,71 p.p. Audiovisual caiu 35,78 p.p.; impressos subiram 26,56 p.p.; adesivos e botons subiram 11,07 p.p. Isso descreve a mudança de alocação observada, não prova uma decisão estratégica deliberada nem seu efeito sobre os votos.

Conferência de despesas originais: em 2020, os registros de gravação de programas de áudio/vídeo somam R$ 215.000,00. Em 2024, as descrições incluem edição/produção audiovisual, fotografia/vídeo, impressos e adesivos. As regras são textuais: R$ 297.126,69 em 2020 e R$ 299.600,05 em 2024 continuam marcados para revisão. A checagem de descrições não constitui validação completa das categorias. Valores são contratados, nominais, não necessariamente pagos, e não abrangem todas as despesas de campanha.

Resultados oficiais: [TRE-RS, Rio Grande em 2020](https://resultados.tre-rs.jus.br/eleicoes/2020/426/RS88153.html) e [TRE-RS, Rio Grande em 2024](https://resultados.tre-rs.jus.br/eleicoes/2024/619/RS88153.html).

Uma pessoa fornece uma observação por eleição: os 0% e 100% no painel são apenas a codificação de derrota e vitória, não uma estimativa de probabilidade. Mudanças no contexto eleitoral, adversários, orçamento total e outras condições não são controladas. Esse caso não é de reeleição entre as duas eleições observadas.

## Outros testes, incluindo um contraponto

| Candidato | Município | Publicidade em 2020 | Publicidade em 2024 | Redistribuição | Resultado observado |
|---|---|---:|---:|---:|---|
| Luiz Fernando Mainardi | Bagé/RS | R$ 182.467,80 | R$ 619.524,00 | 47,04 p.p. | Não eleito → eleito |
| Sarto | Fortaleza/CE | R$ 5.278.558,35 | R$ 11.322.449,82 | 67,37 p.p. | Eleito → não eleito |

Sarto é um contraponto à interpretação de que mudar o perfil ou gastar mais garante vitória. Seus registros de 2020 incluem candidaturas distintas para os dois turnos. O histórico reúne as despesas dessa pessoa no mesmo cargo, território e ano e usa o resultado do último turno; não conta a pessoa duas vezes.

## Testes reproduzíveis

Na raiz do repositório:

```powershell
uv run python -m unittest discover -s tests -p "test_q9_candidatos_reais.py" -v
uv run python -m unittest discover -s tests -p "test_api_q9*.py" -v
```

Os testes reais abrem o arquivo v2 somente para leitura e são ignorados se ele não existir. Verificam três candidatos, reconciliação com o painel anual, soma das categorias, resultado bruto do último turno, uma observação por candidato/território/ano e ausência de uma diferença de taxas entre grupos quando há somente uma pessoa. Os valores esperados documentam esse snapshot e esse catálogo; devem ser revisados quando a fonte ou a classificação mudar.
