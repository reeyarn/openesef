
# setup.py
from setuptools import setup, find_packages

setup(
    name='openesef',
    version='0.2.5',
    author='Reeyarn Zhiyang Li',
    author_email='reeyarn@gmail.com',
    author_url='https://reeyarn.li',
    description='An open-source Python library for ESEF XBRL filings',
    long_description=open('README.md').read(),
    long_description_content_type='python',
    url='https://github.com/reeyarn/openesef',
    packages=find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',
    install_requires=[
        'thefuzz~=0.22.0',
        'pandas~=2.2.0',
        'fs~=2.4.16',
        'python-dateutil~=2.8.0',
        'requests~=2.31.0',
        'beautifulsoup4~=4.12.0',
        'lxml~=5.3.0',
    ],
)