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
    """Returns a list of {content, anchor} dicts, one per README section."""
    markdown_text = fetch_readme()

    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS_TO_SPLIT_ON)
    docs = splitter.split_text(markdown_text)  # each `doc` = one section, with header metadata attached

    chunks = []
    for doc in docs:
        # doc.metadata looks like {"h1": "...", "h2": "Stack"} — grab the deepest header present
        heading_text = doc.metadata.get("h3") or doc.metadata.get("h2") or doc.metadata.get("h1")
        if not heading_text:
            continue  # skip any stray content before the first heading

        anchor = _slugify(heading_text)
        chunks.append({"anchor": anchor, "heading": heading_text, "content": doc.page_content})

    return chunks


def _slugify(heading: str) -> str:
    """Mimics GitHub's own anchor-generation rule: lowercase, spaces -> hyphens, strip most punctuation."""
    text = heading.lower().strip()
    text = "".join(c for c in text if c.isalnum() or c in (" ", "-"))
    return text.replace(" ", "-")