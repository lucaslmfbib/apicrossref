#!/usr/bin/env python3
"""Interface Streamlit para consultas na API Crossref."""

from __future__ import annotations

from collections import Counter
import csv
import io
import json
import re
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

from crossref_client import get_by_doi, get_works, normalize_item


STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "de",
    "do",
    "dos",
    "da",
    "das",
    "e",
    "em",
    "et",
    "for",
    "from",
    "in",
    "is",
    "na",
    "no",
    "nos",
    "of",
    "on",
    "or",
    "os",
    "para",
    "por",
    "the",
    "to",
    "um",
    "uma",
    "with",
}


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


def get_year(item: Dict[str, Any]) -> Optional[int]:
    """Extrai ano de publicação de um item."""
    year = item.get("issued", {}).get("date-parts", [[None]])[0][0]
    if isinstance(year, int):
        return year
    return None


def get_top_authors(items: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """Retorna autores mais frequentes entre os itens retornados."""
    counter: Counter[str] = Counter()
    for item in items:
        for author in item.get("author", []) or []:
            full_name = " ".join(filter(None, [author.get("given"), author.get("family")])).strip()
            if full_name:
                counter[full_name] += 1

    return [{"autor": name, "frequencia": freq} for name, freq in counter.most_common(top_n)]


def get_top_title_terms(items: List[Dict[str, Any]], top_n: int = 15) -> List[Dict[str, Any]]:
    """Retorna termos mais frequentes dos títulos dos itens."""
    counter: Counter[str] = Counter()
    for item in items:
        titles = item.get("title", []) or []
        if not titles:
            continue

        title = titles[0].lower()
        terms = re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ0-9]+", title)
        for term in terms:
            if len(term) < 3 or term in STOPWORDS or term.isdigit():
                continue
            counter[term] += 1

    return [{"termo": term, "frequencia": freq} for term, freq in counter.most_common(top_n)]


def build_work_summary(
    query: str,
    filters: Dict[str, str],
    items: List[Dict[str, Any]],
    total_results: Any,
) -> Dict[str, Any]:
    """Monta resumo consolidado da consulta."""
    years = [year for year in (get_year(item) for item in items) if year is not None]
    doi_count = len({item.get("DOI") for item in items if item.get("DOI")})
    unique_authors = {
        " ".join(filter(None, [author.get("given"), author.get("family")])).strip()
        for item in items
        for author in (item.get("author", []) or [])
        if " ".join(filter(None, [author.get("given"), author.get("family")])).strip()
    }

    publishers = Counter(
        item.get("publisher", "").strip()
        for item in items
        if isinstance(item.get("publisher"), str) and item.get("publisher", "").strip()
    )

    return {
        "query": query,
        "filters_count": len(filters),
        "returned": len(items),
        "total_results": total_results,
        "doi_count": doi_count,
        "unique_authors_count": len(unique_authors),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "top_publisher": publishers.most_common(1)[0] if publishers else None,
    }


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

                    summary = build_work_summary(query.strip(), filters, items, total_results)
                    top_authors = get_top_authors(items)
                    top_terms = get_top_title_terms(items)

                    st.subheader("Resumo do trabalho")
                    st.write(
                        f"Consulta '{summary['query']}' com {summary['filters_count']} filtro(s) retornou "
                        f"{summary['returned']} itens nesta página."
                    )

                    metric1, metric2, metric3, metric4 = st.columns(4)
                    metric1.metric("Registros retornados", summary["returned"])
                    metric2.metric("DOIs únicos", summary["doi_count"])
                    metric3.metric("Autores únicos", summary["unique_authors_count"])
                    metric4.metric("Total na API", summary["total_results"])

                    if summary["year_min"] is not None and summary["year_max"] is not None:
                        st.write(f"Faixa de anos dos resultados: {summary['year_min']} - {summary['year_max']}")

                    if summary["top_publisher"]:
                        publisher, freq = summary["top_publisher"]
                        st.write(f"Editora mais frequente: {publisher} ({freq} registro(s))")

                    stats_col1, stats_col2 = st.columns(2)
                    with stats_col1:
                        st.markdown("**Autores mais frequentes**")
                        if top_authors:
                            st.dataframe(top_authors, use_container_width=True, hide_index=True)
                        else:
                            st.info("Sem autores identificados nos itens retornados.")

                    with stats_col2:
                        st.markdown("**Termos mais frequentes nos títulos**")
                        if top_terms:
                            st.dataframe(top_terms, use_container_width=True, hide_index=True)
                        else:
                            st.info("Sem termos suficientes para análise de frequência.")

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
