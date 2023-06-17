# Owner(s): ["module: sparse"]
import random

import torch
from torch import nn

from torch.sparse.semi_structured import (
    to_sparse_semi_structured,
    SparseSemiStructuredTensor,
    _DTYPE_TO_SEMI_STRUCTURED_SPARSE_CONFIG,
)

from torch.testing._internal.common_utils import (
    TestCase,
    run_tests,
    parametrize,
    subtest,
)

from torch.testing._internal.common_device_type import (
    dtypes,
    instantiate_device_type_tests,
)

from torch.testing._internal.common_dtype import (
    all_types_and_complex
)

SEMI_STRUCTURED_SUPPORTED_DTYPES = _DTYPE_TO_SEMI_STRUCTURED_SPARSE_CONFIG.keys()

def rand_sparse_semi_structured_mask(r, c, dtype=torch.float16, device="cuda", choice=None):
    """
    This function returns a 1:2 sparse matrix of size (r, c).
    Note that this means this matrix will also be 2:4 and 4:8 sparse as well.
    """

    choices = [[0, 1], [1, 0]]
    mask_entries = [choice or random.choice(choices) for i in range(r * c // 2)]

    return (
        torch.tensor(mask_entries, dtype=dtype, device=device)
        .reshape(r, c)
        .contiguous()
    )

class TestSparseSemiStructured(TestCase):

    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_to_sparse_semi_structured(self, dtype):
        a = rand_sparse_semi_structured_mask(128, 128, dtype=dtype)
        a_sparse = to_sparse_semi_structured(a, mask=a.bool())

        assert a.shape == a_sparse.shape
        assert a.device == a_sparse.device
        assert a.dtype == a_sparse.dtype

        assert isinstance(a, torch.Tensor)
        assert isinstance(a_sparse, SparseSemiStructuredTensor)

    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_mm_sparse_first_NT(self, dtype, device):
        """
        This function tests torch.mm(A_sparse, B.T), where the first element is sparse and non-transposed, is correct.
        """
        A = rand_sparse_semi_structured_mask(128, 128, dtype=dtype)
        A_sparse = to_sparse_semi_structured(A, mask=A.bool())

        B = torch.rand((128, 128), device=A_sparse.device).to(dtype)


        # Currently we don't support int matmul on GPU, so evaluate on CPU and copy over
        # CUTLASS and cuSPARSELt have slightly different int8 behavior. CUTLASS will output to an int32 tensor while cuSPARSELt will output to a int8 tensor
        if dtype is torch.int8:
            # This should fail
            with self.assertRaisesRegex(RuntimeError, "_structured_sparse_linear"):
                sparse_result = torch.mm(A_sparse, B)

            # test transpose
            dense_result = torch.mm(A.cpu(), B.t().cpu()).to(device, dtype=torch.int32)
            sparse_result = torch.mm(A_sparse, B.t())
            assert torch.allclose(dense_result, sparse_result, rtol=1e-3, atol=1e-3)
        else:
            dense_result = torch.mm(A, B)
            sparse_result = torch.mm(A_sparse, B)
            assert torch.allclose(dense_result, sparse_result, rtol=1e-3, atol=1e-3)
            # test transpose
            dense_result = torch.mm(A, B.t())
            sparse_result = torch.mm(A_sparse, B.t())
            assert torch.allclose(dense_result, sparse_result, rtol=1e-3, atol=1e-3)


    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_mm_sparse_first_T(self, dtype, device):
        A = rand_sparse_semi_structured_mask(128, 128, dtype=dtype)
        A_sparse = to_sparse_semi_structured(A, mask=A.bool())

        B = torch.rand((128, 128), device=A_sparse.device).to(dtype)

        with self.assertRaisesRegex(NotImplementedError,  r'arg0: SparseSemiStructuredTensor\(.*transposed=True\)'):
            torch.mm(A_sparse.t(), B)


    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_mm_sparse_second_T(self, dtype, device):
        """
        This function tests torch.mm(A_sparse, B.T), where the first element is sparse and non-transposed, is correct.
        """
        B = rand_sparse_semi_structured_mask(128, 128, dtype=dtype)
        B_sparse = to_sparse_semi_structured(B, mask=B.bool())

        A = torch.rand((128, 128), device=B_sparse.device).to(dtype)


        # Currently we don't support int matmul on GPU, so evaluate on CPU and copy over
        # CUTLASS and cuSPARSELt have slightly different int8 behavior. CUTLASS will output to an int32 tensor while cuSPARSELt will output to a int8 tensor
        if dtype is torch.int8:
            dense_result = torch.mm(A.cpu(), B.t().cpu()).to(device, dtype=torch.int32)
            sparse_result = torch.mm(A, B_sparse.t())
        else:
            dense_result = torch.mm(A, B.t())
            sparse_result = torch.mm(A, B_sparse.t())

        assert torch.allclose(dense_result, sparse_result, rtol=1e-3, atol=1e-3)

    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_mm_sparse_second_NT(self, dtype, device):
        """
        This function tests torch.mm(A_sparse, B.T), where the first element is sparse and non-transposed, is correct.
        """
        B = rand_sparse_semi_structured_mask(128, 128, dtype=dtype)
        B_sparse = to_sparse_semi_structured(B, mask=B.bool())

        A = torch.rand((128, 128), device=B_sparse.device).to(dtype)

        with self.assertRaisesRegex(NotImplementedError,  r'arg1: SparseSemiStructuredTensor\(.*transposed=False\)'):
            sparse_result = torch.mm(A, B_sparse)


    @parametrize("inference_mode", [subtest(False), subtest(True)])
    def test_linear(self, inference_mode, device):
        input = torch.rand(128, 128, device=device).half()
        model = nn.Linear(128, 128).to(device).half()
        m, n = model.weight.shape
        mask = rand_sparse_semi_structured_mask(m, n, device=device, dtype=torch.bool)
        # set masked weight
        model.weight = nn.Parameter(model.weight * mask)

        dense_result = model(input)
        model.weight = nn.Parameter(to_sparse_semi_structured(model.weight, mask=mask))

        if inference_mode:
            with torch.inference_mode():
                sparse_result = model(input)
        else:
            sparse_result = model(input)

        assert torch.allclose(dense_result, sparse_result, rtol=1e-5, atol=1e-5)

    def test_values(self):
        A = rand_sparse_semi_structured_mask(128, 128)
        A_sparse = to_sparse_semi_structured(A, mask=A.bool())
        assert A_sparse.values().shape == (128, 64)
        assert (A_sparse.values() == 1).all()

    def test_indices(self):
        A = rand_sparse_semi_structured_mask(128, 128)
        A_sparse = to_sparse_semi_structured(A, mask=A.bool())
        assert A_sparse.indices().shape == (128, 8)

    @dtypes(*SEMI_STRUCTURED_SUPPORTED_DTYPES)
    def test_unsupported_shape(self, dtype, device):
        A = rand_sparse_semi_structured_mask(4, 4, dtype=dtype, device=device)
        with self.assertRaisesRegex(RuntimeError, "Error original_tensor.shape"):
            A_sparse = to_sparse_semi_structured(A, mask=A.bool())

    @dtypes(*all_types_and_complex())
    def test_unsupported_dtype(self, dtype, device):
        A = rand_sparse_semi_structured_mask(128, 128, dtype=dtype, device=device)

        if dtype not in SEMI_STRUCTURED_SUPPORTED_DTYPES:
            with self.assertRaisesRegex(RuntimeError, "Error original_tensor.dtype"):
                A_sparse = to_sparse_semi_structured(A, mask=A.bool())
        else:
            A_sparse = to_sparse_semi_structured(A, mask=A.bool())

    def test_unsupported_dim(self, device):
        A = torch.rand(128, 128, 128, device=device, dtype=torch.float16)

        with self.assertRaisesRegex(RuntimeError, "Error original_tensor.dim"):
            A_sparse = to_sparse_semi_structured(A, mask=A.bool())




instantiate_device_type_tests(TestSparseSemiStructured, globals(), only_for="cuda")

if __name__ == "__main__":
    run_tests()
