"""
Protein Structure Server - An MCP server for retrieving protein information
from UniProt and AlphaFold databases.

This module provides tools to search for proteins, get detailed structure information,
and retrieve UniProt accession numbers.
"""

import logging
from typing import Dict, List, Optional, Any

import httpx
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP("protein_structure")

# API Configuration
UNIPROT_API_SEARCH = 'https://rest.uniprot.org/uniprotkb/search?query={query} organism_name:"Homo sapiens" AND reviewed:true &format=json'
UNIPROT_API_ACCESSION = "https://rest.uniprot.org/uniprotkb/{accession}?format=json"
ALPHAFOLD_API = "https://alphafold.ebi.ac.uk/api/prediction/{uniprot_accession}"

# Constants
DEFAULT_TIMEOUT = 30.0
UNIPROT_TIMEOUT = 10.0
MAX_SEARCH_RESULTS = 5
SEQUENCE_DISPLAY_LIMIT = 500
SEQUENCE_LINE_LENGTH = 60


async def make_alphafold_request(uniprot_accession: str) -> List[Dict[str, Any]]:
    """
    Make a request to the AlphaFold API to get protein structure predictions.

    Args:
        uniprot_accession: The UniProt accession number

    Returns:
        List of dictionaries containing AlphaFold prediction data, or empty list on failure

    Raises:
        httpx.RequestError: If the HTTP request fails
        httpx.HTTPStatusError: If the HTTP response has an error status code
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                ALPHAFOLD_API.format(uniprot_accession=uniprot_accession),
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(
                f"Request error fetching from AlphaFold API for {uniprot_accession}: {e}"
            )
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching from AlphaFold API for {uniprot_accession}: {e}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Unexpected error fetching from AlphaFold API for {uniprot_accession}: {e}"
            )
            return []


async def make_uniprot_request_by_accession(
    uniprot_accession: str,
) -> Optional[Dict[str, Any]]:
    """
    Make a request to the UniProt API using an accession number.

    Args:
        uniprot_accession: The UniProt accession number

    Returns:
        Dictionary containing UniProt data, or None on failure

    Raises:
        httpx.RequestError: If the HTTP request fails
        httpx.HTTPStatusError: If the HTTP response has an error status code
    """
    async with httpx.AsyncClient() as client:
        try:
            url = UNIPROT_API_ACCESSION.format(accession=uniprot_accession)
            response = await client.get(url, timeout=UNIPROT_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(
                f"Request error fetching from UniProt API for accession {uniprot_accession}: {e}"
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching from UniProt API for accession {uniprot_accession}: {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error fetching from UniProt API for accession {uniprot_accession}: {e}"
            )
            return None


async def make_uniprot_request_by_name(protein_name: str) -> Optional[Dict[str, Any]]:
    """
    Make a request to the UniProt API using a protein name, prioritizing human proteins.

    Args:
        protein_name: The name of the protein to search for

    Returns:
        Dictionary containing search results, or None on failure

    Raises:
        httpx.RequestError: If the HTTP request fails
        httpx.HTTPStatusError: If the HTTP response has an error status code
    """
    async with httpx.AsyncClient() as client:
        try:
            url = "https://rest.uniprot.org/uniprotkb/search"
            params = {
                "query": f"{protein_name}",
                "format": "json",
                "size": MAX_SEARCH_RESULTS,
            }

            response = await client.get(url, params=params, timeout=UNIPROT_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("results") and len(data["results"]) > 0:
                return data

            # Fallback search without human-specific filtering
            params = {
                "query": protein_name,
                "format": "json",
                "size": MAX_SEARCH_RESULTS,
            }

            response = await client.get(url, params=params, timeout=UNIPROT_TIMEOUT)
            response.raise_for_status()
            return response.json()

        except httpx.RequestError as e:
            logger.error(
                f"Request error fetching from UniProt API for name {protein_name}: {e}"
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching from UniProt API for name {protein_name}: {e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error fetching from UniProt API for name {protein_name}: {e}"
            )
            return None


def extract_protein_name(uniprot_data: Dict[str, Any]) -> str:
    """
    Extract protein name from UniProt data, trying recommended name first.

    Args:
        uniprot_data: Dictionary containing UniProt protein data

    Returns:
        Protein name or "N/A" if not found
    """
    protein_name = (
        uniprot_data.get("proteinDescription", {})
        .get("recommendedName", {})
        .get("fullName", {})
        .get("value", "N/A")
    )

    if protein_name == "N/A":
        submitted_names = uniprot_data.get("proteinDescription", {}).get(
            "submittedNames", []
        )
        if submitted_names:
            protein_name = submitted_names[0].get("fullName", {}).get("value", "N/A")

    return protein_name


def extract_protein_description(uniprot_data: Dict[str, Any]) -> str:
    """
    Extract protein functional description from UniProt data.

    Args:
        uniprot_data: Dictionary containing UniProt protein data

    Returns:
        Protein description or falls back to protein name if not found
    """
    description = ""

    # Look for functional description in comments
    for comment in uniprot_data.get("comments", []):
        if comment.get("commentType") == "FUNCTION":
            texts = comment.get("texts", [])
            if texts:
                description = texts[0].get("value", "")
                break

    if not description:
        # Fallback to protein name
        description = extract_protein_name(uniprot_data)

    return description


def format_sequence(sequence: str) -> str:
    """
    Format protein sequence for display.

    Args:
        sequence: Raw amino acid sequence

    Returns:
        Formatted sequence string with appropriate line breaks
    """
    if len(sequence) <= SEQUENCE_DISPLAY_LIMIT:
        formatted_sequence = "\n".join(
            sequence[i : i + SEQUENCE_LINE_LENGTH]
            for i in range(0, len(sequence), SEQUENCE_LINE_LENGTH)
        )
        return f"\n\n📄 **Amino Acid Sequence**:\n{formatted_sequence}"
    else:
        return f"\n\n📄 **Amino Acid Sequence**: Too long to display ({len(sequence)} amino acids)"


@mcp.tool()
async def get_protein_structure(uniprot_accession: str) -> str:
    """
    Get the structure, sequence, and metadata of a protein from AlphaFold and UniProt.

    This tool retrieves comprehensive protein information including:
    - Basic metadata (name, organism, description)
    - Amino acid sequence
    - AlphaFold structure prediction links
    - PDB file download links

    Args:
        uniprot_accession: The UniProt accession number of the protein (e.g., "P01308")

    Returns:
        Formatted string containing all protein information and structure data

    Example:
        >>> await get_protein_structure("P01308")
        "🧬 **Protein Information and AlphaFold Structure**
        - **UniProt ID**: P01308
        - **Protein Name**: Insulin
        - **Organism**: Homo sapiens
        ..."
    """
    # Get protein metadata from UniProt
    uniprot_data = await make_uniprot_request_by_accession(uniprot_accession)
    if not uniprot_data:
        return f"Unable to fetch UniProt information for accession {uniprot_accession}."

    accession = uniprot_data.get("primaryAccession", "N/A")
    protein_name = extract_protein_name(uniprot_data)
    description = extract_protein_description(uniprot_data)
    organism = uniprot_data.get("organism", {}).get("scientificName", "N/A")
    sequence = uniprot_data.get("sequence", {}).get("value", "N/A")

    # Get AlphaFold structure information
    alphafold_models = await make_alphafold_request(uniprot_accession)

    structure_url = f"https://alphafold.ebi.ac.uk/entry/{uniprot_accession}"
    pdb_url = "N/A"

    if alphafold_models:
        pdb_url = alphafold_models[0].get("pdbUrl", "N/A")

    sequence_section = format_sequence(sequence)

    return (
        f"🧬 **Protein Information and AlphaFold Structure**\n"
        f"- **UniProt ID**: {accession}\n"
        f"- **Protein Name**: {protein_name}\n"
        f"- **Organism**: {organism}\n"
        f"- **Description**: {description}\n"
        f"- **AlphaFold Page**: {structure_url}\n"
        f"- **Download PDB**: {pdb_url}{sequence_section}"
    )


@mcp.tool()
async def search_proteins(protein_name: str) -> str:
    """
    Search for proteins by name, prioritizing human proteins and showing multiple candidates.

    This tool searches the UniProt database for proteins matching the given name,
    with special prioritization for human (Homo sapiens) proteins. Results include
    accession numbers that can be used with get_protein_structure().

    Args:
        protein_name: The name of the protein to search for (e.g., "insulin", "hemoglobin")

    Returns:
        Formatted string containing up to 5 search results with detailed information

    Example:
        >>> await search_proteins("insulin")
        "🔍 **Search results for 'insulin':**
        1. **P01308** - Insulin
           Gene: INS | Organism: **Homo sapiens**
        ..."
    """
    data = await make_uniprot_request_by_name(protein_name)
    if not data:
        return f"Unable to search for proteins matching '{protein_name}'"

    results = data.get("results", [])
    if not results:
        return f"No proteins found matching '{protein_name}'"

    # Return up to MAX_SEARCH_RESULTS with detailed information
    candidates = []
    for i, result in enumerate(results[:MAX_SEARCH_RESULTS], 1):
        accession = result.get("primaryAccession", "N/A")
        protein_name_full = extract_protein_name(result)
        organism = result.get("organism", {}).get("scientificName", "N/A")

        # Get gene name
        gene_name = "N/A"
        if result.get("genes"):
            gene_name = (
                result.get("genes", [{}])[0].get("geneName", {}).get("value", "N/A")
            )

        # Highlight human proteins
        organism_display = f"**{organism}**" if organism == "Homo sapiens" else organism

        candidates.append(
            f"{i}. **{accession}** - {protein_name_full}\n   Gene: {gene_name} | Organism: {organism_display}"
        )

    note = "\n\n💡 Human proteins are prioritized and shown in bold. Use the accession number with get_protein_structure() for detailed information."
    return (
        f"🔍 **Search results for '{protein_name}':**\n\n"
        + "\n\n".join(candidates)
        + note
    )


@mcp.tool()
async def get_uniprot_id(protein: str) -> str:
    """
    Get UniProt ID (accession number) for a given protein name.

    This is a convenience tool that searches for a protein and returns just
    the UniProt accession number of the first (best) match.

    Args:
        protein: The name of the protein to search for (e.g., "insulin")

    Returns:
        String containing the UniProt ID or an error message

    Example:
        >>> await get_uniprot_id("insulin")
        "UniProt ID for 'insulin': P01308"
    """
    data = await make_uniprot_request_by_name(protein)
    if not data:
        return f"Unable to search for UniProt ID for '{protein}'"

    results = data.get("results", [])
    if results:
        uniprot_id = results[0].get("primaryAccession", "N/A")
        return f"UniProt ID for '{protein}': {uniprot_id}"
    else:
        return f"No UniProt ID found for '{protein}'"


if __name__ == "__main__":
    mcp.run(transport="stdio")
