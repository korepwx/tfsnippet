import numpy as np
import pytest
import tensorflow as tf
from mock import Mock, mock

from tests.helper import assert_variables
from tests.layers.helper import l2_normalize
from tfsnippet.layers import dense, as_gated, gated_dense, l2_regularizer
from tfsnippet.utils import get_static_shape


class DenseTestCase(tf.test.TestCase):

    def test_linear(self):
        np.random.seed(1234)
        kernel = np.random.normal(size=(5, 3)).astype(np.float64)
        bias = np.random.normal(size=(3,)).astype(np.float64)
        x = np.random.normal(size=(11, 7, 5)).astype(np.float64)

        with self.test_session() as sess:
            # test 2d input
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        tf.constant(x[0]), 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias)
                    )
                ),
                np.dot(x[0], kernel) + bias,
                rtol=1e-5
            )

            # test 3d input
            ans = np.dot(x, kernel) + bias
            self.assertEqual(ans.shape, (11, 7, 3))
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        tf.constant(x, dtype=tf.float64), 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias)
                    )
                ),
                ans,
                rtol=1e-5
            )

            # test dynamic batch and sampling size
            ph = tf.placeholder(dtype=tf.float64, shape=(None, None, 5))
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        ph, 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias)
                    ),
                    feed_dict={ph: x}
                ),
                ans,
                rtol=1e-5
            )

            # test use_bias is False
            ans = np.dot(x, kernel)
            self.assertEqual(ans.shape, (11, 7, 3))
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        tf.constant(x, dtype=tf.float64), 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias),
                        use_bias=False
                    )
                ),
                ans,
                rtol=1e-5
            )

        # test create variables
        with tf.Graph().as_default():
            _ = dense(tf.constant(x, dtype=tf.float64), 3)
            assert_variables(['kernel', 'bias'], trainable=True, scope='dense',
                             collections=[tf.GraphKeys.MODEL_VARIABLES])

            kernel_var = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)[-2]
            bias_var = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)[-1]
            self.assertEqual(get_static_shape(kernel_var), kernel.shape)
            self.assertEqual(get_static_shape(bias_var), bias.shape)

        # test create variables, non-trainable
        with tf.Graph().as_default():
            _ = dense(tf.constant(x, dtype=tf.float64), 3, trainable=False)
            assert_variables(['kernel', 'bias'], trainable=False, scope='dense',
                             collections=[tf.GraphKeys.MODEL_VARIABLES])

        # test create variables, use_bias is False
        with tf.Graph().as_default():
            _ = dense(tf.constant(x, dtype=tf.float64), 3, use_bias=False)
            assert_variables(['kernel'], trainable=True, scope='dense',
                             collections=[tf.GraphKeys.MODEL_VARIABLES])
            assert_variables(['bias'], exist=False, scope='dense')

    def test_normalization_and_activation(self):
        np.random.seed(1234)
        kernel = np.random.normal(size=(5, 3)).astype(np.float64)
        bias = np.random.normal(size=(3,)).astype(np.float64)
        x = np.random.normal(size=(11, 7, 5)).astype(np.float64)

        normalizer_fn = lambda x: x * 2. + 1.
        activation_fn = lambda x: x * 1.5 - 3.

        self.assertGreater(
            np.min(np.abs(normalizer_fn(activation_fn(x)) -
                          activation_fn(normalizer_fn(x)))),
            1.
        )

        with self.test_session() as sess:
            # test weight_norm + normalizer + activation
            normalized_kernel = l2_normalize(kernel, axis=0)
            ans = activation_fn(normalizer_fn(np.dot(x, normalized_kernel)))
            self.assertEqual(ans.shape, (11, 7, 3))
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        tf.constant(x, dtype=tf.float64), 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias),
                        activation_fn=activation_fn,
                        normalizer_fn=normalizer_fn,
                        weight_norm=True
                    )
                ),
                ans,
                rtol=1e-5
            )

            # test weight_norm + normalizer + activation, use_bias is True
            ans = activation_fn(
                normalizer_fn(np.dot(x, normalized_kernel) + bias))
            self.assertEqual(ans.shape, (11, 7, 3))
            np.testing.assert_allclose(
                sess.run(
                    dense(
                        tf.constant(x, dtype=tf.float64), 3,
                        kernel=tf.constant(kernel),
                        bias=tf.constant(bias),
                        activation_fn=activation_fn,
                        normalizer_fn=normalizer_fn,
                        weight_norm=True,
                        use_bias=True
                    )
                ),
                ans,
                rtol=1e-5
            )


class GatedDenseTestCase(tf.test.TestCase):

    def test_gated_dense(self):
        as_gated_ret = [None]

        def patched_as_gated(*args, **kwargs):
            as_gated_ret[0] = Mock(wraps=as_gated(*args, **kwargs))
            return as_gated_ret[0]

        with mock.patch('tfsnippet.layers.core.dense_.as_gated',
                        Mock(wraps=patched_as_gated)) as m:
            x = tf.zeros([7, 3])
            kernel_regularizer = l2_regularizer(0.001)
            y = gated_dense(
                x, 5, sigmoid_bias=1., activation_fn=tf.nn.relu,
                kernel_regularizer=kernel_regularizer
            )
            self.assertEqual(y.get_shape().as_list(), [7, 5])
            self.assertEqual(m.call_args, ((dense,), {'sigmoid_bias': 1.}))
            self.assertEqual(as_gated_ret[0].call_args, ((), {
                'input': x,
                'units': 5,
                'activation_fn': tf.nn.relu,
                'kernel_regularizer': kernel_regularizer,
            }))

            with pytest.raises(ValueError,
                               match='The `kernel` and `bias` argument are '
                                     'not supported'):
                _ = gated_dense(x, 5, kernel=tf.zeros([3, 5]))
