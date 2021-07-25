# -*- coding: utf-8 -*-


import brainpy as bp

bp.math.use_backend('numpy')


class LIF(bp.NeuGroup):
  def __init__(self, size, t_refractory=1., V_rest=0.,
               V_reset=-5., V_th=20., R=1., tau=10., **kwargs):
    # parameters
    self.V_rest = V_rest
    self.V_reset = V_reset
    self.V_th = V_th
    self.R = R
    self.tau = tau
    self.t_refractory = t_refractory

    # variables
    self.V = bp.math.ones(size) * V_reset
    self.input = bp.math.zeros(size)
    self.t_last_spike = bp.math.ones(size) * -1e7
    self.spike = bp.math.zeros(size, dtype=bool)
    self.refractory = bp.math.zeros(size, dtype=bool)

    super(LIF, self).__init__(size=size, **kwargs)

  @bp.odeint
  def int_V(self, V, t, Iext):
    return (- (V - self.V_rest) + self.R * Iext) / self.tau

  @bp.math.control_transform
  def update(self, _t, _i):
    for i in range(self.num):
      if _t - self.t_last_spike[i] <= self.t_refractory:
        self.refractory[i] = True
      else:
        V = self.int_V(self.V[i], _t, self.input[i])
        if V >= self.V_th:
          self.V[i] = self.V_reset
          self.spike[i] = 1.
          self.t_last_spike[i] = _t
          self.refractory[i] = True
        else:
          self.spike[i] = 0.
          self.V[i] = V
          self.refractory[i] = False
      self.input[i] = 0.


class LIF2(bp.NeuGroup):
  def __init__(self, size, t_refractory=1., V_rest=0.,
               V_reset=-5., V_th=20., R=1., tau=10., **kwargs):
    # parameters
    self.V_rest = V_rest
    self.V_reset = V_reset
    self.V_th = V_th
    self.R = R
    self.tau = tau
    self.t_refractory = t_refractory

    # variables
    self.V = bp.math.ones(size) * V_reset
    self.input = bp.math.zeros(size)
    self.t_last_spike = bp.math.ones(size) * -1e7
    self.spike = bp.math.zeros(size, dtype=bool)
    self.refractory = bp.math.zeros(size, dtype=bool)

    super(LIF2, self).__init__(size=size, **kwargs)

  @bp.odeint
  def int_V(self, V, t, Iext):
    return (- (V - self.V_rest) + self.R * Iext) / self.tau

  @bp.math.control_transform
  def update(self, _t, _i):
    for i in range(self.num):
      if _t - self.t_last_spike[i] <= self.t_refractory:
        self.refractory[i] = True
      else:
        V = self.int_V(self.V[i], _t, self.input[i])
        if V >= self.V_th:
          self.V[i] = self.V_reset
          self.spike[i] = 1.
          self.t_last_spike[i] = _t
          self.refractory[i] = True
        else:
          self.spike[i] = 0.
          self.V[i] = V
          self.refractory[i] = False
      self.input[i] = 0.


if __name__ == '__main__':
  group = LIF(100, monitors=['V'])

  group.run(duration=200., inputs=('input', 26.), report=True)
  bp.visualize.line_plot(group.mon.ts, group.mon.V, show=True)

  group.run(duration=(200, 400.), report=True)
  bp.visualize.line_plot(group.mon.ts, group.mon.V, show=True)
