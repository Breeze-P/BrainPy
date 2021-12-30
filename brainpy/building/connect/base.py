# -*- coding: utf-8 -*-

import abc
import logging
from typing import Union, List, Tuple

import numpy as np

from brainpy import tools, math
from brainpy.errors import ConnectorError

logger = logging.getLogger('brainpy.simulation.connect')

__all__ = [
  # the connection types
  'CONN_MAT', 'WEIGHT_MAT',
  'PRE_IDS', 'POST_IDS',
  'PRE2POST', 'POST2PRE',
  'PRE2SYN', 'POST2SYN',
  'SUPPORTED_SYN_STRUCTURE',

  # the connection dtypes
  'set_default_dtype', 'MAT_DTYPE', 'IDX_DTYPE',

  # base class
  'Connector', 'TwoEndConnector', 'OneEndConnector',

  # methods
  'csr2csc', 'csr2mat', 'mat2csr', 'ij2csr'
]

CONN_MAT = 'conn_mat'
WEIGHT_MAT = 'weight_mat'
PRE_IDS = 'pre_ids'
POST_IDS = 'post_ids'
PRE2POST = 'pre2post'
POST2PRE = 'post2pre'
PRE2SYN = 'pre2syn'
POST2SYN = 'post2syn'
PRE_SLICE = 'pre_slice'
POST_SLICE = 'post_slice'

SUPPORTED_SYN_STRUCTURE = [CONN_MAT, WEIGHT_MAT,
                           PRE_IDS, POST_IDS,
                           PRE2POST, POST2PRE,
                           PRE2SYN, POST2SYN,
                           PRE_SLICE, POST_SLICE]

MAT_DTYPE = np.bool_
IDX_DTYPE = np.uint32


def set_default_dtype(mat_dtype=None, idx_dtype=None):
  """Set the default dtype.

  Use this method, you can set the default dtype for connetion matrix and
  connection index.

  For examples:

  >>> import numpy as np
  >>> import brainpy as bp
  >>>
  >>> conn = bp.conn.GridFour()(4, 4)
  >>> conn.require('conn_mat')
  JaxArray(DeviceArray([[False,  True, False, False],
                        [ True, False,  True, False],
                        [False,  True, False,  True],
                        [False, False,  True, False]], dtype=bool))
  >>> bp.conn.set_default_dtype(mat_dtype=np.float32)
  >>> conn = bp.conn.GridFour()(4, 4)
  >>> conn.require('conn_mat')
  JaxArray(DeviceArray([[0., 1., 0., 0.],
                        [1., 0., 1., 0.],
                        [0., 1., 0., 1.],
                        [0., 0., 1., 0.]], dtype=float32))

  Parameters
  ----------
  mat_dtype : type
    The default dtype for connection matrix.
  idx_dtype : type
    The default dtype for connection index.
  """
  if mat_dtype is not None:
    global MAT_DTYPE
    MAT_DTYPE = mat_dtype
  if idx_dtype is not None:
    global IDX_DTYPE
    IDX_DTYPE = idx_dtype


class Connector(abc.ABC):
  """Base Synaptic Connector Class."""
  pass


class TwoEndConnector(Connector):
  """Synaptic connector to build synapse connections between two neuron groups."""

  def __init__(self, ):
    self.pre_size = None
    self.post_size = None
    self.pre_num = None
    self.post_num = None

  def __call__(self, pre_size, post_size):
    """Create the concrete connections between two end objects.

    Parameters
    ----------
    pre_size : int, tuple of int, list of int
        The size of the pre-synaptic group.
    post_size : int, tuple of int, list of int
        The size of the post-synaptic group.

    Returns
    -------
    conn : TwoEndConnector
        Return the self.
    """
    if isinstance(pre_size, int):
      pre_size = (pre_size,)
    else:
      pre_size = tuple(pre_size)
    if isinstance(post_size, int):
      post_size = (post_size,)
    else:
      post_size = tuple(post_size)
    self.pre_size, self.post_size = pre_size, post_size
    self.pre_num = tools.size2num(self.pre_size)
    self.post_num = tools.size2num(self.post_size)
    return self

  def _reset_conn(self, pre_size, post_size):
    """Reset connection attributes.

    Parameters
    ----------
    pre_size : int, tuple of int, list of int
        The size of the pre-synaptic group.
    post_size : int, tuple of int, list of int
        The size of the post-synaptic group.
    """
    self.__call__(pre_size, post_size)

  def check(self, structures: Union[Tuple, List, str]):
    # check "pre_num" and "post_num"
    try:
      assert self.pre_num is not None and self.post_num is not None
    except AssertionError:
      raise ConnectorError(f'self.pre_num or self.post_num is not defined. '
                           f'Please use self.__call__(pre_size, post_size) '
                           f'before requiring properties.')

    # check synaptic structures
    if isinstance(structures, str):
      structures = [structures]
    if structures is None or len(structures) == 0:
      raise ConnectorError('No synaptic structure is received.')
    for n in structures:
      if n not in SUPPORTED_SYN_STRUCTURE:
        raise ConnectorError(f'Unknown synapse structure "{n}". '
                             f'Only {SUPPORTED_SYN_STRUCTURE} is supported.')

  def make_returns(self, structures, csr):
    """Make the desired synaptic structures and return them.
    """

    indices, indptr = csr
    assert isinstance(indices, np.ndarray)
    assert isinstance(indptr, np.ndarray)
    assert self.pre_num == indptr.size - 1

    all_data = dict()
    if isinstance(structures, str):
      structures = (structures,)
    assert isinstance(structures, (tuple, list))
    if CONN_MAT in structures:
      conn_mat = csr2mat((indices, indptr), self.pre_num, self.post_num)
      all_data[CONN_MAT] = math.asarray(conn_mat, dtype=MAT_DTYPE)

    if PRE_IDS in structures:
      pre_ids = np.repeat(np.arange(self.pre_num), np.diff(indptr))
      all_data[PRE_IDS] = math.asarray(pre_ids, dtype=IDX_DTYPE)

    if POST_IDS in structures:
      all_data[POST_IDS] = math.asarray(indices, dtype=IDX_DTYPE)

    if PRE2POST in structures:
      all_data[PRE2POST] = (math.asarray(indices, dtype=IDX_DTYPE),
                            math.asarray(indptr, dtype=IDX_DTYPE))

    if POST2PRE in structures:
      indc, indptrc = csr2csc((indices, indptr), self.post_num)
      all_data[POST2PRE] = (math.asarray(indc, dtype=IDX_DTYPE),
                            math.asarray(indptrc, dtype=IDX_DTYPE))

    if PRE2SYN in structures:
      syn_seq = np.arange(indices.size, dtype=IDX_DTYPE)
      all_data[PRE2SYN] = (math.asarray(syn_seq, dtype=IDX_DTYPE),
                           math.asarray(indptr, dtype=IDX_DTYPE))

    if POST2SYN in structures:
      syn_seq = np.arange(indices.size, dtype=IDX_DTYPE)
      _, indptrc, syn_seqc = csr2csc((indices, indptr), self.post_num, syn_seq)
      all_data[POST2SYN] = (math.asarray(syn_seqc, dtype=IDX_DTYPE),
                            math.asarray(indptrc, dtype=IDX_DTYPE))

    if len(structures) == 1:
      return all_data[structures[0]]
    else:
      return tuple([all_data[n] for n in structures])

  def require(self, *structures):
    raise NotImplementedError

  def requires(self, *structures):
    return self.require(*structures)


class OneEndConnector(TwoEndConnector):
  """Synaptic connector to build synapse connections within a population of neurons."""

  def __init__(self):
    super(OneEndConnector, self).__init__()

  def __call__(self, pre_size, post_size=None):
    if post_size is None:
      post_size = pre_size

    try:
      assert pre_size == post_size
    except AssertionError:
      raise ConnectorError(
        f'The shape of pre-synaptic group should be the same with the post group. '
        f'But we got {pre_size} != {post_size}.')

    if isinstance(pre_size, int):
      pre_size = (pre_size,)
    else:
      pre_size = tuple(pre_size)
    if isinstance(post_size, int):
      post_size = (post_size,)
    else:
      post_size = tuple(post_size)
    self.pre_size, self.post_size = pre_size, post_size

    self.pre_num = tools.size2num(self.pre_size)
    self.post_num = tools.size2num(self.post_size)
    return self

  def _reset_conn(self, pre_size, post_size=None):
    self.__init__()

    self.__call__(pre_size, post_size)


def csr2csc(csr, post_num, data=None):
  """Convert csr to csc."""
  indices, indptr = csr
  pre_ids = np.repeat(np.arange(indptr.size - 1), np.diff(indptr))

  sort_ids = np.argsort(indices, kind='mergesort')  # to maintain the original order of the elements with the same value
  pre_ids_new = pre_ids[sort_ids]

  unique_post_ids, count = np.unique(indices, return_counts=True)
  post_count = np.zeros(post_num, dtype=IDX_DTYPE)
  post_count[unique_post_ids] = count

  indptr_new = post_count.cumsum()
  indptr_new = np.insert(indptr_new, 0, 0)
  indptr_new = np.asarray(indptr_new, dtype=IDX_DTYPE)

  if data is None:
    return pre_ids_new, indptr_new
  else:
    data_new = data[sort_ids]
    return pre_ids_new, indptr_new, data_new


def mat2csr(dense):
  """convert a dense matrix to (indices, indptr)."""
  pre_ids, post_ids = np.where(dense > 0)
  pre_num = dense.shape[0]

  uni_idx, count = np.unique(pre_ids, return_counts=True)
  pre_count = np.zeros(pre_num, dtype=IDX_DTYPE)
  pre_count[uni_idx] = count
  indptr = count.cumsum()
  indptr = np.insert(indptr, 0, 0)

  return np.asarray(post_ids, dtype=IDX_DTYPE), np.asarray(indptr, dtype=IDX_DTYPE)


def csr2mat(csr, num_pre, num_post):
  """convert (indices, indptr) to a dense matrix."""
  indices, indptr = csr
  d = np.zeros((num_pre, num_post), dtype=MAT_DTYPE)  # num_pre, num_post
  pre_ids = np.repeat(np.arange(indptr.size - 1), np.diff(indptr))
  d[pre_ids, indices] = True
  return d


def ij2csr(pre_ids, post_ids):
  """convert pre_ids, post_ids to (indices, indptr)."""
  # sorting
  sort_ids = np.argsort(pre_ids, kind='mergesort')
  pre_ids = pre_ids[sort_ids]
  post_ids = post_ids[sort_ids]

  indices = post_ids
  _, pre_count = np.unique(pre_ids, return_counts=True)
  indptr = pre_count.cumsum()
  indptr = np.insert(indptr, 0, 0)

  return indices, np.asarray(indptr, dtype=IDX_DTYPE)
