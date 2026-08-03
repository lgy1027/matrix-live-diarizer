import asyncio

from starlette.responses import JSONResponse

from app.middleware.rate_limit import RateLimitMiddleware


def test_concurrent_login_burst_cannot_bypass_failure_limit():
    async def scenario():
        limiter = RateLimitMiddleware(None, auth_login_per_minute=5)
        release = asyncio.Event()
        admitted = 0

        async def bad_password(_request):
            nonlocal admitted
            admitted += 1
            await release.wait()
            return JSONResponse({"detail": "bad credentials"}, status_code=401)

        tasks = [
            asyncio.create_task(
                limiter._check_auth_login(
                    "203.0.113.10", object(), bad_password, 1_000.0
                )
            )
            for _ in range(20)
        ]
        for _ in range(100):
            if admitted == 5:
                break
            await asyncio.sleep(0)

        assert admitted == 5
        release.set()
        responses = await asyncio.gather(*tasks)
        statuses = [response.status_code for response in responses]
        assert statuses.count(401) == 5
        assert statuses.count(429) == 15
        assert "203.0.113.10" not in limiter._auth_locked

    asyncio.run(scenario())
