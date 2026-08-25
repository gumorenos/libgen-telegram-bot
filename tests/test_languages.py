import asyncio

import httpx

from bookbot.models import BookResult
from bookbot.providers.gutenberg import GutendexProvider
from bookbot.providers.registry import ProviderRegistry
from bookbot.providers.base import ProviderHealth


class FakeProvider:
    key = "fake"
    label = "Fake"

    async def search(self, query: str, limit: int = 8):
        return [
            BookResult(
                source="fake",
                source_label="Fake",
                source_id="1",
                title="English Book",
                authors=[],
                languages=["English"],
                download_count=None,
                formats={},
            ),
            BookResult(
                source="fake",
                source_label="Fake",
                source_id="2",
                title="Spanish Book",
                authors=[],
                languages=["Español"],
                download_count=None,
                formats={},
            ),
        ]

    async def healthcheck(self):
        return ProviderHealth(self.key, self.label, True, "ok")


def test_registry_filters_language_names_and_codes():
    registry = ProviderRegistry([FakeProvider()], languages=("es",))
    books, errors = asyncio.run(registry.search("book", 8))
    assert not errors
    assert [book.title for book in books] == ["Spanish Book"]


def test_gutendex_sends_languages_parameter():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["languages"] = request.url.params.get("languages")
        return httpx.Response(200, json={"results": []}, request=request)

    provider = GutendexProvider(
        "https://gutendex.example",
        languages=("es", "en"),
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(provider.search("quixote"))
    assert seen["languages"] == "es,en"
