import os
import pathlib
import setuptools


def readme():
    if os.path.isfile("README.md"):
        try:
            import requests

            r = requests.post(
                url="http://c.docverter.com/convert",
                data={"from": "markdown", "to": "rst"},
                files={"input_files[]": open("README.md", "r")},
            )
            if r.ok:
                return r.content.decode()
            else:
                return "ERROR CONVERTING README!"
        except ImportError:
            print("No `requests` module. No readme conversion applied.")
            return "!!NO CONVERSION!!\n\n" + open("README.md", "r").read()
    else:
        return "No readme for local builds."


def version():
    versionPath = pathlib.Path(__file__).parent / "VERSION"
    with versionPath.open("r") as versionFile:
        return versionFile.read().strip()


def requirementsFile(name=None):
    filename = f"requirements-{name}.txt" if name else "requirements.txt"
    reqPath = pathlib.Path(__file__).parent / filename
    with reqPath.open("r") as reqFile:
        return reqFile.read().strip().splitlines()


setuptools.setup(
    name="python-spgill-backup",
    version=version(),
    long_description=readme(),
    author="Samuel P. Gillispie II",
    author_email="samuel@spgill.me",
    url="https://github.com/spgill/python-spgill-backup",
    license="MIT",
    packages=setuptools.find_namespace_packages(include=["spgill.*"]),
    include_package_data=True,
    install_requires=requirementsFile(),
    entry_points={
        "console_scripts": [
            "spgill-backup=spgill.backup:cli",
        ]
    },
    classifiers=[
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
    ],
)
