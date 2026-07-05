import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.llm.embeddings import cosine, cosine_similarity, embed_texts


def test_cosine_similarity_identical() -> None:
    v = [1.0, 2.0, 3.0]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-9


def test_cosine_similarity_opposite() -> None:
    a = [1.0, 2.0, 3.0]
    b = [-1.0, -2.0, -3.0]
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-9


def test_cosine_similarity_zero_vector() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


async def test_embed_texts_empty_input() -> None:
    result = await embed_texts([])
    assert result == []


@patch("server.llm.embeddings._get_embedding_client")
async def test_embed_texts_returns_none_on_failure(mock_client_fn: MagicMock) -> None:
    client = AsyncMock()
    client.embeddings.create.side_effect = RuntimeError("API down")
    mock_client_fn.return_value = client

    result = await embed_texts(["hello"])
    assert result is None


@patch("server.llm.embeddings._get_embedding_client")
async def test_embed_texts_skips_blank_inputs(mock_client_fn: MagicMock) -> None:
    """Blank texts never reach the API (it 400s on them); they become zero vectors."""
    embedding_0 = MagicMock(index=0, embedding=[0.1, 0.2])
    response = MagicMock()
    response.data = [embedding_0]

    client = AsyncMock()
    client.embeddings.create.return_value = response
    mock_client_fn.return_value = client

    result = await embed_texts(["", "hello", "   "])
    assert result == [[0.0, 0.0], [0.1, 0.2], [0.0, 0.0]]
    assert client.embeddings.create.call_args.kwargs["input"] == ["hello"]


@patch("server.llm.embeddings._get_embedding_client")
async def test_embed_texts_all_blank_returns_none_without_api_call(
    mock_client_fn: MagicMock,
) -> None:
    result = await embed_texts(["", "  "])
    assert result is None
    mock_client_fn.assert_not_called()


@patch("server.llm.embeddings._get_embedding_client")
async def test_embed_texts_batch_preserves_order(mock_client_fn: MagicMock) -> None:
    embedding_0 = MagicMock(index=0, embedding=[0.1, 0.2])
    embedding_1 = MagicMock(index=1, embedding=[0.3, 0.4])
    response = MagicMock()
    response.data = [embedding_1, embedding_0]

    client = AsyncMock()
    client.embeddings.create.return_value = response
    mock_client_fn.return_value = client

    result = await embed_texts(["first", "second"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]


# ── canonical `cosine` name used by the phone-registry semantic search ──


def test_cosine_identical_is_one() -> None:
    assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_handles_zero_vector() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_known_value() -> None:
    assert cosine([1.0, 0.0], [1.0, 1.0]) == pytest.approx(1 / math.sqrt(2))


def test_cosine_alias_points_at_cosine() -> None:
    assert cosine_similarity is cosine
