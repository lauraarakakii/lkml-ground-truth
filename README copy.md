# Patch Acceptance Analysis

Análise exploratória e modelagem preditiva de aceitação de patches em mailing lists
de projetos open source, com base em metadados de emails.

## Estrutura

```
patch_analysis/
├── data/               ← coloque seus arquivos .parquet / .csv aqui
├── outputs/            ← gráficos e resultados gerados automaticamente
├── config.py           ← única fonte de configuração do projeto
├── loader.py           ← carregamento e schema validation
├── features.py         ← toda a engenharia de features
├── labels.py           ← inferência de aceitação via trailers + threading
├── eda.py              ← análise exploratória + gráficos
├── model.py            ← treino, avaliação e SHAP
└── run.py              ← pipeline completo (único ponto de entrada)
```

## Como usar

```bash
# 1. Coloque os dados em data/
# 2. Ajuste DATA_PATH em config.py se necessário
# 3. Rode o pipeline completo:
python run.py

# Ou rode etapas individualmente:
python eda.py        # só EDA
python model.py      # só modelo (requer features já salvas)
```

## Saídas em outputs/

- `eda_*.png`         — gráficos exploratórios prontos para o artigo
- `features.parquet`  — dataset com todas as features engineered
- `model_report.txt`  — métricas do modelo (AUC, F1, classification report)
- `shap_importance.png` — importância das features via SHAP
- `confusion_matrix.png`

## Proxy de aceitação (label)

Como o dataset não tem label direto, inferimos aceitação por:
1. **Trailers semânticos**: presença de "Applied", "Acked-by", "Reviewed-by"
   nos campos `trailers.identification`
2. **Threading**: patches que recebem resposta (têm mensagens com `in_reply_to`
   apontando para eles) são candidatos a "em revisão"

A combinação gera um score de 0–3 que é binarizado com threshold configurável.
