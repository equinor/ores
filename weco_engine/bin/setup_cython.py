#!/usr/bin/env python3
"""
Build the Cython fallback correlator extension in-place.

Usage::

    python setup_cython.py build_ext --inplace

Or simply::

    cythonize -i weco/_correlator.pyx

This produces ``weco/_correlator*.so`` which is auto-detected by
``weco.correlator_numba`` when the C++ engine is unavailable.
"""

from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np

extensions = [
    Extension(
        "weco._correlator",
        sources=["weco/_correlator.pyx"],
        include_dirs=[np.get_include()],
        define_macros=[("NPY_NO_DEPRECATED_API", "NPY_1_7_API_VERSION")],
    ),
]

setup(
    name="weco-cython-fallback",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    ),
)
