#!/usr/bin/env python3
"""Interface Streamlit para consultas e análise da API Crossref."""

from __future__ import annotations

from collections import Counter
import csv
import io
import json
import re
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

from crossref_client import get_by_doi, get_works, normalize_item

WORKS_ENDPOINT = "https://api.crossref.org/works"
DOCS_URL = "https://api.crossref.org"
DEFAULT_SELECT = (
    "DOI,title,issued,type,publisher,container-title,author,"
    "references-count,is-referenced-by-count,subject"
)
DEFAULT_FILTERS = "type=journal-article\nhas-references=true"

STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "com",
    "da",
    "das",
    "de",
    "del",
    "do",
    "dos",
    "e",
    "em",
    "et",
    "for",
    "from",
    "in",
    "is",
    "na",
    "nas",
    "no",
    "nos",
    "of",
    "on",
    "or",
    "para",
    "por",
    "the",
    "to",
    "um",
    "uma",
    "with",
}


def inject_styles() -> None:
    """Aplica identidade visual da página."""
    st.markdown(
        """
        <style>
        :root {
            --brand: #0b6e4f;
            --accent: #dcefe7;
            --ink: #0f2a21;
            --panel: #f7fbf9;
        }

        .main .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2.5rem;
        }

        .hero {
            background: radial-gradient(circle at top right, #d7efe4 0%, #eaf5f0 38%, #f6fbf8 100%);
            border: 1px solid #d9ebe3;
            border-radius: 18px;
            padding: 1.05rem 1.2rem;
            margin-bottom: 1.1rem;
        }

        .hero h1 {
            color: var(--ink);
            font-size: 1.65rem;
            margin: 0 0 0.3rem 0;
            line-height: 1.2;
        }

        .hero p {
            color: #335348;
            margin: 0;
        }

        .hero-links {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin-bottom: 0.75rem;
        }

        .hero-links a {
            text-decoration: none;
            background: #ffffff;
            border: 1px solid #cfe4da;
            color: #1f4c3d;
            border-radius: 999px;
            padding: 0.22rem 0.72rem;
            font-size: 0.83rem;
        }

        .hero-links a:hover {
            background: #edf7f2;
        }

        .pill {
            display: inline-block;
            background: #eef7f2;
            border: 1px solid #d2e8dc;
            color: #285041;
            border-radius: 999px;
            padding: 0.2rem 0.6rem;
            font-size: 0.8rem;
            margin-right: 0.35rem;
            margin-top: 0.35rem;
        }

        .author-signature {
            margin-top: 0.88rem;
            color: #21483a;
            font-weight: 600;
        }

        div[data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid #d9ebe3;
            border-radius: 14px;
            padding: 0.5rem 0.7rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def parse_filters(raw_filters: str) -> Dict[str, str]:
    """Converte texto com filtros (um key=value por linha) em dicionário."""
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
    if not raw_select.strip():
        return []
    return [field.strip() for field in raw_select.split(",") if field.strip()]


def extract_api_error_message(js: Dict[str, Any], fallback: str) -> str:
    """Extrai mensagem amigável de erro retornada pela API."""
    message = js.get("message")
    if isinstance(message, list):
        parts: List[str] = []
        for entry in message:
            if isinstance(entry, dict):
                value = entry.get("value")
                text = entry.get("message")
                if value and text:
                    parts.append(f"{value}: {text}")
                elif text:
                    parts.append(str(text))
        if parts:
            return " | ".join(parts)
    if isinstance(message, str):
        return message
    return fallback


def get_reference_count(item: Dict[str, Any]) -> Optional[int]:
    """Compatibiliza nomes de campo de referências no retorno da API."""
    value = item.get("reference-count")
    if isinstance(value, int):
        return value
    value = item.get("references-count")
    if isinstance(value, int):
        return value
    return None


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    """Converte lista de dicts para CSV em memória."""
    if not rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def dataframe_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Converte DataFrame para Parquet em memória."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    return buffer.getvalue()


def get_year(item: Dict[str, Any]) -> Optional[int]:
    """Extrai ano de publicação."""
    year = item.get("issued", {}).get("date-parts", [[None]])[0][0]
    if isinstance(year, int):
        return year
    return None


def get_authors(item: Dict[str, Any]) -> List[str]:
    """Extrai nomes completos dos autores."""
    authors: List[str] = []
    for author in item.get("author", []) or []:
        full_name = " ".join(filter(None, [author.get("given"), author.get("family")])).strip()
        if full_name:
            authors.append(full_name)
    return authors


def get_title(item: Dict[str, Any]) -> str:
    """Extrai o primeiro título do registro."""
    titles = item.get("title", []) or []
    return titles[0] if titles else ""


def tokenize_title(title: str) -> List[str]:
    """Tokeniza títulos para análise de frequência de termos."""
    tokens = re.findall(r"[a-zA-ZÀ-ÖØ-öø-ÿ0-9]+", title.lower())
    cleaned: List[str] = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        if len(token) < 3:
            continue
        if token.isdigit():
            continue
        cleaned.append(token)
    return cleaned


def counter_to_df(counter: Counter[str], label_col: str, value_col: str, top_n: int) -> pd.DataFrame:
    """Transforma Counter em DataFrame ordenado para tabela/gráfico."""
    if not counter:
        return pd.DataFrame(columns=[label_col, value_col])

    rows = [{label_col: key, value_col: value} for key, value in counter.most_common(top_n)]
    return pd.DataFrame(rows)


def get_top_authors(items: List[Dict[str, Any]], top_n: int) -> pd.DataFrame:
    """Retorna autores mais frequentes."""
    counter: Counter[str] = Counter()
    for item in items:
        counter.update(get_authors(item))
    return counter_to_df(counter, "autor", "frequencia", top_n)


def get_top_title_terms(items: List[Dict[str, Any]], top_n: int) -> pd.DataFrame:
    """Retorna termos mais frequentes nos títulos."""
    counter: Counter[str] = Counter()
    for item in items:
        counter.update(tokenize_title(get_title(item)))
    return counter_to_df(counter, "termo", "frequencia", top_n)


def get_year_distribution(items: List[Dict[str, Any]]) -> pd.DataFrame:
    """Retorna distribuição por ano."""
    counter: Counter[int] = Counter()
    for item in items:
        year = get_year(item)
        if year is not None:
            counter[year] += 1

    if not counter:
        return pd.DataFrame(columns=["ano", "publicacoes"])

    rows = [{"ano": year, "publicacoes": count} for year, count in sorted(counter.items())]
    return pd.DataFrame(rows)


def get_type_distribution(items: List[Dict[str, Any]], top_n: int) -> pd.DataFrame:
    """Retorna distribuição por tipo de documento."""
    counter: Counter[str] = Counter()
    for item in items:
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type.strip():
            counter[item_type.strip()] += 1
    return counter_to_df(counter, "tipo", "quantidade", top_n)


def get_publisher_distribution(items: List[Dict[str, Any]], top_n: int) -> pd.DataFrame:
    """Retorna distribuição por editora."""
    counter: Counter[str] = Counter()
    for item in items:
        publisher = item.get("publisher")
        if isinstance(publisher, str) and publisher.strip():
            counter[publisher.strip()] += 1
    return counter_to_df(counter, "editora", "quantidade", top_n)


def get_journal_distribution(items: List[Dict[str, Any]], top_n: int) -> pd.DataFrame:
    """Retorna distribuição por periódico (container-title)."""
    counter: Counter[str] = Counter()
    for item in items:
        container_titles = item.get("container-title", []) or []
        if container_titles:
            journal = container_titles[0].strip()
            if journal:
                counter[journal] += 1
    return counter_to_df(counter, "periodico", "quantidade", top_n)


def build_work_summary(
    query: str,
    filters: Dict[str, str],
    items: List[Dict[str, Any]],
    total_results: Any,
) -> Dict[str, Any]:
    """Monta resumo consolidado da consulta."""
    years = [year for year in (get_year(item) for item in items) if year is not None]
    doi_count = len({item.get("DOI") for item in items if item.get("DOI")})
    unique_authors = {author for item in items for author in get_authors(item)}

    languages = Counter(
        item.get("language", "").strip().lower()
        for item in items
        if isinstance(item.get("language"), str) and item.get("language", "").strip()
    )

    publishers = Counter(
        item.get("publisher", "").strip()
        for item in items
        if isinstance(item.get("publisher"), str) and item.get("publisher", "").strip()
    )

    reference_counts = [
        count for item in items for count in [get_reference_count(item)] if count is not None
    ]

    cited_counts = [
        int(item.get("is-referenced-by-count"))
        for item in items
        if isinstance(item.get("is-referenced-by-count"), int)
    ]

    avg_references = round(sum(reference_counts) / len(reference_counts), 2) if reference_counts else None
    avg_citations = round(sum(cited_counts) / len(cited_counts), 2) if cited_counts else None

    top_publisher = publishers.most_common(1)[0] if publishers else None
    top_language = languages.most_common(1)[0] if languages else None

    return {
        "query": query,
        "filters": filters,
        "filters_count": len(filters),
        "returned": len(items),
        "total_results": total_results,
        "doi_count": doi_count,
        "unique_authors_count": len(unique_authors),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "top_publisher": {
            "name": top_publisher[0],
            "count": top_publisher[1],
        }
        if top_publisher
        else None,
        "top_language": {
            "name": top_language[0],
            "count": top_language[1],
        }
        if top_language
        else None,
        "avg_references": avg_references,
        "avg_citations": avg_citations,
    }


def render_api_details(
    *,
    js: Dict[str, Any],
    status: int,
    query_params: Dict[str, Any],
    filters: Dict[str, str],
    timeout: float,
) -> None:
    """Renderiza detalhes técnicos da resposta da API."""
    message = js.get("message", {})
    query_meta = message.get("query", {})

    st.subheader("Informações da API")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Resposta**")
        st.write(f"Endpoint: `{WORKS_ENDPOINT}`")
        st.write(f"Status HTTP: `{status}`")
        st.write(f"Message type: `{js.get('message-type', '-')}`")
        st.write(f"Message version: `{js.get('message-version', '-')}`")
        st.write(f"Items por página: `{message.get('items-per-page', '-')}`")

    with col2:
        st.markdown("**Parâmetros enviados**")
        st.write(f"Timeout: `{timeout}` segundos")
        st.write(f"Estratégia de paginação: `{query_params.get('_strategy', 'offset')}`")
        if query_params.get("_pages_requested") is not None:
            st.write(
                "Páginas (solicitadas/obtidas): "
                f"`{query_params.get('_pages_requested')}/{query_params.get('_pages_retrieved', '-')}`"
            )
        st.write(f"Início da query (start-index): `{query_meta.get('start-index', '-')}`")
        st.write(f"Tamanho da busca (search-terms): `{query_meta.get('search-terms', '-')}`")
        st.write(f"Filtros: `{filters if filters else '-'}`")

    with st.expander("Ver parâmetros em JSON"):
        st.json(query_params)

    with st.expander("Ver resposta bruta da API"):
        st.json(js)


def get_works_paginated(
    *,
    base_params: Dict[str, Any],
    filters: Dict[str, str],
    pages: int,
    timeout: float,
    mailto: Optional[str],
) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    """Consulta múltiplas páginas via offset e agrega os itens em um único payload."""
    rows = int(base_params.get("rows", 25))
    base_offset = int(base_params.get("offset", 0))
    requested_pages = max(1, int(pages))

    offsets: List[int] = []
    items_all: List[Dict[str, Any]] = []
    first_payload: Optional[Dict[str, Any]] = None
    retrieved_pages = 0

    for idx in range(requested_pages):
        current_offset = base_offset + (idx * rows)
        page_params = dict(base_params)
        page_params["offset"] = current_offset
        offsets.append(current_offset)

        js, status = get_works(
            page_params,
            filters,
            timeout=timeout,
            mailto=mailto,
        )
        if status != 200:
            return (
                js,
                status,
                {
                    "pages_requested": requested_pages,
                    "pages_retrieved": retrieved_pages,
                    "offsets": offsets,
                },
            )

        if first_payload is None:
            first_payload = js

        page_items = js.get("message", {}).get("items", []) or []
        items_all.extend(page_items)
        retrieved_pages += 1

        if len(page_items) < rows:
            break

    if first_payload is None:
        return (
            {},
            500,
            {
                "pages_requested": requested_pages,
                "pages_retrieved": 0,
                "offsets": offsets,
            },
        )

    merged = dict(first_payload)
    merged_message = dict(first_payload.get("message", {}))
    merged_message["items"] = items_all
    merged_message["retrieved-pages"] = retrieved_pages
    merged_message["retrieved-items"] = len(items_all)
    merged["message"] = merged_message

    return (
        merged,
        200,
        {
            "pages_requested": requested_pages,
            "pages_retrieved": retrieved_pages,
            "offsets": offsets,
        },
    )


def get_works_cursor_paginated(
    *,
    base_params: Dict[str, Any],
    filters: Dict[str, str],
    pages: int,
    timeout: float,
    mailto: Optional[str],
) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    """Consulta múltiplas páginas via cursor e agrega os itens em um único payload."""
    requested_pages = max(1, int(pages))
    current_cursor = "*"
    items_all: List[Dict[str, Any]] = []
    first_payload: Optional[Dict[str, Any]] = None
    retrieved_pages = 0

    for _ in range(requested_pages):
        page_params = dict(base_params)
        page_params.pop("offset", None)
        page_params["cursor"] = current_cursor

        js, status = get_works(
            page_params,
            filters,
            timeout=timeout,
            mailto=mailto,
        )
        if status != 200:
            return (
                js,
                status,
                {
                    "pages_requested": requested_pages,
                    "pages_retrieved": retrieved_pages,
                    "cursor_mode": True,
                },
            )

        if first_payload is None:
            first_payload = js

        message = js.get("message", {})
        page_items = message.get("items", []) or []
        items_all.extend(page_items)
        retrieved_pages += 1

        next_cursor = message.get("next-cursor")
        if not page_items or not next_cursor or next_cursor == current_cursor:
            break
        current_cursor = next_cursor

    if first_payload is None:
        return (
            {},
            500,
            {
                "pages_requested": requested_pages,
                "pages_retrieved": 0,
                "cursor_mode": True,
            },
        )

    merged = dict(first_payload)
    merged_message = dict(first_payload.get("message", {}))
    merged_message["items"] = items_all
    merged_message["retrieved-pages"] = retrieved_pages
    merged_message["retrieved-items"] = len(items_all)
    merged["message"] = merged_message

    return (
        merged,
        200,
        {
            "pages_requested": requested_pages,
            "pages_retrieved": retrieved_pages,
            "cursor_mode": True,
        },
    )


@st.cache_data(ttl=1800, max_entries=25, show_spinner=False)
def _fetch_works_cached(
    *,
    strategy: str,
    base_params_json: str,
    filters_json: str,
    pages: int,
    timeout: float,
    mailto: str,
) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    """Executa consulta com cache para acelerar buscas repetidas."""
    base_params = json.loads(base_params_json)
    filters = json.loads(filters_json)
    mailto_value = mailto or None

    if strategy == "cursor":
        return get_works_cursor_paginated(
            base_params=base_params,
            filters=filters,
            pages=pages,
            timeout=timeout,
            mailto=mailto_value,
        )

    return get_works_paginated(
        base_params=base_params,
        filters=filters,
        pages=pages,
        timeout=timeout,
        mailto=mailto_value,
    )


def fetch_works(
    *,
    strategy: str,
    base_params: Dict[str, Any],
    filters: Dict[str, str],
    pages: int,
    timeout: float,
    mailto: Optional[str],
) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    """Wrapper de busca com serialização para cache estável."""
    return _fetch_works_cached(
        strategy=strategy,
        base_params_json=json.dumps(base_params, sort_keys=True, ensure_ascii=False),
        filters_json=json.dumps(filters, sort_keys=True, ensure_ascii=False),
        pages=pages,
        timeout=timeout,
        mailto=mailto or "",
    )


def render_query_results(
    *,
    query: str,
    filters: Dict[str, str],
    params: Dict[str, Any],
    js: Dict[str, Any],
    status: int,
    timeout: float,
    top_authors_n: int,
    top_terms_n: int,
    table_preview_rows: int,
) -> None:
    """Renderiza painel completo da consulta por query."""
    message = js.get("message", {})
    items = message.get("items", [])
    normalized = [normalize_item(item) for item in items]
    normalized_df = pd.DataFrame(normalized)

    total_results = message.get("total-results", "?")
    summary = build_work_summary(query, filters, items, total_results)

    year_df = get_year_distribution(items)
    type_df = get_type_distribution(items, top_n=10)
    publisher_df = get_publisher_distribution(items, top_n=10)
    journal_df = get_journal_distribution(items, top_n=10)
    top_authors_df = get_top_authors(items, top_n=top_authors_n)
    top_terms_df = get_top_title_terms(items, top_n=top_terms_n)

    st.success(f"Consulta executada com sucesso. {len(items)} item(ns) retornado(s).")
    retrieved_pages = message.get("retrieved-pages")
    if retrieved_pages is not None:
        st.caption(f"Coleta agregada em {retrieved_pages} página(s).")
    st.subheader("Resumo do trabalho")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Itens retornados", summary["returned"])
    col2.metric("Total na API", summary["total_results"])
    col3.metric("DOIs únicos", summary["doi_count"])
    col4.metric("Autores únicos", summary["unique_authors_count"])
    col5.metric("Qtd. filtros", summary["filters_count"])

    if summary["year_min"] is not None and summary["year_max"] is not None:
        st.write(f"Faixa de anos da amostra atual: **{summary['year_min']} - {summary['year_max']}**")

    notes = []
    if summary["top_publisher"]:
        notes.append(
            f"Editora mais frequente: **{summary['top_publisher']['name']}** "
            f"({summary['top_publisher']['count']} registro(s))"
        )
    if summary["top_language"]:
        notes.append(
            f"Idioma mais frequente: **{summary['top_language']['name']}** "
            f"({summary['top_language']['count']} registro(s))"
        )
    if summary["avg_references"] is not None:
        notes.append(f"Média de referências por item: **{summary['avg_references']}**")
    if summary["avg_citations"] is not None:
        notes.append(f"Média de citações recebidas (`is-referenced-by-count`): **{summary['avg_citations']}**")

    if notes:
        for note in notes:
            st.write(f"- {note}")

    st.subheader("Gráficos")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("**Publicações por ano**")
        if not year_df.empty:
            st.line_chart(year_df.set_index("ano")["publicacoes"], height=260)
        else:
            st.info("Sem dados de ano para construir o gráfico.")

    with chart_col2:
        st.markdown("**Distribuição por tipo de documento**")
        if not type_df.empty:
            st.bar_chart(type_df.set_index("tipo")["quantidade"], height=260)
        else:
            st.info("Sem dados de tipo para construir o gráfico.")

    chart_col3, chart_col4 = st.columns(2)
    with chart_col3:
        st.markdown("**Autores mais frequentes**")
        if not top_authors_df.empty:
            st.bar_chart(top_authors_df.set_index("autor")["frequencia"], height=260)
            st.dataframe(top_authors_df, use_container_width=True, hide_index=True)
        else:
            st.info("Sem autores suficientes para análise.")

    with chart_col4:
        st.markdown("**Termos mais frequentes nos títulos**")
        if not top_terms_df.empty:
            st.bar_chart(top_terms_df.set_index("termo")["frequencia"], height=260)
            st.dataframe(top_terms_df, use_container_width=True, hide_index=True)
        else:
            st.info("Sem termos suficientes para análise.")

    dist_col1, dist_col2 = st.columns(2)
    with dist_col1:
        st.markdown("**Editoras mais frequentes**")
        if not publisher_df.empty:
            st.bar_chart(publisher_df.set_index("editora")["quantidade"], height=260)
            st.dataframe(publisher_df, use_container_width=True, hide_index=True)
        else:
            st.info("Sem dados de editora para análise.")

    with dist_col2:
        st.markdown("**Periódicos mais frequentes**")
        if not journal_df.empty:
            st.bar_chart(journal_df.set_index("periodico")["quantidade"], height=260)
            st.dataframe(journal_df, use_container_width=True, hide_index=True)
        else:
            st.info("Sem dados de periódico para análise.")

    st.subheader("Resultados detalhados")
    if not normalized_df.empty:
        if len(normalized_df) > table_preview_rows:
            st.caption(
                f"Mostrando prévia com {table_preview_rows} de {len(normalized_df)} linhas "
                "(visualização completa pode ficar lenta)."
            )
            st.dataframe(normalized_df.head(table_preview_rows), use_container_width=True)
            if st.checkbox(
                "Exibir tabela completa (pode ficar lento)",
                value=False,
                key="show_full_results_table",
            ):
                st.dataframe(normalized_df, use_container_width=True)
        else:
            st.dataframe(normalized_df, use_container_width=True)
    else:
        st.info("Sem itens para exibir na tabela normalizada.")

    summary_payload = {
        "summary": summary,
        "top_authors": top_authors_df.to_dict(orient="records"),
        "top_terms": top_terms_df.to_dict(orient="records"),
        "types": type_df.to_dict(orient="records"),
        "publishers": publisher_df.to_dict(orient="records"),
        "journals": journal_df.to_dict(orient="records"),
        "years": year_df.to_dict(orient="records"),
    }

    csv_content = normalized_df.to_csv(index=False) if not normalized_df.empty else ""
    parquet_content = b""
    parquet_error = None
    if not normalized_df.empty:
        try:
            parquet_content = dataframe_to_parquet_bytes(normalized_df)
        except Exception as error:  # noqa: BLE001
            parquet_error = str(error)

    down_col1, down_col2, down_col3, down_col4 = st.columns(4)
    with down_col1:
        st.download_button(
            label="Baixar resposta JSON",
            data=json.dumps(js, ensure_ascii=False, indent=2),
            file_name="crossref_query.json",
            mime="application/json",
            use_container_width=True,
        )
    with down_col2:
        st.download_button(
            label="Baixar tabela CSV",
            data=csv_content,
            file_name="crossref_query.csv",
            mime="text/csv",
            disabled=not bool(csv_content),
            use_container_width=True,
        )
    with down_col3:
        st.download_button(
            label="Baixar resumo JSON",
            data=json.dumps(summary_payload, ensure_ascii=False, indent=2),
            file_name="crossref_summary.json",
            mime="application/json",
            use_container_width=True,
        )
    with down_col4:
        st.download_button(
            label="Baixar tabela Parquet",
            data=parquet_content,
            file_name="crossref_query.parquet",
            mime="application/octet-stream",
            disabled=not bool(parquet_content),
            use_container_width=True,
        )
        if parquet_error:
            st.caption(f"Parquet indisponível: {parquet_error}")

    render_api_details(js=js, status=status, query_params=params, filters=filters, timeout=timeout)


def render_doi_result(item: Dict[str, Any]) -> None:
    """Renderiza painel da busca por DOI."""
    normalized_item = normalize_item(item)
    authors = get_authors(item)
    year = get_year(item)

    st.success("DOI encontrado com sucesso.")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Ano", year if year is not None else "-")
    col2.metric("Tipo", item.get("type", "-"))
    col3.metric("Autores", len(authors))
    col4.metric("Referências", get_reference_count(item) or "-")
    col5.metric("Citações", item.get("is-referenced-by-count", "-"))

    st.markdown("**Metadados principais**")
    metadata = {
        "DOI": item.get("DOI"),
        "Título": get_title(item),
        "Publisher": item.get("publisher"),
        "Idioma": item.get("language", "-"),
        "Periódico": (item.get("container-title", []) or ["-"])[0],
        "URL": item.get("URL", "-"),
    }
    st.dataframe(pd.DataFrame([metadata]), use_container_width=True, hide_index=True)

    if authors:
        st.markdown("**Autores**")
        st.dataframe(
            pd.DataFrame({"autor": authors, "ordem": list(range(1, len(authors) + 1))}),
            use_container_width=True,
            hide_index=True,
        )

    st.download_button(
        label="Baixar JSON do DOI",
        data=json.dumps(item, ensure_ascii=False, indent=2),
        file_name="crossref_doi.json",
        mime="application/json",
        use_container_width=True,
    )

    st.download_button(
        label="Baixar CSV do DOI",
        data=rows_to_csv([normalized_item]),
        file_name="crossref_doi.csv",
        mime="text/csv",
        use_container_width=True,
    )

    with st.expander("Ver JSON bruto do DOI"):
        st.json(item)


def main() -> None:
    """Ponto de entrada da aplicação Streamlit."""
    st.set_page_config(page_title="Crossref Insight Studio", page_icon="📚", layout="wide")
    inject_styles()

    st.markdown(
        """
        <div class="hero">
            <div class="hero-links">
                <a href="https://www.linkedin.com/in/lucaslmf/" target="_blank">LinkedIn</a>
                <a href="https://github.com/lucaslmfbib" target="_blank">GitHub</a>
                <a href="https://www.instagram.com/lucaslmf_/" target="_blank">Instagram</a>
            </div>
            <h1>Crossref Insight Studio</h1>
            <p>
                Explore metadados da API Crossref com foco em resumo do trabalho,
                frequência de autores/termos e gráficos de distribuição.
            </p>
            <span class="pill">Endpoint /works</span>
            <span class="pill">Análise bibliométrica rápida</span>
            <span class="pill">Export JSON/CSV</span>
            <div class="author-signature">Feito pelo Bibliotecário Lucas Martins</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.subheader("Configuração")
        mailto = st.text_input("Email (mailto)", placeholder="seu-email@exemplo.com")
        pagination_mode = st.selectbox(
            "Paginação",
            options=[
                "cursor (recomendado para volume alto)",
                "offset (simples e direto)",
            ],
            index=0,
        )
        timeout = st.number_input(
            "Timeout (segundos)",
            min_value=5.0,
            max_value=120.0,
            value=20.0,
            step=1.0,
        )
        table_preview_rows = st.slider(
            "Linhas na tabela (preview)",
            min_value=100,
            max_value=5000,
            value=1000,
            step=100,
        )
        top_authors_n = st.slider("Top autores", min_value=5, max_value=20, value=10, step=1)
        top_terms_n = st.slider("Top termos nos títulos", min_value=5, max_value=25, value=15, step=1)

        st.markdown("---")
        st.markdown("**API Crossref**")
        st.write(f"Endpoint: `{WORKS_ENDPOINT}`")
        st.markdown(f"[Documentação oficial]({DOCS_URL})")
        st.caption("Dica: inclua `mailto` para identificação do cliente na API.")
        if st.button("Limpar cache de consultas", use_container_width=True):
            st.cache_data.clear()
            st.success("Cache limpo.")

    query_tab, doi_tab = st.tabs(["Busca por Query", "Busca por DOI"])

    with query_tab:
        with st.form("query_form"):
            query = st.text_input("Consulta", placeholder="deep learning")
            strategy = "cursor" if pagination_mode.startswith("cursor") else "offset"

            col1, col2, col3 = st.columns(3)
            with col1:
                rows = st.number_input("Rows por página", min_value=1, max_value=1000, value=100, step=1)
            with col2:
                offset = st.number_input(
                    "Offset",
                    min_value=0,
                    max_value=100000,
                    value=0,
                    step=1,
                    disabled=(strategy == "cursor"),
                    help="Usado apenas no modo offset.",
                )
            with col3:
                pages = st.number_input("Páginas", min_value=1, max_value=50, value=5, step=1)

            select_raw = st.text_input(
                "Campos select (separados por vírgula; vazio = campos completos)",
                value=DEFAULT_SELECT,
            )
            filters_raw = st.text_area(
                "Filtros (um key=value por linha)",
                value=DEFAULT_FILTERS,
                height=115,
            )

            query_submit = st.form_submit_button("Buscar e Analisar", type="primary")

        if query_submit:
            if not query.strip():
                st.warning("Informe uma consulta em 'Consulta'.")
            else:
                try:
                    filters = parse_filters(filters_raw)
                    select_fields = parse_select(select_raw)
                    target_total = int(rows) * int(pages)
                    if target_total > 10000:
                        st.warning(
                            "Você solicitou muitos registros de uma vez. "
                            "Pode ficar lento ou sofrer limite de API."
                        )

                    params: Dict[str, Any] = {
                        "query": query.strip(),
                        "rows": int(rows),
                    }
                    if strategy == "offset":
                        params["offset"] = int(offset)
                    if select_fields:
                        params["select"] = ",".join(select_fields)
                    if mailto.strip():
                        params["mailto"] = mailto.strip()

                    with st.spinner("Consultando a API e gerando análise..."):
                        js, status, paging_meta = fetch_works(
                            strategy=strategy,
                            base_params=params,
                            filters=filters,
                            pages=int(pages),
                            timeout=float(timeout),
                            mailto=mailto.strip() or None,
                        )
                except ValueError as error:
                    st.error(str(error))
                except requests.RequestException as error:
                    st.error(f"Erro de rede: {error}")
                else:
                    if status != 200:
                        details = extract_api_error_message(js, "Verifique parâmetros de select/filtros.")
                        st.error(f"A API retornou status {status}. {details}")
                        with st.expander("Detalhes técnicos do erro"):
                            st.json(js)
                    else:
                        params["_strategy"] = strategy
                        params["_pages_requested"] = int(pages)
                        params["_pages_retrieved"] = paging_meta["pages_retrieved"]
                        if "offsets" in paging_meta:
                            params["_offsets"] = paging_meta["offsets"]
                        render_query_results(
                            query=query.strip(),
                            filters=filters,
                            params=params,
                            js=js,
                            status=status,
                            timeout=float(timeout),
                            top_authors_n=top_authors_n,
                            top_terms_n=top_terms_n,
                            table_preview_rows=table_preview_rows,
                        )

    with doi_tab:
        with st.form("doi_form"):
            doi = st.text_input("DOI", value="10.1038/s41586-020-2649-2")
            doi_submit = st.form_submit_button("Buscar DOI", type="primary")

        if doi_submit:
            if not doi.strip():
                st.warning("Informe um DOI válido.")
            else:
                try:
                    with st.spinner("Consultando DOI..."):
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
                        render_doi_result(item)


if __name__ == "__main__":
    main()
