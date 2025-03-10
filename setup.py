from setuptools import setup, Extension
from Cython.Build import cythonize
import os

extensions = [
    Extension(
        'openesef.engines.tax_pres',
        sources=['openesef/engines/tax_pres.pyx'],
    )
]

setup(
    name='openesef',
    version='0.3.8',
    description='Open ESEF Library',
    author='Dominik Deitelhoff',
    author_email='d.deitelhoff@hs-osnabrueck.de',
    packages=[
        'openesef',
        'openesef.base',
        'openesef.edgar',
        'openesef.engines',
        'openesef.filings_xbrl_org',
        'openesef.instance',
        'openesef.ixbrl',
        'openesef.taxonomy',
        'openesef.taxonomy.formula',
        'openesef.taxonomy.table',
        'openesef.taxonomy.xdt',
        'openesef.test',
        'openesef.test.ixbrl',
        'openesef.util'
    ],
    package_data={
        'openesef.engines': ['*.pyx'],
    },
    include_package_data=True,
    ext_modules=cythonize(extensions),
    install_requires=[
        'beautifulsoup4>=4.12.2',
        'lxml>=4.9.3',
        'numpy>=1.24.3',
        'pandas>=2.0.2',
        'requests>=2.31.0',
        'tqdm>=4.65.0',
        'urllib3>=2.0.3',
        'Cython>=3.0.0',
    ],
    python_requires='>=3.11',
) 