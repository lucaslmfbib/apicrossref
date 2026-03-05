#!/usr/bin/env python3
"""Cliente de linha de comando para a API Crossref (/works)."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

LOGGER = logging.getLogger("crossref_client")
WORKS_API_URL = "https://api.crossref.org/works"


def filters_to_param(filters: Dict[str, str]) -> str:
    """Converte filtros em string aceitas pela API Crossref.

    Exemplo: {"type": "journal-article", "has-references": "true"}
    -> "type:journal-article,has-references:true"
    """
    return ",".join(f"{key}:{value}" for key, value in filters.items())


def parse_key_value(items: List[str], label: str) -> Dict[str, str]:
    """Converte argumentos no formato key=value em dicionário."""
    parsed: Dict[str, str] = {}
    for raw in items:
        if "=" not in raw:
            raise ValueError(f"{label} inválido '{raw}'. Use formato key=value.")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"{label} inválido '{raw}'. Use formato key=value.")
        parsed[key] = value
    return parsed


def build_headers(mailto: Optional[str]) -> Dict[str, str]:
    if mailto:
        return {"User-Agent": f"CrossrefStudy/1.0 (mailto:{mailto})"}
    return {"User-Agent": "CrossrefStudy/1.0"}


def get_works(
    params: Dict[str, Any],
    filters: Optional[Dict[str, str]] = None,
    *,
    timeout: float = 20.0,
    mailto: Optional[str] = None,
) -> tuple[Dict[str, Any], int]:
    """Consulta /works e retorna (json, status_code)."""
    query_params = dict(params)
    if filters:
        query_params["filter"] = filters_to_param(filters)

    response = requests.get(
        WORKS_API_URL,
        params=query_params,
        headers=build_headers(mailto),
        timeout=timeout,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "failed", "message": response.text}

    if response.status_code == 200:
        return payload, response.status_code

    LOGGER.error("Falha na consulta (%s): %s", response.status_code, response.text)
    return payload, response.status_code


def get_by_doi(
    doi: str,
    *,
    timeout: float = 20.0,
    mailto: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Consulta metadados de um DOI em /works/{doi}."""
    response = requests.get(
        f"{WORKS_API_URL}/{doi}",
        headers=build_headers(mailto),
        timeout=timeout,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("message")


def normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza os campos principais de um item Crossref para CSV."""
    title = "; ".join(item.get("title", []) or [])
    doi = item.get("DOI")
    container = "; ".join(item.get("container-title", []) or [])
    publisher = item.get("publisher")
    published_year = item.get("issued", {}).get("date-parts", [[None]])[0][0]

    authors = []
    for author in item.get("author", []) or []:
        full_name = " ".join(filter(None, [author.get("given"), author.get("family")]))
        if full_name:
            authors.append(full_name)

    return {
        "title": title,
        "doi": doi,
        "authors": "; ".join(authors),
        "container_title": container,
        "publisher": publisher,
        "year": published_year,
    }


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def save_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        LOGGER.warning("Nenhuma linha para exportar CSV: %s", path)
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_query_summary(js: Dict[str, Any]) -> None:
    """Exibe resumo do volume de resultados da consulta."""
    message = js.get("message", {})
    total = message.get("total-results")
    returned = len(message.get("items", []) or [])
    if total is None:
        print("Não foi possível extrair total-results da resposta.")
        return
    print(f"{total} registros no total; {returned} retornados nesta chamada.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cliente CLI para a API Crossref")

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--query", help="Consulta livre (title/author/keyword)")
    source_group.add_argument("--doi", help="DOI específico para consulta")

    parser.add_argument("--rows", type=int, default=20, help="Quantidade de resultados")
    parser.add_argument("--offset", type=int, default=0, help="Offset para paginação")
    parser.add_argument("--select", nargs="*", default=[], help="Campos da API (ex: DOI title issued)")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Filtro key=value; repita a flag para múltiplos filtros",
    )
    parser.add_argument("--mailto", help="Email de contato recomendado pela Crossref")
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="json",
        help="Formato de saída",
    )
    parser.add_argument("--out", required=True, help="Arquivo de saída (sem extensão em --format both)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout da requisição em segundos")
    parser.add_argument("--verbose", action="store_true", help="Logs em modo detalhado")
    return parser.parse_args()


def resolve_output_path(out: str, output_format: str, target: str) -> Path:
    base = Path(out)
    if output_format == "both":
        return base.with_suffix(f".{target}")
    return base


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    try:
        filters = parse_key_value(args.filter, "Filtro")
    except ValueError as error:
        LOGGER.error(str(error))
        return 2

    if args.doi:
        LOGGER.info("Consultando DOI %s", args.doi)
        try:
            item = get_by_doi(args.doi, timeout=args.timeout, mailto=args.mailto)
        except requests.RequestException as error:
            LOGGER.error("Erro ao consultar DOI: %s", error)
            return 1

        if item is None:
            LOGGER.error("DOI não encontrado: %s", args.doi)
            return 1

        if args.format in ("json", "both"):
            save_json(resolve_output_path(args.out, args.format, "json"), item)
        if args.format in ("csv", "both"):
            save_csv(resolve_output_path(args.out, args.format, "csv"), [normalize_item(item)])

        LOGGER.info("Consulta finalizada com sucesso")
        return 0

    params: Dict[str, Any] = {
        "query": args.query,
        "rows": args.rows,
        "offset": args.offset,
    }
    if args.select:
        params["select"] = ",".join(args.select)
    if args.mailto:
        params["mailto"] = args.mailto

    LOGGER.info("Consultando /works para query '%s'", args.query)
    try:
        js, status_code = get_works(
            params,
            filters,
            timeout=args.timeout,
            mailto=args.mailto,
        )
    except requests.RequestException as error:
        LOGGER.error("Erro de rede na consulta: %s", error)
        return 1

    if status_code != 200:
        return 1

    print_query_summary(js)
    items = js.get("message", {}).get("items", [])

    if args.format in ("json", "both"):
        save_json(resolve_output_path(args.out, args.format, "json"), js)
    if args.format in ("csv", "both"):
        save_csv(resolve_output_path(args.out, args.format, "csv"), [normalize_item(it) for it in items])

    LOGGER.info("Consulta finalizada com sucesso")
    return 0


if __name__ == "__main__":
    sys.exit(main())
