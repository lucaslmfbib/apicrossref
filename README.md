# Trabalho com API da Crossref (baseado no tutorial oficial)

Este diretório foi estruturado com base no commit `24d9391109b9055c6efe9e43dd3cf809a2a0f4d0` do repositório:

- [crossref/tutorials/intro-to-crossref-api-using-python](https://gitlab.com/crossref/tutorials/intro-to-crossref-api-using-python)

## Conteúdo

- `notebooks/Intro_to_Jupyter_notebooks.ipynb`: introdução ao uso de notebooks.
- `notebooks/Crossref_API_query_template.ipynb`: template oficial de consulta da API `/works`.
- `crossref_client.py`: módulo com funções de integração com a API Crossref.
- `Untitled-1.py`: CLI do projeto (wrapper para `crossref_client.py`).
- `streamlit_app.py`: interface web com Streamlit.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Rodar no terminal (CLI)

Consulta por texto livre:

```bash
python Untitled-1.py \
  --query "deep learning" \
  --rows 20 \
  --filter type=journal-article \
  --filter has-references=true \
  --select DOI title issued \
  --mailto seu-email@exemplo.com \
  --format both \
  --out outputs/deep_learning
```

Consulta por DOI:

```bash
python Untitled-1.py \
  --doi 10.1038/s41586-020-2649-2 \
  --mailto seu-email@exemplo.com \
  --format both \
  --out outputs/paper
```

## Rodar no Streamlit

```bash
streamlit run streamlit_app.py
```

A interface permite:
- busca por query ou por DOI;
- filtros no formato `key=value`;
- download dos resultados em JSON e CSV.

## Publicar no GitHub

1. Crie um repositório vazio no GitHub.
2. Conecte o remote e envie os arquivos:

```bash
git init
git add .
git commit -m "Crossref app com CLI e Streamlit"
git branch -M main
git remote add origin <URL_DO_REPOSITORIO>
git push -u origin main
```

## Observações

- `--filter` aceita `key=value` e pode ser repetido.
- `--select` reduz campos retornados pela API.
- `--mailto` é recomendado pela Crossref para identificação do cliente.
- Em `--format both`, o script salva `<out>.json` e `<out>.csv`.
