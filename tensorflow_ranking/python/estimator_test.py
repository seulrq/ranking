# Copyright 2020 The TensorFlow Ranking Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for estimator.py."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import six
import tensorflow as tf

from tensorflow_ranking.python import estimator as tfr_estimator
from tensorflow_ranking.python import feature as feature_lib


def _example_feature_columns():
  return {
      name:
      tf.feature_column.numeric_column(name, shape=(1,), default_value=0.0)
      for name in ["f1", "f2", "f3"]
  }


def _context_feature_columns():
  return {
      name:
      tf.feature_column.numeric_column(name, shape=(1,), default_value=0.0)
      for name in ["c1"]
  }


def _scoring_function(context_features, example_features, mode):
  del context_features
  del mode
  batch_size = tf.shape(input=example_features["f1"])[0]
  return tf.ones([batch_size, 1], dtype=tf.float32)


def _multiply_by_two_transform_fn(features, mode):
  for feature, tensor in six.iteritems(features):
    features[feature] = 2 * tensor

  context, example = feature_lib.encode_listwise_features(
      features=features,
      context_feature_columns=_context_feature_columns(),
      example_feature_columns=_example_feature_columns(),
      mode=mode)
  return context, example


def _get_hparams():
  hparams = dict(
      train_input_pattern="",
      eval_input_pattern="",
      learning_rate=0.01,
      train_batch_size=8,
      eval_batch_size=8,
      checkpoint_secs=120,
      num_checkpoints=100,
      num_train_steps=10000,
      num_eval_steps=100,
      loss="softmax_loss",
      list_size=10,
      convert_labels_to_binary=False,
      model_dir=None)
  return hparams


class EstimatorBuilderTest(tf.test.TestCase):

  def _create_default_estimator(self):
    return tfr_estimator.EstimatorBuilder(
        _context_feature_columns(),
        _example_feature_columns(),
        _scoring_function,
        hparams=_get_hparams())

  def test_create_estimator_with_misspecified_args(self):
    hparams = _get_hparams()
    with self.assertRaises(ValueError):
      _ = tfr_estimator.EstimatorBuilder(
          _context_feature_columns,
          None,  # `document_feature_columns` is None.
          _scoring_function,
          hparams=hparams)

    with self.assertRaises(ValueError):
      _ = tfr_estimator.EstimatorBuilder(
          _context_feature_columns,
          _example_feature_columns,
          None,  # `scoring_function` is None.
          hparams=hparams)

    # Either the optimizer or the hparams["learning_rate"] should be specified.
    del hparams["learning_rate"]
    with self.assertRaises(ValueError):
      _ = tfr_estimator.EstimatorBuilder(
          _context_feature_columns,
          _example_feature_columns,
          _scoring_function,
          optimizer=None,
          hparams=hparams)

    # Passing an optimizer (no hparams["learning_rate"]) will slience the error.
    pip = tfr_estimator.EstimatorBuilder(
        _context_feature_columns,
        _example_feature_columns,
        _scoring_function,
        optimizer=tf.compat.v1.train.AdamOptimizer(learning_rate=0.01),
        hparams=_get_hparams())
    self.assertIsInstance(pip, tfr_estimator.EstimatorBuilder)

    # Adding "learning_rate" to hparams (no optimizer) also silences the errors.
    hparams.update(learning_rate=0.01)
    pip = tfr_estimator.EstimatorBuilder(
        _context_feature_columns,
        _example_feature_columns,
        _scoring_function,
        optimizer=None,
        hparams=_get_hparams())
    self.assertIsInstance(pip, tfr_estimator.EstimatorBuilder)

  def test_default_transform_fn(self):
    estimator_with_default_transform_fn = self._create_default_estimator()

    # The below tests the `transform_fn` in the TRAIN mode. In this mode, the
    # `_transform_fn` invokes the `encode_listwise_features()`, which requires
    # 3D example features and 2D context features.
    context, example = estimator_with_default_transform_fn._transform_fn(
        {
            "f1": tf.ones([10, 10, 1], dtype=tf.float32),
            "f2": tf.ones([10, 10, 1], dtype=tf.float32) * 2.0,
            "f3": tf.ones([10, 10, 1], dtype=tf.float32) * 3.0,
            "c1": tf.ones([10, 1], dtype=tf.float32),
            "c2": tf.ones([10, 1], dtype=tf.float32) * 2.0,
        }, tf.estimator.ModeKeys.TRAIN)
    # `c1` is the only context feature defined in `_context_feature_columns()`.
    self.assertCountEqual(context.keys(), ["c1"])

    # `f1`, `f2`, `f3` are all defined in the `_example_feature_columns()`.
    self.assertCountEqual(example.keys(), ["f1", "f2", "f3"])

    # Validates the `context` and `example` features are transformed correctly.
    self.assertAllEqual(tf.ones(shape=[10, 1]), context["c1"])
    self.assertAllEqual(tf.ones(shape=[10, 10, 1]), example["f1"])

    # The below tests the `transform_fn` in the PREDICT mode. In this mode, the
    # `_transform_fn` invokes the `encode_pointwise_features()`, which requires
    # 2D example features and 2D context features.
    context, example = estimator_with_default_transform_fn._transform_fn(
        {
            "f1": tf.ones([10, 1], dtype=tf.float32),
            "f2": tf.ones([10, 1], dtype=tf.float32) * 2.0,
            "f3": tf.ones([10, 1], dtype=tf.float32) * 3.0,
            "c1": tf.ones([10, 1], dtype=tf.float32),
            "c2": tf.ones([10, 1], dtype=tf.float32) * 2.0,
        }, tf.estimator.ModeKeys.PREDICT)

    # After transformation, we get 2D context tensor and 3D example tensor.
    self.assertAllEqual(tf.ones(shape=[10, 1]), context["c1"])
    self.assertAllEqual(tf.ones(shape=[10, 1, 1]), example["f1"])

  def test_custom_transform_fn(self):
    estimator_with_customized_transform_fn = tfr_estimator.EstimatorBuilder(
        _context_feature_columns(),
        _example_feature_columns(),
        _scoring_function,
        transform_function=_multiply_by_two_transform_fn,
        hparams=_get_hparams())

    context, example = estimator_with_customized_transform_fn._transform_fn(
        {
            "f1": tf.ones([10, 10, 1], dtype=tf.float32),
            "f2": tf.ones([10, 10, 1], dtype=tf.float32) * 2.0,
            "f3": tf.ones([10, 10, 1], dtype=tf.float32) * 3.0,
            "c1": tf.ones([10, 1], dtype=tf.float32),
            "c2": tf.ones([10, 1], dtype=tf.float32) * 2.0,
        }, tf.estimator.ModeKeys.TRAIN)

    self.assertCountEqual(context.keys(), ["c1"])
    self.assertCountEqual(example.keys(), ["f1", "f2", "f3"])
    # By adopting `_multiply_by_two_transform_fn`, the `context` and `example`
    # tensors will be both multiplied by 2.
    self.assertAllEqual(2 * tf.ones(shape=[10, 1]), context["c1"])
    self.assertAllEqual(2 * tf.ones(shape=[10, 10, 1]), example["f1"])

  def test_group_score_fn(self):
    estimator = self._create_default_estimator()
    logits = estimator._group_score_fn(
        {"c1": tf.ones([10, 1], dtype=tf.float32)},
        {"f1": tf.ones([10, 1, 1], dtype=tf.float32)},
        tf.estimator.ModeKeys.TRAIN, None, None)

    self.assertAllEqual(logits, tf.ones([10, 1], dtype=tf.float32))

  def test_eval_metric_fns(self):
    estimator = self._create_default_estimator()
    self.assertCountEqual(estimator._eval_metric_fns().keys(), [
        "metric/mrr", "metric/mrr_10", "metric/ndcg", "metric/ndcg_10",
        "metric/ndcg_5"
    ])

  def test_optimizer(self):
    estimator_with_default_optimizer = self._create_default_estimator()
    self.assertIsInstance(estimator_with_default_optimizer._optimizer,
                          tf.compat.v1.train.AdagradOptimizer)

    estimator_with_adam_optimizer = tfr_estimator.EstimatorBuilder(
        _context_feature_columns(),
        _example_feature_columns(),
        _scoring_function,
        optimizer=tf.compat.v1.train.AdamOptimizer(learning_rate=0.01),
        hparams=_get_hparams())
    self.assertIsInstance(estimator_with_adam_optimizer._optimizer,
                          tf.compat.v1.train.AdamOptimizer)


if __name__ == "__main__":
  tf.test.main()
