"""Metadata đóng gói theo khuôn Phanlacan12/CoreTrainingTimeSeries.

Lưu ý quan trọng: build backend thật của project là uv_build (xem
[build-system] trong pyproject.toml), nên `uv build` / `uv sync` KHÔNG đọc file
này. setup.py ở đây là lớp tương thích setuptools cho môi trường chỉ có pip:

    python -m pip install -r requirements.txt      # chỉ runtime
    python -m pip install -r requirements-dev.txt  # kèm style/test

Muốn setup.py thành backend chính thức (giống repo mẫu) thì đổi [build-system]
trong pyproject.toml sang setuptools.build_meta và bỏ các field tĩnh trùng
trong [project].
"""

from pathlib import Path

from setuptools import find_packages, setup

BASE_DIR = Path(__file__).parent


def _read_requirements(filename: str) -> list[str]:
    """Đọc requirements, bỏ comment, dòng trống và các chỉ thị -r/-c/-e."""
    path = BASE_DIR / filename
    if not path.exists():
        return []
    requirements = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirements.append(line)
    return requirements


required_packages = _read_requirements("requirements.txt")

style_packages = [
    "black>=25.9.0",
    "flake8>=7.3.0",
    "isort>=6.0.1",
    "mypy>=2.4.1",
    "pylint>=4.1.4",
    "pre-commit>=4.7.0",
    "types-boto3>=1.44.3",
]

test_packages = [
    "pytest>=9.2.0",
    "pytest-asyncio>=1.5.0",
    "pytest-cov>=7.1.0",
    "moto[s3]>=5.2.5",
    "respx>=0.23.1",
]

readme_path = BASE_DIR / "README.md"
readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

license_path = BASE_DIR / "LICENSE"
license_text = license_path.read_text(encoding="utf-8") if license_path.exists() else ""

setup(
    name="document-service",
    version="0.1.0",
    description=("Kho raw data dung chung - Document Service (OpenMetadata + Object Storage S3)"),
    long_description=readme,
    long_description_content_type="text/markdown",
    license=license_text,
    package_dir={"": "src"},
    packages=find_packages(where="src", exclude=("tests", "tests.*", "docs")),
    include_package_data=True,
    install_requires=required_packages,
    python_requires=">=3.12",
    extras_require={
        "dev": required_packages + style_packages + test_packages,
        "test": required_packages + test_packages,
        "style": style_packages,
    },
    entry_points={
        "console_scripts": ["document-service = document_service.main:cli"],
    },
)
