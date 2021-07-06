# -*- coding: utf-8 -*-

from collections import OrderedDict
from brainpy import errors, math
from brainpy.integrators.integrators import Integrator
from brainpy.simulation.brainobjects.base import DynamicSystem
from brainpy.simulation import collector

__all__ = [
  'Container',
]


class Container(DynamicSystem, dict):
  """Container object which is designed to add other DynamicalSystem instances.

  What's different from the other DynamicSystem objects is that Container has
  one more useful function :py:func:`add`. It can be used to add the children
  objects.

  Parameters
  ----------
  steps : function, list of function, tuple of function, dict of (str, function), optional
      The step functions.
  monitors : tuple, list, Monitor, optional
      The monitor object.
  name : str, optional
      The object name.
  show_code : bool
      Whether show the formatted code.
  dynamic_systems : dict of (str, DynamicSystem)
      The instance of DynamicSystem with the format of "key=value".
  """

  def __init__(self, steps=None, monitors=None, name=None, **dynamic_systems):
    # initialize "dict"
    for val in dynamic_systems.values():
      if not isinstance(val, DynamicSystem):
        raise errors.ModelUseError(f'{self.__class__.__name__} receives '
                                   f'instances of DynamicSystem, however, '
                                   f'we got {type(val)}.')
    dict.__init__(self, **dynamic_systems)

    # check 'monitors'
    if monitors is not None:
      raise errors.ModelUseError(f'"monitors" cannot be used in '
                                 f'"brainpy.{self.__class__.__name__}".')

    # initialize "DynamicSystem"
    if steps is None:
      steps = OrderedDict()
      for obj_key, obj in dynamic_systems.items():
        for step_key, step in obj.steps.items():
          steps[f'{obj_key}_{step_key}'] = step
    DynamicSystem.__init__(self,
                           steps=steps,
                           monitors=monitors,
                           name=name)

  def vars(self, prefix=''):
    """Collect all the variables (and their names) contained
    in the list and its children instance of DynamicSystem.

    Parameters
    ----------
    prefix : str
      string to prefix to the variable names.

    Returns
    -------
    gather collector.ArrayCollector
        A collection of all the variables.
    """
    gather = collector.ArrayCollector()
    for k, v in self.items():
      gather.update(v.vars(f'{prefix}{k}.'))
    for k, v in self.__dict__.items():
      if isinstance(v, math.ndarray):
        gather[prefix + k] = v
        gather[f'{self.name}.{k}'] = v
      elif isinstance(v, DynamicSystem):
        gather.update(v.vars(prefix=f'{prefix}{k}.'))
    return gather

  def ints(self, prefix=''):
    gather = collector.Collector()
    for k, v in self.items():
      gather.update(v.ints(prefix=f'{prefix}{k}.'))
    for k, v in self.__dict__.items():
      if isinstance(v, Integrator):
        gather[prefix + k] = v
      elif isinstance(v, DynamicSystem):
        gather.update(v.ints(prefix=f'{prefix}{k}.'))
    return gather

  def nodes(self, prefix=''):
    gather = collector.Collector()
    for k, v in self.items():
      gather[prefix + k] = v
      gather[v.name] = v
      gather.update(v.nodes(f'{prefix}{k}.'))
    for k, v in self.__dict__.items():
      if isinstance(v, DynamicSystem):
        gather[v.name] = v
        gather[prefix + k] = v
        gather.update(v.nodes(f'{prefix}{k}.'))
    return gather

  def __getattr__(self, item):
    if item in self:
      return self[item]
    else:
      return super(Container, self).__getattribute__(item)
