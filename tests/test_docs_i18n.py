from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"


def test_english_and_chinese_docs_have_matching_pages() -> None:
    english_pages = {
        path.name
        for path in DOCS_DIR.glob("*.md")
        if not path.name.endswith(".zh.md")
    }
    chinese_pages = {
        path.name.removesuffix(".zh.md") + ".md"
        for path in DOCS_DIR.glob("*.zh.md")
    }

    assert chinese_pages == english_pages
