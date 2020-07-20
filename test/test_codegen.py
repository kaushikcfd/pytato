#!/usr/bin/env python

__copyright__ = "Copyright (C) 2020 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import operator
import sys

import loopy as lp
import numpy as np
import pyopencl as cl
import pyopencl.array as cl_array  # noqa
import pyopencl.cltypes as cltypes  # noqa
import pyopencl.tools as cl_tools  # noqa
from pyopencl.tools import (  # noqa
        pytest_generate_tests_for_pyopencl as pytest_generate_tests)
import pytest  # noqa

import pytato as pt
from pytato.array import Placeholder


def test_basic_codegen(ctx_factory):
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    namespace = pt.Namespace()
    x = Placeholder(namespace, "x", (5,), np.int)
    prog = pt.generate_loopy(x * x, target=pt.PyOpenCLTarget(queue))
    x_in = np.array([1, 2, 3, 4, 5])
    _, (out,) = prog(x=x_in)
    assert (out == x_in * x_in).all()


def test_scalar_placeholder(ctx_factory):
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    namespace = pt.Namespace()
    x = Placeholder(namespace, "x", (), np.int)
    prog = pt.generate_loopy(x, target=pt.PyOpenCLTarget(queue))
    x_in = np.array(1)
    _, (x_out,) = prog(x=x_in)
    assert x_out == x_in


def test_size_param(ctx_factory):
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    namespace = pt.Namespace()
    n = pt.make_size_param(namespace, "n")
    pt.make_placeholder(namespace, "x", "(n,)", np.int)
    prog = pt.generate_loopy(n, target=pt.PyOpenCLTarget(queue))
    x_in = np.array([1, 2, 3, 4, 5])
    _, (n_out,) = prog(x=x_in)
    assert n_out == 5


@pytest.mark.parametrize("x1_ndim", (1, 2))
@pytest.mark.parametrize("x2_ndim", (1, 2))
def test_matmul(ctx_factory, x1_ndim, x2_ndim):
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    def get_array(ndim):
        arr = np.array([[1, 2], [3, 4]])
        return arr[(0,) * (arr.ndim - ndim)]

    x1_in = get_array(x1_ndim)
    x2_in = get_array(x2_ndim)

    namespace = pt.Namespace()
    x1 = pt.make_data_wrapper(namespace, x1_in)
    x2 = pt.make_data_wrapper(namespace, x2_in)
    prog = pt.generate_loopy(x1 @ x2, target=pt.PyOpenCLTarget(queue))
    _, (out,) = prog()

    assert (out == x1_in @ x2_in).all()


def test_data_wrapper(ctx_factory):
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    # Without name/shape
    namespace = pt.Namespace()
    x_in = np.array([1, 2, 3, 4, 5])
    x = pt.make_data_wrapper(namespace, x_in)
    prog = pt.generate_loopy(x, target=pt.PyOpenCLTarget(queue))
    _, (x_out,) = prog()
    assert (x_out == x_in).all()

    # With name/shape
    namespace = pt.Namespace()
    x_in = np.array([[1, 2], [3, 4], [5, 6]])
    pt.make_size_param(namespace, "n")
    x = pt.make_data_wrapper(namespace, x_in, name="x", shape="(n, 2)")
    prog = pt.generate_loopy(x, target=pt.PyOpenCLTarget(queue))
    _, (x_out,) = prog()
    assert (x_out == x_in).all()


def test_codegen_with_DictOfNamedArrays(ctx_factory):  # noqa
    ctx = ctx_factory()
    queue = cl.CommandQueue(ctx)

    namespace = pt.Namespace()
    x = Placeholder(namespace, "x", (5,), np.int)
    y = Placeholder(namespace, "y", (5,), np.int)
    x_in = np.array([1, 2, 3, 4, 5])
    y_in = np.array([6, 7, 8, 9, 10])

    result = pt.DictOfNamedArrays(dict(x_out=x, y_out=y))

    # Without return_dict.
    prog = pt.generate_loopy(result, target=pt.PyOpenCLTarget(queue))
    _, (x_out, y_out) = prog(x=x_in, y=y_in)
    assert (x_out == x_in).all()
    assert (y_out == y_in).all()

    # With return_dict.
    prog = pt.generate_loopy(result,
            target=pt.PyOpenCLTarget(queue),
            options=lp.Options(return_dict=True))

    _, outputs = prog(x=x_in, y=y_in)
    assert (outputs["x_out"] == x_in).all()
    assert (outputs["y_out"] == y_in).all()


@pytest.mark.parametrize("shift", (-1, 1, -20, 20))
@pytest.mark.parametrize("axis", (0, 1))
def test_roll(ctx_factory, shift, axis):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    namespace = pt.Namespace()
    pt.make_size_param(namespace, "n")
    x = pt.make_placeholder(namespace, "x", shape=("n", "n"), dtype=np.float)

    prog = pt.generate_loopy(
            pt.roll(x, shift=shift, axis=axis),
            target=pt.PyOpenCLTarget(queue))

    x_in = np.array([[1., 2.], [3., 4.]])

    _, (x_out,) = prog(x=x_in)

    assert (x_out == np.roll(x_in, shift=shift, axis=axis)).all()


@pytest.mark.parametrize("axes", (
    (), (0, 1), (1, 0),
    (0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)))
def test_axis_permutation(ctx_factory, axes):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    ndim = len(axes)
    shape = (3, 4, 5)[:ndim]

    from numpy.random import default_rng
    rng = default_rng()

    x_in = rng.random(size=shape)

    namespace = pt.Namespace()
    x = pt.make_data_wrapper(namespace, x_in)
    prog = pt.generate_loopy(
            pt.transpose(x, axes),
            target=pt.PyOpenCLTarget(queue))

    _, (x_out,) = prog()
    assert (x_out == np.transpose(x_in, axes)).all()


def test_transpose(ctx_factory):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    shape = (2, 8)

    from numpy.random import default_rng
    rng = default_rng()
    x_in = rng.random(size=shape)

    namespace = pt.Namespace()
    x = pt.make_data_wrapper(namespace, x_in)
    prog = pt.generate_loopy(x.T, target=pt.PyOpenCLTarget(queue))

    _, (x_out,) = prog()
    assert (x_out == x_in.T).all()


def reverse_args(f):
    def wrapper(*args):
        return f(*reversed(args))
    return wrapper


@pytest.mark.parametrize("which", ("add", "sub", "mul", "truediv"))
@pytest.mark.parametrize("reverse", (False, True))
def test_scalar_array_binary_arith(ctx_factory, which, reverse):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    op = getattr(operator, which)
    if reverse:
        op = reverse_args(op)

    arg = 2

    x_in = np.array([1., 2., 3., 4., 5.])
    namespace = pt.Namespace()
    x = pt.make_data_wrapper(namespace, x_in)
    prog = pt.generate_loopy(op(arg, x), target=pt.PyOpenCLTarget(queue))

    _, (x_out,) = prog()
    assert (x_out == op(arg, x_in)).all()


@pytest.mark.parametrize("which", ("neg", "pos"))
def test_unary_arith(ctx_factory, which):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    op = getattr(operator, which)

    x_in = np.array([1., 2., 3., 4., 5.])
    namespace = pt.Namespace()
    x = pt.make_data_wrapper(namespace, x_in)
    prog = pt.generate_loopy(op(x), target=pt.PyOpenCLTarget(queue))

    _, (x_out,) = prog()
    assert (x_out == op(x_in)).all()


@pytest.mark.parametrize("which", ("add", "sub", "mul", "truediv"))
@pytest.mark.parametrize("reverse", (False, True))
def test_array_array_binary_arith(ctx_factory, which, reverse):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)

    op = getattr(operator, which)
    if reverse:
        op = reverse_args(op)

    x_in = np.array([1., 2., 3., 4., 5.])
    y_in = np.array([6., 7., 8., 9., 10.])
    namespace = pt.Namespace()
    x = pt.make_data_wrapper(namespace, x_in)
    y = pt.make_data_wrapper(namespace, y_in)
    prog = pt.generate_loopy(op(x, y), target=pt.PyOpenCLTarget(queue))

    _, (out,) = prog()
    assert (out == op(x_in, y_in)).all()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        exec(sys.argv[1])
    else:
        from pytest import main
        main([__file__])

# vim: filetype=pyopencl:fdm=marker
