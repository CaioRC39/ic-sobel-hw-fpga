from pathlib import Path
import re
import sys


STATUS_FILE = Path("docs/STATUS.md")
README_FILE = Path("README.md")


def extract_summary(content: str) -> str:
    """
    Extrai o conteúdo da seção '## Resumo' até a próxima
    seção de mesmo nível ou até o final do arquivo.
    """

    pattern = (
        r"^## Resumo\s*$"
        r"([\s\S]*?)"
        r"(?=^## |^---\s*$|\Z)"
    )

    match = re.search(
        pattern,
        content,
        flags=re.MULTILINE
    )

    if not match:
        raise ValueError(
            "Seção '## Resumo' não encontrada em docs/STATUS.md."
        )

    return match.group(1).strip()


def update_readme(readme: str, summary: str) -> str:
    """
    Substitui o conteúdo entre os marcadores STATUS:START
    e STATUS:END.
    """

    pattern = (
        r"(<!-- STATUS:START -->)"
        r"[\s\S]*?"
        r"(<!-- STATUS:END -->)"
    )

    replacement = (
        r"\1\n\n"
        + summary
        + r"\n\n\2"
    )

    updated, count = re.subn(
        pattern,
        replacement,
        readme,
        count=1
    )

    if count == 0:
        raise ValueError(
            "Marcadores STATUS:START/STATUS:END "
            "não encontrados em README.md."
        )

    return updated


def main():
    try:
        status_content = STATUS_FILE.read_text(
            encoding="utf-8"
        )

        readme_content = README_FILE.read_text(
            encoding="utf-8"
        )

        summary = extract_summary(status_content)

        updated_readme = update_readme(
            readme_content,
            summary
        )

        if updated_readme == readme_content:
            print("README.md já está atualizado.")
            return

        README_FILE.write_text(
            updated_readme,
            encoding="utf-8"
        )

        print("README.md atualizado com sucesso.")

    except Exception as error:
        print(f"Erro: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()