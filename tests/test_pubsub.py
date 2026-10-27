"""
Unit tests for shared/pubsub.py.

Covers:
- Fan-out: multiple subscribers each receive every published payload
- Retained latest value: latest() returns the most recent payload without a subscription
- Subscriber cleanup: the queue is removed when iteration stops
"""

from __future__ import annotations

import asyncio


from shared.pubsub import PubSub


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------

class TestFanOut:
    def test_single_subscriber_receives_payload(self):
        async def _test():
            bus = PubSub()
            results = []

            async def consumer():
                async for item in bus.subscribe("match"):
                    results.append(item)
                    break  # stop after first item

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0)          # let consumer register
            await bus.publish("match", {"score": "1-0"})
            await task
            return results

        assert run(_test()) == [{"score": "1-0"}]

    def test_multiple_subscribers_each_receive_payload(self):
        async def _test():
            bus = PubSub()
            received_a = []
            received_b = []

            async def consumer_a():
                async for item in bus.subscribe("events"):
                    received_a.append(item)
                    break

            async def consumer_b():
                async for item in bus.subscribe("events"):
                    received_b.append(item)
                    break

            task_a = asyncio.create_task(consumer_a())
            task_b = asyncio.create_task(consumer_b())
            await asyncio.sleep(0)  # let both register
            await bus.publish("events", "goal")
            await task_a
            await task_b
            return received_a, received_b

        a, b = run(_test())
        assert a == ["goal"]
        assert b == ["goal"]

    def test_subscribers_on_different_topics_are_isolated(self):
        async def _test():
            bus = PubSub()
            got_match = []
            got_audio = []

            async def sub_match():
                async for item in bus.subscribe("match"):
                    got_match.append(item)
                    break

            async def sub_audio():
                async for item in bus.subscribe("audio"):
                    got_audio.append(item)
                    break

            t1 = asyncio.create_task(sub_match())
            t2 = asyncio.create_task(sub_audio())
            await asyncio.sleep(0)
            await bus.publish("match", "match_payload")
            await bus.publish("audio", "audio_payload")
            await t1
            await t2
            return got_match, got_audio

        m, a = run(_test())
        assert m == ["match_payload"]
        assert a == ["audio_payload"]

    def test_multiple_payloads_delivered_in_order(self):
        async def _test():
            bus = PubSub()
            results = []

            async def consumer():
                async for item in bus.subscribe("seq"):
                    results.append(item)
                    if len(results) == 3:
                        break

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0)
            for i in range(3):
                await bus.publish("seq", i)
            await task
            return results

        assert run(_test()) == [0, 1, 2]


# ---------------------------------------------------------------------------
# Retained latest value
# ---------------------------------------------------------------------------

class TestLatest:
    def test_latest_returns_none_before_any_publish(self):
        bus = PubSub()
        assert bus.latest("unknown_topic") is None

    def test_latest_returns_most_recent_payload(self):
        async def _test():
            bus = PubSub()
            await bus.publish("state", {"minute": 10})
            await bus.publish("state", {"minute": 20})
            return bus.latest("state")

        assert run(_test()) == {"minute": 20}

    def test_latest_does_not_require_a_subscriber(self):
        async def _test():
            bus = PubSub()
            await bus.publish("solo", "value")
            return bus.latest("solo")

        assert run(_test()) == "value"

    def test_latest_independent_per_topic(self):
        async def _test():
            bus = PubSub()
            await bus.publish("a", 1)
            await bus.publish("b", 2)
            return bus.latest("a"), bus.latest("b")

        a, b = run(_test())
        assert a == 1
        assert b == 2


# ---------------------------------------------------------------------------
# Subscriber cleanup
# ---------------------------------------------------------------------------

class TestSubscriberCleanup:
    def test_subscriber_removed_after_break(self):
        async def _test():
            bus = PubSub()

            async def consumer():
                async for _ in bus.subscribe("cleanup"):
                    break  # stop immediately after first item

            task = asyncio.create_task(consumer())
            await asyncio.sleep(0)
            assert bus.subscriber_count("cleanup") == 1
            await bus.publish("cleanup", "ping")
            await task
            return bus.subscriber_count("cleanup")

        assert run(_test()) == 0

    def test_subscriber_removed_after_aclose(self):
        async def _test():
            bus = PubSub()
            sub = bus.subscribe("close_test")
            # Queue is registered upon creation.
            assert bus.subscriber_count("close_test") == 1
            # Close without consuming any items.
            await sub.aclose()
            return bus.subscriber_count("close_test")

        assert run(_test()) == 0

    def test_no_leak_across_multiple_subscribe_unsubscribe_cycles(self):
        async def _test():
            bus = PubSub()

            for _ in range(5):
                async def consumer():
                    async for _ in bus.subscribe("cycle"):
                        break

                task = asyncio.create_task(consumer())
                await asyncio.sleep(0)
                await bus.publish("cycle", "x")
                await task

            return bus.subscriber_count("cycle")

        assert run(_test()) == 0
