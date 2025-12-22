"""
Although Python packaging ecosystem is moving towards using pyproject.toml as the standard configuration file, 
as it provides a more modern and flexible way to define project metadata and dependencies, 

however, setup.py is still widely used, especially for projects that need to support editable installations or 
other legacy features not yet fully supported by pyproject.toml.
"""
from setuptools import setup, Extension, Command
from setuptools.command.build_ext import build_ext
from Cython.Build import cythonize
import os
import tomli


def _get_version():
    with open("pyproject.toml", "rb") as f:
        return tomli.load(f)["project"]["version"]


class CustomBuildExt(build_ext):
    def finalize_options(self):
        build_ext.finalize_options(self)
        print(f"[DEBUG] Build directory: {self.build_lib}")
        print(f"[DEBUG] Current directory: {os.getcwd()}")


    def build_extension(self, ext):
        print(f"[DEBUG] Building extension: {ext.name}")
        print(f"[DEBUG] Sources before: {ext.sources}")


        # Copy tax_pres_py.py to tax_pres.pyx
        if ext.sources[0] == 'openesef/engines/tax_pres.pyx':
            py_file = 'openesef/engines/tax_pres_py.py'
            if os.path.exists(py_file):
                os.system(f'rm {ext.sources[0]}')  # rm old .pyx file
                os.system(f'cp {py_file} {ext.sources[0]}')  # Copy .py to .pyx
                print(f"[DEBUG] Copied {py_file} to {ext.sources[0]}")
            else:
                print(f"[DEBUG] File {py_file} does not exist") 


        # Convert sources to relative paths
        sources = []
        for source in ext.sources:
            if os.path.isabs(source):
                source = os.path.relpath(source, os.path.dirname(__file__))
            sources.append(source)
        ext.sources = sources
        
        print(f"[DEBUG] Sources after: {ext.sources}")
        build_ext.build_extension(self, ext)


        # Delete the .pyx file after compilation
        if os.path.exists(ext.sources[0]):
            os.remove(ext.sources[0])  # Remove the .pyx file


extensions = [
    Extension(
        'openesef.engines.tax_pres',
        sources=['openesef/engines/tax_pres.pyx'],
    )
]


setup(
    name="openesef",
    version=_get_version(),
    description='An open-source Python library for ESEF XBRL filings',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/reeyarn/openesef',    
    author="Reeyarn Zhiyang Li",
    author_email="reeyarn@gmail.com",
    packages=["openesef", "openesef.engines"],
    ext_modules=cythonize(extensions),
    cmdclass={'build_ext': CustomBuildExt}
) 
