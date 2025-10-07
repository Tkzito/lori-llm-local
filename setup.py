from setuptools import setup, find_packages

setup(
    name="assistant-cli",
    version="1.0.0",
    author="Silveira",
    description="Lori, uma assistente de IA local para o terminal e web.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "lori-cli=assistant_cli.cli:main",
            "lori-tools=assistant_cli.tools_cli:main",
        ],
    },
    python_requires=">=3.10",
)