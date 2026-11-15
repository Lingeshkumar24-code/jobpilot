import asyncio
from app.services.job_sources import RemoteOKConnector, ArbeitnowConnector, RemotiveConnector

async def main():
    for c in (RemoteOKConnector(), ArbeitnowConnector(), RemotiveConnector()):
        try:
            r = await c.fetch({}, 5)
            print(c.key, 'ok' if r.ok else r.error, 'listings:', len(r.listings))
            for j in r.listings[:3]:
                print('   ', j.title[:60], '|', j.company[:30], '|', (j.location or '')[:25], '|', j.posted_at)
        except Exception as e:
            print(c.key, 'FAILED', type(e).__name__, str(e)[:200])

asyncio.run(main())
