"""Export authenticated Douyin browser state locally; never print credential values."""
import argparse
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright
from douyin_crawler.browser import wait_login
from douyin_crawler.jobs import atomic_json
from douyin_crawler.config import ROOT


async def main(output):
    temporary = ROOT / ".cache/tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(str(ROOT / 'browser_profile'), channel='msedge', headless=False)
        try:
            page = context.pages[0]
            await page.goto('https://www.douyin.com/', wait_until='domcontentloaded')
            await wait_login(context, page, 600)
            state = await context.storage_state(indexed_db=True)
            state['cookies'] = [c for c in state['cookies'] if c['domain'].lstrip('.') == 'douyin.com' or c['domain'].endswith('.douyin.com')]
            state['origins'] = [o for o in state['origins'] if o['origin'].endswith('.douyin.com') or o['origin']=='https://douyin.com']
            atomic_json(output, state)
            print('AUTH_STATE_EXPORTED; values not logged', flush=True)
        finally:
            await context.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
