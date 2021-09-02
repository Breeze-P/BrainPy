# -*- coding: utf-8 -*-

from typing import cast

import numpy as np

__all__ = [
  'ndarray',
  'Variable',
  'TrainVar',
  'Parameter',
]

ndarray = np.ndarray


class Variable(np.ndarray):
  def __new__(cls, value, type='', replicate=None):
    value = np.asarray(value)
    obj = value.view(cls)
    obj.value = value
    obj.type = type
    obj.replicate = replicate
    return obj

  def __array_finalize__(self, obj):
    if obj is None: return
    self.replicate = getattr(obj, 'replicate', None)
    self.value = getattr(obj, 'value', None)
    self.type = getattr(obj, 'type', None)

  def issametype(self, other):
    if self.type:
      return not isinstance(other, Variable)
    else:
      if not isinstance(other, Variable):
        return False
      else:
        return other.type == self.type


class TrainVar(Variable):
  __slots__ = ()

  def __new__(cls, value, replicate=None):
    return cast(TrainVar, super().__new__(cls, value=value, type='train', replicate=replicate))


class Parameter(Variable):
  __slots__ = ()

  def __new__(cls, value, replicate=None):
    return cast(TrainVar, super().__new__(cls, value=value, type='param', replicate=replicate))
