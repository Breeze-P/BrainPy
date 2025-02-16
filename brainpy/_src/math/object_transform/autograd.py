# -*- coding: utf-8 -*-

import inspect
from functools import partial, wraps
from typing import Union, Callable, Dict, Sequence, Any, Optional

import jax
import numpy as np
from jax import linear_util, dtypes, vmap, numpy as jnp, core
from jax._src.api import (_vjp, _jvp)
from jax.api_util import argnums_partial
from jax.errors import UnexpectedTracerError
from jax.interpreters import xla
from jax.tree_util import (tree_flatten, tree_unflatten,
                           tree_map, tree_transpose,
                           tree_structure)
from jax.util import safe_map

from brainpy import errors, tools, check
from brainpy._src.math.ndarray import Array, Variable, add_context, del_context
from brainpy._src.math.object_transform.abstract import ObjectTransform
from brainpy._src.math.object_transform.base import BrainPyObject

__all__ = [
  'grad',  # gradient of scalar function
  'vector_grad',  # gradient of vector/matrix/...
  'jacobian', 'jacrev', 'jacfwd',  # gradient of jacobian
  'hessian',  # gradient of hessian
]


class GradientTransform(ObjectTransform):
  """Object-oriented Automatic Differentiation Transformation in BrainPy.
  """

  def __init__(
      self,
      target: Callable,
      transform: Callable,

      # variables and nodes
      grad_vars: Any,
      dyn_vars: Dict[str, Variable],
      child_objs: Dict[str, Variable],

      # gradient setting
      argnums: Optional[Union[int, Sequence[int]]],
      return_value: bool,
      has_aux: bool,
      transform_setting: Optional[Dict[str, Any]] = None,

      # other
      name: str = None,
  ):
    super().__init__(name=name)

    # gradient variables
    self._grad_vars, self._grad_tree = tree_flatten(grad_vars, is_leaf=lambda a: isinstance(a, Array))

    # register variables and nodes
    self.register_implicit_vars(dyn_vars, self._grad_vars)
    self.register_implicit_nodes(child_objs)

    # parameters
    if argnums is None and len(self._grad_vars) == 0:
      argnums = 0
    if argnums is None:
      assert len(self._grad_vars) > 0
      _argnums = 0
    elif isinstance(argnums, int):
      _argnums = (0, argnums + 2) if len(self._grad_vars) > 0 else (argnums + 2)
    else:
      _argnums = check.is_sequence(argnums, elem_type=int, allow_none=False)
      _argnums = tuple(a + 2 for a in _argnums)
      if len(self._grad_vars) > 0:
        _argnums = (0,) + _argnums
    self._nonvar_argnums = argnums
    self.return_value = return_value
    self.has_aux = has_aux

    # target and transform
    self.target = target
    self.transform = transform
    self._dyn_vars = tuple((self.vars().unique() - self._grad_vars).values())

    # settings
    transform_setting = dict() if transform_setting is None else transform_setting
    if self.has_aux:
      self._call = transform(self._f_grad_with_aux_to_transform,
                             argnums=_argnums,
                             has_aux=True,
                             **transform_setting)
    else:
      self._call = transform(self._f_grad_without_aux_to_transform,
                             argnums=_argnums,
                             has_aux=True,
                             **transform_setting)

  def _f_grad_with_aux_to_transform(self, grad_values, dyn_values, *args, **kwargs):
    for v, d in zip(self._dyn_vars, dyn_values): v._value = d
    for v, d in zip(self._grad_vars, grad_values): v._value = d
    # Users should return the auxiliary data like::
    # >>> # 1. example of return one data
    # >>> return scalar_loss, data
    # >>> # 2. example of return multiple data
    # >>> return scalar_loss, (data1, data2, ...)
    outputs = self.target(*args, **kwargs)
    # outputs: [0] is the value for gradient,
    #          [1] is other values for return
    output0 = tree_map(lambda a: (a.value if isinstance(a, Array) else a), outputs[0])
    return output0, (outputs, [v.value for v in self._grad_vars], [v.value for v in self._dyn_vars])

  def _f_grad_without_aux_to_transform(self, grad_values, dyn_values, *args, **kwargs):
    for v, d in zip(self._dyn_vars, dyn_values): v._value = d
    for v, d in zip(self._grad_vars, grad_values): v._value = d
    # Users should return the scalar value like this::
    # >>> return scalar_loss
    output = self.target(*args, **kwargs)
    output0 = tree_map(lambda a: (a.value if isinstance(a, Array) else a), output)
    return output0, (output, [v.value for v in self._grad_vars], [v.value for v in self._dyn_vars])

  def __repr__(self):
    name = self.__class__.__name__
    f = tools.repr_object(self.target)
    f = tools.repr_context(f, " " * (len(name) + 6))
    format_ref = (f'{name}(target={f}, \n' +
                  f'{" " * len(name)} num_of_grad_vars={len(self._grad_vars)}, \n'
                  f'{" " * len(name)} num_of_dyn_vars={len(self._dyn_vars)})')
    return format_ref

  def __call__(self, *args, **kwargs):
    # old_grad_vs = [v.value for v in self._grad_vars]
    # old_dyn_vs = [v.value for v in self._dyn_vars]
    try:
      add_context(self.name)
      grads, (outputs, new_grad_vs, new_dyn_vs) = self._call(
        [v.value for v in self._grad_vars],
        [v.value for v in self._dyn_vars],
        *args,
        **kwargs
      )
      del_context(self._name)
    except UnexpectedTracerError as e:
      del_context(self._name)
      # for v, d in zip(self._grad_vars, old_grad_vs): v._value = d
      # for v, d in zip(self._dyn_vars, old_dyn_vs): v._value = d
      raise errors.JaxTracerError() from e
    except Exception as e:
      del_context(self._name)
      # for v, d in zip(self._grad_vars, old_grad_vs): v._value = d
      # for v, d in zip(self._dyn_vars, old_dyn_vs): v._value = d
      raise e
    else:
      for v, d in zip(self._grad_vars, new_grad_vs): v._value = d
      for v, d in zip(self._dyn_vars, new_dyn_vs): v._value = d

    # check returned grads
    if len(self._grad_vars) > 0:
      if self._nonvar_argnums is None:
        grads = self._grad_tree.unflatten(grads)
      else:
        var_grads = self._grad_tree.unflatten(grads[0])
        arg_grads = grads[1] if isinstance(self._nonvar_argnums, int) else grads[1:]
        grads = (var_grads, arg_grads)

    # check returned value
    if self.return_value:
      # check aux
      if self.has_aux:
        return grads, outputs[0], outputs[1]
      else:
        return grads, outputs
    else:
      # check aux
      if self.has_aux:
        return grads, outputs[1]
      else:
        return grads


def _make_grad(func: Callable,
               grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
               dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
               child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
               argnums: Optional[Union[int, Sequence[int]]] = None,
               holomorphic: Optional[bool] = False,
               allow_int: Optional[bool] = False,
               reduce_axes: Optional[Sequence[str]] = (),
               has_aux: Optional[bool] = None,
               return_value: Optional[bool] = False, ):
  child_objs = check.is_all_objs(child_objs, out_as='dict')
  dyn_vars = check.is_all_vars(dyn_vars, out_as='dict')

  return GradientTransform(target=func,
                           transform=jax.grad,
                           grad_vars=grad_vars,
                           dyn_vars=dyn_vars,
                           child_objs=child_objs,
                           argnums=argnums,
                           return_value=return_value,
                           has_aux=False if has_aux is None else has_aux,
                           transform_setting=dict(holomorphic=holomorphic,
                                                  allow_int=allow_int,
                                                  reduce_axes=reduce_axes))


def grad(
    func: Callable = None,
    grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
    argnums: Optional[Union[int, Sequence[int]]] = None,
    holomorphic: Optional[bool] = False,
    allow_int: Optional[bool] = False,
    reduce_axes: Optional[Sequence[str]] = (),
    has_aux: Optional[bool] = None,
    return_value: Optional[bool] = False,
) -> GradientTransform:
  """Automatic gradient computation for functions or class objects.

  This gradient function only support scalar return. It creates a function
  which evaluates the gradient of ``func``.

  It's worthy to note that the returns are different for different argument settings (where ``arg_grads`` refers
  to the gradients of "argnums", and ``var_grads`` refers to the gradients of "grad_vars").

  1. When "grad_vars" is None
    - "has_aux=False" + "return_value=False" => ``arg_grads``.
    - "has_aux=True" + "return_value=False" => ``(arg_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(arg_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(arg_grads, loss_value, aux_data)``.
  2. When "grad_vars" is not None and "argnums" is None
    - "has_aux=False" + "return_value=False" => ``var_grads``.
    - "has_aux=True" + "return_value=False" => ``(var_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(var_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(var_grads, loss_value, aux_data)``.
  3. When "grad_vars" is not None and "argnums" is not None
    - "has_aux=False" + "return_value=False" => ``(var_grads, arg_grads)``.
    - "has_aux=True" + "return_value=False" => ``((var_grads, arg_grads), aux_data)``.
    - "has_aux=False" + "return_value=True" => ``((var_grads, arg_grads), loss_value)``.
    - "has_aux=True" + "return_value=True" => ``((var_grads, arg_grads), loss_value, aux_data)``.

  Let's see some examples below.

  Before start, let's figure out what should be provided as ``grad_vars``?
  And, what should be labeled in ``argnums``?
  Take the following codes as example:

  >>> import brainpy as bp
  >>> import brainpy.math as bm
  >>>
  >>> class Example(bp.BrainPyObject):
  >>>   def __init__(self):
  >>>     super(Example, self).__init__()
  >>>     self.x = bm.TrainVar(bm.zeros(1))
  >>>     self.y = bm.random.rand(10)
  >>>   def __call__(self, z, v):
  >>>     t1 = self.x * self.y.sum()
  >>>     t2 = bm.tanh(z * v + t1)
  >>>     return t2.mean()
  >>>
  >>> # This code is equivalent to the following function:
  >>>
  >>> x = bm.TrainVar(bm.zeros(1))
  >>> y = bm.random.rand(10)
  >>> def f(z, v):
  >>>   t1 = x * y.sum()
  >>>   t2 = bm.tanh(z * v + t1)
  >>>   return t2.mean()

  Generally speaking, all gradient variables which not provided in arguments should be
  labeled as ``grad_vars``, while all gradient variables provided in the function arguments
  should be declared in ``argnums``.
  In above codes, we try to take gradients of ``self.x`` and arguments ``z`` and ``v``, we should
  call ``brainpy.math.grad`` as:

  >>> f = Example()
  >>> f_grad = bm.grad(f, grad_vars=f.x, argnums=(0, 1))


  Examples
  --------

  Grad for a pure function:

  >>> import brainpy as bp
  >>> grad_tanh = grad(bp.math.tanh)
  >>> print(grad_tanh(0.2))
  0.961043

  Parameters
  ----------
  func : callable, function, BrainPyObject
    Function to be differentiated. Its arguments at positions specified by
    ``argnums`` should be arrays, scalars, or standard Python containers.
    Argument arrays in the positions specified by ``argnums`` must be of
    inexact (i.e., floating-point or complex) type. It should return a scalar
    (which includes arrays with shape ``()`` but not arrays with shape ``(1,)`` etc.)
  dyn_vars : optional, ArrayType, sequence of ArrayType, dict
    The dynamically changed variables used in ``func``.
  child_objs: optional, BrainPyObject, sequnce, dict

    .. versionadded:: 2.3.1
  grad_vars : optional, ArrayType, sequence of ArrayType, dict
    The variables in ``func`` to take their gradients.
  argnums : optional, integer or sequence of integers
    Specifies which positional argument(s) to differentiate with respect to (default 0).
  has_aux: optional, bool
    Indicates whether ``fun`` returns a pair where the
    first element is considered the output of the mathematical function to be
    differentiated and the second element is auxiliary data. Default False.
  return_value : bool
    Whether return the loss value.
  holomorphic: optional, bool
    Indicates whether ``fun`` is promised to be
    holomorphic. If True, inputs and outputs must be complex. Default False.
  allow_int: optional, bool
    Whether to allow differentiating with
    respect to integer valued inputs. The gradient of an integer input will
    have a trivial vector-space dtype (float0). Default False.
  reduce_axes: optional, tuple of int
    tuple of axis names. If an axis is listed here, and
    ``fun`` implicitly broadcasts a value over that axis, the backward pass
    will perform a ``psum`` of the corresponding gradient. Otherwise, the
    gradient will be per-example over named axes. For example, if ``'batch'``
    is a named batch axis, ``grad(f, reduce_axes=('batch',))`` will create a
    function that computes the total gradient while ``grad(f)`` will create
    one that computes the per-example gradient.

  Returns
  -------
  func : GradientTransform
    A function with the same arguments as ``fun``, that evaluates the gradient
    of ``fun``. If ``argnums`` is an integer then the gradient has the same
    shape and type as the positional argument indicated by that integer. If
    argnums is a tuple of integers, the gradient is a tuple of values with the
    same shapes and types as the corresponding arguments. If ``has_aux`` is True
    then a pair of (gradient, auxiliary_data) is returned.
  """
  if func is None:
    return lambda f: _make_grad(f,
                                grad_vars=grad_vars,
                                dyn_vars=dyn_vars,
                                child_objs=child_objs,
                                argnums=argnums,
                                holomorphic=holomorphic,
                                allow_int=allow_int,
                                reduce_axes=reduce_axes,
                                has_aux=has_aux,
                                return_value=return_value)
  else:
    return _make_grad(func=func,
                      grad_vars=grad_vars,
                      dyn_vars=dyn_vars,
                      child_objs=child_objs,
                      argnums=argnums,
                      holomorphic=holomorphic,
                      allow_int=allow_int,
                      reduce_axes=reduce_axes,
                      has_aux=has_aux,
                      return_value=return_value)


def _unravel_array_into_pytree(pytree, axis, arr, is_leaf=None):
  leaves, treedef = tree_flatten(pytree, is_leaf=is_leaf)
  axis = axis % arr.ndim
  shapes = [arr.shape[:axis] + np.shape(l) + arr.shape[axis + 1:] for l in leaves]
  parts = arr.split(np.cumsum(safe_map(np.size, leaves[:-1])), axis)
  reshaped_parts = [x.reshape(shape) for x, shape in zip(parts, shapes)]
  return tree_unflatten(treedef, reshaped_parts, )


def _std_basis(pytree):
  leaves, _ = tree_flatten(pytree)
  ndim = sum(safe_map(np.size, leaves))
  dtype = dtypes.result_type(*leaves)
  flat_basis = jax.numpy.eye(ndim, dtype=dtype)
  return _unravel_array_into_pytree(pytree, 1, flat_basis)


_isleaf = lambda x: isinstance(x, Array)


def _jacrev(fun, argnums=0, holomorphic=False, allow_int=False, has_aux=False, return_value=False):
  _check_callable(fun)

  @wraps(fun)
  def jacfun(*args, **kwargs):
    f = linear_util.wrap_init(fun, kwargs)
    f_partial, dyn_args = argnums_partial(f, argnums, args, require_static_args_hashable=False)
    tree_map(partial(_check_input_dtype_jacrev, holomorphic, allow_int), dyn_args)
    if has_aux:
      y, pullback, aux = _vjp(f_partial, *dyn_args, has_aux=True)
    else:
      y, pullback = _vjp(f_partial, *dyn_args, has_aux=False)
    tree_map(partial(_check_output_dtype_jacrev, holomorphic), y)
    jac = vmap(pullback)(_std_basis(y))
    jac = jac[0] if isinstance(argnums, int) else jac
    example_args = dyn_args[0] if isinstance(argnums, int) else dyn_args
    jac_tree = tree_map(partial(_unravel_array_into_pytree, y, 0, is_leaf=_isleaf), jac, is_leaf=_isleaf)
    jac = tree_transpose(tree_structure(example_args), tree_flatten(y, is_leaf=_isleaf)[1], jac_tree)
    if return_value:
      return (jac, y, aux) if has_aux else (jac, y)
    else:
      return (jac, aux) if has_aux else jac

  return jacfun


def jacrev(
    func: Callable,
    grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
    argnums: Optional[Union[int, Sequence[int]]] = None,
    has_aux: Optional[bool] = None,
    return_value: bool = False,
    holomorphic: bool = False,
    allow_int: bool = False,
) -> ObjectTransform:
  """Extending automatic Jacobian (reverse-mode) of ``func`` to classes.

  This function extends the JAX official ``jacrev`` to make automatic jacobian
  computation on functions and class functions. Moreover, it supports returning
  value ("return_value") and returning auxiliary data ("has_aux").

  Same as `brainpy.math.grad <./brainpy.math.autograd.grad.html>`_, the returns are
  different for different argument settings in ``brainpy.math.jacrev``.

  1. When "grad_vars" is None
    - "has_aux=False" + "return_value=False" => ``arg_grads``.
    - "has_aux=True" + "return_value=False" => ``(arg_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(arg_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(arg_grads, loss_value, aux_data)``.
  2. When "grad_vars" is not None and "argnums" is None
    - "has_aux=False" + "return_value=False" => ``var_grads``.
    - "has_aux=True" + "return_value=False" => ``(var_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(var_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(var_grads, loss_value, aux_data)``.
  3. When "grad_vars" is not None and "argnums" is not None
    - "has_aux=False" + "return_value=False" => ``(var_grads, arg_grads)``.
    - "has_aux=True" + "return_value=False" => ``((var_grads, arg_grads), aux_data)``.
    - "has_aux=False" + "return_value=True" => ``((var_grads, arg_grads), loss_value)``.
    - "has_aux=True" + "return_value=True" => ``((var_grads, arg_grads), loss_value, aux_data)``.


  Parameters
  ----------
  func: Function whose Jacobian is to be computed.
  dyn_vars : optional, ArrayType, sequence of ArrayType, dict
    The dynamically changed variables used in ``func``.
  grad_vars : optional, ArrayType, sequence of ArrayType, dict
    The variables in ``func`` to take their gradients.
  child_objs: optional, BrainPyObject, sequence, dict

    .. versionadded:: 2.3.1
  has_aux: optional, bool
    Indicates whether ``fun`` returns a pair where the
    first element is considered the output of the mathematical function to be
    differentiated and the second element is auxiliary data. Default False.
  return_value : bool
    Whether return the loss value.
  argnums: Optional, integer or sequence of integers.
    Specifies which
    positional argument(s) to differentiate with respect to (default ``0``).
  holomorphic: Optional, bool.
    Indicates whether ``fun`` is promised to be
    holomorphic. Default False.
  allow_int: Optional, bool.
    Whether to allow differentiating with
    respect to integer valued inputs. The gradient of an integer input will
    have a trivial vector-space dtype (float0). Default False.

  Returns
  -------
  fun: GradientTransform
    The transformed object.
  """
  child_objs = check.is_all_objs(child_objs, out_as='dict')
  dyn_vars = check.is_all_vars(dyn_vars, out_as='dict')

  return GradientTransform(target=func,
                           transform=_jacrev,
                           grad_vars=grad_vars,
                           dyn_vars=dyn_vars,
                           child_objs=child_objs,
                           argnums=argnums,
                           return_value=return_value,
                           has_aux=False if has_aux is None else has_aux,
                           transform_setting=dict(holomorphic=holomorphic,
                                                  allow_int=allow_int))


jacobian = jacrev


def _jacfwd(fun, argnums=0, holomorphic=False, has_aux=False, return_value=False):
  _check_callable(fun)
  if has_aux and jax.__version__ < '0.2.28':
    raise NotImplementedError(f'"has_aux" only supported in jax>=0.2.28, but we detect '
                              f'the current jax version is {jax.__version__}')

  @wraps(fun)
  def jacfun(*args, **kwargs):
    f = linear_util.wrap_init(fun, kwargs)
    f_partial, dyn_args = argnums_partial(f, argnums, args, require_static_args_hashable=False)
    tree_map(partial(_check_input_dtype_jacfwd, holomorphic), dyn_args)
    if has_aux:
      pushfwd = partial(_jvp, f_partial, dyn_args, has_aux=True)
      y, jac, aux = vmap(pushfwd, out_axes=(None, -1, None))(_std_basis(dyn_args))
    else:
      pushfwd = partial(_jvp, f_partial, dyn_args)
      y, jac = vmap(pushfwd, out_axes=(None, -1))(_std_basis(dyn_args))
    tree_map(partial(_check_output_dtype_jacfwd, holomorphic), y)
    example_args = dyn_args[0] if isinstance(argnums, int) else dyn_args
    jac = tree_map(partial(_unravel_array_into_pytree, example_args, -1, is_leaf=_isleaf), jac, is_leaf=_isleaf)
    if return_value:
      return (jac, y, aux) if has_aux else (jac, y)
    else:
      return (jac, aux) if has_aux else jac

  return jacfun


def jacfwd(
    func: Callable,
    grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
    argnums: Optional[Union[int, Sequence[int]]] = None,
    has_aux: Optional[bool] = None,
    return_value: bool = False,
    holomorphic: bool = False,
) -> ObjectTransform:
  """Extending automatic Jacobian (forward-mode) of ``func`` to classes.

  This function extends the JAX official ``jacfwd`` to make automatic jacobian
  computation on functions and class functions. Moreover, it supports returning
  value ("return_value") and returning auxiliary data ("has_aux").

  Same as `brainpy.math.grad <./brainpy.math.autograd.grad.html>`_, the returns are
  different for different argument settings in ``brainpy.math.jacfwd``.

  1. When "grad_vars" is None
    - "has_aux=False" + "return_value=False" => ``arg_grads``.
    - "has_aux=True" + "return_value=False" => ``(arg_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(arg_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(arg_grads, loss_value, aux_data)``.
  2. When "grad_vars" is not None and "argnums" is None
    - "has_aux=False" + "return_value=False" => ``var_grads``.
    - "has_aux=True" + "return_value=False" => ``(var_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(var_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(var_grads, loss_value, aux_data)``.
  3. When "grad_vars" is not None and "argnums" is not None
    - "has_aux=False" + "return_value=False" => ``(var_grads, arg_grads)``.
    - "has_aux=True" + "return_value=False" => ``((var_grads, arg_grads), aux_data)``.
    - "has_aux=False" + "return_value=True" => ``((var_grads, arg_grads), loss_value)``.
    - "has_aux=True" + "return_value=True" => ``((var_grads, arg_grads), loss_value, aux_data)``.

  Parameters
  ----------
  func: Function whose Jacobian is to be computed.
  dyn_vars : optional, ArrayType, sequence of ArrayType, dict
    The dynamically changed variables used in ``func``.
  grad_vars : optional, ArrayType, sequence of ArrayType, dict
    The variables in ``func`` to take their gradients.
  child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,

    .. versionadded:: 2.3.1
  has_aux: optional, bool
    Indicates whether ``fun`` returns a pair where the
    first element is considered the output of the mathematical function to be
    differentiated and the second element is auxiliary data. Default False.
  return_value : bool
    Whether return the loss value.
  argnums: Optional, integer or sequence of integers. Specifies which
    positional argument(s) to differentiate with respect to (default ``0``).
  holomorphic: Optional, bool. Indicates whether ``fun`` is promised to be
    holomorphic. Default False.

  Returns
  -------
  obj: GradientTransform
    The transformed object.
  """
  child_objs = check.is_all_objs(child_objs, out_as='dict')
  dyn_vars = check.is_all_vars(dyn_vars, out_as='dict')

  return GradientTransform(target=func,
                           transform=_jacfwd,
                           grad_vars=grad_vars,
                           dyn_vars=dyn_vars,
                           child_objs=child_objs,
                           argnums=argnums,
                           return_value=return_value,
                           has_aux=False if has_aux is None else has_aux,
                           transform_setting=dict(holomorphic=holomorphic))


def hessian(
    func: Callable,
    grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
    argnums: Optional[Union[int, Sequence[int]]] = None,
    return_value: bool = False,
    holomorphic=False,
) -> ObjectTransform:
  """Hessian of ``func`` as a dense array.

  Parameters
  ----------
  func : callable, function
    Function whose Hessian is to be computed.  Its arguments at positions
    specified by ``argnums`` should be arrays, scalars, or standard Python
    containers thereof. It should return arrays, scalars, or standard Python
    containers thereof.
  dyn_vars : optional, ArrayCollector, sequence of ArrayType
    The dynamical changed variables.
  child_objs: optional, BrainPyObject, sequnce, dict

    .. versionadded:: 2.3.1
  grad_vars : optional, ArrayCollector, sequence of ArrayType
    The variables required to compute their gradients.
  argnums: Optional, integer or sequence of integers
    Specifies which positional argument(s) to differentiate with respect to (default ``0``).
  holomorphic : bool
    Indicates whether ``fun`` is promised to be holomorphic. Default False.
  return_value : bool
    Whether return the hessian values.

  Returns
  -------
  obj: ObjectTransform
    The transformed object.
  """
  child_objs = check.is_all_objs(child_objs, out_as='dict')
  dyn_vars = check.is_all_vars(dyn_vars, out_as='dict')

  return jacfwd(jacrev(func,
                       dyn_vars=dyn_vars,
                       child_objs=child_objs,
                       grad_vars=grad_vars,
                       argnums=argnums,
                       holomorphic=holomorphic),
                dyn_vars=dyn_vars,
                child_objs=child_objs,
                grad_vars=grad_vars,
                argnums=argnums,
                holomorphic=holomorphic,
                return_value=return_value)


def _vector_grad(func, argnums=0, return_value=False, has_aux=False):
  _check_callable(func)

  @wraps(func)
  def grad_fun(*args, **kwargs):
    f = linear_util.wrap_init(func, kwargs)
    f_partial, dyn_args = argnums_partial(f, argnums, args, require_static_args_hashable=False)
    if has_aux:
      y, vjp_fn, aux = _vjp(f_partial, *dyn_args, has_aux=True)
    else:
      y, vjp_fn = _vjp(f_partial, *dyn_args, has_aux=False)
    leaves, tree = tree_flatten(y)
    tangents = tree_unflatten(tree, [jnp.ones_like(l) for l in leaves])
    grads = vjp_fn(tangents)
    if isinstance(argnums, int):
      grads = grads[0]
    if has_aux:
      return (grads, y, aux) if return_value else (grads, aux)
    else:
      return (grads, y) if return_value else grads

  return grad_fun


def vector_grad(
    func: Callable,
    grad_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    dyn_vars: Optional[Union[Variable, Sequence[Variable], Dict[str, Variable]]] = None,
    child_objs: Optional[Union[BrainPyObject, Sequence[BrainPyObject], Dict[str, BrainPyObject]]] = None,
    argnums: Optional[Union[int, Sequence[int]]] = None,
    return_value: bool = False,
    has_aux: Optional[bool] = None,
) -> ObjectTransform:
  """Take vector-valued gradients for function ``func``.

  Same as `brainpy.math.grad <./brainpy.math.autograd.grad.html>`_,
  `brainpy.math.jacrev <./brainpy.math.autograd.jacrev.html>`_ and
  `brainpy.math.jacfwd <./brainpy.math.autograd.jacfwd.html>`_,
  the returns in this function are different for different argument settings.

  1. When "grad_vars" is None
    - "has_aux=False" + "return_value=False" => ``arg_grads``.
    - "has_aux=True" + "return_value=False" => ``(arg_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(arg_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(arg_grads, loss_value, aux_data)``.
  2. When "grad_vars" is not None and "argnums" is None
    - "has_aux=False" + "return_value=False" => ``var_grads``.
    - "has_aux=True" + "return_value=False" => ``(var_grads, aux_data)``.
    - "has_aux=False" + "return_value=True" => ``(var_grads, loss_value)``.
    - "has_aux=True" + "return_value=True" => ``(var_grads, loss_value, aux_data)``.
  3. When "grad_vars" is not None and "argnums" is not None
    - "has_aux=False" + "return_value=False" => ``(var_grads, arg_grads)``.
    - "has_aux=True" + "return_value=False" => ``((var_grads, arg_grads), aux_data)``.
    - "has_aux=False" + "return_value=True" => ``((var_grads, arg_grads), loss_value)``.
    - "has_aux=True" + "return_value=True" => ``((var_grads, arg_grads), loss_value, aux_data)``.


  Parameters
  ----------
  func: Callable
    Function whose gradient is to be computed.
  dyn_vars : optional, ArrayType, sequence of ArrayType, dict
    The dynamically changed variables used in ``func``.
  child_objs: optional, BrainPyObject, sequnce, dict

    .. versionadded:: 2.3.1
  grad_vars : optional, ArrayType, sequence of ArrayType, dict
    The variables in ``func`` to take their gradients.
  has_aux: optional, bool
    Indicates whether ``fun`` returns a pair where the
    first element is considered the output of the mathematical function to be
    differentiated and the second element is auxiliary data. Default False.
  return_value : bool
    Whether return the loss value.
  argnums: Optional, integer or sequence of integers. Specifies which
    positional argument(s) to differentiate with respect to (default ``0``).

  Returns
  -------
  func : GradientTransform
    The vector gradient function.
  """
  child_objs = check.is_all_objs(child_objs, out_as='dict')
  dyn_vars = check.is_all_vars(dyn_vars, out_as='dict')

  return GradientTransform(target=func,
                           transform=_vector_grad,
                           grad_vars=grad_vars,
                           dyn_vars=dyn_vars,
                           child_objs=child_objs,
                           argnums=argnums,
                           return_value=return_value,
                           has_aux=False if has_aux is None else has_aux)


def _check_callable(fun):
  # In Python 3.10+, the only thing stopping us from supporting staticmethods
  # is that we can't take weak references to them, which the C++ JIT requires.
  if isinstance(fun, staticmethod):
    raise TypeError(f"staticmethod arguments are not supported, got {fun}")
  if not callable(fun):
    raise TypeError(f"Expected a callable value, got {fun}")
  if _isgeneratorfunction(fun):
    raise TypeError(f"Expected a function, got a generator function: {fun}")


def _isgeneratorfunction(fun):
  # re-implemented here because of https://bugs.python.org/issue33261
  while inspect.ismethod(fun):
    fun = fun.__func__
  while isinstance(fun, partial):
    fun = fun.func
  return inspect.isfunction(fun) and bool(fun.__code__.co_flags & inspect.CO_GENERATOR)


def _check_arg(arg):
  if not (isinstance(arg, core.Tracer) or _valid_jaxtype(arg)):
    raise TypeError(f"Argument '{arg}' of type {type(arg)} is not a valid JAX type.")


def _valid_jaxtype(arg):
  try:
    xla.abstractify(arg)  # faster than core.get_aval
  except TypeError:
    return core.valid_jaxtype(arg)
  else:
    return True


def _check_output_dtype_revderiv(name, holomorphic, x):
  aval = core.get_aval(x)
  if core.is_opaque_dtype(aval.dtype):
    raise TypeError(
      f"{name} with output element type {aval.dtype.name}")
  if holomorphic:
    if not dtypes.issubdtype(aval.dtype, np.complexfloating):
      raise TypeError(f"{name} with holomorphic=True requires outputs with complex dtype, "
                      f"but got {aval.dtype.name}.")
  elif dtypes.issubdtype(aval.dtype, np.complexfloating):
    raise TypeError(f"{name} requires real-valued outputs (output dtype that is "
                    f"a sub-dtype of np.floating), but got {aval.dtype.name}. "
                    "For holomorphic differentiation, pass holomorphic=True. "
                    "For differentiation of non-holomorphic functions involving complex "
                    "outputs, use jax.vjp directly.")
  elif not dtypes.issubdtype(aval.dtype, np.floating):
    raise TypeError(f"{name} requires real-valued outputs (output dtype that is "
                    f"a sub-dtype of np.floating), but got {aval.dtype.name}. "
                    "For differentiation of functions with integer outputs, use "
                    "jax.vjp directly.")


def _check_input_dtype_revderiv(name, holomorphic, allow_int, x):
  _check_arg(x)
  aval = core.get_aval(x)
  if core.is_opaque_dtype(aval.dtype):
    raise TypeError(
      f"{name} with input element type {aval.dtype.name}")
  if holomorphic:
    if not dtypes.issubdtype(aval.dtype, np.complexfloating):
      raise TypeError(f"{name} with holomorphic=True requires inputs with complex dtype, "
                      f"but got {aval.dtype.name}.")
  if (dtypes.issubdtype(aval.dtype, np.integer) or
      dtypes.issubdtype(aval.dtype, np.bool_)):
    if not allow_int:
      raise TypeError(f"{name} requires real- or complex-valued inputs (input dtype "
                      f"that is a sub-dtype of np.inexact), but got {aval.dtype.name}. "
                      "If you want to use Boolean- or integer-valued inputs, use vjp "
                      "or set allow_int to True.")
  elif not dtypes.issubdtype(aval.dtype, np.inexact):
    raise TypeError(f"{name} requires numerical-valued inputs (input dtype that is a "
                    f"sub-dtype of np.bool_ or np.number), but got {aval.dtype.name}.")


_check_output_dtype_jacrev = partial(_check_output_dtype_revderiv, "jacrev")
_check_input_dtype_jacrev = partial(_check_input_dtype_revderiv, "jacrev")


def _check_output_dtype_jacfwd(holomorphic, x):
  aval = core.get_aval(x)
  if holomorphic:
    if not dtypes.issubdtype(aval.dtype, np.complexfloating):
      raise TypeError("jacfwd with holomorphic=True requires outputs with complex dtype, "
                      f"but got {aval.dtype.name}.")


def _check_input_dtype_jacfwd(holomorphic: bool, x: Any) -> None:
  _check_arg(x)
  aval = core.get_aval(x)
  if core.is_opaque_dtype(aval.dtype):
    raise TypeError(f"jacfwd with input element type {aval.dtype.name}")
  if holomorphic:
    if not dtypes.issubdtype(aval.dtype, np.complexfloating):
      raise TypeError("jacfwd with holomorphic=True requires inputs with complex "
                      f"dtype, but got {aval.dtype.name}.")
  elif not dtypes.issubdtype(aval.dtype, np.floating):
    raise TypeError("jacfwd requires real-valued inputs (input dtype that is "
                    f"a sub-dtype of np.floating), but got {aval.dtype.name}. "
                    "For holomorphic differentiation, pass holomorphic=True. "
                    "For differentiation of non-holomorphic functions involving "
                    "complex inputs or integer inputs, use jax.jvp directly.")
