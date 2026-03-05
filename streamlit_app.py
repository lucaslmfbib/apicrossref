#!/usr/bin/env python3
"""Interface Streamlit para consultas na API Crossref."""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

import requests
import streamlit as st

from crossref_client import get_by_doi, get_works, normalize_item


def parse_filters(raw_filters: str) -> Dict[str, str]:
    """Converte texto com filtros (um key=value por linha) em dict."""
    parsed: Dict[str, str] = {}
    for line in raw_filters.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if "=" not in cleaned:
            raise ValueError(f"Filtro inválido '{cleaned}'. Use key=value.")
        key, value = cleaned.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"Filtro inválido '{cleaned}'. Use key=value.")
        parsed[key] = value
    return parsed


def parse_select(raw_select: str) -> List[str]:
    """Converte campos select separados por vírgula em lista."""
    return [field.strip() for field in raw_select.split(",") if field.strip()]


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    """Converte lista de dicts para CSV em memória."""
    if not rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


st.set_page_config(page_title="Crossref Explorer", page_icon="📚", layout="wide")
st.title("Crossref Explorer")
st.caption("Busca de metadados científicos via endpoint /works da Crossref")

with st.sidebar:
    st.subheader("Configuração")
    mailto = st.text_input("Email (mailto)", placeholder="seu-email@exemplo.com")
    timeout = st.number_input("Timeout (segundos)", min_value=5.0, max_value=120.0, value=20.0, step=1.0)

query_tab, doi_tab = st.tabs(["Busca por Query", "Busca por DOI"])

with query_tab:
    query = st.text_input("Consulta", placeholder="deep learning")

    col1, col2 = st.columns(2)
    with col1:
        rows = st.number_input("Rows", min_value=1, max_value=1000, value=20, step=1)
    with col2:
        offset = st.number_input("Offset", min_value=0, max_value=100000, value=0, step=1)

    select_raw = st.text_input("Campos select (separados por vírgula)", value="DOI,title,issued")
    filters_raw = st.text_area(
        "Filtros (um key=value por linha)",
        value="type=journal-article\nhas-references=true",
        height=110,
    )

    if st.button("Buscar por Query", type="primary"):
        if not query.strip():
            st.warning("Informe uma consulta em 'Consulta'.")
        else:
            try:
                filters = parse_filters(filters_raw)
                select_fields = parse_select(select_raw)

                params: Dict[str, Any] = {
                    "query": query.strip(),
                    "rows": int(rows),
                    "offset": int(offset),
                }
                if select_fields:
                    params["select"] = ",".join(select_fields)
                if mailto.strip():
                    params["mailto"] = mailto.strip()

                js, status = get_works(
                    params,
                    filters,
                    timeout=float(timeout),
                    mailto=mailto.strip() or None,
                )
            except ValueError as error:
                st.error(str(error))
            except requests.RequestException as error:
                st.error(f"Erro de rede: {error}")
            else:
                if status != 200:
                    st.error(f"A API retornou status {status}.")
                else:
                    message = js.get("message", {})
                    items = message.get("items", [])
                    normalized = [normalize_item(item) for item in items]

                    total_results = message.get("total-results", "?")
                    st.success(f"Consulta executada. {len(items)} itens retornados.")
                    st.write(f"Total de resultados informados pela API: {total_results}")

                    if normalized:
                        st.dataframe(normalized, use_container_width=True)
                    else:
                        st.info("Sem itens retornados para os parâmetros informados.")

                    st.download_button(
                        label="Baixar JSON",
                        data=json.dumps(js, ensure_ascii=False, indent=2),
                        file_name="crossref_query.json",
                        mime="application/json",
                    )

                    csv_content = rows_to_csv(normalized)
                    if csv_content:
                        st.download_button(
                            label="Baixar CSV",
                            data=csv_content,
                            file_name="crossref_query.csv",
                            mime="text/csv",
                        )

                    with st.expander("Ver JSON bruto"):
                        st.json(js)

with doi_tab:
    doi = st.text_input("DOI", value="10.1038/s41586-020-2649-2")

    if st.button("Buscar por DOI", type="primary"):
        if not doi.strip():
            st.warning("Informe um DOI válido.")
        else:
            try:
                item = get_by_doi(
                    doi.strip(),
                    timeout=float(timeout),
                    mailto=mailto.strip() or None,
                )
            except requests.RequestException as error:
                st.error(f"Erro de rede: {error}")
            else:
                if item is None:
                    st.error("DOI não encontrado.")
                else:
                    normalized_item = normalize_item(item)
                    st.success("DOI encontrado com sucesso.")
                    st.dataframe([normalized_item], use_container_width=True)

                    st.download_button(
                        label="Baixar JSON",
                        data=json.dumps(item, ensure_ascii=False, indent=2),
                        file_name="crossref_doi.json",
                        mime="application/json",
                    )

                    st.download_button(
                        label="Baixar CSV",
                        data=rows_to_csv([normalized_item]),
                        file_name="crossref_doi.csv",
                        mime="text/csv",
                    )

                    with st.expander("Ver JSON bruto"):
                        st.json(item)
