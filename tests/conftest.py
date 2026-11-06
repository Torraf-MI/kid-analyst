import json
from pathlib import Path

import anthropic
import httpx2 as httpx  # il trasporto dell'SDK Anthropic 2.x
import pytest

from kid_analyst.valutazione import carica_dataset

DATASET = Path(__file__).resolve().parents[1] / "dataset"


@pytest.fixture(scope="session")
def dataset():
    return carica_dataset(DATASET)


class ApiFinta:
    """Messages API simulata dietro il vero SDK Anthropic: verifica il formato delle richieste senza rete."""

    def __init__(self, risposte: list[dict], token_input: int = 3000):
        self.risposte = list(risposte)
        self.token_input = token_input
        self.richieste: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        self.richieste.append((request.url.path, corpo))
        if request.url.path.endswith("/count_tokens"):
            return httpx.Response(200, json={"input_tokens": self.token_input})
        r = self.risposte.pop(0)
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": corpo["model"],
            "content": r["content"], "stop_reason": r.get("stop_reason", "end_turn"), "stop_sequence": None,
            "usage": {"input_tokens": self.token_input, "output_tokens": r.get("output_tokens", 500)}})

    @property
    def messaggi(self) -> list[dict]:
        return [c for p, c in self.richieste if p.endswith("/messages")]

    def client(self) -> anthropic.Anthropic:
        trasporto = anthropic.DefaultHttpxClient(transport=httpx.MockTransport(self))
        return anthropic.Anthropic(api_key="test", base_url="http://api.test", http_client=trasporto, max_retries=0)


@pytest.fixture
def api_finta():
    return ApiFinta
