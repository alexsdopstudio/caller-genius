"""Calls the authenticated server; only pending prospects are selected."""
import argparse
import asyncio
import httpx
from app.config import get_settings


async def run(args):
    s = get_settings()
    async with httpx.AsyncClient(base_url=args.url, auth=(s.admin_user, s.admin_password), timeout=60) as client:
        offset, done = 0, 0
        while done < args.limit:
            response = await client.get('/api/prospects', params={'offset': offset})
            response.raise_for_status()
            prospects = response.json()
            if not prospects:
                break
            for p in prospects:
                if p['audit_status'] != 'pending':
                    continue
                response = await client.post(f'/api/audit/{p["id"]}/start')
                print(p['id'], response.status_code)
                if response.status_code not in (200, 409):
                    response.raise_for_status()
                done += 1
                if done >= args.limit:
                    break
                await asyncio.sleep(args.interval)
            offset += len(prospects)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--interval', type=float, default=5)
    parser.add_argument('--url', default='http://localhost:8000')
    args = parser.parse_args()
    if args.limit < 1 or args.interval < 1:
        parser.error('limit e interval devono essere >= 1')
    asyncio.run(run(args))
