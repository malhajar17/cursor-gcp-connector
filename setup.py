from setuptools import setup, find_packages

setup(
    name="cursor-gcp-connector",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "litellm[proxy]>=1.80.0",
        "google-cloud-aiplatform>=1.38",
    ],
    entry_points={
        "console_scripts": [
            "cursor-gcp-connector=cursor_gcp_connector.cli:main",
        ],
    },
    python_requires=">=3.8",
    description="Bridge Cursor IDE to Vertex AI Claude",
    author="malhajar17",
    url="https://github.com/malhajar17/cursor-gcp-connector",
)



