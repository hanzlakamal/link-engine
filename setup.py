"""
Setup script for Backlink Strategy Engine
"""
from setuptools import setup, find_packages

setup(
    name="backlink-engine",
    version="1.0.0",
    description="Intelligent Link Building Automation Platform",
    author="Your Name",
    author_email="your@email.com",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=[
        "PyQt6>=6.6.0",
        "PyQt6-Charts>=6.6.0",
        "playwright>=1.41.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.1.0",
        "httpx>=0.26.0",
        "anthropic>=0.18.0",
        "openai>=1.12.0",
        "sqlalchemy>=2.0.0",
        "pandas>=2.2.0",
        "imapclient>=3.0.0",
        "pydantic>=2.6.0",
        "pydantic-settings>=2.1.0",
        "loguru>=0.7.0",
        "python-dotenv>=1.0.0",
        "cryptography>=42.0.0",
        "rich>=13.7.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.23.0",
            "black>=24.0.0",
            "flake8>=7.0.0",
            "mypy>=1.8.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "backlink-engine=main:main",
        ],
    },
)