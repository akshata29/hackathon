"""
Locust load test for the Portfolio Advisor backend.

Run via VS Code task or directly:
    locust -f locustfile.py -u 10 -r 2 --run-time 1m --host http://localhost:8000
"""

import random
import uuid

from locust import HttpUser, between, task

CHAT_QUESTIONS = [
    "What is the outlook for technology stocks?",
    "How is my portfolio performing this year?",
    "What is the current inflation rate?",
    "Compare AAPL and MSFT on valuation metrics.",
    "What are analysts saying about NVIDIA?",
    "Should I be concerned about my energy sector exposure?",
    "What does the latest fed rate decision mean for my bonds?",
    "Give me the top 3 holdings in my portfolio.",
    "What is the P/E ratio for Amazon?",
    "How does my portfolio compare to the S&P 500?",
]


class PortfolioAdvisorUser(HttpUser):
    wait_time = between(1, 5)
    session_id: str

    def on_start(self) -> None:
        self.session_id = str(uuid.uuid4())

    @task(1)
    def health_check(self) -> None:
        with self.client.get("/health", name="GET /health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def get_holdings(self) -> None:
        with self.client.get(
            "/api/portfolio/holdings",
            name="GET /api/portfolio/holdings",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(5)
    def send_chat_message(self) -> None:
        question = random.choice(CHAT_QUESTIONS)
        payload = {
            "message": question,
            "session_id": self.session_id,
            "mode": "handoff",
        }
        with self.client.post(
            "/api/chat/message",
            json=payload,
            headers={"Accept": "text/event-stream"},
            name="POST /api/chat/message",
            stream=True,
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 400):
                resp.failure(f"Unexpected status {resp.status_code}")
                return
            # Consume SSE stream to completion
            for line in resp.iter_lines():
                if line == b"data: [DONE]":
                    break
