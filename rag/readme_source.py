from langchain_text_splitters import MarkdownHeaderTextSplitter

from github_app import get_repo

# Which header levels count as their own chunk — matches the anchors
HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]

# A custom Error class so we know why code failed
class ReadmeNotFoundError(Exception):
    """Raised when the target repo has no README.md at all. Later, this will
    trigger a 'generate a README from scratch by reading the code' flow —
    not built yet, deliberately deferred."""

def fetch_readme() -> str:
    repo = get_repo()
    try:
        readme = repo.get_contents("README.md")  # exact path — Notes.md is never touched here at all
    except Exception as e:
        raise ReadmeNotFoundError( 
            f"No README.md found in {repo.full_name} — nothing to check for staleness."
        ) from e
    return readme.decoded_content.decode()

# calls the splitter, then for each resulting chunk, pulls out its heading text from the metadata (preferring the most specific
# level available — h3 if present, else h2, else h1) and converts that heading into a URL-style anchor slug.
def chunk_readme() -> list[dict]:
    markdown_text = fetch_readme()
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS_TO_SPLIT_ON)
    docs = splitter.split_text(markdown_text) # each `doc` = one section, with header metadata attached

    chunks = []
    for doc in docs:
        # doc.metadata looks like {"h1": "...", "h2": "Stack"} — grab the deepest header present
        if doc.metadata.get("h3"):
            heading_text, level = doc.metadata["h3"], 3
        elif doc.metadata.get("h2"):
            heading_text, level = doc.metadata["h2"], 2
        elif doc.metadata.get("h1"):
            heading_text, level = doc.metadata["h1"], 1
        else:
            continue # skip any stray content before the first heading

        anchor = _slugify(heading_text)
        chunks.append({"anchor": anchor, "heading": heading_text, "level": level, "content": doc.page_content})

    return chunks


def _slugify(heading: str) -> str:
    """Mimics GitHub's own anchor-generation rule: lowercase, spaces -> hyphens, strip most punctuation."""
    text = heading.lower().strip()
    text = "".join(c for c in text if c.isalnum() or c in (" ", "-"))
    return text.replace(" ", "-")

def build_full_readme_preview(rewritten_by_anchor: dict[str, str]) -> str:
    """Rebuilds the entire README, replacing only the sections that were rewritten."""
    chunks = chunk_readme()
    parts = []
    for chunk in chunks:
        content = rewritten_by_anchor.get(chunk["anchor"], chunk["content"])  # use rewrite if we have one, else original
        parts.append(f"{'#' * chunk['level']} {chunk['heading']}\n\n{content}\n")
    return "\n".join(parts)