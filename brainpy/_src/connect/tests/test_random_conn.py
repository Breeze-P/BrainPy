# -*- coding: utf-8 -*-

import pytest

import unittest

import brainpy as bp


class TestFixedProb(unittest.TestCase):
  def test_size_consistent(self):
    conn1 = bp.connect.FixedProb(prob=0.1, seed=123)
    conn1(pre_size=(10, 20), post_size=(10, 20))
    pre_ids, post_ids, pre2post = conn1.require('pre_ids', 'post_ids', 'pre2post')
    self.assertTrue(len(pre_ids) == len(post_ids))
    self.assertTrue(len(pre_ids) == len(pre2post[0]))

  def test_require_method(self):
    conn2 = bp.connect.FixedProb(prob=0.1, seed=123)
    conn2(pre_size=(10, 20), post_size=(10, 20))
    mat = conn2.require(bp.connect.CONN_MAT)
    self.assertTrue(mat.shape == (200, 200))

    mat = conn2(100, 1000).require(bp.connect.CONN_MAT)
    self.assertTrue(mat.shape == (100, 1000))

    mat = conn2.require(10, 20, bp.connect.CONN_MAT)
    self.assertTrue(mat.shape == (10, 20))


def test_random_fix_pre1():
  for num in [0.4, 20]:
    conn1 = bp.connect.FixedPreNum(num, seed=1234)(pre_size=(10, 15), post_size=(10, 20))
    mat1 = conn1.require(bp.connect.CONN_MAT)

    conn2 = bp.connect.FixedPreNum(num, seed=1234)(pre_size=(10, 15), post_size=(10, 20))
    mat2 = conn2.require(bp.connect.CONN_MAT)

    print()
    print(f'num = {num}')
    print('conn_mat 1\n', mat1)
    print(mat1.sum())
    print('conn_mat 2\n', mat2)
    print(mat2.sum())

    assert bp.math.array_equal(mat1, mat2)


def test_random_fix_pre2():
  for num in [0.5, 3]:
    conn1 = bp.connect.FixedPreNum(num, seed=1234)(pre_size=5, post_size=4)
    mat1 = conn1.require(bp.connect.CONN_MAT)
    print()
    print(mat1)


def test_random_fix_pre3():
  with pytest.raises(bp.errors.ConnectorError):
    conn1 = bp.connect.FixedPreNum(num=6, seed=1234)(pre_size=3, post_size=4)
    conn1.require(bp.connect.CONN_MAT)


def test_random_fix_post1():
  for num in [0.4, 20]:
    conn1 = bp.connect.FixedPostNum(num, seed=1234)(pre_size=(10, 15), post_size=(10, 20))
    mat1 = conn1.require(bp.connect.CONN_MAT)

    conn2 = bp.connect.FixedPostNum(num, seed=1234)(pre_size=(10, 15), post_size=(10, 20))
    mat2 = conn2.require(bp.connect.CONN_MAT)

    print()
    print('conn_mat 1\n', mat1)
    print('conn_mat 2\n', mat2)

    assert bp.math.array_equal(mat1, mat2)


def test_random_fix_post2():
  for num in [0.5, 3]:
    conn1 = bp.connect.FixedPostNum(num, seed=1234)(pre_size=5, post_size=4)
    mat1 = conn1.require(bp.connect.CONN_MAT)
    print(mat1)


def test_random_fix_post3():
  with pytest.raises(bp.errors.ConnectorError):
    conn1 = bp.connect.FixedPostNum(num=6, seed=1234)(pre_size=3, post_size=4)
    conn1.require(bp.connect.CONN_MAT)


def test_gaussian_prob1():
  conn = bp.connect.GaussianProb(sigma=1., include_self=False)(pre_size=100)
  mat = conn.require(bp.connect.CONN_MAT)

  print()
  print('conn_mat', mat)


def test_gaussian_prob2():
  conn = bp.connect.GaussianProb(sigma=4)(pre_size=(50, 50))
  mat = conn.require(bp.connect.CONN_MAT)

  print()
  print('conn_mat', mat)


def test_gaussian_prob3():
  conn = bp.connect.GaussianProb(sigma=4, periodic_boundary=True)(pre_size=(50, 50))
  mat = conn.require(bp.connect.CONN_MAT)

  print()
  print('conn_mat', mat)


def test_gaussian_prob4():
  conn = bp.connect.GaussianProb(sigma=4, periodic_boundary=True)(pre_size=(10, 10, 10))
  conn.require(bp.connect.CONN_MAT,
               bp.connect.PRE_IDS, bp.connect.POST_IDS,
               bp.connect.PRE2POST, bp.connect.POST_IDS)


def test_SmallWorld1():
  conn = bp.connect.SmallWorld(num_neighbor=2, prob=0.5, include_self=False)
  conn(pre_size=10, post_size=10)

  mat = conn.require(bp.connect.CONN_MAT)

  print('conn_mat', mat)


def test_SmallWorld3():
  conn = bp.connect.SmallWorld(num_neighbor=2, prob=0.5, include_self=True)
  conn(pre_size=20, post_size=20)

  mat = conn.require(bp.connect.CONN_MAT)

  print('conn_mat', mat)


def test_SmallWorld2():
  conn = bp.connect.SmallWorld(num_neighbor=2, prob=0.5)
  conn(pre_size=(100,), post_size=(100,))
  mat, _, _, _, _ = conn.require(bp.connect.CONN_MAT,
                                 bp.connect.PRE_IDS, bp.connect.POST_IDS,
                                 bp.connect.PRE2POST, bp.connect.POST_IDS)
  print()
  print('conn_mat', mat)


def test_ScaleFreeBA():
  conn = bp.connect.ScaleFreeBA(m=2)
  for size in [100, (10, 20), (2, 10, 20)]:
    conn(pre_size=size, post_size=size)
    mat, _, _, _, _ = conn.require(bp.connect.CONN_MAT,
                                   bp.connect.PRE_IDS, bp.connect.POST_IDS,
                                   bp.connect.PRE2POST, bp.connect.POST_IDS)
    print()
    print('conn_mat', mat)


def test_ScaleFreeBADual():
  conn = bp.connect.ScaleFreeBADual(m1=2, m2=3, p=0.4)
  for size in [100, (10, 20), (2, 10, 20)]:
    conn(pre_size=size, post_size=size)
    mat, _, _, _, _ = conn.require(bp.connect.CONN_MAT,
                                   bp.connect.PRE_IDS, bp.connect.POST_IDS,
                                   bp.connect.PRE2POST, bp.connect.POST_IDS)
  print()
  print('conn_mat', mat)


def test_PowerLaw():
  conn = bp.connect.PowerLaw(m=3, p=0.4)
  for size in [100, (10, 20), (2, 10, 20)]:
    conn(pre_size=size, post_size=size)
    mat, _, _, _, _ = conn.require(bp.connect.CONN_MAT,
                                   bp.connect.PRE_IDS, bp.connect.POST_IDS,
                                   bp.connect.PRE2POST, bp.connect.POST_IDS)
    print()
    print('conn_mat', mat)
