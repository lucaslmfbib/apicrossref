# apicrossref

Ferramentas para consultar a API pública da Crossref (`/works`): biblioteca Python, CLI, app Streamlit e notebooks. Baseado no tutorial oficial da Crossref (commit `24d9391`).

## Estrutura
- `crossref_client.py`: toda a lógica de acesso à API (busca, paginação por cursor/offset, filtros, DOI). Mudanças de comportamento começam aqui.
- `streamlit_app.py`: interface web (busca, gráficos, rankings, cache, downloads JSON/CSV/Parquet).
- `Untitled-1.py`: CLI, um wrapper fino sobre `crossref_client.py`. O nome é herdado; renomear exige atualizar README e `.vscode/launch.json`.
- `notebooks/`: tutoriais e um notebook pronto para o Colab (`Crossref_Insight_Colab.ipynb`).
- `.vscode/`: configurações de execução/debug (Streamlit e CLI).

## Como rodar
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
python Untitled-1.py --query "deep learning" --rows 20 --mailto seu-email@exemplo.com --format both --out outputs/teste
```

## Convenções
- Sempre enviar `mailto` nas requisições (pool "polite" da Crossref).
- Para volumes grandes, preferir paginação por `cursor`.
- Não há testes automatizados; validar manualmente rodando o app ou a CLI.
- Idioma da interface e da documentação: português.
