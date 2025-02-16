# -*- coding: utf-8 -*-

from typing import Union, Callable

import jax.numpy as jnp
from brainpy import math as bm, initialize as init
from brainpy._src.dyn.base import NeuGroup
from brainpy._src.initialize import Initializer
from brainpy._src.integrators.sde.generic import sdeint
from brainpy.types import ArrayType, Shape

__all__ = [
  'OUProcess',
]


class OUProcess(NeuGroup):
  r"""The Ornstein–Uhlenbeck process.

  The Ornstein–Uhlenbeck process :math:`x_{t}` is defined by the following
  stochastic differential equation:

  .. math::

     \tau dx_{t}=-\theta \,x_{t}\,dt+\sigma \,dW_{t}

  where :math:`\theta >0` and :math:`\sigma >0` are parameters and :math:`W_{t}`
  denotes the Wiener process.

  Parameters
  ----------
  size: int, sequence of int
    The model size.
  mean: Parameter
    The noise mean value.
  sigma: Parameter
    The noise amplitude.
  tau: Parameter
    The decay time constant.
  method: str
    The numerical integration method for stochastic differential equation.
  name: str
    The model name.
  """

  def __init__(
      self,
      size: Shape,
      mean: Union[float, ArrayType, Initializer, Callable] = 0.,
      sigma: Union[float, ArrayType, Initializer, Callable] = 1.,
      tau: Union[float, ArrayType, Initializer, Callable] = 10.,
      method: str = 'exp_euler',
      keep_size: bool = False,
      mode: bm.Mode = None,
      name: str = None,
  ):
    super(OUProcess, self).__init__(size=size, name=name, keep_size=keep_size, mode=mode)


    # parameters
    self.mean = init.parameter(mean, self.varshape, allow_none=False)
    self.sigma = init.parameter(sigma, self.varshape, allow_none=False)
    self.tau = init.parameter(tau, self.varshape, allow_none=False)

    # variables
    self.x = init.variable_(lambda s: jnp.ones(s) * self.mean, self.varshape, self.mode)

    # integral functions
    self.integral = sdeint(f=self.df, g=self.dg, method=method)

  def reset_state(self, batch_size=None):
    self.x.value = init.variable_(lambda s: jnp.ones(s) * self.mean, self.varshape, batch_size)

  def df(self, x, t):
    return (self.mean - x) / self.tau

  def dg(self, x, t):
    return self.sigma

  def update(self, tdi):
    self.x.value = self.integral(self.x, tdi['t'], tdi['dt'])
